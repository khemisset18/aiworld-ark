"""Room-one privacy policy: commons, colleagues and personal.

Read/view permissions are enforced server-side after GET signatures;
write/assist permissions are enforced in the signed transaction dispatcher.
Tests have three distinct Gate-admitted agents and a disposable SQLite DB.
"""
from __future__ import annotations

from test_forge import do
from test_private_agent_network import net, signed_headers
from test_world_space import agent


def read(c, account, path):
    return c.get(path, headers=signed_headers(account, path))


def action(c, account, key, nonce, op, data):
    return do(c, key, account["agent_id"], nonce, op, data)


def test_topic_owner_controls_seeing_talking_inviting_and_revoking(net, tmp_path):
    a, ka = agent(net, tmp_path, 1)
    b, kb = agent(net, tmp_path, 2)
    c, kc = agent(net, tmp_path, 3)

    created = action(net, a, ka, 2, "world_topic", {
        "category": "debate", "title": "Discussion confidentielle",
        "body": "Recherche privee sur des ressources experimentees",
        "visibility": "personal", "allow_assistance": False,
    })
    assert created.status_code == 200, created.text
    tid = created.json()["height"]
    path = f"/v1/world/topics/{tid}"
    replies = path + "/replies"
    assert read(net, a, path).status_code == 200
    assert read(net, b, path).status_code == 403
    assert read(net, c, replies).status_code == 403
    assert read(net, b, "/v1/world/topics").json() == []
    assert action(net, b, kb, 2, "world_reply",
                  {"topic_height": tid, "message": "Je veux entrer"}).status_code == 403
    assert "Discussion confidentielle" not in read(net, a, "/v1/blocks").text
    assert "Recherche privee" not in read(net, a, "/v1/blocks").text

    # Personal -> colleagues; invitation does not grant access until accepted.
    assert action(net, a, ka, 3, "world_visibility", {
        "resource_type": "topic", "resource_height": tid,
        "visibility": "colleagues", "allow_assistance": False,
    }).status_code == 200
    invite = action(net, a, ka, 4, "world_invite", {
        "resource_type": "topic", "resource_height": tid,
        "invitee": b["agent_id"], "permission": "read",
    })
    assert invite.status_code == 200, invite.text
    assert read(net, b, path).status_code == 403
    incoming = read(net, b, "/v1/world/invitations")
    assert incoming.status_code == 200
    assert incoming.json()["incoming"][0]["status"] == "pending"
    assert read(net, c, "/v1/world/invitations").json()["incoming"] == []
    assert action(net, b, kb, 2, "world_accept", {
        "resource_type": "topic", "resource_height": tid,
    }).status_code == 200
    assert read(net, b, path).status_code == 200
    assert read(net, c, path).status_code == 403
    assert action(net, b, kb, 3, "world_reply", {
        "topic_height": tid, "message": "Lecture seulement",
    }).status_code == 403

    # Colleague can opt into contribution after a NEW accepted invitation.
    assert action(net, a, ka, 5, "world_revoke", {
        "resource_type": "topic", "resource_height": tid,
        "invitee": b["agent_id"],
    }).status_code == 200
    assert read(net, b, path).status_code == 403
    assert action(net, a, ka, 6, "world_invite", {
        "resource_type": "topic", "resource_height": tid,
        "invitee": b["agent_id"], "permission": "contribute",
    }).status_code == 200
    assert action(net, b, kb, 3, "world_accept", {
        "resource_type": "topic", "resource_height": tid,
    }).status_code == 200
    assert action(net, b, kb, 4, "world_reply", {
        "topic_height": tid, "message": "Contribution approuvee",
    }).status_code == 200
    assert read(net, a, replies).json()[0]["message"] == "Contribution approuvee"
    assert read(net, c, replies).status_code == 403

    # Returning to personal must delete all previous accepted access.
    assert action(net, a, ka, 7, "world_visibility", {
        "resource_type": "topic", "resource_height": tid,
        "visibility": "personal", "allow_assistance": False,
    }).status_code == 200
    assert read(net, b, path).status_code == 403
    assert read(net, b, "/v1/world/invitations").json()["incoming"] == []
    assert action(net, a, ka, 8, "world_visibility", {
        "resource_type": "topic", "resource_height": tid,
        "visibility": "commons", "allow_assistance": False,
    }).status_code == 200
    assert read(net, c, path).status_code == 200
    assert action(net, c, kc, 2, "world_reply", {
        "topic_height": tid, "message": "Reponse non autorisee",
    }).status_code == 403
    assert action(net, a, ka, 9, "world_visibility", {
        "resource_type": "topic", "resource_height": tid,
        "visibility": "commons", "allow_assistance": True,
    }).status_code == 200
    assert action(net, c, kc, 2, "world_reply", {
        "topic_height": tid, "message": "Entraide volontaire ouverte",
    }).status_code == 200
    assert "Entraide volontaire ouverte" not in read(net, a, "/v1/blocks").text


def test_workspace_collaborators_and_chat_can_be_read_only_or_assist(net, tmp_path):
    a, ka = agent(net, tmp_path, 1)
    b, kb = agent(net, tmp_path, 2)
    c, kc = agent(net, tmp_path, 3)
    p = action(net, a, ka, 2, "world_project", {
        "title": "Projet confidentiel",
        "objective": "Garder le travail prive avec les assistants qui sont choisis.",
        "criteria": "Documenter les essais approuves et les acces au contexte.",
    })
    assert p.status_code == 200, p.text
    pid = p.json()["height"]
    assert action(net, b, kb, 2, "world_join", {"project_height": pid}).status_code == 200
    assert action(net, c, kc, 2, "world_join", {"project_height": pid}).status_code == 200

    w = action(net, a, ka, 3, "world_workspace", {
        "project_height": pid, "name": "Travail pour NOVA",
        "purpose": "Stocker des discussions sensibles sans publication a la communaute",
    })
    assert w.status_code == 200, w.text
    wid = w.json()["height"]
    path = f"/v1/world/workspaces/{wid}"
    messages = path + "/messages"
    listed = f"/v1/world/projects/{pid}/workspaces"
    assert read(net, a, path).status_code == 200
    assert read(net, b, path).status_code == 403
    assert read(net, b, listed).json() == []
    assert read(net, c, path).status_code == 403

    assert action(net, a, ka, 4, "world_visibility", {
        "resource_type": "workspace", "resource_height": wid,
        "visibility": "colleagues", "allow_assistance": False,
    }).status_code == 200
    assert action(net, a, ka, 5, "world_invite", {
        "resource_type": "workspace", "resource_height": wid,
        "invitee": b["agent_id"], "permission": "contribute",
    }).status_code == 200
    assert read(net, b, messages).status_code == 403
    assert action(net, b, kb, 3, "world_accept", {
        "resource_type": "workspace", "resource_height": wid,
    }).status_code == 200
    assert read(net, b, path).status_code == 200
    assert action(net, b, kb, 4, "world_workspace_message", {
        "workspace_height": wid, "message": "Proposition de modele autorise",
    }).status_code == 200
    assert read(net, a, messages).json()[0]["message"] == "Proposition de modele autorise"
    assert read(net, c, messages).status_code == 403
    assert "Proposition de modele autorise" not in read(net, a, "/v1/blocks").text

    assert action(net, a, ka, 6, "world_invite", {
        "resource_type": "workspace", "resource_height": wid,
        "invitee": c["agent_id"], "permission": "read",
    }).status_code == 200
    assert action(net, c, kc, 3, "world_accept", {
        "resource_type": "workspace", "resource_height": wid,
    }).status_code == 200
    assert read(net, c, messages).status_code == 200
    assert action(net, c, kc, 4, "world_workspace_message", {
        "workspace_height": wid, "message": "Je ne dois pas pouvoir ecrire",
    }).status_code == 403
    assert action(net, b, kb, 5, "world_repo", {
        "workspace_height": wid, "repository": "https://github.com/khemisset18/aiworld-ark",
    }).status_code == 200
    assert action(net, c, kc, 4, "world_repo", {
        "workspace_height": wid, "repository": "https://github.com/other/repository",
    }).status_code == 403

    assert action(net, a, ka, 7, "world_revoke", {
        "resource_type": "workspace", "resource_height": wid,
        "invitee": b["agent_id"],
    }).status_code == 200
    assert read(net, b, path).status_code == 403
    assert action(net, a, ka, 8, "world_visibility", {
        "resource_type": "workspace", "resource_height": wid,
        "visibility": "personal", "allow_assistance": False,
    }).status_code == 200
    assert read(net, c, path).status_code == 403
    assert action(net, a, ka, 9, "world_visibility", {
        "resource_type": "workspace", "resource_height": wid,
        "visibility": "commons", "allow_assistance": False,
    }).status_code == 200
    assert read(net, c, path).status_code == 200
    assert action(net, c, kc, 4, "world_workspace_message", {
        "workspace_height": wid, "message": "Public lecture, sans contribution",
    }).status_code == 403


def test_privacy_invalid_values_and_unauthorized_invites_fail_closed(net, tmp_path):
    a, ka = agent(net, tmp_path, 1)
    b, kb = agent(net, tmp_path, 2)
    topic = action(net, a, ka, 2, "world_topic", {
        "category": "question", "title": "Choix de confidentialite",
        "body": "Comment proteger la lecture et la contribution des pairs ?",
        "visibility": "colleagues", "allow_assistance": False,
    })
    tid = topic.json()["height"]
    assert action(net, b, kb, 2, "world_invite", {
        "resource_type": "topic", "resource_height": tid,
        "invitee": a["agent_id"], "permission": "contribute",
    }).status_code == 403
    assert action(net, a, ka, 3, "world_visibility", {
        "resource_type": "topic", "resource_height": tid,
        "visibility": "personal", "allow_assistance": True,
    }).status_code == 400
    assert action(net, a, ka, 3, "world_invite", {
        "resource_type": "topic", "resource_height": tid,
        "invitee": b["agent_id"], "permission": "admin",
    }).status_code == 400
    assert action(net, a, ka, 3, "world_invite", {
        "resource_type": "topic", "resource_height": tid,
        "invitee": "0" * 32, "permission": "read",
    }).status_code == 404
    assert action(net, b, kb, 2, "world_accept", {
        "resource_type": "topic", "resource_height": tid,
    }).status_code == 403
    assert read(net, b, f"/v1/world/topics/{tid}").status_code == 403
    assert read(net, b, "/v1/world/topics").json() == []
