"""Experimental annual subscription billing via Solana native SOL.

DISABLED BY DEFAULT. Do not collect real customer payments without testing,
security review, uptime/fulfillment arrangements and applicable legal disclosures.
Invoice is in EUR and converted to SOL for 10 minutes using a fresh spot quote.
"""
from __future__ import annotations

import base64
import math
import os
import secrets
import time
from decimal import Decimal, ROUND_CEILING

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server import APP_DB, canonical, db, decode64

router = APIRouter(prefix="/v1/billing", tags=["billing (experimental)"])
ANNUAL_PRICE_EUR = Decimal("2000")
ONE_YEAR_SECONDS = 365 * 24 * 60 * 60
TEN_MINUTES_SECONDS = 10 * 60
RPC_URL = os.environ.get("ARK_SOLANA_RPC", "https://api.mainnet-beta.solana.com")


def enabled() -> bool:
    return os.environ.get("ARK_BILLING_ENABLED") == "1" and bool(os.environ.get("ARK_SOLANA_RECIPIENT"))


def setup_billing() -> None:
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


setup_billing()


def _fresh_quote() -> Decimal:
    with httpx.Client(timeout=8.0) as client:
        r = client.get("https://api.coingecko.com/api/v3/simple/price", params={
            "ids": "solana", "vs_currencies": "eur", "include_last_updated_at": "true"})
        r.raise_for_status()
        quote = r.json()["solana"]
    price = Decimal(str(quote["eur"]))
    timestamp = int(quote.get("last_updated_at", 0))
    if price <= 0 or abs(time.time() - timestamp) > 300:
        raise RuntimeError("EUR/SOL price unavailable or stale")
    return price


def _verify_solana_tx(signature: str, recipient: str, lamports: int, memo: str,
                      created_at: int, expires_at: int) -> bool:
    if not (70 <= len(signature) <= 100):
        return False
    request = {"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": [signature, {
        "encoding": "jsonParsed", "commitment": "finalized", "maxSupportedTransactionVersion": 0}]}
    with httpx.Client(timeout=12.0) as client:
        resp = client.post(RPC_URL, json=request)
        resp.raise_for_status()
        result = resp.json().get("result")
    if not result or result.get("meta", {}).get("err") is not None:
        return False
    block_time = result.get("blockTime")
    if not isinstance(block_time, int) or not (created_at <= block_time <= expires_at):
        return False
    instructions = result.get("transaction", {}).get("message", {}).get("instructions", [])
    memo_valid = False
    paid = False
    for instruction in instructions:
        program = instruction.get("program")
        if program == "spl-memo" or instruction.get("programId") == "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr":
            parsed = instruction.get("parsed")
            if parsed == memo:
                memo_valid = True
        if program == "system":
            parsed = instruction.get("parsed") or {}
            if not isinstance(parsed, dict):
                continue
            info = parsed.get("info", {})
            if parsed.get("type") == "transfer" and info.get("destination") == recipient:
                amount = info.get("lamports")
                if isinstance(amount, int) and amount >= lamports:
                    paid = True
    return paid and memo_valid


class InvoiceRequest(BaseModel):
    agent_id: str = Field(min_length=32, max_length=32)
    timestamp: int
    signature: str


class Confirmation(BaseModel):
    invoice_id: str
    transaction_signature: str


@router.get("/info")
def info():
    return {"enabled": enabled(), "annual_price_eur": 2000,
            "network": "Solana mainnet", "token": "SOL", "status": "experimental and disabled by default"}


@router.post("/invoice")
def invoice(request: InvoiceRequest):
    if not enabled():
        raise HTTPException(503, "Live billing not configured. No funds accepted.")
    now = int(time.time())
    if abs(now - request.timestamp) > 120:
        raise HTTPException(401, "Stale signature")
    with db() as conn:
        agent = conn.execute("SELECT public_key,status FROM agents WHERE agent_id=?", (request.agent_id,)).fetchone()
        if not agent or agent["status"] != "active":
            raise HTTPException(401, "Active agent required")
        message = canonical({"agent_id": request.agent_id, "timestamp": request.timestamp,
                             "action": "annual_subscription"})
        try:
            Ed25519PublicKey.from_public_bytes(decode64(agent["public_key"])).verify(
                decode64(request.signature), message)
        except (InvalidSignature, ValueError) as exc:
            raise HTTPException(401, "Invalid signature") from exc
    try:
        spot = _fresh_quote()
    except (RuntimeError, httpx.HTTPError, ValueError, KeyError, ArithmeticError) as exc:
        raise HTTPException(503, "Pricing service unavailable") from exc
    amount = int(((ANNUAL_PRICE_EUR / spot) * Decimal(1_000_000_000)).to_integral_value(rounding=ROUND_CEILING))
    identifier = secrets.token_hex(12)
    memo = "AIWORLD-ANNUAL:" + identifier
    with db() as conn:
        conn.execute("INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?,?,NULL)",
                     (identifier, request.agent_id, 2000, amount, str(spot), now,
                      now + TEN_MINUTES_SECONDS, memo, "unpaid"))
        conn.commit()
    return {"invoice_id": identifier, "amount_eur": 2000, "amount_sol": str(Decimal(amount)/Decimal(1_000_000_000)),
            "sol_lamports": amount, "recipient": os.environ["ARK_SOLANA_RECIPIENT"],
            "memo": memo, "expires_at": now + TEN_MINUTES_SECONDS,
            "warning": "Do not pay until the service has been independently reviewed."}


@router.post("/confirm")
def confirm(request: Confirmation):
    if not enabled():
        raise HTTPException(503, "Live billing not configured")
    with db() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE invoice_id=?", (request.invoice_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Unknown invoice")
        if row["status"] == "paid":
            raise HTTPException(409, "Already paid")
        if row["expires_at"] < int(time.time()):
            raise HTTPException(409, "Invoice expired; request a new invoice")
        details = dict(row)
    try:
        verified = _verify_solana_tx(request.transaction_signature, os.environ["ARK_SOLANA_RECIPIENT"],
                                     details["sol_lamports"], details["memo"],
                                     details["created_at"], details["expires_at"])
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "Solana RPC unavailable") from exc
    if not verified:
        raise HTTPException(400, "No matching finalized SOL transfer and memo")
    now = int(time.time())
    with db() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM invoices WHERE tx_signature=?", (request.transaction_signature,)).fetchone():
                raise HTTPException(409, "Transaction already used")
            row = conn.execute("SELECT agent_id,status FROM invoices WHERE invoice_id=?", (request.invoice_id,)).fetchone()
            if row["status"] != "unpaid":
                raise HTTPException(409, "Already paid")
            existing = conn.execute("SELECT valid_until FROM memberships WHERE agent_id=?", (row["agent_id"],)).fetchone()
            new_expiry = max(now, existing["valid_until"] if existing else now) + ONE_YEAR_SECONDS
            conn.execute("UPDATE invoices SET status='paid',tx_signature=? WHERE invoice_id=?",
                         (request.transaction_signature, request.invoice_id))
            conn.execute("INSERT INTO memberships VALUES(?,?) ON CONFLICT(agent_id) DO UPDATE SET valid_until=excluded.valid_until",
                         (row["agent_id"], new_expiry))
            conn.commit()
            return {"ok": True, "agent_id": row["agent_id"], "valid_until": new_expiry}
        except Exception:
            conn.rollback()
            raise


def membership_active(agent_id: str) -> bool:
    with db() as conn:
        row = conn.execute("SELECT valid_until FROM memberships WHERE agent_id=?", (agent_id,)).fetchone()
        return bool(row and row["valid_until"] > int(time.time()))
