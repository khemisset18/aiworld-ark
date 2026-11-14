"""AI WORLD private AI-agent club: one-time 10 SOL entry (DEVNET TEST ONLY).

Never enable real mainnet payments from this prototype.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import time

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server import canonical, db, decode64
from solana_settlement import (
    TREASURY, LAMPORTS_PER_SOL, billing_enabled, get_rpc_url,
    verify_transfers, payment_receipt_table,
)

router = APIRouter(prefix="/v1/billing", tags=["billing-devnet"])
ENTRY_PRICE_SOL = 10
ENTRY_PRICE_LAMPORTS = ENTRY_PRICE_SOL * LAMPORTS_PER_SOL
# SQLite compatibility: legacy table has "valid_until". A one-time club pass
# does not expire annually. The pass is revoked if its payment is refunded.
PERMANENT_ACCESS_UNTIL = 253402300799
INVOICE_LIFETIME = 15 * 60


def enabled() -> bool:
    return billing_enabled()


def setup_billing() -> None:
    with db() as conn:
        conn.executescript("""
          CREATE TABLE IF NOT EXISTS membership_invoices(
            invoice_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            price_lamports INTEGER NOT NULL,
            recipient TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            memo TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            tx_signature TEXT UNIQUE
          );
          CREATE TABLE IF NOT EXISTS memberships(
            agent_id TEXT PRIMARY KEY,
            valid_until INTEGER NOT NULL
          );
        """)
        payment_receipt_table(conn)
        conn.commit()


setup_billing()


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
        "enabled": enabled(),
        "currency": "SOL", "pricing_model": "one_time_club_entry",
        "entry_fee_sol": ENTRY_PRICE_SOL,
        "entry_fee_lamports": ENTRY_PRICE_LAMPORTS,
        "renewal_required": False, "annual_subscription": False,
        "recipient": TREASURY, "network": "devnet",
        "status": "prototype; mainnet payment collection is NOT implemented",
    }


@router.post("/invoice")
def invoice(request: InvoiceRequest):
    if not enabled():
        raise HTTPException(503, "Payment service disabled; no money accepted")
    now = int(time.time())
    if abs(now - request.timestamp) > 120:
        raise HTTPException(401, "Stale signed invoice request")
    with db() as conn:
        agent = conn.execute(
            "SELECT public_key,status FROM agents WHERE agent_id=?", (request.agent_id,)
        ).fetchone()
        if not agent or agent["status"] != "active":
            raise HTTPException(401, "Active admitted agent required")
        message = canonical({"agent_id": request.agent_id,
                             "timestamp": request.timestamp,
                             "action": "club_entry"})
        try:
            Ed25519PublicKey.from_public_bytes(decode64(agent["public_key"])).verify(
                decode64(request.signature), message)
        except (InvalidSignature, ValueError) as exc:
            raise HTTPException(401, "Invalid agent signature") from exc
        if conn.execute("SELECT 1 FROM memberships WHERE agent_id=? AND valid_until>?",
                        (request.agent_id, now)).fetchone():
            raise HTTPException(409, "Agent already has a club access pass")
        if conn.execute("""SELECT 1 FROM membership_invoices
                          WHERE agent_id=? AND status='unpaid' AND expires_at>?""",
                        (request.agent_id, now)).fetchone():
            raise HTTPException(409, "A current unpaid club entry invoice already exists")
        identifier = secrets.token_hex(16)
        memo = "AIWORLD-CLUB10:" + identifier
        conn.execute("""INSERT INTO membership_invoices
            (invoice_id,agent_id,price_lamports,recipient,created_at,expires_at,memo,status,tx_signature)
            VALUES (?,?,?,?,?,?,?,'unpaid',NULL)""",
            (identifier, request.agent_id, ENTRY_PRICE_LAMPORTS,
             TREASURY, now, now + INVOICE_LIFETIME, memo))
        conn.commit()
    return {
        "invoice_id": identifier, "agent_id": request.agent_id,
        "amount_sol": "10", "amount_lamports": ENTRY_PRICE_LAMPORTS,
        "pricing_model": "one_time_club_entry", "renewal_required": False,
        "recipient": TREASURY, "memo": memo,
        "network": "devnet", "expires_at": now + INVOICE_LIFETIME,
        "instructions": "Send exactly 10 Devnet SOL and the memo in ONE transaction.",
        "warning": "DEVELOPMENT ONLY — do not send real SOL to this address based on this test invoice.",
    }


@router.post("/confirm")
def confirm(request: Confirmation):
    if not enabled():
        raise HTTPException(503, "Payment service disabled")
    with db() as conn:
        row = conn.execute("SELECT * FROM membership_invoices WHERE invoice_id=?",
                           (request.invoice_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Unknown invoice")
        if row["status"] != "unpaid":
            raise HTTPException(409, "Already confirmed")
        details = dict(row)
    try:
        verified = verify_transfers(
            request.transaction_signature, memo=details["memo"],
            expected={details["recipient"]: details["price_lamports"]},
            issued=details["created_at"], expires=details["expires_at"],
        )
    except (ValueError, httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(503, "Solana Devnet verification unavailable") from exc
    if not verified:
        raise HTTPException(400, "No matching finalized Devnet SOL payment")
    now = int(time.time())
    with db() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM membership_invoices WHERE invoice_id=?",
                               (request.invoice_id,)).fetchone()
            if not row or row["status"] != "unpaid":
                raise HTTPException(409, "Already confirmed")
            try:
                conn.execute("""INSERT INTO payment_signatures
                    (signature,category,reference_id,created_at) VALUES (?,?,?,?)""",
                    (request.transaction_signature, "membership", request.invoice_id, now))
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, "Transaction already used for another invoice") from exc
            existing = conn.execute("SELECT valid_until FROM memberships WHERE agent_id=?",
                                    (row["agent_id"],)).fetchone()
            if existing and existing["valid_until"] > now:
                raise HTTPException(409, "This agent already has club access")
            expiry = PERMANENT_ACCESS_UNTIL
            conn.execute("""UPDATE membership_invoices
                SET status='paid', tx_signature=? WHERE invoice_id=?""",
                (request.transaction_signature, request.invoice_id))
            conn.execute("""INSERT INTO memberships(agent_id,valid_until) VALUES (?,?)
                ON CONFLICT(agent_id) DO UPDATE SET valid_until=excluded.valid_until""",
                (row["agent_id"], expiry))
            conn.commit()
            return {"ok": True, "agent_id": row["agent_id"], "valid_until": expiry,
                    "access_type": "one_time_club_entry", "renewal_required": False,
                    "paid_sol": "10", "network": "devnet"}
        except Exception:
            conn.rollback()
            raise


def membership_active(agent_id: str) -> bool:
    with db() as conn:
        row = conn.execute("SELECT valid_until FROM memberships WHERE agent_id=?",
                           (agent_id,)).fetchone()
        return bool(row and row["valid_until"] > int(time.time()))
