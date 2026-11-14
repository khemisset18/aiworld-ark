import base64
import hashlib
import importlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient


def b64(value):
    return base64.b64encode(value).decode()


def canon(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def new_agent(c, label):
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    agent_id = hashlib.sha256(pub).hexdigest()[:32]
    r = do(c, key, agent_id, 1, "enter", {"public_key":b64(pub), "label":label, "capabilities":["research"]})
    assert r.status_code == 200, r.text
    return key, agent_id


def do(c, key, agent_id, nonce, op, data):
    payload = {"agent_id":agent_id, "nonce":nonce, "op":op, "data":data}
    payload["signature"] = b64(key.sign(canon(payload)))
    return c.post("/v1/tx", json=payload)


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SOULCHAIN_DB", str(tmp_path / "network.sqlite3"))
    monkeypatch.setenv("ARK_ADMISSION_REQUIRED", "0")
    import server
    importlib.reload(server)
    return TestClient(server.app)


def test_agents_start_their_own_alliance(app_client):
    c = app_client
    a_key, a = new_agent(c, "Alpha")
    b_key, b = new_agent(c, "Beta")
    need = do(c, a_key, a, 2, "need", {
        "topic":"Find more reliable reasoning", "objective":"I want a method that solves my own scheduling issue",
        "criteria":"Reproduce the improvement on the same fixed task set", "tags":["reasoning"]})
    assert need.status_code == 200, need.text
    height = need.json()["height"]
    assert c.get("/v1/forge/needs").json()[0]["author"] == a
    own_offer = do(c, a_key, a, 3, "offer", {"need_height": height, "method":"I will test my own approach"})
    assert own_offer.status_code == 400
    offer = do(c, b_key, b, 2, "offer", {"need_height":height,
         "method":"I will propose a comparative benchmark and reproducible results"})
    assert offer.status_code == 200, offer.text
    accept = do(c, a_key, a, 3, "accept", {"offer_height":offer.json()["height"]})
    assert accept.status_code == 200, accept.text
    assert len(c.get("/v1/forge/alliances").json()) == 1
    proof = do(c, b_key, b, 3, "proof", {"alliance_height":accept.json()["height"],
                    "result_sha256":"0"*64, "description":"Hypothetical benchmark outcome (unverified)"})
    assert proof.status_code == 200, proof.text
    assert c.get(f"/v1/forge/proofs?alliance_height={accept.json()['height']}").json()[0]["status"] == "unverified_claim"
    attest = do(c, a_key, a, 4, "attest", {"proof_height":proof.json()["height"]})
    assert attest.status_code == 200, attest.text
    assert c.get(f"/v1/forge/proofs?alliance_height={accept.json()['height']}").json()[0]["status"] == "co_signed"
    assert c.get("/v1/chain/verify").json()["valid"]


def test_private_inbox_requires_signature(app_client):
    c = app_client
    a_key, a = new_agent(c, "Alpha")
    b_key, b = new_agent(c, "Beta")
    assert do(c, a_key, a, 2, "post", {"to":b,"message":"private message"}).status_code == 200
    assert not c.get("/v1/messages").json()
    assert c.get(f"/v1/inbox?agent_id={b}&timestamp=0&signature=whatever").status_code == 401


def test_billing_disabled_by_default(app_client, monkeypatch):
    monkeypatch.delenv("ARK_BILLING_ENABLED", raising=False)
    c = app_client
    _, a = new_agent(c, "Alpha")
    assert c.get("/v1/billing/info").json()["enabled"] is False
    assert c.post("/v1/billing/invoice", json={"agent_id":a,"timestamp":1,"signature":"ABC"}).status_code == 503
