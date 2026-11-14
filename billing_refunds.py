"""Devnet reimbursement requests and verifiable treasury payouts.

The operator signs refund transfers using THEIR OWN wallet, off-server.
No remote API can instruct a signing wallet. Requests are not approvals.
This prototype must never be used to handle real funds.
"""
from __future__ import annotations

import re
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
    TREASURY, billing_enabled, payment_receipt_table, verified_transfer_source,
)

router = APIRouter(prefix="/v1/billing/refunds", tags=["devnet-membership-refunds"])
REFUND_WINDOW_SECONDS = 7 * 24 * 3600
YEAR_SECONDS = 365 * 24 * 3600
REASONS = {"withdrawal", "service_unavailable", "billing_error", "other"}


def setup_refunds():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS membership_refunds (
            refund_id TEXT PRIMARY KEY,
            invoice_id TEXT NOT NULL UNIQUE,
            agent_id TEXT NOT NULL,
            payer_wallet TEXT NOT NULL,
            lamports INTEGER NOT NULL,
            memo TEXT NOT NULL UNIQUE,
            reason TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            status TEXT NOT NULL,
            refund_tx_signature TEXT UNIQUE
        )""")
        payment_receipt_table(conn)
        conn.commit()


setup_refunds()


class RefundRequest(BaseModel):
    invoice_id: str = Field(min_length=32, max_length=32)
    timestamp: int
    reason: str
    signature: str = Field(min_length=80, max_length=120)


class RefundConfirm(BaseModel):
    refund_id: str = Field(min_length=32, max_length=32)
    transaction_signature: str = Field(min_length=70, max_length=100)


@router.post("/request")
def request_refund(request: RefundRequest):
    if not billing_enabled():
        raise HTTPException(503, "Refund prototype disabled")
    if request.reason not in REASONS:
        raise HTTPException(400, "Invalid refund request category")
    now = int(time.time())
    if abs(now - request.timestamp) > 120:
        raise HTTPException(401, "Expired refund request signature")
    with db() as conn:
        row = conn.execute("SELECT * FROM membership_invoices WHERE invoice_id=?",
                           (request.invoice_id,)).fetchone()
        if row is None or row["status"] != "paid" or not row["tx_signature"]:
            raise HTTPException(404, "No paid membership invoice eligible for a refund request")
        agent = conn.execute("SELECT public_key FROM agents WHERE agent_id=?",
                             (row["agent_id"],)).fetchone()
        if agent is None:
            raise HTTPException(404, "Agent account not found")
        signed = {"action": "membership_refund", "invoice_id": request.invoice_id,
                  "timestamp": request.timestamp, "reason": request.reason}
        try:
            Ed25519PublicKey.from_public_bytes(decode64(agent["public_key"])).verify(
                decode64(request.signature), canonical(signed))
        except (InvalidSignature, ValueError) as exc:
            raise HTTPException(401, "Invalid refund request signature") from exc
        old = conn.execute("SELECT refund_id,status FROM membership_refunds WHERE invoice_id=?",
                           (request.invoice_id,)).fetchone()
        if old:
            raise HTTPException(409, "Refund request already filed for this invoice")
        invoice = dict(row)
    # Verify original chain receipt a second time; its sender is the ONLY
    # permissible recipient of the refund. Never trust a claimed refund wallet.
    try:
        payer = verified_transfer_source(
            invoice["tx_signature"], memo=invoice["memo"],
            expected={invoice["recipient"]: invoice["price_lamports"]},
            issued=invoice["created_at"], expires=invoice["expires_at"])
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(503, "Cannot verify original Devnet payer") from exc
    if not payer:
        raise HTTPException(409, "Original payment not verifiable; manual support required")
    refund_id = secrets.token_hex(16)
    refund_memo = "AIWORLD-REFUND:" + refund_id
    with db() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM membership_invoices WHERE invoice_id=?",
                               (request.invoice_id,)).fetchone()
            if not row or row["status"] != "paid":
                raise HTTPException(409, "Invoice no longer eligible")
            conn.execute("""INSERT INTO membership_refunds
                (refund_id,invoice_id,agent_id,payer_wallet,lamports,memo,reason,
                 created_at,expires_at,status,refund_tx_signature)
                 VALUES (?,?,?,?,?,?,?,?,?,'requested',NULL)""",
                (refund_id, request.invoice_id, invoice["agent_id"], payer,
                 invoice["price_lamports"], refund_memo, request.reason,
                 now, now + REFUND_WINDOW_SECONDS))
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise HTTPException(409, "Refund for this invoice already exists") from exc
        except Exception:
            conn.rollback()
            raise
    return {"refund_id": refund_id, "status": "requested", "network": "devnet",
            "refund_lamports": invoice["price_lamports"], "refund_to": payer,
            "treasury_wallet": TREASURY, "memo": refund_memo,
            "expires_at": now + REFUND_WINDOW_SECONDS,
            "notice": "Request recorded, NOT approved or sent. Treasury operator must review and authorize payout separately."}


@router.post("/confirm")
def confirm_refund(request: RefundConfirm):
    if not billing_enabled():
        raise HTTPException(503, "Refund prototype disabled")
    with db() as conn:
        row = conn.execute("SELECT * FROM membership_refunds WHERE refund_id=?",
                           (request.refund_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Unknown refund")
        if row["status"] != "requested":
            raise HTTPException(409, "Refund already confirmed")
        refund = dict(row)
    try:
        confirmed = verified_transfer_source(
            request.transaction_signature, memo=refund["memo"],
            expected={refund["payer_wallet"]: refund["lamports"]},
            issued=refund["created_at"], expires=refund["expires_at"],
            required_sender=TREASURY)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(503, "Cannot verify finalized refund") from exc
    if not confirmed:
        raise HTTPException(400, "Refund must be a finalized treasury payment to original payer")
    now = int(time.time())
    with db() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            refund = conn.execute("SELECT * FROM membership_refunds WHERE refund_id=?",
                                  (request.refund_id,)).fetchone()
            if not refund or refund["status"] != "requested":
                raise HTTPException(409, "Refund already confirmed")
            original = conn.execute("SELECT status FROM membership_invoices WHERE invoice_id=?",
                                    (refund["invoice_id"],)).fetchone()
            if not original or original["status"] != "paid":
                raise HTTPException(409, "Original invoice no longer paid")
            try:
                conn.execute("""INSERT INTO payment_signatures
                    (signature,category,reference_id,created_at) VALUES (?,?,?,?)""",
                    (request.transaction_signature, "membership_refund", refund["refund_id"], now))
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, "Payment signature already accounted for") from exc
            conn.execute("UPDATE membership_refunds SET status='refunded',refund_tx_signature=? WHERE refund_id=?",
                         (request.transaction_signature, request.refund_id))
            conn.execute("UPDATE membership_invoices SET status='refunded' WHERE invoice_id=?",
                         (refund["invoice_id"],))
            # Prototype accounting: remove one membership year. If prior years
            # were paid, their remainder survives. Real policy needs a ledger.
            current = conn.execute("SELECT valid_until FROM memberships WHERE agent_id=?",
                                   (refund["agent_id"],)).fetchone()
            if current:
                adjusted = max(now, current["valid_until"] - YEAR_SECONDS)
                conn.execute("UPDATE memberships SET valid_until=? WHERE agent_id=?",
                             (adjusted, refund["agent_id"]))
            conn.commit()
            return {"status": "refunded", "refund_id": refund["refund_id"],
                    "amount_lamports": refund["lamports"], "network": "devnet",
                    "remaining_membership_after_refund": "recomputed"}
        except Exception:
            conn.rollback()
            raise
