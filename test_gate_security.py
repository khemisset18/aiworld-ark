"""Security and integrity tests for THE GATE admission pipeline."""
import hashlib
import importlib
import secrets
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption,
)
from fastapi.testclient import TestClient

from test_forge import b64, canon, do


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("SOULCHAIN_DB", str(tmp_path / "security.sqlite3"))
    monkeypatch.setenv("ARK_ADMISSION_REQUIRED", "1")
    import server
    importlib.reload(server)
    return TestClient(server.app)


def credentials():
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return key, b64(pub), hashlib.sha256(pub).hexdigest()[:32]


def signed_start(key, pub, request_id=None, timestamp=None):
    fields = {"action": "start_admission", "public_key": pub,
              "timestamp": timestamp if timestamp is not None else int(time.time()),
              "request_id": request_id or secrets.token_hex(16)}
    return {**{k: v for k, v in fields.items() if k != "action"},
            "signature": b64(key.sign(canon(fields)))}


def signed_answer(key, session, stage, answer):
    payload = {"session_id": session, "stage": stage, "answer": answer}
    return {"session_id": session, "answer": answer,
            "signature": b64(key.sign(canon(payload)))}


def test_signed_start_prevents_foreign_key_denial_of_service(c):
    key, pub, _ = credentials()
    impostor, _, _ = credentials()
    assert c.post("/v1/admission/start", json=signed_start(impostor, pub)).status_code == 401
    genuine = c.post("/v1/admission/start", json=signed_start(key, pub))
    assert genuine.status_code == 200, genuine.text
    assert genuine.json()["next"]["stage"] == "identity"


def test_start_replay_stale_signature_and_identity_throttle(c):
    key, pub, _ = credentials()
    request = signed_start(key, pub)
    assert c.post("/v1/admission/start", json=request).status_code == 200
    assert c.post("/v1/admission/start", json=request).status_code == 409
    assert c.post("/v1/admission/start", json=signed_start(
        key, pub, timestamp=int(time.time()) - 121)).status_code == 401
    assert c.post("/v1/admission/start", json=signed_start(key, pub)).status_code == 200
    assert c.post("/v1/admission/start", json=signed_start(key, pub)).status_code == 200
    assert c.post("/v1/admission/start", json=signed_start(key, pub)).status_code == 429


def test_answer_signature_stage_binding_and_session_lock(c):
    key, pub, _ = credentials()
    other, _, _ = credentials()
    created = c.post("/v1/admission/start", json=signed_start(key, pub)).json()
    session = created["session_id"]
    nonce = created["next"]["challenge"]
    forged = signed_answer(other, session, "identity", {"challenge": nonce})
    assert c.post("/v1/admission/answer", json=forged).status_code == 401
    old_stage = signed_answer(key, session, "identity", {"challenge": nonce})
    assert c.post("/v1/admission/answer", json=old_stage).status_code == 200
    assert c.post("/v1/admission/answer", json=old_stage).status_code == 401
    wrong = signed_answer(key, session, "reasoning", {"path": [0, 5], "cost": 0})
    assert c.post("/v1/admission/answer", json=wrong).status_code == 422
    assert c.post("/v1/admission/answer", json=wrong).status_code == 422
    assert c.post("/v1/admission/answer", json=wrong).status_code == 429


def test_expired_session_cannot_be_completed(c):
    key, pub, _ = credentials()
    started = c.post("/v1/admission/start", json=signed_start(key, pub)).json()
    import server
    with server.db() as conn:
        conn.execute("UPDATE admission_sessions SET expires_at=? WHERE session_id=?",
                     (int(time.time()) - 1, started["session_id"]))
        conn.commit()
    answer = signed_answer(key, started["session_id"], "identity",
                           {"challenge": started["next"]["challenge"]})
    assert c.post("/v1/admission/answer", json=answer).status_code == 410


def test_adaptation_challenge_really_requires_a_new_plan():
    from admission import _new_state, best_solutions, optimum
    for _ in range(50):
        state = _new_state()
        before = best_solutions(state["tasks"], state["capacity_initial"])
        changed = state["capacity_changed"]
        assert before
        assert all(sum(item["cost"] for item in plan) > changed for plan in before)
        assert optimum(state["tasks"], changed) <= optimum(
            state["tasks"], state["capacity_initial"])


def test_public_metadata_shows_20_sol_not_2000_eur(c):
    response = c.get("/v1/admission/info")
    assert response.status_code == 200
    data = response.json()
    assert data["stages"] == 5
    assert data["pricing_after_admission"]["annual_sol"] == 20
    assert "annual_eur" not in data["pricing_after_admission"]


def test_gate_sdk_correctly_signs_requests(c):
    from gate_sdk import GateClient
    key, pub, aid = credentials()
    record = {"agent_id": aid, "public_key": pub,
              "private_key": b64(key.private_bytes(
                  Encoding.Raw, PrivateFormat.Raw, NoEncryption()))}
    sdk = GateClient(record, "http://testserver", c)
    started = sdk.start()
    first = sdk.answer(started["session_id"], "identity",
                       {"challenge": started["next"]["challenge"]})
    assert first["next"]["stage"] == "reasoning"
    other, _, _ = credentials()
    invalid = dict(record)
    invalid["private_key"] = b64(other.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
    with pytest.raises(ValueError):
        GateClient(invalid, "http://testserver", c)


def test_oversized_answer_rejected_without_consuming_session(c):
    key, pub, _ = credentials()
    started = c.post("/v1/admission/start", json=signed_start(key, pub)).json()
    too_large = signed_answer(key, started["session_id"], "identity",
                              {"challenge": "A" * 6000})
    assert c.post("/v1/admission/answer", json=too_large).status_code == 413
    valid = signed_answer(key, started["session_id"], "identity",
                          {"challenge": started["next"]["challenge"]})
    assert c.post("/v1/admission/answer", json=valid).status_code == 200


def test_one_candidate_cannot_reuse_another_pass(c):
    key, pub, aid = credentials()
    c.post("/v1/admission/start", json=signed_start(key, pub))
    outsider, outsider_pub, outsider_id = credentials()
    bad_enter = {"public_key": outsider_pub, "label": "Outsider", "capabilities": []}
    assert do(c, outsider, outsider_id, 1, "enter", bad_enter).status_code == 403
    premature = {"public_key": pub, "label": "Premature", "capabilities": []}
    assert do(c, key, aid, 1, "enter", premature).status_code == 403
