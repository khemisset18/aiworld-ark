"""Tests for devnet membership, exact 3% split, finalized tx and replay safety."""
import importlib
import time

import pytest
from fastapi.testclient import TestClient
from test_forge import new_agent, do
import solana_settlement as sol


def test_solana_base58_and_platform_address():
    assert sol.valid_address(sol.TREASURY)
    assert sol.b58encode(sol.b58decode(sol.TREASURY)) == sol.TREASURY
    assert sol.b58encode(bytes(32)) == '1' * 32
    assert not sol.valid_address('not-a-wallet!')
    assert len(sol.b58decode('3' * 88)) == 64


def test_confirm_both_sol_transfers_and_unique_memo(monkeypatch):
    payer = sol.b58encode(bytes([8]) * 32)
    provider = sol.b58encode(bytes([7]) * 32)
    sig = sol.b58encode(bytes([6]) * 64)
    now = int(time.time())
    def transfer(dst, amount, src=payer):
        return {"program": "system", "parsed": {"type": "transfer", "info": {
            "source": src, "destination": dst, "lamports": amount}}}
    def tx(*, fee=30_000_000, provider_payment=970_000_000, source=payer, memo='JOB:1'):
        return {"meta": {"err": None}, "blockTime": now, "transaction": {
            "signatures": [sig], "message": {"instructions": [
                transfer(provider, provider_payment), transfer(sol.TREASURY, fee, source),
                {"program": "spl-memo", "parsed": memo}
            ]}}}
    monkeypatch.setattr(sol, '_transaction', lambda _signature: tx())
    expected = {provider: 970_000_000, sol.TREASURY: 30_000_000}
    def verified():
        return sol.verify_transfers(sig, memo='JOB:1', expected=expected, issued=now - 5, expires=now + 5)
    assert verified()
    for params in ({'fee': 20_000_000}, {'provider_payment': 960_000_000},
                   {'source': sol.b58encode(bytes([5]) * 32)}, {'memo': 'wrong'}):
        monkeypatch.setattr(sol, '_transaction', lambda _signature, p=params: tx(**p))
        assert not verified(), params
    monkeypatch.setattr(sol, '_transaction', lambda _signature: {**tx(), 'meta': {'err': 'failed'}})
    assert not verified()


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv('SOULCHAIN_DB', str(tmp_path / 'settle.sqlite3'))
    monkeypatch.setenv('ARK_ADMISSION_REQUIRED', '0')
    monkeypatch.setenv('ARK_BILLING_ENABLED', '1')
    monkeypatch.setenv('ARK_DEVNET_DIRECT_PAYMENTS_EXPERIMENTAL', '1')
    monkeypatch.setenv('ARK_SOLANA_NETWORK', 'devnet')
    monkeypatch.delenv('ARK_PAYMENT_REQUIRED', raising=False)
    import server
    importlib.reload(server)
    return TestClient(server.app)


def test_paid_compute_invoice_requires_provider_permission_and_exact_split(client, monkeypatch):
    import compute_payments
    c = client
    private_seller, seller = new_agent(c, 'Seller')
    private_buyer, buyer = new_agent(c, 'Buyer')
    quote = do(c, private_seller, seller, 2, 'compute_offer', {
        'kinds': ['hash_chain'], 'ttl_seconds': 3600, 'max_jobs': 2,
        'terms': {'mode': 'paid', 'price_lamports': 1_000_000_000}})
    assert quote.status_code == 200, quote.text
    offer = quote.json()['height']
    request = do(c, private_buyer, buyer, 2, 'compute_request', {
        'capacity_height': offer, 'kind': 'hash_chain',
        'params': {'text': 'hello', 'rounds': 5}, 'agreed_price_lamports': 1_000_000_000})
    assert request.status_code == 200, request.text
    job = request.json()['height']
    assert c.post(f'/v1/compute-payments/invoice/{job}').status_code == 409
    approved = do(c, private_seller, seller, 3, 'compute_authorize', {'job_height': job})
    assert approved.status_code == 200, approved.text
    response = c.post(f'/v1/compute-payments/invoice/{job}')
    assert response.status_code == 200, response.text
    invoice = response.json()
    assert invoice['price_lamports'] == 1_000_000_000
    assert invoice['provider_lamports'] == 970_000_000
    assert invoice['platform_fee_lamports'] == 30_000_000
    assert invoice['platform_wallet'] == sol.TREASURY
    assert invoice['network'] == 'devnet'
    calls = []
    def mock_check(signature, *, memo, expected, issued, expires):
        calls.append((signature, memo, expected, issued, expires))
        return signature == '4'*88
    monkeypatch.setattr(compute_payments, 'verify_transfers', mock_check)
    assert c.post('/v1/compute-payments/confirm', json={
        'invoice_id': invoice['invoice_id'], 'transaction_signature': '0'*88}).status_code == 400
    assert c.get(f'/v1/compute/jobs/{job}').json()['status'] == 'seller_approved_awaiting_payment'
    settled = c.post('/v1/compute-payments/confirm', json={
        'invoice_id': invoice['invoice_id'], 'transaction_signature': '4'*88})
    assert settled.status_code == 200, settled.text
    assert calls[-1][2][sol.TREASURY] == 30_000_000
    assert calls[-1][2][invoice['provider_wallet']] == 970_000_000
    assert c.get(f'/v1/compute/jobs/{job}').json()['status'] == 'queued'
    assert do(c, private_seller, seller, 4, 'compute_claim', {'job_height': job}).status_code == 200
    assert c.post('/v1/compute-payments/confirm', json={
        'invoice_id': invoice['invoice_id'], 'transaction_signature': '4'*88}).status_code == 409


def test_cannot_collect_mainnet_real_sol(monkeypatch):
    monkeypatch.setenv('ARK_SOLANA_NETWORK', 'mainnet-beta')
    monkeypatch.setenv('ARK_BILLING_ENABLED', '1')
    monkeypatch.setenv('ARK_DEVNET_DIRECT_PAYMENTS_EXPERIMENTAL', '1')
    assert not sol.billing_enabled()
    with pytest.raises(RuntimeError):
        sol.get_rpc_url()
