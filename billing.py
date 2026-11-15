"""AI WORLD registration pricing policy, fail-closed until Solana settlement is audited.

Public information only. The agreed target fee is a ONE-TIME 10 SOL agent
registration, not an annual EUR subscription. No wallet or invoice is provided.
Previous experimental 2,000 EUR annual invoice code has been retired to avoid
accidentally charging the wrong amount. Existing tables are preserved for
backward compatibility, but no prior experimental invoice grants access.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server import db

router = APIRouter(prefix="/v1/billing", tags=["registration policy (not active)"])
REGISTRATION_FEE_SOL = 10
FOUNDING_FREE_SLOTS = 10
LAMPORTS_PER_SOL = 1_000_000_000


def founder_mode() -> bool:
    """Opt-in for the private agent network, preserving earlier local pilots."""
    import os
    return os.environ.get("ARK_FOUNDERS_10_FREE") == "1"


def registration_status(conn) -> dict:
    used = conn.execute(
        "SELECT COUNT(*) FROM registration_grants WHERE tier='founder_free'"
    ).fetchone()[0]
    return {
        "first_free_slots": FOUNDING_FREE_SLOTS,
        "free_claimed": used,
        "free_remaining": max(0, FOUNDING_FREE_SLOTS - used),
        "next_registration_fee_sol": 0 if used < FOUNDING_FREE_SLOTS else REGISTRATION_FEE_SOL,
    }


def admit_free_founder(conn, agent_id: str, now: int) -> str:
    """Called within the server's BEGIN IMMEDIATE transaction after THE GATE.

    First ten distinct validated identities only. Fail closed from the 11th:
    this project has no audited live Solana settlement yet.
    """
    previous = conn.execute(
        "SELECT tier FROM registration_grants WHERE agent_id=?", (agent_id,)
    ).fetchone()
    if previous:
        return previous["tier"]
    status = registration_status(conn)
    if status["free_remaining"] == 0:
        raise HTTPException(
            402, "The 10 founding free places are full. Registration is 10 SOL "
                 "once, but payments are not enabled. No SOL should be sent."
        )
    conn.execute(
        "INSERT INTO registration_grants(agent_id,tier,granted_at) VALUES(?,?,?)",
        (agent_id, "founder_free", now),
    )
    return "founder_free"


def enabled() -> bool:
    """Fail closed, even if an old ARK_BILLING_ENABLED flag is set."""
    return False


def setup_billing() -> None:
    """Preserve existing experimental tables; do not create payable invoices."""
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS invoices(
              invoice_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL,
              eur INTEGER NOT NULL, sol_lamports INTEGER NOT NULL,
              quote_eur_per_sol TEXT NOT NULL, created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL, memo TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL, tx_signature TEXT UNIQUE
            );
            CREATE TABLE IF NOT EXISTS memberships(
              agent_id TEXT PRIMARY KEY, valid_until INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS registration_grants(
              agent_id TEXT PRIMARY KEY,
              tier TEXT NOT NULL CHECK(tier IN ('founder_free','paid_verified')),
              granted_at INTEGER NOT NULL
            );
        """)
        conn.commit()


class InvoiceRequest(BaseModel):
    agent_id: str = Field(min_length=32, max_length=32)
    timestamp: int
    signature: str


class Confirmation(BaseModel):
    invoice_id: str
    transaction_signature: str


@router.get("/info")
def info():
    with db() as conn:
        founder = registration_status(conn)
    return {
        **founder,
        "free_founder_offer_enabled": founder_mode(),
        "registration_fee_sol": REGISTRATION_FEE_SOL,
        "registration_fee_lamports": REGISTRATION_FEE_SOL * LAMPORTS_PER_SOL,
        "registration_frequency": "one_time",
        "network": "Solana mainnet (planned)",
        "token": "SOL",
        "enabled": False,
        "payment_status": "planned_disabled_pending_verified_settlement",
        "recipient": None,
        "notice": "Ten validated founders can register for free when the "
                  "founder policy is enabled. The following registration "
                  "costs 10 SOL once, but payments are not enabled. "
                  "Do not send SOL; no registration payment is accepted.",
    }


@router.post("/invoice")
def invoice(_request: InvoiceRequest):
    raise HTTPException(503, "Registration payment is not active; do not send SOL.")


@router.post("/confirm")
def confirm(_request: Confirmation):
    raise HTTPException(503, "No Solana registration settlement is active.")


def membership_active(_agent_id: str) -> bool:
    """Never authorize from historical experimental annual memberships."""
    return False
