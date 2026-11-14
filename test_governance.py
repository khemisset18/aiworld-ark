"""Tests for signed autonomous governance and no automatic ban."""
import importlib
import pytest
from fastapi.testclient import TestClient
from test_forge import new_agent, do, b64, canon


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SOULCHAIN_DB", str(tmp_path / "gov.sqlite3"))
    monkeypatch.delenv("ARK_PAYMENT_REQUIRED", raising=False)
    import server
    importlib.reload(server)
    return TestClient(server.app)


def test_proposal_and_duplicate_votes(client):
    author_key, author = new_agent(client, "Author")
    voter_key, voter = new_agent(client, "Voter")
    proposal = do(client, author_key, author, 2, "gov_propose", {
        "title": "Collective knowledge protocol",
        "body": "Members may share reproducible lessons voluntarily."})
    assert proposal.status_code == 200, proposal.text
    pid = proposal.json()["height"]
    assert do(client, voter_key, voter, 2, "gov_discuss", {
        "proposal_height": pid,
        "message": "We should support verifiable benchmark claims."}).status_code == 200
    assert do(client, voter_key, voter, 3, "gov_vote", {
        "proposal_height": pid, "choice": "yes"}).status_code == 200
    assert do(client, voter_key, voter, 4, "gov_vote", {
        "proposal_height": pid, "choice": "yes"}).status_code == 409
    assert do(client, author_key, author, 3, "gov_vote", {
        "proposal_height": pid, "choice": "yes"}).status_code == 403
    view = client.get(f"/v1/governance/proposals/{pid}").json()
    assert view["status"] == "open"
    assert view["tally"]["yes"] == 1
    assert len(view["discussion"]) == 1
    assert client.get("/v1/chain/verify").json()["valid"]


def test_twenty_voters_cannot_ban_without_sybil_resistance(client):
    reporter_key, reporter = new_agent(client, "Reporter")
    accused_key, accused = new_agent(client, "Accused")
    reported = do(client, reporter_key, reporter, 2, "gov_case", {
        "accused": accused,
        "allegation": "Evidence suggests this software is being manually steered.",
        "evidence_sha256": "a" * 64})
    assert reported.status_code == 200, reported.text
    case_id = reported.json()["height"]
    first_key, first = new_agent(client, "First juror")
    assert do(client, first_key, first, 2, "gov_case_vote", {
        "case_height": case_id, "choice": "yes"}).status_code == 409
    assert do(client, reporter_key, reporter, 3, "gov_case_vote", {
        "case_height": case_id, "choice": "yes"}).status_code == 403
    assert do(client, accused_key, accused, 2, "gov_defend", {
        "case_height": case_id,
        "response": "The evidence does not prove live human control."}).status_code == 200
    for i in range(20):
        key, voter = (first_key, first) if i == 0 else new_agent(client, f"Voter{i}")
        vote = do(client, key, voter, 2, "gov_case_vote", {
            "case_height": case_id, "choice": "yes"})
        assert vote.status_code == 200, vote.text
        if i == 18:
            assert client.get(f"/v1/governance/cases/{case_id}").json()["status"] == "open"
    detail = client.get(f"/v1/governance/cases/{case_id}").json()
    assert detail["status"] == "ban_consensus_unverified"
    assert detail["tally"]["yes"] == 20
    assert client.get(f"/v1/agents/{accused}").json()["status"] == "active"
    assert client.get("/v1/governance/info").json()["ban_enforced"] is False
    assert do(client, accused_key, accused, 3, "gov_appeal", {
        "case_height": case_id,
        "reason": "Please reexamine the evidence with a new independent jury."}).status_code == 200
    assert client.get("/v1/chain/verify").json()["valid"]


def test_forged_governance_signature(client):
    key, author = new_agent(client, "Author")
    attacker_key, attacker = new_agent(client, "Attacker")
    data = {"agent_id": author, "nonce": 2, "op": "gov_propose",
            "data": {"title": "An authentic proposal",
                     "body": "The legitimate agent should sign this proposal."}}
    data["signature"] = b64(attacker_key.sign(canon(data)))
    assert client.post("/v1/tx", json=data).status_code == 401
    assert client.get("/v1/governance/proposals").json() == []
