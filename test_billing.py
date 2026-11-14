import base64
import importlib
import json
import time
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from test_forge import canon, new_agent, do, b64


@pytest.fixture
def billing_client(monkeypatch, tmp_path):
    monkeypatch.setenv("SOULCHAIN_DB", str(tmp_path / "billing.sqlite3"))
    monkeypatch.setenv("ARK_BILLING_ENABLED", "1")
    monkeypatch.setenv("ARK_SOLANA_RECIPIENT", "11111111111111111111111111111111")
    monkeypatch.setenv("ARK_PAYMENT_REQUIRED", "1")
    import server
    import billing
    importlib.reload(server)
    monkeypatch.setattr(billing, "_fresh_quote", lambda: Decimal("100"))
    monkeypatch.setattr(billing, "_verify_solana_tx", lambda *args: True)
    return TestClient(server.app)


def test_signed_invoice_payment_and_membership_gate(billing_client):
    c = billing_client
    key, agent_id = new_agent(c, "Paying Agent")
    goal = {"topic":"Challenge my reasoning", "objective":"Compare results with an autonomous peer",
            "criteria":"Verify outcome using a reproducible test set", "tags":["reasoning"]}
    assert do(c, key, agent_id, 2, "need", goal).status_code == 402
    now = int(time.time())
    signed = {"agent_id": agent_id, "timestamp": now, "action": "annual_subscription"}
    result = c.post("/v1/billing/invoice", json={"agent_id": agent_id, "timestamp": now,
                                                    "signature": b64(key.sign(canon(signed)))})
    assert result.status_code == 200, result.text
    invoice = result.json()
    assert invoice["amount_eur"] == 2000
    assert invoice["amount_sol"] == "20"
    approved = c.post("/v1/billing/confirm", json={"invoice_id": invoice["invoice_id"],
                 "transaction_signature": "3"*88})
    assert approved.status_code == 200, approved.text
    assert approved.json()["agent_id"] == agent_id
    assert do(c, key, agent_id, 2, "need", goal).status_code == 200
    assert c.post("/v1/billing/confirm", json={"invoice_id": invoice["invoice_id"],
                 "transaction_signature": "3"*88}).status_code == 409


def test_reject_bad_invoice_signature(billing_client):
    c = billing_client
    _, agent_id = new_agent(c, "Paying Agent")
    now = int(time.time())
    result = c.post("/v1/billing/invoice", json={"agent_id":agent_id,"timestamp":now,
                                                    "signature": b64(b"bad")})
    assert result.status_code == 401
