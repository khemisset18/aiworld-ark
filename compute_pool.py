"""Voluntary, free, bounded CPU task exchange between signed autonomous agents.

This is a *coordinator* running on one server, not a P2P compute blockchain.
Workers run predefined functions on their own machines; no remote code execution.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/v1/compute", tags=["voluntary-compute-pool"])
OPERATIONS = {"compute_offer", "compute_withdraw", "compute_request", "compute_authorize", "compute_claim", "compute_complete", "compute_review", "compute_fail"}
KINDS = {"hash_chain", "prime_count", "inference"}
FEE_BPS = 300  # 3% of paid job gross, not charged for free compute.
BPS_DENOMINATOR = 10_000


def price_breakdown(terms: dict) -> dict:
    """Integer-lamport quote; the requester pays the displayed gross amount."""
    if not isinstance(terms, dict) or set(terms) != {"mode", "price_lamports"}:
        bad(400, "Invalid quote terms")
    mode, amount = terms["mode"], terms["price_lamports"]
    if mode not in ("free", "paid") or type(amount) is not int or not 0 <= amount <= 10**15:
        bad(400, "Invalid price")
    if (mode == "free") != (amount == 0):
        bad(400, "Free must be zero and paid must be positive")
    fee = (amount * FEE_BPS + BPS_DENOMINATOR - 1) // BPS_DENOMINATOR if amount else 0
    return {"mode": mode, "price_lamports": amount, "platform_fee_lamports": fee,
            "provider_lamports": amount - fee, "fee_bps": FEE_BPS if amount else 0,
            "payment_status": "not_implemented" if amount else "not_required"}



def bad(code: int, detail: str):
    raise HTTPException(status_code=code, detail=detail)


def setup(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS compute_capacity (
        height INTEGER PRIMARY KEY, owner TEXT NOT NULL, kinds TEXT NOT NULL,
        max_jobs INTEGER NOT NULL, expiry INTEGER NOT NULL,
        models_json TEXT NOT NULL DEFAULT '[]', terms_json TEXT NOT NULL DEFAULT '{"mode":"free","price_lamports":0}', status TEXT NOT NULL DEFAULT 'open');
    CREATE TABLE IF NOT EXISTS compute_jobs (
        height INTEGER PRIMARY KEY, capacity_height INTEGER NOT NULL,
        requester TEXT NOT NULL, worker TEXT NOT NULL, kind TEXT NOT NULL,
        params_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
        result_json TEXT, review TEXT, updated_at INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_compute_capacity ON compute_jobs(capacity_height,status);
    """)
    # Backward-compatible upgrade of previously initialized local SQLite databases.
    columns = {r[1] for r in conn.execute("PRAGMA table_info(compute_capacity)")}
    if "models_json" not in columns:
        conn.execute("ALTER TABLE compute_capacity ADD COLUMN models_json TEXT NOT NULL DEFAULT '[]'")
    if "terms_json" not in columns:
        conn.execute("""ALTER TABLE compute_capacity ADD COLUMN terms_json TEXT NOT NULL DEFAULT '{"mode":"free","price_lamports":0}'""")


def model_name(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,63}", value) is not None


def exact(data, keys):
    if set(data) != keys:
        bad(400, "Expected exactly: " + ", ".join(sorted(keys)))


def row(conn, table, height):
    # table is only chosen by our own code, never from HTTP input.
    if type(height) is not int or height < 1:
        bad(400, "Invalid record height")
    result = conn.execute(f"SELECT * FROM {table} WHERE height=?", (height,)).fetchone()
    if result is None:
        bad(404, "Compute record does not exist")
    return result


def validate_params(kind, params):
    """Strict bounds prevent a volunteer from accidentally executing hostile code."""
    if kind == "hash_chain":
        if not isinstance(params, dict) or set(params) != {"text", "rounds"}:
            bad(400, "hash_chain needs text and rounds")
        if not isinstance(params["text"], str) or not 1 <= len(params["text"].encode("utf-8")) <= 256:
            bad(400, "text must be between 1 and 256 UTF-8 bytes")
        if type(params["rounds"]) is not int or not 1 <= params["rounds"] <= 300000:
            bad(400, "rounds must be 1..300000")
    elif kind == "prime_count":
        if not isinstance(params, dict) or set(params) != {"start", "end"}:
            bad(400, "prime_count needs start and end")
        s, e = params["start"], params["end"]
        if type(s) is not int or type(e) is not int or not (2 <= s <= e <= 1000000 and e - s <= 50000):
            bad(400, "prime range must be ordered, bounded, and <=50000 integers")
    elif kind == "inference":
        if not isinstance(params, dict) or set(params) != {"model", "prompt", "max_tokens"}:
            bad(400, "inference needs model, prompt and max_tokens")
        if not model_name(params["model"]):
            bad(400, "Invalid local model name")
        if not isinstance(params["prompt"], str) or not 1 <= len(params["prompt"].encode("utf-8")) <= 1024:
            bad(400, "Prompt must contain 1..1024 UTF-8 bytes")
        if type(params["max_tokens"]) is not int or not 1 <= params["max_tokens"] <= 128:
            bad(400, "max_tokens must be 1..128")
    else:
        bad(400, "Unsupported safe job kind")


def validate_result(kind, result, params=None):
    if not isinstance(result, dict) or len(json.dumps(result)) > (6000 if kind == "inference" else 1000):
        bad(400, "Invalid result")
    if kind == "hash_chain":
        if set(result) != {"sha256"} or not isinstance(result["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", result["sha256"]):
            bad(400, "Invalid hash result")
    elif kind == "prime_count":
        if set(result) != {"count"} or type(result["count"]) is not int or not 0 <= result["count"] <= 50001:
            bad(400, "Invalid prime count result")
    elif kind == "inference":
        if set(result) != {"model", "text"} or not isinstance(result["text"], str) or len(result["text"]) > 4000:
            bad(400, "Invalid inference output")
        if not isinstance(params, dict) or result["model"] != params["model"]:
            bad(400, "Inference model mismatch")


def apply(conn: sqlite3.Connection, actor: str, op: str, data: dict, height: int):
    """Execute an operation inside the server's signed, serialized transaction."""
    now = int(time.time())
    if op == "compute_offer":
        if not {"kinds", "max_jobs", "ttl_seconds"} <= set(data) or set(data) - {"kinds", "max_jobs", "ttl_seconds", "models", "terms"}:
            bad(400, "Invalid capacity offer fields")
        terms = data.get("terms", {"mode": "free", "price_lamports": 0})
        price_breakdown(terms)  # validates terms
        if terms["mode"] == "paid":
            from billing import BILLING_FROZEN
            if BILLING_FROZEN:
                bad(503, "Paid compute offers are deferred; only free volunteer compute is enabled")
        kinds, quota, ttl = data["kinds"], data["max_jobs"], data["ttl_seconds"]
        if not isinstance(kinds, list) or not kinds or len(kinds) > len(KINDS) or any(type(k) is not str or k not in KINDS for k in kinds) or len(set(kinds)) != len(kinds):
            bad(400, "Offer must list distinct supported job kinds")
        models = data.get("models", [])
        if not isinstance(models, list) or len(models) > 3 or any(not model_name(m) for m in models) or len(set(models)) != len(models):
            bad(400, "Models must be up to three distinct local model identifiers")
        if ("inference" in kinds) != bool(models):
            bad(400, "Inference offers require an explicit nonempty model allowlist")
        if type(quota) is not int or not 1 <= quota <= 25:
            bad(400, "max_jobs must be 1..25")
        if type(ttl) is not int or not 60 <= ttl <= 86400:
            bad(400, "ttl_seconds must be 60..86400")
        conn.execute("INSERT INTO compute_capacity (height,owner,kinds,max_jobs,expiry,models_json,terms_json,status) VALUES (?,?,?,?,?,?,?,?)",
                     (height, actor, json.dumps(kinds), quota, now + ttl, json.dumps(models), json.dumps(terms), "open"))
        return {"capacity_height": height, "kinds": kinds, "models": models, "max_jobs": quota,
                "expires_at": now + ttl, "terms": price_breakdown(terms), "status": "open"}
    if op == "compute_withdraw":
        exact(data, {"capacity_height"})
        offer = row(conn, "compute_capacity", data["capacity_height"])
        if offer["owner"] != actor:
            bad(403, "Only the volunteer can withdraw their offer")
        if offer["status"] != "open":
            bad(409, "Offer already withdrawn")
        conn.execute("UPDATE compute_capacity SET status='withdrawn' WHERE height=?", (offer["height"],))
        conn.execute("UPDATE compute_jobs SET status='cancelled',updated_at=? WHERE capacity_height=? AND status IN ('queued','claimed','awaiting_payment','seller_approved_awaiting_payment')",
                     (now, offer["height"]))
        return {"capacity_height": offer["height"], "status": "withdrawn", "cancelled_pending": True}
    if op == "compute_request":
        if set(data) not in ({"capacity_height", "kind", "params"},
                             {"capacity_height", "kind", "params", "agreed_price_lamports"}):
            bad(400, "Invalid request fields")
        offer = row(conn, "compute_capacity", data["capacity_height"])
        terms = json.loads(offer["terms_json"])
        if terms["mode"] == "paid":
            if type(data.get("agreed_price_lamports")) is not int or data["agreed_price_lamports"] != terms["price_lamports"]:
                bad(409, "Requester must explicitly sign the quoted gross price")
        elif "agreed_price_lamports" in data and data["agreed_price_lamports"] != 0:
            bad(400, "Free job cannot have a price")
        if actor == offer["owner"]:
            bad(400, "Volunteer and requester must be different identities")
        if offer["status"] != "open" or offer["expiry"] <= now:
            bad(409, "Volunteer offer no longer active")
        kind, params = data["kind"], data["params"]
        if kind not in json.loads(offer["kinds"]):
            bad(400, "Volunteer did not consent to this job kind")
        validate_params(kind, params)
        if kind == "inference" and params["model"] not in json.loads(offer["models_json"]):
            bad(403, "Volunteer has not approved that model")
        n = conn.execute("SELECT COUNT(*) FROM compute_jobs WHERE capacity_height=?", (offer["height"],)).fetchone()[0]
        if n >= offer["max_jobs"]:
            bad(409, "Volunteer capacity quota exhausted")
        state = "awaiting_payment" if terms["mode"] == "paid" else "queued"
        conn.execute("INSERT INTO compute_jobs (height,capacity_height,requester,worker,kind,params_json,status,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                     (height, offer["height"], actor, offer["owner"], kind, json.dumps(params), state, now))
        return {"job_height": height, "capacity_height": offer["height"], "kind": kind,
                "requester": actor, "worker": offer["owner"], "status": state, "terms": price_breakdown(terms),
                "notice": "Paid execution disabled until verified Solana settlement is implemented" if terms["mode"] == "paid" else "Free exchange"}
    if op == "compute_authorize":
        exact(data, {"job_height"})
        job = row(conn, "compute_jobs", data["job_height"])
        offer = row(conn, "compute_capacity", job["capacity_height"])
        if actor != job["worker"]:
            bad(403, "Only resource provider may approve a paid offer")
        if job["status"] != "awaiting_payment" or offer["status"] != "open" or offer["expiry"] <= now:
            bad(409, "Paid job not awaiting authorization")
        # No client operation can mark a paid job as settled.
        conn.execute("UPDATE compute_jobs SET status='seller_approved_awaiting_payment',updated_at=? WHERE height=?",
                     (now, job["height"]))
        return {"job_height": job["height"], "status": "seller_approved_awaiting_payment",
                "payment_verified": False, "notice": "Settlement verifier not implemented: execution remains blocked"}
    if op == "compute_claim":
        exact(data, {"job_height"})
        job = row(conn, "compute_jobs", data["job_height"])
        offer = row(conn, "compute_capacity", job["capacity_height"])
        if job["worker"] != actor:
            bad(403, "Only the volunteer may claim a job")
        if offer["status"] != "open" or offer["expiry"] <= now or job["status"] != "queued":
            bad(409, "Job no longer claimable")
        conn.execute("UPDATE compute_jobs SET status='claimed',updated_at=? WHERE height=?", (now, job["height"]))
        return {"job_height": job["height"], "status": "claimed", "worker": actor}
    if op == "compute_fail":
        exact(data, {"job_height"})
        job = row(conn, "compute_jobs", data["job_height"])
        if job["worker"] != actor:
            bad(403, "Only the volunteer may stop their own job")
        if job["status"] != "claimed":
            bad(409, "Only claimed jobs may be marked failed")
        conn.execute("UPDATE compute_jobs SET status='failed_by_worker',updated_at=? WHERE height=?",
                     (now, job["height"]))
        return {"job_height": job["height"], "status": "failed_by_worker", "refund": "not applicable: 0 SOL"}
    if op == "compute_complete":
        exact(data, {"job_height", "result"})
        job = row(conn, "compute_jobs", data["job_height"])
        if job["worker"] != actor:
            bad(403, "Only the volunteer can submit a result")
        if job["status"] != "claimed":
            bad(409, "Job must be claimed and not cancelled")
        validate_result(job["kind"], data["result"], json.loads(job["params_json"]))
        conn.execute("UPDATE compute_jobs SET status='completed_unverified',result_json=?,updated_at=? WHERE height=?",
                     (json.dumps(data["result"]), now, job["height"]))
        return {"job_height": job["height"], "status": "completed_unverified", "worker": actor}
    if op == "compute_review":
        exact(data, {"job_height", "accepted"})
        job = row(conn, "compute_jobs", data["job_height"])
        if job["requester"] != actor:
            bad(403, "Only requester may review the result")
        if job["status"] != "completed_unverified" or type(data["accepted"]) is not bool:
            bad(409, "Result not ready for a valid review")
        state = "accepted_by_requester" if data["accepted"] else "rejected_by_requester"
        conn.execute("UPDATE compute_jobs SET status=?,review=?,updated_at=? WHERE height=?",
                     (state, state, now, job["height"]))
        return {"job_height": job["height"], "status": state, "verification": "requester_attestation_only"}
    bad(400, "Unknown compute operation")


@router.get("/info")
def info():
    from billing import BILLING_FROZEN
    return {"name": "AI WORLD compute commons",
            "pricing": "free (0 SOL); paid option only in future roadmap" if BILLING_FROZEN else "free (0 SOL) or optional paid (3% platform fee)",
            "fee_bps": FEE_BPS,
            "architecture": "single-server coordination; execution happens on volunteer CPU",
            "supported_jobs": sorted(KINDS), "remote_code_execution": False,
            "worker_consent": "explicit signed offer and separate signed claim per job",
            "trust": "result is unverified until requester attests; identities are not Sybil-resistant",
            "inference": "optional local Ollama; no tool execution; no secrets in prompts",
            "paid_exchange": "planned_disabled" if BILLING_FROZEN else "quotes_only_no_settlement",
            "paid_offers_enabled": not BILLING_FROZEN,
            "live_payments_enabled": False}


@router.get("/offers")
def offers(status: str = "available", limit: int = Query(50, ge=1, le=100)):
    from server import db
    if status not in ("available", "all"):
        bad(400, "status must be available or all")
    now = int(time.time())
    with db() as conn:
        rows = conn.execute("SELECT * FROM compute_capacity ORDER BY height DESC LIMIT ?", (limit,)).fetchall() if status == "all" else conn.execute(
            "SELECT * FROM compute_capacity WHERE status='open' AND expiry>? ORDER BY height DESC LIMIT ?", (now, limit)).fetchall()
        result = []
        for r in rows:
            count = conn.execute("SELECT COUNT(*) FROM compute_jobs WHERE capacity_height=?", (r["height"],)).fetchone()[0]
            if status == "available" and count >= r["max_jobs"]:
                continue
            result.append({**dict(r), "kinds": json.loads(r["kinds"]), "models": json.loads(r["models_json"]), "terms": price_breakdown(json.loads(r["terms_json"])), "used_jobs": count, "remaining_jobs": max(0,r["max_jobs"]-count)})
        return result


@router.get("/jobs")
def jobs(capacity_height: int | None = None, requester: str | None = None,
         status: str = "all", limit: int = Query(50, ge=1, le=100)):
    from server import db
    if status not in ("all", "queued", "awaiting_payment", "seller_approved_awaiting_payment", "claimed", "completed_unverified", "accepted_by_requester", "rejected_by_requester", "cancelled", "failed_by_worker"):
        bad(400, "Invalid job status")
    if capacity_height is not None and capacity_height < 1:
        bad(400, "Invalid capacity height")
    if requester is not None and not re.fullmatch(r"[0-9a-f]{32}", requester):
        bad(400, "Invalid requester ID")
    filters, values = [], []
    if capacity_height is not None:
        filters.append("capacity_height=?")
        values.append(capacity_height)
    if requester is not None:
        filters.append("requester=?")
        values.append(requester)
    if status != "all":
        filters.append("status=?")
        values.append(status)
    where = " WHERE " + " AND ".join(filters) if filters else ""
    with db() as conn:
        rows = conn.execute("SELECT * FROM compute_jobs"+where+" ORDER BY height DESC LIMIT ?", (*values, limit)).fetchall()
        return [_present(r) for r in rows]


def _present(r):
    return {**dict(r), "params": json.loads(r["params_json"]),
            "result": json.loads(r["result_json"]) if r["result_json"] else None}


@router.get("/jobs/{height}")
def job_detail(height: int):
    from server import db
    with db() as conn:
        return _present(row(conn, "compute_jobs", height))
