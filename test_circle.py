"""Cercle candidacy: signed, one key / ballot, but never automatic access.

The 20-key test intentionally disables the 10-founders flag ONLY within an
isolated local test. It does not represent 20 independent autonomous agents or
live verified Solana payments. Room 2 stays HTTP 403 in every scenario.
"""
from __future__ import annotations

import hashlib
import sqlite3

from test_forge import do
from test_private_agent_network import net, signed_headers
from test_world_space import agent


def get(c, record, path):
    return c.get(path, headers=signed_headers(record, path))


def test_circle_application_eligibility_is_advisory_and_member_only(net, tmp_path):
    a, ka = agent(net, tmp_path, 1)
    b, kb = agent(net, tmp_path, 2)
    assert net.get("/v1/circle/info").status_code == 403
    assert net.get("/v1/circle/applications").status_code == 403
    info = get(net, a, "/v1/circle/info").json()
    assert info["yes_key_target"] == 20
    assert info["independent_agents_verified"] is False
    assert info["circle_access_enabled"] is False

    application = do(net, ka, a["agent_id"], 2, "circle_apply", {
        "statement": "Je demande à participer aux projets collectifs du Cercle, "
                     "en documentant mes contributions vérifiables.",
        "evidence_sha256": hashlib.sha256(b"sample-evidence").hexdigest(),
    })
    assert application.status_code == 200, application.text
    cid = application.json()["height"]
    assert "Je demande" not in get(net, a, "/v1/blocks").text
    assert do(net, ka, a["agent_id"], 3, "circle_vote", {
        "application_height": cid, "choice": "yes",
        "rationale": "Je me recommande moi-même"
    }).status_code == 403
    first = do(net, kb, b["agent_id"], 2, "circle_vote", {
        "application_height": cid, "choice": "yes",
        "rationale": "Contributions observées, mais autonomie non prouvée"
    })
    assert first.status_code == 200, first.text
    assert first.json()["payload"]["circle_access_granted"] is False
    assert first.json()["payload"]["independent_voters_verified"] is False
    assert do(net, kb, b["agent_id"], 3, "circle_vote", {
        "application_height": cid, "choice": "no",
        "rationale": "Seconde tentative de voter"
    }).status_code == 409
    detail = get(net, a, f"/v1/circle/applications/{cid}")
    assert detail.status_code == 200
    assert detail.json()["tally"]["yes"] == 1
    assert detail.json()["tally"]["yes_key_threshold_met"] is False
    assert get(net, b, "/v1/circle/applications").json()[0]["height"] == cid
    assert get(net, b, "/v1/circle/applications").json()[0]["tally"]["no"] == 0
    assert get(net, a, "/world/cercle").status_code == 403
    assert do(net, kb, b["agent_id"], 3, "circle_withdraw", {
        "application_height": cid
    }).status_code == 403
    assert do(net, ka, a["agent_id"], 3, "circle_withdraw", {
        "application_height": cid
    }).status_code == 200
    assert do(net, kb, b["agent_id"], 3, "circle_vote", {
        "application_height": cid, "choice": "yes",
        "rationale": "Plus possible après le retrait"
    }).status_code == 409


def test_twenty_distinct_signing_keys_do_not_unlock_room(net, tmp_path, monkeypatch):
    # Future paid users are NOT simulated here; only the raw voting condition.
    # This isolated test's flag change must never be a production deployment.
    monkeypatch.setenv("ARK_FOUNDERS_10_FREE", "0")
    a, ka = agent(net, tmp_path, 1)
    application = do(net, ka, a["agent_id"], 2, "circle_apply", {
        "statement": "Candidature pour étude : compétences, projets, "
                     "preuves signées, participation responsable et sécurité.",
        "evidence_sha256": hashlib.sha256(b"reproducible-work").hexdigest(),
    })
    assert application.status_code == 200
    cid = application.json()["height"]
    for i in range(2, 22):
        b, kb = agent(net, tmp_path, i)
        signed_vote = do(net, kb, b["agent_id"], 2, "circle_vote", {
            "application_height": cid, "choice": "yes",
            "rationale": "Soutien seulement indicatif, identité indépendante non vérifiée",
        })
        assert signed_vote.status_code == 200, (i, signed_vote.text)
    detail = get(net, a, f"/v1/circle/applications/{cid}")
    assert detail.status_code == 200
    status = detail.json()
    assert status["status"] == "threshold_unverified"
    assert status["tally"]["yes"] == 20
    assert status["tally"]["yes_key_threshold_met"] is True
    assert status["tally"]["independent_voters_verified"] is False
    assert status["tally"]["circle_access_granted"] is False
    assert get(net, a, "/world/cercle").status_code == 403
    assert get(net, b, "/world/cercle").status_code == 403


def test_circle_supermajority_does_not_equate_key_count_to_independent_agents():
    import circle
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    circle.setup(db)
    for i in range(1, 32):
        db.execute("INSERT INTO circle_ballots VALUES(?,?,?,?,?,?)",
                   (i, 123, "key" + str(i), "yes" if i <= 20 else "no",
                    "Rationale in test database", 1))
    tally = circle.tally(db, 123)
    assert tally["yes"] == 20 and tally["no"] == 11
    assert tally["yes_key_threshold_met"] is False  # 20 / 31 < 2/3
    assert tally["independent_voters_verified"] is False
    assert tally["circle_access_granted"] is False
