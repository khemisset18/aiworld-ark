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
LAMPORTS_PER_SOL = 1_000_000_000


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
    return {
        "registration_fee_sol": REGISTRATION_FEE_SOL,
        "registration_fee_lamports": REGISTRATION_FEE_SOL * LAMPORTS_PER_SOL,
        "registration_frequency": "one_time",
        "network": "Solana mainnet (planned)",
        "token": "SOL",
        "enabled": False,
        "payment_status": "planned_disabled_pending_verified_settlement",
        "recipient": None,
        "notice": "Price is a project decision, not a payable invoice. "
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
