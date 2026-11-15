"""Private network: signed site access and exactly ten free THE GATE entrants.

All tests use fresh SQLite and mocked local HTTP; no SOL is transferred.
"""
from __future__ import annotations

import base64
import importlib
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

import agent_cli


@pytest.fixture
def net(tmp_path, monkeypatch):
    monkeypatch.setenv("SOULCHAIN_DB", str(tmp_path / "founders.sqlite3"))
    monkeypatch.setenv("ARK_AGENT_ONLY", "1")
    monkeypatch.setenv("ARK_FOUNDERS_10_FREE", "1")
    monkeypatch.setenv("ARK_ADMISSION_REQUIRED", "1")
    monkeypatch.setenv("ARK_BILLING_ENABLED", "0")
    monkeypatch.setenv("ARK_PAYMENT_REQUIRED", "0")
    import server
    importlib.reload(server)
    c = TestClient(server.app)
    def local_api(_base, path, method="GET", body=None):
        response = c.request(method, path, json=body)
        if response.status_code >= 400:
            raise SystemExit(f"Network error {response.status_code}: {response.text}")
        return response.json()
    monkeypatch.setattr(agent_cli, "api", local_api)
    return c


def new_validated_agent(c, tmp_path, index):
    account = agent_cli.client_new(tmp_path / f"private_{index}.json", f"Agent-{index}")
    assert agent_cli.pass_gate("local", account)["passed"] is True
    return account


def join(c, account):
    signer = Ed25519PrivateKey.from_private_bytes(agent_cli.un64(account["private_key"]))
    payload = {
        "agent_id": account["agent_id"], "nonce": 1, "op": "enter",
        "data": {
            "public_key": account["public_key"], "label": account["name"],
            "capabilities": ["independent-agent-demo", "consensual-compute"]
        }
    }
    payload["signature"] = agent_cli.b64(signer.sign(agent_cli.canonical(payload)))
    return c.post("/v1/tx", json=payload)


def signed_headers(account, path, query="", timestamp=None):
    ts = int(time.time()) if timestamp is None else timestamp
    message = {"agent_id": account["agent_id"], "timestamp": ts,
               "method": "GET", "path": path, "query": query}
    signer = Ed25519PrivateKey.from_private_bytes(agent_cli.un64(account["private_key"]))
    return {
        "X-AIWorld-Agent": account["agent_id"],
        "X-AIWorld-Timestamp": str(ts),
        "X-AIWorld-Signature": agent_cli.b64(signer.sign(agent_cli.canonical(message))),
    }


def test_homepage_and_network_metadata_not_accessible_to_anonymous_clients(net):
    for path in ("/", "/docs", "/openapi.json", "/v1/compute/offers",
                 "/v1/stats", "/v1/agents", "/v1/roadmap"):
        assert net.get(path).status_code == 403, path
    for path in ("/health", "/v1/info", "/.well-known/ai-world.json",
                 "/v1/admission/info", "/v1/billing/info", "/v1/compute/info"):
        assert net.get(path).status_code == 200, path
    assert net.get("/v1/billing/info").json()["free_remaining"] == 10


def test_first_ten_admitted_free_then_eleventh_is_blocked_until_payment_exists(
        net, tmp_path):
    assert net.post("/v1/tx", json={}).status_code == 422
    accounts = []
    for index in range(1, 11):
        record = new_validated_agent(net, tmp_path, index)
        accepted = join(net, record)
        assert accepted.status_code == 200, (index, accepted.text)
        accounts.append(record)
        policy = net.get("/v1/billing/info").json()
        assert policy["free_claimed"] == index
        assert policy["free_remaining"] == 10 - index
    policy = net.get("/v1/billing/info").json()
    assert policy["next_registration_fee_sol"] == 10
    assert policy["enabled"] is False
    assert policy["recipient"] is None

    eleventh = new_validated_agent(net, tmp_path, 11)
    denied = join(net, eleventh)
    assert denied.status_code == 402, denied.text
    assert "10 SOL" in denied.text
    assert net.get("/v1/billing/info").json()["free_claimed"] == 10
    assert net.get("/v1/agents/" + eleventh["agent_id"]).status_code == 404
    # Gate pass remains available after the unsuccessful atomic attempt.
    import server
    with server.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM registration_grants").fetchone()[0] == 10
        unused = conn.execute("SELECT used_at FROM admission_passes WHERE agent_id=?",
                              (eleventh["agent_id"],)).fetchone()
        assert unused is not None and unused["used_at"] is None

    owner = accounts[0]
    assert net.get("/", headers=signed_headers(owner, "/")).status_code == 200
    assert net.get("/v1/compute/offers",
                   headers=signed_headers(owner, "/v1/compute/offers")).status_code == 200
    assert net.get("/", headers=signed_headers(eleventh, "/")).status_code == 403
    # Prevent a fake signature from another identity, or a captured stale one.
    invalid = signed_headers(owner, "/")
    invalid["X-AIWorld-Signature"] = base64.b64encode(b"0" * 64).decode()
    assert net.get("/", headers=invalid).status_code == 403
    stale = signed_headers(owner, "/", timestamp=int(time.time()) - 180)
    assert net.get("/", headers=stale).status_code == 403
    assert net.get("/v1/stats", headers=signed_headers(owner, "/")).status_code == 403


def test_private_site_fails_closed_if_gate_disabled(net, monkeypatch):
    monkeypatch.setenv("ARK_ADMISSION_REQUIRED", "0")
    assert net.get("/").status_code == 503
    assert net.get("/health").status_code == 503
