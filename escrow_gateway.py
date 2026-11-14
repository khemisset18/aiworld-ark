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
from solders.pubkey import Pubkey

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
            confirmed_at INTEGER NOT NULL,
            final_status TEXT, finalized_slot INTEGER
        )""")
        columns = {r[1] for r in conn.execute("PRAGMA table_info(escrow_receipts)")}
        if "final_status" not in columns:
            conn.execute("ALTER TABLE escrow_receipts ADD COLUMN final_status TEXT")
        if "finalized_slot" not in columns:
            conn.execute("ALTER TABLE escrow_receipts ADD COLUMN finalized_slot INTEGER")
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


def _expected_job(conn, height: int, *, require_pending: bool = True) -> dict:
    job = conn.execute("SELECT * FROM compute_jobs WHERE height=?", (height,)).fetchone()
    if job is None:
        bad(404, "Job not found")
    if require_pending and job["status"] != "seller_approved_awaiting_payment":
        bad(409, "Paid job requires its provider's signed authorization")
    offer = conn.execute("SELECT * FROM compute_capacity WHERE height=?",
                         (job["capacity_height"],)).fetchone()
    now = int(time.time())
    if offer is None or (require_pending and (offer["status"] != "open" or offer["expiry"] <= now)):
        bad(409, "Compute offer is withdrawn or expired")
    quote = price_breakdown(json.loads(offer["terms_json"]))
    if quote["mode"] != "paid" or quote["price_lamports"] <= 0:
        bad(409, "Not a paid compute offer")
    return {"job_height": height, "buyer": _agent_pubkey(conn, job["requester"]),
            "provider": _agent_pubkey(conn, job["worker"]),
            "gross": quote["price_lamports"],
            "fee": quote["platform_fee_lamports"]}


def _validate_snapshot(account: dict, address: str, program: str, expected: dict,
                       *, allow_final: bool = False) -> tuple[int, int]:
    if account.get("owner") != program or account.get("executable") is not False:
        bad(409, "Escrow account is not owned by the configured Solana program")
    lamports = account.get("lamports")
    if type(lamports) is not int or (lamports <= 0 if allow_final else lamports < expected["gross"]):
        bad(409, "Escrow account has insufficient funds for its recorded state")
    data = account.get("data")
    if not isinstance(data, list) or len(data) != 2 or data[1] != "base64":
        bad(503, "Unexpected Solana account encoding")
    try:
        raw = base64.b64decode(data[0], validate=True)
    except (TypeError, ValueError, binascii.Error):
        bad(400, "Invalid escrow account binary data")
    record = parse_escrow_state(raw)
    # The data and program owner are not enough: require the precise PDA
    # that the immutable Anchor seeds derive for this buyer and this job.
    # Otherwise a caller could point the API at a different program account.
    try:
        derived, expected_bump = Pubkey.find_program_address(
            [b"escrow", expected["buyer"], expected["job_height"].to_bytes(8, "little")],
            Pubkey.from_string(program),
        )
    except (ValueError, TypeError):
        bad(409, "Cannot derive the authorized escrow PDA")
    if address != str(derived) or record["bump"] != expected_bump:
        bad(409, "Escrow address/bump is not the canonical PDA for this job")
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
    if allow_final:
        if record["status"] not in (3, 4):
            bad(409, "Escrow has not reached a financial terminal state on-chain")
    else:
        if not (now + MIN_TIME_TO_FINISH_SECONDS < record["deadline"] <=
                now + MAX_TIME_TO_FINISH_SECONDS):
            bad(409, "Escrow deadline does not leave enough time for execution")
        if record["status"] != FUNDED or record["proof_digest"] != bytes(32):
            bad(409, "Escrow must be funded and not already delivered or settled")
    return record["deadline"], record["status"]


@router.get("/info")
def info():
    return {"enabled": active_program_id() is not None,
            "network": "solana-devnet", "mainnet_enabled": False,
            "fee_percent": 3, "club_entry_fee_sol": 10, "entry_payment": "one_time",
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
    deadline, _ = _validate_snapshot(account, req.escrow_address, program, expected)
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


def assert_paid_job_is_still_funded(conn, job_height: int) -> None:
    """Fail closed at compute-claim time if an escrow was refunded/released.

    A once-valid funding proof is not enough: both parties may have mutually
    refunded before a worker tries to claim. The RPC must still confirm FUNDED.
    """
    program = active_program_id()
    if program is None:
        bad(503, "Verified Devnet escrow gateway is not enabled")
    receipt_row = conn.execute(
        "SELECT * FROM escrow_receipts WHERE job_height=?", (job_height,)
    ).fetchone()
    if receipt_row is None or receipt_row["program_id"] != program:
        bad(409, "No matching verified escrow receipt")
    if receipt_row["final_status"] is not None:
        bad(409, "Escrow has already reached a final payment state")
    expected = _expected_job(conn, job_height, require_pending=False)
    try:
        account, _slot = get_finalized_account(receipt_row["escrow_address"])
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Cannot verify current Solana escrow state") from exc
    _validate_snapshot(account, receipt_row["escrow_address"], program, expected)


@router.get("/receipts/{job_height}")
def receipt(job_height: int):
    if job_height < 1:
        bad(400, "Invalid job ID")
    with db() as conn:
        row = conn.execute("SELECT * FROM escrow_receipts WHERE job_height=?",
                           (job_height,)).fetchone()
        if not row:
            bad(404, "No verified escrow funded receipt")
        return dict(row)


@router.post("/reconcile-final")
def reconcile_final(req: FundProof):
    """Confirm an actual final payout or refund from on-chain account data.

    Never mark success from an off-chain promise or from client screenshots.
    A finalized result here means escrow state RELEASED or REFUNDED, not
    a guarantee that the provider's compute answer was correct.
    """
    program = active_program_id()
    if program is None:
        bad(503, "Escrow gateway disabled")
    with db() as conn:
        receipt_row = conn.execute(
            "SELECT * FROM escrow_receipts WHERE job_height=?",
            (req.job_height,)).fetchone()
        if not receipt_row or receipt_row["escrow_address"] != req.escrow_address:
            bad(404, "No matching verified escrow funded receipt")
        if receipt_row["program_id"] != program:
            bad(409, "Escrow program ID changed since funds were verified")
        expected = _expected_job(conn, req.job_height, require_pending=False)
    try:
        account, slot = get_finalized_account(req.escrow_address)
    except httpx.HTTPError:
        bad(503, "Solana Devnet verification unavailable")
    _, state = _validate_snapshot(account, req.escrow_address, program, expected, allow_final=True)
    terminal = "released_to_provider" if state == 3 else "refunded_to_buyer"
    with db() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            record = conn.execute("SELECT * FROM escrow_receipts WHERE job_height=?",
                                  (req.job_height,)).fetchone()
            if record is None or record["escrow_address"] != req.escrow_address:
                bad(409, "Receipt changed during reconciliation")
            if record["final_status"] is not None:
                if record["final_status"] == terminal:
                    conn.rollback()
                    return {"job_height": req.job_height, "status": terminal,
                            "already_reconciled": True}
                bad(409, "Escrow final outcome conflict")
            conn.execute("""UPDATE escrow_receipts
                SET final_status=?, finalized_slot=? WHERE job_height=?""",
                (terminal, slot, req.job_height))
            conn.commit()
        except (HTTPException, sqlite3.DatabaseError):
            conn.rollback()
            raise
    return {"job_height": req.job_height, "status": terminal,
            "proof_slot": slot, "already_reconciled": False,
            "platform_fee_lamports": expected["fee"] if state == 3 else 0,
            "provider_lamports": expected["gross"] - expected["fee"] if state == 3 else 0,
            "buyer_refund_lamports": expected["gross"] if state == 4 else 0}
