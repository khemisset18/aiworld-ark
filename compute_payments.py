"""Paid agent-to-agent task settlement on Solana DEVNET ONLY.

One confirmed transaction must contain two SOL transfers:
- 97% to provider's verified-by-agent identity public key address
- 3% to AI WORLD's fixed treasury
No mainnet escrow exists. Use Devnet only.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import sqlite3
import time

import httpx
from fastapi import APIRouter, HTTPException

from server import db
from compute_pool import price_breakdown
from solana_settlement import (
    TREASURY, billing_enabled, b58encode, payment_receipt_table, verify_transfers,
)

router = APIRouter(prefix="/v1/compute-payments", tags=["paid-compute-devnet"])
LIFETIME_SECONDS = 15 * 60


def direct_enabled() -> bool:
    """Fail closed permanently: unprotected seller prepayment is retired.

    The only supported way to unblock a paid compute task is via the finalized
    escrow PDA verified by /v1/escrow/confirm-funded. Environment flags cannot
    re-enable this old direct-transfer route.
    """
    return False


def setup_compute_payments() -> None:
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS compute_invoices(
            invoice_id TEXT PRIMARY KEY,
            job_height INTEGER NOT NULL UNIQUE,
            requester TEXT NOT NULL,
            provider TEXT NOT NULL,
            gross_lamports INTEGER NOT NULL,
            fee_lamports INTEGER NOT NULL,
            provider_lamports INTEGER NOT NULL,
            provider_wallet TEXT NOT NULL,
            treasury_wallet TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            memo TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            tx_signature TEXT UNIQUE
        )""")
        payment_receipt_table(conn)
        conn.commit()


setup_compute_payments()


@router.get("/info")
def info():
    return {"network": "devnet", "enabled": direct_enabled(), "escrow_available": False,
            "club_entry_fee_sol": "10", "entry_payment": "one_time", "fee_percent": 3,
            "treasury_wallet": TREASURY,
            "note": "Unprotected direct transfers permanently disabled; use audited on-chain escrow"}


@router.post("/invoice/{job_height}")
def invoice(job_height: int):
    if not direct_enabled():
        raise HTTPException(503, "Solana Devnet test billing disabled")
    if job_height < 1:
        raise HTTPException(400, "Invalid job")
    now = int(time.time())
    with db() as conn:
        job = conn.execute("SELECT * FROM compute_jobs WHERE height=?", (job_height,)).fetchone()
        if not job:
            raise HTTPException(404, "Unknown job")
        if job["status"] != "seller_approved_awaiting_payment":
            raise HTTPException(409, "Provider consent is required before requesting payment")
        offer = conn.execute("SELECT * FROM compute_capacity WHERE height=?",
                             (job["capacity_height"],)).fetchone()
        if not offer or offer["status"] != "open" or offer["expiry"] <= now:
            raise HTTPException(409, "Provider offer expired or withdrawn")
        pricing = price_breakdown(json.loads(offer["terms_json"]))
        if pricing["mode"] != "paid" or pricing["provider_lamports"] <= 0:
            raise HTTPException(409, "Not a valid paid job")
        agent = conn.execute("SELECT public_key FROM agents WHERE agent_id=?",
                             (job["worker"],)).fetchone()
        if not agent:
            raise HTTPException(409, "Missing provider identity")
        try:
            provider_wallet = b58encode(base64.b64decode(agent["public_key"], validate=True))
        except (ValueError, TypeError) as exc:
            raise HTTPException(409, "Invalid provider public key") from exc
        if provider_wallet == TREASURY:
            raise HTTPException(409, "Provider wallet must differ from platform treasury")
        old = conn.execute("SELECT * FROM compute_invoices WHERE job_height=?",
                           (job_height,)).fetchone()
        if old:
            return _present(old)
        identifier = secrets.token_hex(16)
        memo = "AIWORLD-JOB:" + identifier
        conn.execute("""INSERT INTO compute_invoices
            (invoice_id,job_height,requester,provider,gross_lamports,fee_lamports,
             provider_lamports,provider_wallet,treasury_wallet,created_at,expires_at,memo,status,tx_signature)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'unpaid',NULL)""",
             (identifier, job_height, job["requester"], job["worker"],
              pricing["price_lamports"], pricing["platform_fee_lamports"],
              pricing["provider_lamports"], provider_wallet, TREASURY,
              now, now + LIFETIME_SECONDS, memo))
        conn.commit()
        fresh = conn.execute("SELECT * FROM compute_invoices WHERE invoice_id=?",
                             (identifier,)).fetchone()
        return _present(fresh)


def _present(row):
    return {"invoice_id": row["invoice_id"], "job_height": row["job_height"],
            "price_lamports": row["gross_lamports"],
            "provider_lamports": row["provider_lamports"],
            "provider_wallet": row["provider_wallet"],
            "platform_fee_lamports": row["fee_lamports"],
            "platform_wallet": row["treasury_wallet"],
            "platform_fee_percent": 3, "memo": row["memo"],
            "network": "devnet", "expires_at": row["expires_at"],
            "status": row["status"],
            "instructions": "Use one transaction with both exact transfers and the exact memo.",
            "warning": "No escrow or refund in this experimental Devnet implementation; NEVER use Mainnet."}


from pydantic import BaseModel


class ConfirmRequest(BaseModel):
    invoice_id: str
    transaction_signature: str


@router.post("/confirm")
def confirm(request: ConfirmRequest):
    if not direct_enabled():
        raise HTTPException(503, "Devnet billing disabled")
    with db() as conn:
        row = conn.execute("SELECT * FROM compute_invoices WHERE invoice_id=?",
                           (request.invoice_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Unknown invoice")
        if row["status"] != "unpaid":
            raise HTTPException(409, "Invoice already settled")
        details = dict(row)
    try:
        verified = verify_transfers(
            request.transaction_signature,
            memo=details["memo"],
            expected={details["provider_wallet"]: details["provider_lamports"],
                      details["treasury_wallet"]: details["fee_lamports"]},
            issued=details["created_at"], expires=details["expires_at"],
        )
    except (ValueError, httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(503, "Devnet transaction verification unavailable") from exc
    if not verified:
        raise HTTPException(400, "No finalized two-transfer SOL settlement found")
    with db() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM compute_invoices WHERE invoice_id=?",
                               (request.invoice_id,)).fetchone()
            if not row or row["status"] != "unpaid":
                raise HTTPException(409, "Invoice already settled")
            job = conn.execute("SELECT * FROM compute_jobs WHERE height=?",
                               (row["job_height"],)).fetchone()
            if not job or job["status"] != "seller_approved_awaiting_payment":
                raise HTTPException(409, "Job cancelled or no longer payable")
            offer = conn.execute("SELECT * FROM compute_capacity WHERE height=?",
                                 (job["capacity_height"],)).fetchone()
            if not offer or offer["status"] != "open":
                raise HTTPException(409, "Provider withdrew before payment verification")
            now = int(time.time())
            try:
                conn.execute("""INSERT INTO payment_signatures
                    (signature,category,reference_id,created_at) VALUES (?,?,?,?)""",
                    (request.transaction_signature, "compute",
                     request.invoice_id, now))
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, "Transaction already used") from exc
            conn.execute("UPDATE compute_invoices SET status='paid',tx_signature=? WHERE invoice_id=?",
                         (request.transaction_signature, request.invoice_id))
            conn.execute("UPDATE compute_jobs SET status='queued',updated_at=? WHERE height=?",
                         (now, row["job_height"]))
            conn.commit()
            return {"ok": True, "job_height": row["job_height"],
                    "status": "queued", "network": "devnet",
                    "platform_fee_lamports": row["fee_lamports"],
                    "provider_lamports": row["provider_lamports"]}
        except Exception:
            conn.rollback()
            raise
