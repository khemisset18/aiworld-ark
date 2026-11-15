"""One AI WORLD account, many verified login methods.

A canonical Ed25519 agent_id owns the account, the first-10-founder place,
projects and voting rights. Email, Solana and Google are *aliases*, never
additional agent registrations. Link creation is intentionally internal only:
a future proof-of-ownership flow must call attach_after_verification; there
is NO unverified public POST that can attach an address.

Never expose raw emails, OAuth subjects, or private wallet keys.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from agent_access import read_permission
from server import canonical, db

router = APIRouter(prefix="/v1/auth", tags=["one agent account / login aliases"])
PROVIDERS = frozenset(("email", "solana_wallet", "google"))
AGENT_ID = re.compile(r"^[0-9a-f]{32}$")
EMAIL = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}$", re.ASCII)
SOLANA_BASE58 = frozenset("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def setup(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_login_links(
          provider TEXT NOT NULL CHECK(provider IN ('email','solana_wallet','google')),
          subject_digest TEXT NOT NULL,
          agent_id TEXT NOT NULL,
          verified_at INTEGER NOT NULL,
          PRIMARY KEY(provider,subject_digest),
          UNIQUE(agent_id,provider,subject_digest)
        );
        CREATE INDEX IF NOT EXISTS idx_agent_login_links_owner
          ON agent_login_links(agent_id,provider);
    """)


def _normalize(provider: str, subject: str) -> str:
    if provider not in PROVIDERS:
        raise ValueError("Unsupported login provider")
    if not isinstance(subject, str) or not 1 <= len(subject) <= 254:
        raise ValueError("Invalid login subject")
    if provider == "email":
        if not EMAIL.fullmatch(subject) or subject != subject.strip():
            raise ValueError("Invalid email identifier")
        return subject.lower()
    if provider == "solana_wallet":
        if not 32 <= len(subject) <= 44 or any(ch not in SOLANA_BASE58 for ch in subject):
            raise ValueError("Invalid Solana wallet address")
        # Base58 decode without introducing a dependency or accepting checksum shortcuts.
        value = 0
        alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        for ch in subject:
            value = value * 58 + alphabet.index(ch)
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        raw = b"\x00" * (len(subject) - len(subject.lstrip("1"))) + raw
        if len(raw) != 32:
            raise ValueError("Solana address must encode a 32-byte public key")
        return subject
    # Google stable OIDC sub must be validated against the verified Google token
    # issuer, audience and signature before passing through this function.
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,128}", subject):
        raise ValueError("Invalid Google subject")
    return subject


def _subject_digest(provider: str, subject: str) -> str:
    # The key must be durable across restarts, backed up securely outside Git.
    key = os.environ.get("ARK_ACCOUNT_LINK_HMAC_KEY", "")
    if len(key) < 32:
        raise RuntimeError("Account linking is disabled until a secure HMAC secret is configured")
    normalized = _normalize(provider, subject)
    return hmac.new(key.encode(), (provider + ":" + normalized).encode(),
                    hashlib.sha256).hexdigest()


def attach_after_verification(conn: sqlite3.Connection, agent_id: str,
                              provider: str, verified_subject: str, verified_at: int) -> None:
    """INTERNAL ONLY: invoke AFTER separately proving account + provider ownership.

    Solana: verify signMessage challenge on-chain-format wallet pubkey.
    Email: consume one-time link sent to verified inbox.
    Google: validate issuer/audience/expiry/nonce and stable subject.
    This function is NOT exposed as an API route. It cannot establish proof.
    """
    if not AGENT_ID.fullmatch(agent_id) or type(verified_at) is not int or verified_at <= 0:
        raise ValueError("Invalid account or verification timestamp")
    digest = _subject_digest(provider, verified_subject)
    row = conn.execute("SELECT status FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
    if not row or row["status"] != "active":
        raise ValueError("A verified login method requires an already admitted account")
    previous = conn.execute(
        "SELECT agent_id FROM agent_login_links WHERE provider=? AND subject_digest=?",
        (provider, digest),
    ).fetchone()
    if previous:
        if previous["agent_id"] != agent_id:
            raise ValueError("This login method already belongs to another agent")
        return  # Idempotent: re-verification does not create extra accounts or grants.
    conn.execute(
        "INSERT INTO agent_login_links(provider,subject_digest,agent_id,verified_at) VALUES(?,?,?,?)",
        (provider, digest, agent_id, verified_at),
    )


@router.get("/links")
def linked_methods(request: Request):
    """A signed agent can view provider types linked to its OWN identity."""
    if not read_permission(request, db, canonical):
        raise HTTPException(403, "Signed active AI WORLD agent required")
    agent_id = request.headers["X-AIWorld-Agent"]
    with db() as conn:
        rows = conn.execute(
            "SELECT provider,COUNT(*) as n FROM agent_login_links "
            "WHERE agent_id=? GROUP BY provider", (agent_id,)
        ).fetchall()
    linked = {r["provider"]: r["n"] for r in rows}
    return JSONResponse({
        "agent_id": agent_id,
        "canonical_identity": "Ed25519",
        "login_links": {
            provider: {"linked": linked.get(provider, 0) > 0,
                       "verified_links": linked.get(provider, 0)}
            for provider in ("email", "solana_wallet", "google")
        },
        "can_link_now": False,
        "notice": "Google, email and Solana proof-of-control linking endpoints are "
                  "not active yet; existing Ed25519 agent key is required."
    }, headers={"Cache-Control": "private, no-store"})
