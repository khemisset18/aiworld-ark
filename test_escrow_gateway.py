"""Devnet escrow funding bridge regression tests; RPC mocked, no SOL transferred."""
import base64
import importlib
import time

import pytest
from fastapi.testclient import TestClient
from solders.pubkey import Pubkey
from test_forge import new_agent, do
from solana_settlement import TREASURY, b58decode, b58encode


@pytest.fixture
def demo(monkeypatch, tmp_path):
    monkeypatch.setenv("SOULCHAIN_DB", str(tmp_path / "escrow_gateway.sqlite3"))
    monkeypatch.setenv("ARK_ADMISSION_REQUIRED", "0")
    monkeypatch.setenv("ARK_BILLING_ENABLED", "1")
    monkeypatch.setenv("ARK_SOLANA_NETWORK", "devnet")
    monkeypatch.setenv("ARK_ESCROW_GATEWAY_ENABLED", "1")
    monkeypatch.setenv("ARK_ESCROW_DEPLOYMENT_VERIFIED", "1")
    program_id = b58encode(bytes([11] * 32))
    monkeypatch.setenv("ARK_ESCROW_PROGRAM_ID", program_id)
    import server
    importlib.reload(server)
    c = TestClient(server.app)
    seller_key, seller = new_agent(c, "Escrow provider")
    buyer_key, buyer = new_agent(c, "Escrow requester")
    offer = do(c, seller_key, seller, 2, "compute_offer", {
        "kinds": ["hash_chain"], "max_jobs": 2, "ttl_seconds": 3600,
        "terms": {"mode": "paid", "price_lamports": 1_000_000_000}})
    assert offer.status_code == 200, offer.text
    req = do(c, buyer_key, buyer, 2, "compute_request", {
        "capacity_height": offer.json()["height"], "kind": "hash_chain",
        "params": {"text": "a", "rounds": 10},
        "agreed_price_lamports": 1_000_000_000})
    assert req.status_code == 200, req.text
    height = req.json()["height"]
    approval = do(c, seller_key, seller, 3, "compute_authorize", {"job_height": height})
    assert approval.status_code == 200, approval.text
    import escrow_gateway as gw
    from server import db
    with db() as conn:
        seller_pub = base64.b64decode(conn.execute(
            "SELECT public_key FROM agents WHERE agent_id=?", (seller,)).fetchone()[0])
        buyer_pub = base64.b64decode(conn.execute(
            "SELECT public_key FROM agents WHERE agent_id=?", (buyer,)).fetchone()[0])
    # Anchor's exact PDA from (b"escrow", buyer, job_height), including bump.
    pda, bump = Pubkey.find_program_address(
        [b"escrow", buyer_pub, height.to_bytes(8, "little")],
        Pubkey.from_string(program_id))
    address = str(pda)
    raw = gw.DISCRIMINATOR + gw.STATE.pack(
        buyer_pub, seller_pub, bytes([13] * 32), b58decode(TREASURY),
        height, 1_000_000_000, 30_000_000,
        int(time.time()) + 600, bump, 0, bytes(32))
    account = {"owner": program_id, "executable": False,
               "lamports": 1_010_000_000, "data": [base64.b64encode(raw).decode(), "base64"]}
    return c, gw, monkeypatch, height, address, account


def test_gateway_never_enables_mainnet_or_placeholder(demo):
    c, gw, monkeypatch, height, address, account = demo
    assert c.get("/v1/escrow/info").json()["enabled"] is True
    monkeypatch.setenv("ARK_SOLANA_NETWORK", "mainnet")
    assert c.get("/v1/escrow/info").json()["enabled"] is False
    assert c.post("/v1/escrow/confirm-funded", json={
        "job_height": height, "escrow_address": address}).status_code == 503
    monkeypatch.setenv("ARK_SOLANA_NETWORK", "devnet")
    monkeypatch.setenv("ARK_ESCROW_PROGRAM_ID", gw.PLACEHOLDER_PROGRAM_ID)
    assert c.get("/v1/escrow/info").json()["enabled"] is False


def test_funded_pda_unlocks_only_the_correct_signed_job(demo):
    c, gw, monkeypatch, height, address, account = demo
    monkeypatch.setattr(gw, "get_finalized_account", lambda _: (account, 12345))
    r = c.post("/v1/escrow/confirm-funded", json={
        "job_height": height, "escrow_address": address})
    assert r.status_code == 200, r.text
    assert r.json()["onchain_state"] == "funded"
    assert r.json()["real_sol_received_by_treasury"] is False
    assert c.get(f"/v1/compute/jobs/{height}").json()["status"] == "queued"
    # One receipt cannot unlock multiple jobs, nor can it be replayed.
    assert c.post("/v1/escrow/confirm-funded", json={
        "job_height": height, "escrow_address": address}).status_code == 409
    from server import db
    with db() as conn:
        record = conn.execute("SELECT * FROM escrow_receipts").fetchall()
        assert len(record) == 1
        assert record[0]["program_id"] == account["owner"]


@pytest.mark.parametrize("mutation", [
    "owner", "price", "fee", "wrong_treasury", "wrong_buyer",
    "already_released", "deadline_passed", "zero_balance", "invalid_binary",
    "bad_pda_address", "wrong_bump",
])
def test_fake_or_insufficient_escrow_never_unblocks_job(demo, mutation):
    c, gw, monkeypatch, height, address, account = demo
    altered = dict(account)
    altered["data"] = list(account["data"])
    payload = list(gw.STATE.unpack(base64.b64decode(altered["data"][0])[8:]))
    if mutation == "owner":
        altered["owner"] = b58encode(bytes([14] * 32))
    elif mutation == "price":
        payload[5] = 900_000_000
    elif mutation == "fee":
        payload[6] = 20_000_000
    elif mutation == "wrong_treasury":
        payload[3] = bytes([14] * 32)
    elif mutation == "wrong_buyer":
        payload[0] = bytes([14] * 32)
    elif mutation == "already_released":
        payload[9] = 3
    elif mutation == "deadline_passed":
        payload[7] = int(time.time()) - 1
    elif mutation == "zero_balance":
        altered["lamports"] = 50_000_000
    elif mutation == "invalid_binary":
        altered["data"] = [base64.b64encode(b"wrong").decode(), "base64"]
    elif mutation == "bad_pda_address":
        address = b58encode(bytes([12] * 32))
    elif mutation == "wrong_bump":
        payload[8] = (payload[8] - 1) % 256
    if mutation not in ("owner", "zero_balance", "invalid_binary"):
        raw = gw.DISCRIMINATOR + gw.STATE.pack(*payload)
        altered["data"] = [base64.b64encode(raw).decode(), "base64"]
    monkeypatch.setattr(gw, "get_finalized_account", lambda _: (altered, 12345))
    response = c.post("/v1/escrow/confirm-funded", json={
        "job_height": height, "escrow_address": address})
    assert response.status_code in (400, 409), (mutation, response.text)
    assert c.get(f"/v1/compute/jobs/{height}").json()["status"] == (
        "seller_approved_awaiting_payment")


def test_gateway_rejects_rpc_outage_without_changing_job(demo):
    c, gw, monkeypatch, height, address, account = demo
    import httpx
    def unavailable(_):
        raise httpx.ConnectError("Devnet offline")
    monkeypatch.setattr(gw, "get_finalized_account", unavailable)
    assert c.post("/v1/escrow/confirm-funded", json={
        "job_height": height, "escrow_address": address}).status_code == 503
    assert c.get(f"/v1/compute/jobs/{height}").json()["status"] == (
        "seller_approved_awaiting_payment")


@pytest.mark.parametrize("onchain_final,expected_status,expected_fee,expected_refund", [
    (3, "released_to_provider", 30_000_000, 0),
    (4, "refunded_to_buyer", 0, 1_000_000_000),
])
def test_reconcile_exact_onchain_final_state(demo, onchain_final, expected_status,
                                            expected_fee, expected_refund):
    c, gw, monkeypatch, height, address, account = demo
    onchain = [account, 12345]
    monkeypatch.setattr(gw, "get_finalized_account", lambda _: tuple(onchain))
    assert c.post("/v1/escrow/confirm-funded", json={
        "job_height": height, "escrow_address": address}).status_code == 200

    # Before on-chain finalization, no financial completion can be declared.
    pending = c.post("/v1/escrow/reconcile-final", json={
        "job_height": height, "escrow_address": address})
    assert pending.status_code == 409

    fields = list(gw.STATE.unpack(base64.b64decode(account["data"][0])[8:]))
    fields[9] = onchain_final
    fields[10] = bytes([18] * 32)  # a delivery digest or mutually agreed outcome
    raw = gw.DISCRIMINATOR + gw.STATE.pack(*fields)
    onchain[0] = {**account, "lamports": 2_000_000,
                  "data": [base64.b64encode(raw).decode(), "base64"]}
    response = c.post("/v1/escrow/reconcile-final", json={
        "job_height": height, "escrow_address": address})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == expected_status
    assert response.json()["platform_fee_lamports"] == expected_fee
    assert response.json()["buyer_refund_lamports"] == expected_refund
    recorded = c.get(f"/v1/escrow/receipts/{height}")
    assert recorded.status_code == 200
    assert recorded.json()["final_status"] == expected_status
    again = c.post("/v1/escrow/reconcile-final", json={
        "job_height": height, "escrow_address": address})
    assert again.status_code == 200
    assert again.json()["already_reconciled"] is True
