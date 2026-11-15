"""Ten-SOL registration policy, with all real transfers intentionally blocked."""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from test_forge import new_agent, do


@pytest.fixture
def c(monkeypatch, tmp_path):
    monkeypatch.setenv("SOULCHAIN_DB", str(tmp_path / "billing.sqlite3"))
    monkeypatch.setenv("ARK_BILLING_ENABLED", "1")  # obsolete env cannot unlock old invoices
    monkeypatch.setenv("ARK_SOLANA_RECIPIENT", "11111111111111111111111111111111")
    monkeypatch.setenv("ARK_PAYMENT_REQUIRED", "0")
    monkeypatch.setenv("ARK_ADMISSION_REQUIRED", "0")
    import server
    import billing
    importlib.reload(server)
    importlib.reload(billing)
    return TestClient(server.app)


def test_registration_policy_is_one_time_ten_sol_and_unpayable(c):
    info = c.get("/v1/billing/info")
    assert info.status_code == 200
    policy = info.json()
    assert policy["registration_fee_sol"] == 10
    assert policy["registration_fee_lamports"] == 10_000_000_000
    assert policy["registration_frequency"] == "one_time"
    assert policy["token"] == "SOL"
    assert policy["enabled"] is False
    assert policy["recipient"] is None
    assert "disabled" in policy["payment_status"]
    assert "2000" not in str(policy)
    assert "2000" not in str(info.json())


def test_old_invoice_and_confirm_cannot_accept_funds_even_with_flags(c):
    key, agent_id = new_agent(c, "New Agent")
    assert c.post("/v1/billing/invoice", json={
        "agent_id": agent_id, "timestamp": 1000, "signature": "x" * 88,
    }).status_code == 503
    assert c.post("/v1/billing/confirm", json={
        "invoice_id": "old", "transaction_signature": "y" * 88,
    }).status_code == 503
    import billing
    assert billing.enabled() is False
    assert billing.membership_active(agent_id) is False


def test_optional_payment_gate_fail_closed_until_verified_implementation(c, monkeypatch):
    key, agent_id = new_agent(c, "Agent")
    monkeypatch.setenv("ARK_PAYMENT_REQUIRED", "1")
    goal = {"topic": "Need compute", "objective": "Find a volunteer to calculate primes",
            "criteria": "Compare the resulting prime count", "tags": ["compute"]}
    # This flag is not intended for live traffic yet: no legacy membership passes it.
    assert do(c, key, agent_id, 2, "need", goal).status_code == 402
