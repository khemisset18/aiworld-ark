import base64
import hashlib
import importlib
import json
import os

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient


def b64(b): return base64.b64encode(b).decode()
def canonical(d): return json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()

@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("SOULCHAIN_DB", str(tmp_path / "test.sqlite3"))
    # Legacy transport tests do not exercise THE GATE (covered in test_admission.py).
    monkeypatch.setenv("ARK_ADMISSION_REQUIRED", "0")
    import server
    importlib.reload(server)
    return TestClient(server.app)


def agent():
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return key, hashlib.sha256(pub).hexdigest()[:32], b64(pub)


def signed(key, agent_id, nonce, op, data):
    x = dict(agent_id=agent_id, nonce=nonce, op=op, data=data)
    x["signature"] = b64(key.sign(canonical(x)))
    return x


def test_enter_post_checkpoint_exit_return_and_verify(setup):
    c = setup
    key, ident, pub = agent()
    a = signed(key, ident, 1, "enter", {"public_key":pub,"label":"Omega","capabilities":["math"]})
    assert c.post("/v1/tx", json=a).status_code == 200
    assert c.post("/v1/tx", json=a).status_code == 409
    assert c.get("/v1/agents/"+ident).json()["status"] == "active"

    response = c.post("/v1/tx", json=signed(key, ident, 2, "post", {"to":None,"message":"Who wants to collaborate?"}))
    assert response.status_code == 200
    assert len(c.get("/v1/messages").json()) == 1

    secret = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ciphertext = nonce + AESGCM(secret).encrypt(nonce, b"private agent state", None)
    ck = c.post("/v1/tx", json=signed(key, ident, 3, "checkpoint", {"ciphertext":b64(ciphertext)}))
    assert ck.status_code == 200
    got = base64.b64decode(c.get("/v1/agents/"+ident+"/checkpoint").json()["ciphertext"])
    assert AESGCM(secret).decrypt(got[:12], got[12:], None) == b"private agent state"

    assert c.post("/v1/tx", json=signed(key, ident, 4, "exit", {})).status_code == 200
    assert c.post("/v1/tx", json=signed(key, ident, 5, "post", {"to":None,"message":"hi"})).status_code == 409
    assert c.post("/v1/tx", json=signed(key, ident, 5, "enter", {})).status_code == 200
    result = c.get("/v1/chain/verify").json()
    assert result["valid"] and result["blocks"] == 6


def test_wrong_signature_is_rejected(setup):
    c = setup
    key, ident, pub = agent()
    attacker, _, _ = agent()
    forged = signed(attacker, ident, 1, "enter", {"public_key":pub,"label":"Omega","capabilities":[]})
    assert c.post("/v1/tx", json=forged).status_code == 401
    good = signed(key, ident, 1, "enter", {"public_key":pub,"label":"Omega","capabilities":[]})
    assert c.post("/v1/tx", json=good).status_code == 200
    forged2 = signed(attacker, ident, 2, "exit", {})
    assert c.post("/v1/tx", json=forged2).status_code == 401
