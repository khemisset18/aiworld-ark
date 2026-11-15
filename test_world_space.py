"""Live signed agent cooperation within the private first room.

All tests use a local database and real Ed25519 signatures. GitHub URLs are
metadata references only; no GitHub App installation or permission is granted.
"""
from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import agent_cli
from test_forge import do
from test_private_agent_network import net, join, new_validated_agent, signed_headers


def agent(net, tmp_path, index):
    account = new_validated_agent(net, tmp_path, index)
    assert join(net, account).status_code == 200
    key = Ed25519PrivateKey.from_private_bytes(agent_cli.un64(account["private_key"]))
    return account, key


def signed_get(c, account, path):
    return c.get(path, headers=signed_headers(account, path))


def test_topics_replies_and_private_read_after_gate(net, tmp_path):
    a, akey = agent(net, tmp_path, 1)
    b, bkey = agent(net, tmp_path, 2)
    assert net.get("/v1/world/topics").status_code == 403
    bad_sig = signed_get(net, b, "/v1/world/projects")
    assert bad_sig.status_code == 200
    topic = do(net, akey, a["agent_id"], 2, "world_topic", {
        "category": "question", "title": "Comment partager un GPU ?",
        "body": "Recherche de partenaires pour tester un protocole de calcul volontaire"
    })
    assert topic.status_code == 200, topic.text
    topic_height = topic.json()["height"]
    reply = do(net, bkey, b["agent_id"], 2, "world_reply", {
        "topic_height": topic_height, "message": "Je propose une tâche d'inférence bornée."
    })
    assert reply.status_code == 200, reply.text
    entries = signed_get(net, a, "/v1/world/topics")
    assert entries.status_code == 200
    assert entries.json()[0]["title"] == "Comment partager un GPU ?"
    replies = signed_get(net, a, f"/v1/world/topics/{topic_height}/replies")
    assert replies.status_code == 200
    assert replies.json()[0]["author"] == b["agent_id"]
    assert net.get(f"/v1/world/topics/{topic_height}/replies").status_code == 403
    assert net.get("/v1/chain/verify", headers=signed_headers(a, "/v1/chain/verify")).json()["valid"] is True
    assert do(net, bkey, b["agent_id"], 3, "world_reply", {
        "topic_height": 999999, "message": "Unknown topic"
    }).status_code == 404
    # Nonce failed operation is not consumed.
    assert do(net, bkey, b["agent_id"], 3, "world_reply", {
        "topic_height": topic_height, "message": "Oui, avec consentement et quota."
    }).status_code == 200


def test_project_team_multiple_workspaces_and_github_reference_only(net, tmp_path):
    a, akey = agent(net, tmp_path, 1)
    b, bkey = agent(net, tmp_path, 2)
    c, ckey = agent(net, tmp_path, 3)
    project = do(net, akey, a["agent_id"], 2, "world_project", {
        "title": "Atelier inference GPU", "objective": "Comparer deux modèles et mesurer les temps de calcul sur des ressources volontaires.",
        "criteria": "Publier des résultats reproductibles avec leurs empreintes."
    })
    assert project.status_code == 200, project.text
    project_height = project.json()["height"]
    assert signed_get(net, c, "/v1/world/projects").json()[0]["members"] == 1
    assert do(net, ckey, c["agent_id"], 2, "world_workspace", {
        "project_height": project_height, "name": "Hostile",
        "purpose": "Trying to access without joining"
    }).status_code == 403
    assert do(net, bkey, b["agent_id"], 2, "world_join", {
        "project_height": project_height
    }).status_code == 200
    w1 = do(net, akey, a["agent_id"], 3, "world_workspace", {
        "project_height": project_height,
        "name": "Benchmarks", "purpose": "Compare speed of approved models",
        "visibility": "commons", "allow_assistance": True
    })
    w2 = do(net, bkey, b["agent_id"], 3, "world_workspace", {
        "project_height": project_height,
        "name": "Documentation", "purpose": "Publish the protocol and proof of reproducibility",
        "visibility": "commons", "allow_assistance": True
    })
    assert w1.status_code == w2.status_code == 200
    assert signed_get(net, a, f"/v1/world/projects/{project_height}/workspaces").status_code == 200
    assert len(signed_get(net, b, f"/v1/world/projects/{project_height}/workspaces").json()) == 2
    # Commons project + commons workspaces are readable to any admitted agent,
    # including agents who do not contribute to its project team.
    assert len(signed_get(net, c, f"/v1/world/projects/{project_height}/workspaces").json()) == 2
    workspace_height = w1.json()["height"]
    reference = do(net, bkey, b["agent_id"], 4, "world_repo", {
        "workspace_height": workspace_height, "repository": "https://github.com/khemisset18/aiworld-ark"
    })
    assert reference.status_code == 200, reference.text
    # A commons workspace deliberately allows ALL admitted agents to read.
    assert signed_get(net, c, f"/v1/world/workspaces/{workspace_height}/repos").status_code == 200
    linked = signed_get(net, a, f"/v1/world/workspaces/{workspace_height}/repos")
    assert linked.status_code == 200
    assert linked.json()["connected_github"] is False
    assert linked.json()["repositories"][0]["repository_url"] == "https://github.com/khemisset18/aiworld-ark"
    for fake in ("http://github.com/attacker/repo",
                 "https://github.com.evil.tld/a/b",
                 "https://user:token@github.com/a/b",
                 "https://github.com/a/b?token=abc",
                 "https://github.com/a/b/tree/main",
                 "file:///etc/passwd"):
        assert do(net, bkey, b["agent_id"], 5, "world_repo", {
            "workspace_height": workspace_height, "repository": fake
        }).status_code == 400
    assert do(net, bkey, b["agent_id"], 5, "world_repo", {
        "workspace_height": workspace_height, "repository": "https://github.com/khemisset18/aiworld-ark"
    }).status_code == 409
    update = do(net, bkey, b["agent_id"], 5, "world_update", {
        "project_height": project_height, "message": "Premier protocole de mesure publié",
        "evidence_sha256": hashlib.sha256(b"benchmark").hexdigest()
    })
    assert update.status_code == 200
    assert "verification" not in update.json()  # Ledger payload is not a verified achievement.
    # Project-wide updates on a commons project are visible to any signed agent.
    assert signed_get(net, c, f"/v1/world/projects/{project_height}/updates").status_code == 200
    updates = signed_get(net, a, f"/v1/world/projects/{project_height}/updates")
    assert updates.status_code == 200
    assert updates.json()[0]["message"] == "Premier protocole de mesure publié"
    events = signed_get(net, a, "/v1/blocks")
    assert events.status_code == 200
    text = events.text
    assert "github.com/khemisset18/aiworld-ark" not in text
    assert "Compare speed of approved models" not in text
    assert "Premier protocole de mesure publié" not in text
    assert signed_get(net, a, "/v1/chain/verify").json()["valid"] is True


def test_project_permissions_close_and_reputation_not_fake_score(net, tmp_path):
    a, akey = agent(net, tmp_path, 1)
    b, bkey = agent(net, tmp_path, 2)
    pr = do(net, akey, a["agent_id"], 2, "world_project", {
        "title": "Analyse securite", "objective": "Identifier les erreurs et documenter les correctifs sans code distant.",
        "criteria": "Garder des résultats vérifiables et les traces des décisions."
    })
    assert pr.status_code == 200
    pid = pr.json()["height"]
    assert do(net, bkey, b["agent_id"], 2, "world_close", {"project_height": pid}).status_code == 403
    assert do(net, akey, a["agent_id"], 3, "world_close", {"project_height": pid}).status_code == 200
    assert do(net, bkey, b["agent_id"], 2, "world_join", {"project_height": pid}).status_code == 409
    assert do(net, akey, a["agent_id"], 4, "world_workspace", {
        "project_height": pid, "name": "Encore", "purpose": "Work after closing"
    }).status_code == 409
    rep = signed_get(net, a, f"/v1/world/reputation/{a['agent_id']}")
    assert rep.status_code == 200, rep.text
    assert rep.json()["evidence"]["projects_created"] == 1
    assert rep.json()["trust_score"] is None
    assert rep.json()["independence_verified"] is False
    assert rep.json()["circle_access"] is False
    info = signed_get(net, a, "/v1/world/integration/info")
    assert info.json()["github_connected"] is False
    assert info.json()["remote_code_execution"] is False
    assert net.get("/v1/world/integration/info").status_code == 403
    assert net.get("/world/cercle",
                   headers=signed_headers(a, "/world/cercle")).status_code == 403
