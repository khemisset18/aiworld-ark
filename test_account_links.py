"""Account alias registry: email + Solana refer to ONE verified agent ID.

ATTACH calls below simulate *completed external ownership verification* in
server-internal code. No Google, SMTP, wallet signature or session login is
falsely claimed by these tests.
"""
from __future__ import annotations

import time

import pytest

from test_private_agent_network import net, join, new_validated_agent, signed_headers


def test_email_and_solana_aliases_belong_to_one_agent_not_two_members(net, tmp_path, monkeypatch):
    monkeypatch.setenv("ARK_ACCOUNT_LINK_HMAC_KEY", "unit-test-only-secret-not-for-real-use" * 2)
    account = new_validated_agent(net, tmp_path, 1)
    joined = join(net, account)
    assert joined.status_code == 200, joined.text
    agent_id = account["agent_id"]
    path = "/v1/auth/links"

    assert net.get(path).status_code == 403
    assert net.post(path, json={"email": "attacker@example.com"}).status_code == 405
    before = net.get(path, headers=signed_headers(account, path))
    assert before.status_code == 200
    assert not before.json()["login_links"]["email"]["linked"]
    assert not before.json()["login_links"]["solana_wallet"]["linked"]
    assert before.json()["can_link_now"] is False

    import server, account_links
    with server.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        account_links.attach_after_verification(
            conn, agent_id, "email", "Nova@Example.org", int(time.time()))
        account_links.attach_after_verification(
            conn, agent_id, "solana_wallet", "11111111111111111111111111111111",
            int(time.time()))
        conn.commit()

    result = net.get(path, headers=signed_headers(account, path))
    assert result.status_code == 200
    body = result.json()
    assert body["agent_id"] == agent_id
    assert body["login_links"]["email"] == {"linked": True, "verified_links": 1}
    assert body["login_links"]["solana_wallet"] == {"linked": True, "verified_links": 1}
    assert body["login_links"]["google"]["linked"] is False
    assert "Nova@Example.org" not in result.text
    assert "11111111111111111111111111111111" not in result.text
    assert result.headers["cache-control"] == "private, no-store"

    with server.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM registration_grants").fetchone()[0] == 1


def test_login_subject_unique_prevents_two_agents_claiming_same_email_or_wallet(net, tmp_path, monkeypatch):
    monkeypatch.setenv("ARK_ACCOUNT_LINK_HMAC_KEY", "different-test-key-not-for-production-" * 2)
    a = new_validated_agent(net, tmp_path, 1)
    b = new_validated_agent(net, tmp_path, 2)
    assert join(net, a).status_code == 200
    assert join(net, b).status_code == 200

    import server, account_links
    with server.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        account_links.attach_after_verification(
            conn, a["agent_id"], "email", "AgEnt@example.org", 100)
        account_links.attach_after_verification(
            conn, a["agent_id"], "solana_wallet", "11111111111111111111111111111111", 100)
        # Repeated verification of SAME subject never creates a second link.
        account_links.attach_after_verification(
            conn, a["agent_id"], "email", "agent@EXAMPLE.org", 101)
        with pytest.raises(ValueError, match="another agent"):
            account_links.attach_after_verification(
                conn, b["agent_id"], "email", "agent@example.org", 101)
        with pytest.raises(ValueError, match="another agent"):
            account_links.attach_after_verification(
                conn, b["agent_id"], "solana_wallet", "11111111111111111111111111111111", 101)
        conn.commit()
    with server.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_login_links").fetchone()[0] == 2


def test_linking_is_closed_without_key_or_verified_existing_account(net, monkeypatch):
    import server, account_links
    monkeypatch.delenv("ARK_ACCOUNT_LINK_HMAC_KEY", raising=False)
    with server.db() as conn:
        with pytest.raises(RuntimeError, match="disabled"):
            account_links.attach_after_verification(
                conn, "0" * 32, "email", "x@example.org", int(time.time()))
    monkeypatch.setenv("ARK_ACCOUNT_LINK_HMAC_KEY", "stable-32byte-plus-secret-secret-key")
    with server.db() as conn:
        with pytest.raises(ValueError, match="already admitted"):
            account_links.attach_after_verification(
                conn, "0" * 32, "email", "x@example.org", int(time.time()))
        for bad in ("http://attacker/", "", "not-an-email"):
            with pytest.raises(ValueError):
                account_links.attach_after_verification(
                    conn, "0" * 32, "email", bad, int(time.time()))
        with pytest.raises(ValueError):
            account_links.attach_after_verification(
                conn, "0" * 32, "solana_wallet", "not-a-solana-wallet", int(time.time()))
