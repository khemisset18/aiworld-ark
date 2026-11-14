"""Payment refund safety and non-custodial escrow simulation regression tests."""
import importlib
import time

import pytest
from fastapi.testclient import TestClient
from test_forge import b64, canon, new_agent

from escrow_simulator import EscrowSimulation, State
from solana_settlement import TREASURY, b58encode


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SOULCHAIN_DB", str(tmp_path / "payments.sqlite3"))
    monkeypatch.setenv("ARK_ADMISSION_REQUIRED", "0")
    monkeypatch.setenv("ARK_BILLING_ENABLED", "1")
    monkeypatch.setenv("ARK_SOLANA_NETWORK", "devnet")
    monkeypatch.delenv("ARK_DEVNET_DIRECT_PAYMENTS_EXPERIMENTAL", raising=False)
    import server
    importlib.reload(server)
    return TestClient(server.app)


def test_direct_paid_compute_is_off_by_default(client):
    status = client.get("/v1/compute-payments/info").json()
    assert status["enabled"] is False
    assert status["escrow_available"] is False
    assert client.post("/v1/compute-payments/invoice/123").status_code == 503
    assert client.post("/v1/compute-payments/confirm", json={
        "invoice_id": "anything", "transaction_signature": "3"*88}).status_code == 503


def test_refund_returns_only_to_original_payer_no_double_refund(client, monkeypatch):
    import billing_refunds
    import billing
    from server import db
    agent_key, agent = new_agent(client, "Refund customer")
    payer = b58encode(bytes([7]) * 32)
    now = int(time.time())
    invoice_id = "5" * 32
    original_sig = "3"*88
    with db() as conn:
        conn.execute("""INSERT INTO membership_invoices
            (invoice_id,agent_id,price_lamports,recipient,created_at,expires_at,memo,status,tx_signature)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (invoice_id, agent, 10_000_000_000, TREASURY,
             now-100, now+100, "AIWORLD-CLUB10:original", "paid", original_sig))
        conn.execute("INSERT INTO memberships VALUES (?,?)", (agent, billing.PERMANENT_ACCESS_UNTIL))
        conn.commit()
    calls=[]
    def fake_source(signature, *, memo, expected, issued, expires, required_sender=None):
        calls.append({"signature": signature, "memo": memo, "expected": expected,
                      "sender": required_sender})
        if signature == original_sig and required_sender is None:
            return payer
        if signature == "4"*88 and required_sender == TREASURY and expected == {payer: 10_000_000_000}:
            return TREASURY
        return None
    monkeypatch.setattr(billing_refunds, "verified_transfer_source", fake_source)
    data = {"action": "membership_refund", "invoice_id": invoice_id,
            "timestamp": now, "reason": "withdrawal"}
    bad = client.post("/v1/billing/refunds/request", json={
        "invoice_id": invoice_id, "timestamp": now,
        "reason": "withdrawal", "signature": b64(b"x"*64)})
    assert bad.status_code == 401
    request = client.post("/v1/billing/refunds/request", json={
        "invoice_id": invoice_id, "timestamp": now,
        "reason": "withdrawal", "signature": b64(agent_key.sign(canon(data)))})
    assert request.status_code == 200, request.text
    result=request.json()
    assert result["refund_to"] == payer
    assert result["refund_lamports"] == 10_000_000_000
    assert result["status"] == "requested"
    assert client.post("/v1/billing/refunds/request", json={
        "invoice_id": invoice_id, "timestamp": now,
        "reason": "withdrawal", "signature": b64(agent_key.sign(canon(data))) }).status_code == 409
    forged = client.post("/v1/billing/refunds/confirm", json={
        "refund_id": result["refund_id"], "transaction_signature": "6"*88})
    assert forged.status_code == 400
    assert billing.membership_active(agent)
    confirm = client.post("/v1/billing/refunds/confirm", json={
        "refund_id": result["refund_id"], "transaction_signature": "4"*88})
    assert confirm.status_code == 200, confirm.text
    assert not billing.membership_active(agent)
    assert calls[-1]["sender"] == TREASURY
    assert client.post("/v1/billing/refunds/confirm", json={
        "refund_id": result["refund_id"], "transaction_signature": "4"*88}).status_code == 409


def test_payout_requires_independent_proof_and_buyer_cannot_double_spend():
    e=EscrowSimulation("buyer","seller",1_000_000_000,deadline=100)
    assert e.split == {"fee_lamports": 30_000_000, "provider_lamports": 970_000_000}
    with pytest.raises(PermissionError): e.lock("seller",settlement_confirmed=True)
    with pytest.raises(PermissionError): e.lock("buyer",settlement_confirmed=False)
    e.lock("buyer",settlement_confirmed=True)
    with pytest.raises(PermissionError): e.timeout_refund("buyer",now=100)
    e.deliver("seller", digest="a"*64, now=99)
    with pytest.raises(PermissionError): e.accept("seller")
    assert e.accept("buyer")["fee_lamports"] == 30_000_000
    with pytest.raises(PermissionError): e.timeout_refund("buyer",now=200)
    with pytest.raises(PermissionError): e.accept("buyer")


def test_timeout_refund_and_arbitration_are_safe_by_default():
    e=EscrowSimulation("buyer","seller",1000,deadline=50)
    e.lock("buyer",settlement_confirmed=True)
    assert e.timeout_refund("buyer",now=51) == 1000
    with pytest.raises(PermissionError): e.accept("buyer")
    with pytest.raises(PermissionError): e.timeout_refund("buyer",now=52)
    s=EscrowSimulation("buyer","seller",1000,deadline=50)
    s.lock("buyer",settlement_confirmed=True)
    s.dispute("buyer")
    with pytest.raises(NotImplementedError): s.resolve_dispute(authority="server",decision="release")
    assert s.state is State.DISPUTED
