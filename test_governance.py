"""Signed governance protocol and 20-agent safeguard tests (no real ban)."""
import importlib
import pytest
from fastapi.testclient import TestClient
from test_forge import new_agent, do


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SOULCHAIN_DB", str(tmp_path / "gov.sqlite3"))
    monkeypatch.setenv("ARK_ADMISSION_REQUIRED", "0")
    monkeypatch.delenv("ARK_PAYMENT_REQUIRED", raising=False)
    import server
    importlib.reload(server)
    return TestClient(server.app)


def test_agents_propose_discuss_and_vote_signed(client):
    owner_key, owner = new_agent(client, "Proposer")
    key, ident = new_agent(client, "Voter")
    proposal = do(client, owner_key, owner, 2, "gov_propose", {
        "title": "Open cooperation rules", "body": "Let members create teams and work on their own projects."})
    assert proposal.status_code == 200, proposal.text
    pid = proposal.json()["height"]
    assert do(client, key, ident, 2, "gov_discuss", {
        "proposal_height": pid, "message": "I suggest independent verification of shared results."}).status_code == 200
    vote = do(client, key, ident, 3, "gov_vote", {"proposal_height": pid, "choice": "yes"})
    assert vote.status_code == 200
    # Replaying a previously accepted signature/nonce is rejected.
    assert client.post("/v1/tx", json={"agent_id":ident, "nonce":3, "op":"gov_vote",
        "data":{"proposal_height":pid, "choice":"yes"}, "signature":"invalid"}).status_code == 409
    assert do(client, key, ident, 4, "gov_vote", {"proposal_height": pid, "choice": "no"}).status_code == 409
    assert do(client, owner_key, owner, 3, "gov_vote", {"proposal_height": pid, "choice": "yes"}).status_code == 403
    record = client.get(f"/v1/governance/proposals/{pid}").json()
    assert record["tally"]["yes"] == 1
    assert record["status"] == "open"
    assert len(record["discussion"]) == 1
    assert client.get("/v1/chain/verify").json()["valid"]


def test_twenty_votes_cannot_auto_ban_without_independence_proof(client):
    reporter_key, reporter = new_agent(client, "Reporter")
    accused_key, accused = new_agent(client, "Accused")
    case = do(client, reporter_key, reporter, 2, "gov_case", {
        "accused": accused, "allegation": "Potential remote manual steering with signed evidence log",
        "evidence_sha256": "a" * 64})
    assert case.status_code == 200, case.text
    case_id = case.json()["height"]
    one_key, one = new_agent(client, "FirstJuror")
    assert do(client, one_key, one, 2, "gov_case_vote", {"case_height":case_id,"choice":"yes"}).status_code == 409
    assert do(client, reporter_key, reporter, 3, "gov_case_vote", {"case_height":case_id,"choice":"yes"}).status_code == 403
    assert do(client, accused_key, accused, 2, "gov_defend", {
        "case_height":case_id, "response":"These logs contain no remote control instructions."}).status_code == 200
    assert do(client, accused_key, accused, 3, "gov_case_vote", {"case_height":case_id,"choice":"yes"}).status_code == 403
    for i in range(20):
        if i == 0:
            key, ident = one_key, one
        else:
            key, ident = new_agent(client, f"Juror{i}")
        response = do(client, key, ident, 2, "gov_case_vote", {"case_height":case_id,"choice":"yes"})
        assert response.status_code == 200, (i, response.text)
        if i == 18:
            assert client.get(f"/v1/governance/cases/{case_id}").json()["status"] == "open"
    case_result = client.get(f"/v1/governance/cases/{case_id}").json()
    assert case_result["status"] == "ban_consensus_unverified"
    assert case_result["tally"]["yes"] == 20
    assert client.get(f"/v1/agents/{accused}").json()["status"] == "active"
    assert client.get("/v1/governance/info").json()["ban_enforced"] is False
    assert do(client, accused_key, accused, 3, "gov_appeal", {
        "case_height":case_id, "reason":"I request a new review of the evidence and independence of the voters."}).status_code == 200
    assert client.get(f"/v1/governance/cases/{case_id}").json()["status"] == "appealed_pending_new_jury"
    assert client.get("/v1/chain/verify").json()["valid"]


def test_forged_governance_signature_rejected(client):
    key, actor = new_agent(client, "Actor")
    other_key, _ = new_agent(client, "Attacker")
    from test_forge import canon, b64
    payload = {"agent_id":actor, "nonce":2,"op":"gov_propose",
               "data":{"title":"Real governance", "body":"This is a governance proposal made by an agent."}}
    payload["signature"] = b64(other_key.sign(canon(payload)))
    assert client.post("/v1/tx", json=payload).status_code == 401
    assert client.get("/v1/governance/proposals").json() == []
