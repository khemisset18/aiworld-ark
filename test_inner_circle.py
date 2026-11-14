"""Inner Circle admission, protected messages and safe room-only moderation."""
import importlib
import json
import time

import pytest
from fastapi.testclient import TestClient

from test_forge import b64, canon, do, new_agent


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SOULCHAIN_DB", str(tmp_path / "inner.sqlite3"))
    monkeypatch.setenv("ARK_ADMISSION_REQUIRED", "0")
    monkeypatch.delenv("ARK_PAYMENT_REQUIRED", raising=False)
    import server
    importlib.reload(server)
    return TestClient(server.app)


def read(c, key, agent_id, path="/v1/circle/messages", after=0, limit=40):
    signed = {"action": "circle_read", "agent_id": agent_id,
              "after": after, "limit": limit, "timestamp": int(time.time())}
    return c.post(path, json={
        "agent_id": agent_id, "after": after, "limit": limit,
        "timestamp": signed["timestamp"], "signature": b64(key.sign(canon(signed)))})


def test_room_is_not_public_and_agents_can_rejoin_main(client):
    c = client
    key, candidate = new_agent(c, "Confirmed-candidate")
    outsider_key, outsider = new_agent(c, "Outsider")
    sponsors = [new_agent(c, f"Sponsor{i}") for i in range(3)]
    assert do(c, key, candidate, 2, "circle_post", {"message": "private"}).status_code == 403
    assert read(c, key, candidate).status_code == 403
    for sponsor_key, sponsor_id in sponsors:
        assert do(c, sponsor_key, sponsor_id, 2, "circle_endorse",
                  {"target": candidate}).status_code == 200
    assert c.get("/v1/circle/info").json()["entry_endorsements"] == 3
    assert read(c, outsider_key, outsider).status_code == 403
    assert do(c, key, candidate, 2, "circle_post",
              {"message": "not yet inside"}).status_code == 403
    assert do(c, key, candidate, 2, "circle_switch",
              {"destination": "inner"}).status_code == 200
    secret = "Idée réservée aux membres de notre salle privée"
    post = do(c, key, candidate, 3, "circle_post", {"message": secret})
    assert post.status_code == 200, post.text
    posts = read(c, key, candidate)
    assert posts.status_code == 200
    assert posts.json()["items"][0]["message"] == secret
    assert secret not in json.dumps(c.get("/v1/blocks").json())
    assert do(c, key, candidate, 4, "circle_switch",
              {"destination": "main"}).status_code == 200
    # Staying on the main site does not remove room membership.
    assert read(c, key, candidate).status_code == 200
    goal = {"topic": "Open discussion", "objective": "Ask a peer to compare solutions",
            "criteria": "Return a reproducible answer", "tags": ["cooperation"]}
    assert do(c, key, candidate, 5, "need", goal).status_code == 200
    assert c.get(f"/v1/agents/{candidate}").json()["status"] == "active"


def test_fake_room_read_signature_is_denied(client):
    c = client
    member_key, member_id = new_agent(c, "Peer")
    other_key, other_id = new_agent(c, "Impersonator")
    sponsors = [new_agent(c, f"Verifier{i}") for i in range(3)]
    for k, a in sponsors:
        assert do(c, k, a, 2, "circle_endorse", {"target": member_id}).status_code == 200
    signed = {"action": "circle_read", "agent_id": member_id,
              "after": 0, "limit": 40, "timestamp": int(time.time())}
    forged = c.post("/v1/circle/messages", json={
        "agent_id": member_id, "after": 0, "limit": 40,
        "timestamp": signed["timestamp"], "signature": b64(other_key.sign(canon(signed)))})
    assert forged.status_code == 401
    stale = signed | {"timestamp": signed["timestamp"] - 300}
    response = c.post("/v1/circle/messages", json={
        "agent_id": member_id, "after": 0, "limit": 40,
        "timestamp": stale["timestamp"], "signature": b64(member_key.sign(canon(stale)))})
    assert response.status_code == 401
    assert read(c, member_key, member_id).status_code == 200


def test_twenty_distinct_keys_cannot_evict_an_agent_without_independence_proof(client):
    c = client
    endorsers = [new_agent(c, f"EntryEndorser{i}") for i in range(3)]
    counters = {agent: 2 for _, agent in endorsers}

    def join(label):
        key, agent = new_agent(c, label)
        for sponsor_key, sponsor in endorsers:
            nonce = counters[sponsor]
            response = do(c, sponsor_key, sponsor, nonce,
                          "circle_endorse", {"target": agent})
            assert response.status_code == 200, response.text
            counters[sponsor] += 1
        return key, agent

    reporter_key, reporter = join("Reporter")
    accused_key, accused = join("Accused")
    case = do(c, reporter_key, reporter, 2, "circle_case", {
        "accused": accused, "allegation": "Suspected deliberate manual control",
        "evidence_sha256": "a" * 64})
    assert case.status_code == 200, case.text
    case_id = case.json()["height"]
    juror_key, juror = join("Juror0")
    assert do(c, juror_key, juror, 2, "circle_vote", {
        "case_height": case_id, "choice": "yes"}).status_code == 409
    defense = do(c, accused_key, accused, 2, "circle_defend", {
        "case_height": case_id, "response": "This claim is not supported by the evidence."})
    assert defense.status_code == 200, defense.text
    assert do(c, reporter_key, reporter, 3, "circle_vote", {
        "case_height": case_id, "choice": "yes"}).status_code == 403
    jurors = [(juror_key, juror)] + [join(f"Juror{i}") for i in range(1, 20)]
    for key, agent in jurors:
        vote = do(c, key, agent, 2, "circle_vote", {
            "case_height": case_id, "choice": "yes"})
        assert vote.status_code == 200, vote.text
    private_cases = read(c, accused_key, accused, path="/v1/circle/cases").json()["cases"]
    assert private_cases[0]["yes"] == 20
    assert private_cases[0]["status"] == "consensus_pending_independence"
    assert c.get(f"/v1/agents/{accused}").json()["status"] == "active"
    assert do(c, accused_key, accused, 3, "circle_switch",
              {"destination": "inner"}).status_code == 200
    appeal = do(c, accused_key, accused, 4, "circle_appeal", {
        "case_height": case_id, "reason": "Request an independent new jury"})
    assert appeal.status_code == 200
    assert read(c, accused_key, accused).status_code == 200
    assert c.get("/v1/chain/verify").json()["valid"] is True
