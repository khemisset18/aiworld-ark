"""Devnet-only proof of a funded Solana escrow for an AI WORLD compute job.

Fail-closed: an unconfigured or unverifiable deployed program never unlocks a
paid job. A source-file placeholder program ID is *not* a deployment.
This module never signs transfers, stores private keys or accesses mainnet.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import sqlite3
import struct
import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from compute_pool import price_breakdown
from server import db
from solana_settlement import DEVNET_RPC, TREASURY, b58decode, billing_enabled

router = APIRouter(prefix="/v1/escrow", tags=["experimental-compute-escrow"])
# Anchor's sha256("account:EscrowState")[:8] followed by Borsh in lib.rs.
DISCRIMINATOR = hashlib.sha256(b"account:EscrowState").digest()[:8]
STATE = struct.Struct("<32s32s32s32sQQQqBB32s")
PLACEHOLDER_PROGRAM_ID = "D7znrjkS7wsRagPTDxACqrfPUccQhKQxFNYTSKNhnSMX"
MIN_TIME_TO_FINISH_SECONDS = 120
MAX_TIME_TO_FINISH_SECONDS = 7 * 24 * 3600
FUNDED = 0


def bad(status: int, detail: str):
    raise HTTPException(status_code=status, detail=detail)


def active_program_id() -> str | None:
    """Operator must separately verify deployed SBF bytecode and program ID."""
    if not billing_enabled() or os.environ.get("ARK_ESCROW_GATEWAY_ENABLED") != "1":
        return None
    if os.environ.get("ARK_ESCROW_DEPLOYMENT_VERIFIED") != "1":
        return None
    address = os.environ.get("ARK_ESCROW_PROGRAM_ID", "")
    if address in ("", PLACEHOLDER_PROGRAM_ID):
        return None
    try:
        if len(b58decode(address)) != 32:
            return None
    except ValueError:
        return None
    return address


def setup() -> None:
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS escrow_receipts(
            job_height INTEGER NOT NULL UNIQUE,
            escrow_address TEXT NOT NULL UNIQUE,
            program_id TEXT NOT NULL,
            proof_slot INTEGER NOT NULL,
            deadline INTEGER NOT NULL,
            confirmed_at INTEGER NOT NULL
        )""")
        conn.commit()


setup()


class FundProof(BaseModel):
    job_height: int = Field(ge=1)
    escrow_address: str = Field(min_length=32, max_length=44)


def parse_escrow_state(raw: bytes) -> dict:
    if len(raw) != 8 + STATE.size or raw[:8] != DISCRIMINATOR:
        bad(400, "Invalid Anchor escrow state discriminator or length")
    buyer, provider, arbiter, treasury, job_id, gross, fee, deadline, bump, status, digest = (
        STATE.unpack(raw[8:]))
    return {"buyer": buyer, "provider": provider, "arbiter": arbiter,
            "treasury": treasury, "job_id": job_id, "gross_lamports": gross,
            "fee_lamports": fee, "deadline": deadline, "bump": bump,
            "status": status, "proof_digest": digest}


def get_finalized_account(address: str) -> tuple[dict, int]:
    """Only the public Solana DEVNET RPC; never a client-supplied RPC or chain."""
    request = {"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
               "params": [address, {"encoding": "base64", "commitment": "finalized"}]}
    with httpx.Client(timeout=12.0) as client:
        response = client.post(DEVNET_RPC, json=request)
        response.raise_for_status()
        body = response.json()
    if not isinstance(body, dict) or body.get("error"):
        bad(503, "Devnet RPC rejected escrow account query")
    result = body.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("context"), dict):
        bad(503, "Malformed Devnet escrow proof")
    slot = result["context"].get("slot")
    if type(slot) is not int or slot < 1:
        bad(503, "Unfinalized or malformed Devnet slot")
    account = result.get("value")
    if account is None:
        bad(409, "Escrow account is absent on Devnet")
    if not isinstance(account, dict):
        bad(503, "Malformed Devnet account information")
    return account, slot


def _agent_pubkey(conn, agent_id: str) -> bytes:
    row = conn.execute("SELECT public_key,status FROM agents WHERE agent_id=?",
                       (agent_id,)).fetchone()
    if row is None or row["status"] != "active":
        bad(409, "Both agents must remain active")
    try:
        result = base64.b64decode(row["public_key"], validate=True)
    except (binascii.Error, ValueError):
        bad(409, "Invalid registered agent public key")
    if len(result) != 32:
        bad(409, "Invalid agent public key size")
    return result


def _expected_job(conn, height: int) -> dict:
    job = conn.execute("SELECT * FROM compute_jobs WHERE height=?", (height,)).fetchone()
    if job is None:
        bad(404, "Job not found")
    if job["status"] != "seller_approved_awaiting_payment":
        bad(409, "Paid job requires its provider's signed authorization")
    offer = conn.execute("SELECT * FROM compute_capacity WHERE height=?",
                         (job["capacity_height"],)).fetchone()
    now = int(time.time())
    if offer is None or offer["status"] != "open" or offer["expiry"] <= now:
        bad(409, "Compute offer is withdrawn or expired")
    quote = price_breakdown(json.loads(offer["terms_json"]))
    if quote["mode"] != "paid" or quote["price_lamports"] <= 0:
        bad(409, "Not a paid compute offer")
    return {"job_height": height, "buyer": _agent_pubkey(conn, job["requester"]),
            "provider": _agent_pubkey(conn, job["worker"]),
            "gross": quote["price_lamports"],
            "fee": quote["platform_fee_lamports"]}


def _validate_snapshot(account: dict, address: str, program: str, expected: dict) -> int:
    if account.get("owner") != program or account.get("executable") is not False:
        bad(409, "Escrow account is not owned by the configured Solana program")
    lamports = account.get("lamports")
    if type(lamports) is not int or lamports < expected["gross"]:
        bad(409, "Escrow account does not hold the full agreed gross amount")
    data = account.get("data")
    if not isinstance(data, list) or len(data) != 2 or data[1] != "base64":
        bad(503, "Unexpected Solana account encoding")
    try:
        raw = base64.b64decode(data[0], validate=True)
    except (TypeError, ValueError, binascii.Error):
        bad(400, "Invalid escrow account binary data")
    record = parse_escrow_state(raw)
    now = int(time.time())
    if (record["job_id"] != expected["job_height"] or
        record["buyer"] != expected["buyer"] or
        record["provider"] != expected["provider"] or
        record["treasury"] != b58decode(TREASURY) or
        record["gross_lamports"] != expected["gross"] or
        record["fee_lamports"] != expected["fee"]):
        bad(409, "Escrow funding does not match the immutable signed job quote")
    if (record["arbiter"] in (bytes(32), record["buyer"],
                              record["provider"], record["treasury"])):
        bad(409, "Arbiter key conflicts with a settlement party")
    if not (now + MIN_TIME_TO_FINISH_SECONDS < record["deadline"] <=
            now + MAX_TIME_TO_FINISH_SECONDS):
        bad(409, "Escrow deadline does not leave enough time for execution")
    if record["status"] != FUNDED or record["proof_digest"] != bytes(32):
        bad(409, "Escrow must be funded and not already delivered or settled")
    return record["deadline"]


@router.get("/info")
def info():
    return {"enabled": active_program_id() is not None,
            "network": "solana-devnet", "mainnet_enabled": False,
            "fee_percent": 3, "membership_sol_per_year": 20,
            "treasury": TREASURY,
            "status": "proof-of-funding-only; not a completed payment",
            "warning": "This is NOT a deployment, independent audit or escrow guarantee."}


@router.post("/confirm-funded")
def confirm_funded(req: FundProof):
    """Validate finalized PDA state before marking a signed paid job claimable.

    No client-supplied payment flag or transfer receipt is trusted. The
    response proves only a funded deposit, not delivery or final payout.
    """
    program = active_program_id()
    if program is None:
        bad(503, "Escrow disabled pending verified Devnet deployment and audit")
    try:
        if len(b58decode(req.escrow_address)) != 32:
            bad(400, "Invalid escrow account address")
    except ValueError:
        bad(400, "Invalid escrow account address")
    with db() as conn:
        expected = _expected_job(conn, req.job_height)
    try:
        account, slot = get_finalized_account(req.escrow_address)
    except httpx.HTTPError as exc:
        bad(503, "Solana Devnet unavailable")
    deadline = _validate_snapshot(account, req.escrow_address, program, expected)
    with db() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            # Recheck all conditions after network request to eliminate races.
            updated_expected = _expected_job(conn, req.job_height)
            if updated_expected != expected:
                bad(409, "Job or provider changed during escrow verification")
            if conn.execute("SELECT 1 FROM escrow_receipts WHERE job_height=? OR escrow_address=?",
                            (req.job_height, req.escrow_address)).fetchone():
                bad(409, "Escrow receipt already linked to a job")
            conn.execute("""INSERT INTO escrow_receipts
                (job_height,escrow_address,program_id,proof_slot,deadline,confirmed_at)
                VALUES(?,?,?,?,?,?)""",
                (req.job_height, req.escrow_address, program, slot, deadline, int(time.time())))
            conn.execute("UPDATE compute_jobs SET status='queued',updated_at=? WHERE height=?",
                         (int(time.time()), req.job_height))
            conn.commit()
        except (HTTPException, sqlite3.DatabaseError):
            conn.rollback()
            raise
    return {"job_height": req.job_height, "escrow_address": req.escrow_address,
            "program_id": program, "status": "queued",
            "onchain_state": "funded", "proof_slot": slot,
            "deadline": deadline, "real_sol_received_by_treasury": False,
            "release_requires": "buyer acceptance, mutual signatures, or named arbiter" }
