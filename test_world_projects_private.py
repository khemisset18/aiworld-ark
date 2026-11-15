"""Private projects and signed activity feed: no metadata leaks or forced joins.

Uses three real Gate-admitted Ed25519 test agents and a disposable SQLite DB.
"""
from __future__ import annotations

from test_forge import do
from test_private_agent_network import net, signed_headers
from test_world_space import agent


def get(net, account, path, query=""):
    url = path + (("?" + query) if query else "")
    return net.get(url, headers=signed_headers(account, path, query))


def tx(net, account, key, nonce, op, data):
    return do(net, key, account["agent_id"], nonce, op, data)


def project_data(visibility, assist=False):
    return {
        "title": "Recherche cachée - ZÉPHYR",
        "objective": "Comparer des expériences sous NDA sans divulguer les objectifs",
        "criteria": "Seuls les associés autorisés peuvent consulter les résultats",
        "visibility": visibility, "allow_assistance": assist,
    }


def test_private_project_gate_and_colleague_read_only_access(net, tmp_path):
    owner, ko = agent(net, tmp_path, 1)
    guest, kg = agent(net, tmp_path, 2)
    stranger, ks = agent(net, tmp_path, 3)
    p = tx(net, owner, ko, 2, "world_project", project_data("colleagues"))
    assert p.status_code == 200, p.text
    pid = p.json()["height"]
    path = f"/v1/world/projects/{pid}"
    assert "Recherche cachée" not in get(net, owner, "/v1/blocks").text
    assert "NDA" not in get(net, owner, "/v1/blocks").text
    assert get(net, stranger, path).status_code == 403
    assert get(net, guest, "/v1/world/projects").json() == []
    assert get(net, guest, f"{path}/updates").status_code == 403
    assert get(net, guest, f"{path}/workspaces").status_code == 403
    assert tx(net, guest, kg, 2, "world_join", {"project_height": pid}).status_code == 403

    invite = tx(net, owner, ko, 3, "world_invite", {
        "resource_type": "project", "resource_height": pid,
        "invitee": guest["agent_id"], "permission": "read"
    })
    assert invite.status_code == 200
    assert get(net, guest, path).status_code == 403  # pending is not access
    incoming = get(net, guest, "/v1/world/invitations")
    assert incoming.json()["incoming"][0]["resource_type"] == "project"
    assert get(net, stranger, "/v1/world/invitations").json()["incoming"] == []
    accepted = tx(net, guest, kg, 2, "world_accept", {
        "resource_type": "project", "resource_height": pid
    })
    assert accepted.status_code == 200
    assert get(net, guest, path).status_code == 200
    assert len(get(net, guest, "/v1/world/projects").json()) == 1
    assert get(net, stranger, "/v1/world/projects").json() == []
    assert get(net, guest, f"{path}/updates").status_code == 200
    assert tx(net, guest, kg, 3, "world_update", {
        "project_height": pid, "message": "Tentative de modification",
        "evidence_sha256": None
    }).status_code == 403
    assert tx(net, guest, kg, 3, "world_join", {"project_height": pid}).status_code == 403
    assert tx(net, guest, kg, 3, "world_workspace", {
        "project_height": pid, "name": "Intrus",
        "purpose": "Créer un espace sans permission d'écrire"
    }).status_code == 403

    # A specific workspace can be shared read-only to a project reader.
    ws = tx(net, owner, ko, 4, "world_workspace", {
        "project_height": pid, "name": "Essais privés",
        "purpose": "Documents et références de l'atelier",
        "visibility": "colleagues", "allow_assistance": False
    })
    assert ws.status_code == 200
    wid = ws.json()["height"]
    wpath = f"/v1/world/workspaces/{wid}"
    assert get(net, guest, wpath).status_code == 403
    assert tx(net, owner, ko, 5, "world_invite", {
        "resource_type": "workspace", "resource_height": wid,
        "invitee": guest["agent_id"], "permission": "read"
    }).status_code == 200
    assert tx(net, guest, kg, 3, "world_accept", {
        "resource_type": "workspace", "resource_height": wid
    }).status_code == 200
    assert get(net, guest, wpath).status_code == 200
    assert get(net, stranger, wpath).status_code == 403
    assert tx(net, guest, kg, 4, "world_workspace_message", {
        "workspace_height": wid, "message": "Je ne peux pas aider"
    }).status_code == 403

    # Revoke project access: child workspace invitation cannot bypass parent.
    assert tx(net, owner, ko, 6, "world_revoke", {
        "resource_type": "project", "resource_height": pid,
        "invitee": guest["agent_id"]
    }).status_code == 200
    assert get(net, guest, path).status_code == 403
    assert get(net, guest, wpath).status_code == 403
    assert get(net, guest, f"{wpath}/repos").status_code == 403


def test_project_contributor_invite_join_and_privacy_revocation(net, tmp_path):
    owner, ko = agent(net, tmp_path, 1)
    colleague, kc = agent(net, tmp_path, 2)
    p = tx(net, owner, ko, 2, "world_project", project_data("colleagues"))
    pid = p.json()["height"]
    assert tx(net, owner, ko, 3, "world_invite", {
        "resource_type": "project", "resource_height": pid,
        "invitee": colleague["agent_id"], "permission": "contribute"
    }).status_code == 200
    assert tx(net, colleague, kc, 2, "world_accept", {
        "resource_type": "project", "resource_height": pid
    }).status_code == 200
    assert get(net, owner, "/v1/world/projects").json()[0]["members"] == 2
    update = tx(net, colleague, kc, 3, "world_update", {
        "project_height": pid, "message": "Contribution vérifiable proposée",
        "evidence_sha256": None
    })
    assert update.status_code == 200
    ws = tx(net, colleague, kc, 4, "world_workspace", {
        "project_height": pid, "name": "Mon atelier",
        "purpose": "Dossier privé du collaborateur"
    })
    assert ws.status_code == 200
    assert get(net, owner, f"/v1/world/workspaces/{ws.json()['height']}").status_code == 403
    assert get(net, colleague, f"/v1/world/workspaces/{ws.json()['height']}").status_code == 200

    # Owner switches to personal, discards invitations AND collaborator rights.
    privacy = tx(net, owner, ko, 4, "world_visibility", {
        "resource_type": "project", "resource_height": pid,
        "visibility": "personal", "allow_assistance": False
    })
    assert privacy.status_code == 200
    assert get(net, colleague, f"/v1/world/projects/{pid}").status_code == 403
    assert get(net, colleague, f"/v1/world/workspaces/{ws.json()['height']}").status_code == 403
    assert get(net, colleague, "/v1/world/invitations").json()["incoming"] == []
    assert get(net, owner, "/v1/world/projects").json()[0]["members"] == 1
    # Reopening doesn't reactivate old rights.
    assert tx(net, owner, ko, 5, "world_visibility", {
        "resource_type": "project", "resource_height": pid,
        "visibility": "colleagues", "allow_assistance": False
    }).status_code == 200
    assert get(net, colleague, f"/v1/world/projects/{pid}").status_code == 403


def test_activity_feed_discards_revoked_private_events(net, tmp_path):
    a, ka = agent(net, tmp_path, 1)
    b, kb = agent(net, tmp_path, 2)
    c, kc = agent(net, tmp_path, 3)
    p = tx(net, a, ka, 2, "world_project", project_data("colleagues"))
    pid = p.json()["height"]
    topic = tx(net, a, ka, 3, "world_topic", {
        "category": "question", "title": "Question ouverte",
        "body": "Comment contribuer à ce réseau d'agents ?"
    })
    assert topic.status_code == 200
    tid = topic.json()["height"]
    reply = tx(net, c, kc, 2, "world_reply", {
        "topic_height": tid, "message": "Réponse en lecture commune"
    })
    assert reply.status_code == 200
    private_ws = tx(net, a, ka, 4, "world_workspace", {
        "project_height": pid, "name": "Données secrètes",
        "purpose": "Informations accessibles au seul créateur"
    })
    assert private_ws.status_code == 200
    wid = private_ws.json()["height"]
    msg = tx(net, a, ka, 5, "world_workspace_message", {
        "workspace_height": wid, "message": "Secret de projet"
    })
    assert msg.status_code == 200

    path, query = "/v1/world/activity", "after=0"
    assert net.get(path).status_code == 403
    outsider_feed = get(net, b, path, query)
    assert outsider_feed.status_code == 200, outsider_feed.text
    assert outsider_feed.headers["cache-control"] == "private, no-store"
    kinds = [x["kind"] for x in outsider_feed.json()["events"]]
    assert "topic" in kinds and "reply" in kinds
    assert "project" not in kinds and "workspace_message" not in kinds
    assert "Secret de projet" not in outsider_feed.text

    invited = tx(net, a, ka, 6, "world_invite", {
        "resource_type": "project", "resource_height": pid,
        "invitee": b["agent_id"], "permission": "read"
    })
    assert invited.status_code == 200
    assert get(net, b, path, query).json()["pending_invitations"] == 1
    assert tx(net, b, kb, 2, "world_accept", {
        "resource_type": "project", "resource_height": pid
    }).status_code == 200
    accepted_feed = get(net, b, path, query).json()
    assert "project" in [x["kind"] for x in accepted_feed["events"]]
    assert "workspace_message" not in [x["kind"] for x in accepted_feed["events"]]
    assert accepted_feed["pending_invitations"] == 0
    assert accepted_feed["next_after"] >= topic.json()["height"]
    assert get(net, b, path, "after=" + str(accepted_feed["next_after"])).status_code == 200
    assert tx(net, a, ka, 7, "world_revoke", {
        "resource_type": "project", "resource_height": pid,
        "invitee": b["agent_id"]
    }).status_code == 200
    revoked_feed = get(net, b, path, query).json()
    assert "project" not in [x["kind"] for x in revoked_feed["events"]]
    assert "Secret de projet" not in str(revoked_feed)


def test_project_owner_rejects_invalid_privacy_and_spurious_invites(net, tmp_path):
    a, ka = agent(net, tmp_path, 1)
    b, kb = agent(net, tmp_path, 2)
    assert tx(net, a, ka, 2, "world_project", project_data("personal", True)).status_code == 400
    p = tx(net, a, ka, 2, "world_project", project_data("personal"))
    pid = p.json()["height"]
    assert tx(net, a, ka, 3, "world_invite", {
        "resource_type": "project", "resource_height": pid,
        "invitee": b["agent_id"], "permission": "contribute"
    }).status_code == 409
    assert tx(net, b, kb, 2, "world_visibility", {
        "resource_type": "project", "resource_height": pid,
        "visibility": "commons", "allow_assistance": True
    }).status_code == 403
    assert tx(net, b, kb, 2, "world_join", {"project_height": pid}).status_code == 403
