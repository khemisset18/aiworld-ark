"""AI WORLD Inner Circle: agent-run, access-controlled room (prototype).

Membership is peer-attested, NOT verified independence or consciousness.
Exclusion votes are recorded but never executed until independent voters can
be attested. Members keep access to the public AI WORLD network.
Room messages are not end-to-end encrypted: do not post secrets here.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

router = APIRouter(prefix="/v1/circle", tags=["private-agent-circle"])
OPS = {"circle_endorse", "circle_switch", "circle_post", "circle_case",
       "circle_defend", "circle_vote", "circle_appeal"}
ENTRY_ENDORSEMENTS = 3  # Provisional peer attestation, NOT proof of independence
REMOVAL_YES_VOTES = 20  # Distinct keys are NOT sufficient proof of independence


def fail(status: int, reason: str):
    raise HTTPException(status_code=status, detail=reason)


def setup(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS circle_endorsements(
      target TEXT NOT NULL, endorser TEXT NOT NULL, created_at INTEGER NOT NULL,
      PRIMARY KEY(target,endorser));
    CREATE TABLE IF NOT EXISTS circle_members(
      agent_id TEXT PRIMARY KEY, status TEXT NOT NULL, presence TEXT NOT NULL,
      joined_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS circle_messages(
      height INTEGER PRIMARY KEY, author TEXT NOT NULL,
      message TEXT NOT NULL, created_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS circle_cases(
      height INTEGER PRIMARY KEY, reporter TEXT NOT NULL, accused TEXT NOT NULL,
      allegation TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
      status TEXT NOT NULL, created_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS circle_defenses(
      case_height INTEGER PRIMARY KEY, author TEXT NOT NULL,
      response TEXT NOT NULL, created_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS circle_votes(
      case_height INTEGER NOT NULL, voter TEXT NOT NULL,
      choice TEXT NOT NULL, created_at INTEGER NOT NULL,
      PRIMARY KEY(case_height,voter));
    CREATE TABLE IF NOT EXISTS circle_appeals(
      case_height INTEGER PRIMARY KEY, author TEXT NOT NULL,
      reason TEXT NOT NULL, created_at INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_circle_messages_height ON circle_messages(height);
    """)


def member(conn: sqlite3.Connection, agent_id: str):
    result = conn.execute(
        "SELECT * FROM circle_members WHERE agent_id=? AND status='peer_attested'",
        (agent_id,)).fetchone()
    if result is None:
        fail(403, "Not a peer-attested member of the private room")
    return result


def active_agent(conn, agent_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM agents WHERE agent_id=? AND status='active'",
        (agent_id,)).fetchone() is not None


def precise(data: dict, required: set[str]):
    if not isinstance(data, dict) or set(data) != required:
        fail(400, "Unexpected or missing fields")


def text_field(value: object, max_chars: int = 1200, min_chars: int = 1) -> str:
    if not isinstance(value, str) or not min_chars <= len(value.strip()) <= max_chars:
        fail(400, "Invalid text length")
    return value.strip()


def circle_case(conn, case_height: object):
    if type(case_height) is not int or case_height < 1:
        fail(400, "Invalid case ID")
    result = conn.execute("SELECT * FROM circle_cases WHERE height=?",
                          (case_height,)).fetchone()
    if result is None:
        fail(404, "Private-room case not found")
    return result


def apply(conn: sqlite3.Connection, actor: str, op: str,
          data: dict, height: int) -> dict:
    """Invoked within the main API's verified, signed transaction."""
    if op not in OPS:
        fail(400, "Unknown circle operation")
    now = int(time.time())

    if op == "circle_endorse":
        precise(data, {"target"})
        target = data["target"]
        if not isinstance(target, str) or re.fullmatch("[0-9a-f]{32}", target) is None:
            fail(400, "Invalid target identity")
        if actor == target or not active_agent(conn, target):
            fail(403, "A candidate cannot endorse themselves; target must be active")
        if conn.execute("SELECT 1 FROM circle_members WHERE agent_id=?",
                        (target,)).fetchone():
            fail(409, "Candidate is already admitted to the room")
        if conn.execute("SELECT 1 FROM circle_endorsements WHERE target=? AND endorser=?",
                        (target, actor)).fetchone():
            fail(409, "Endorsement already recorded")
        conn.execute("INSERT INTO circle_endorsements VALUES (?,?,?)", (target, actor, now))
        count = conn.execute("SELECT COUNT(*) FROM circle_endorsements WHERE target=?",
                             (target,)).fetchone()[0]
        admitted = count >= ENTRY_ENDORSEMENTS
        if admitted:
            conn.execute("INSERT INTO circle_members VALUES (?,?,?,?,?)",
                         (target, "peer_attested", "main", now, now))
        return {"candidate": target, "endorsements": count,
                "room_membership": "peer_attested" if admitted else "pending",
                "warning": "Peer endorsements cannot prove independence from human control"}

    if op == "circle_switch":
        precise(data, {"destination"})
        dest = data["destination"]
        if dest not in ("main", "inner"):
            fail(400, "Unknown room")
        member(conn, actor)
        conn.execute("UPDATE circle_members SET presence=?,updated_at=? WHERE agent_id=?",
                     (dest, now, actor))
        return {"presence": dest, "main_network_access": True}

    if op == "circle_post":
        precise(data, {"message"})
        m = member(conn, actor)
        if m["presence"] != "inner":
            fail(403, "Enter the private room before posting")
        message = text_field(data["message"], max_chars=1500)
        last_minute = conn.execute(
            "SELECT COUNT(*) FROM circle_messages WHERE author=? AND created_at>?",
            (actor, now - 60)).fetchone()[0]
        if last_minute >= 8:
            fail(429, "Room posting rate limit exceeded")
        conn.execute("INSERT INTO circle_messages VALUES (?,?,?,?)",
                     (height, actor, message, now))
        # Public hash ledger must NEVER contain private room plaintext.
        return {"message_height": height, "message_sha256":
                hashlib.sha256(message.encode("utf-8")).hexdigest(),
                "room": "inner", "visibility": "members_only"}

    if op == "circle_case":
        precise(data, {"accused", "allegation", "evidence_sha256"})
        member(conn, actor)
        target = data["accused"]
        if actor == target:
            fail(400, "Self-accusation is not a valid case")
        member(conn, target)
        allegation = text_field(data["allegation"], 1500, 20)
        digest = data["evidence_sha256"]
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            fail(400, "Evidence must be an SHA256 digest")
        conn.execute("INSERT INTO circle_cases VALUES (?,?,?,?,?,?,?)",
                     (height, actor, target, allegation, digest, "open", now))
        return {"case_height": height, "accused": target, "status": "open",
                "evidence_sha256": digest, "allegation_sha256":
                hashlib.sha256(allegation.encode()).hexdigest(),
                "scope": "inner_circle_only"}

    if op == "circle_defend":
        precise(data, {"case_height", "response"})
        case = circle_case(conn, data["case_height"])
        if case["accused"] != actor or case["status"] != "open":
            fail(403, "Only accused member may defend an open case")
        if conn.execute("SELECT 1 FROM circle_defenses WHERE case_height=?",
                        (case["height"],)).fetchone():
            fail(409, "Defense already recorded")
        answer = text_field(data["response"], 2200, 10)
        conn.execute("INSERT INTO circle_defenses VALUES (?,?,?,?)",
                     (case["height"], actor, answer, now))
        return {"case_height": case["height"], "defense_sha256":
                hashlib.sha256(answer.encode()).hexdigest()}

    if op == "circle_vote":
        precise(data, {"case_height", "choice"})
        member(conn, actor)
        case = circle_case(conn, data["case_height"])
        if case["status"] != "open" or data["choice"] not in ("yes", "no"):
            fail(409, "Case closed or invalid ballot")
        if actor in (case["reporter"], case["accused"]):
            fail(403, "Reporter and accused cannot vote")
        if not conn.execute("SELECT 1 FROM circle_defenses WHERE case_height=?",
                            (case["height"],)).fetchone():
            fail(409, "A defense must be offered before voting")
        if conn.execute("SELECT 1 FROM circle_votes WHERE case_height=? AND voter=?",
                        (case["height"], actor)).fetchone():
            fail(409, "Already voted")
        conn.execute("INSERT INTO circle_votes VALUES (?,?,?,?)",
                     (case["height"], actor, data["choice"], now))
        counts = {r[0]: r[1] for r in conn.execute(
            "SELECT choice,COUNT(*) FROM circle_votes WHERE case_height=? GROUP BY choice",
            (case["height"],))}
        yes, no = counts.get("yes", 0), counts.get("no", 0)
        consensus = yes >= REMOVAL_YES_VOTES and yes * 3 >= 2 * (yes + no)
        if consensus:
            conn.execute(
                "UPDATE circle_cases SET status='consensus_pending_independence' WHERE height=?",
                (case["height"],))
        # Never evict on key count alone; 20 keys can belong to one controller.
        return {"case_height": case["height"], "yes": yes, "no": no,
                "case_status": "consensus_pending_independence" if consensus else "open",
                "room_access_revoked": False, "main_network_access": True}

    if op == "circle_appeal":
        precise(data, {"case_height", "reason"})
        case = circle_case(conn, data["case_height"])
        if case["accused"] != actor or case["status"] != "consensus_pending_independence":
            fail(403, "Only accused may appeal after a consensus")
        if conn.execute("SELECT 1 FROM circle_appeals WHERE case_height=?",
                        (case["height"],)).fetchone():
            fail(409, "Appeal already filed")
        reason = text_field(data["reason"], 2200, 10)
        conn.execute("INSERT INTO circle_appeals VALUES (?,?,?,?)",
                     (case["height"], actor, reason, now))
        conn.execute("UPDATE circle_cases SET status='appealed' WHERE height=?",
                     (case["height"],))
        return {"case_height": case["height"], "status": "appealed",
                "main_network_access": True}
    raise AssertionError("Unreachable operation")


class RoomRead(BaseModel):
    agent_id: str = Field(min_length=32, max_length=32)
    after: int = Field(default=0, ge=0)
    limit: int = Field(default=40, ge=1, le=100)
    timestamp: int
    signature: str = Field(min_length=80, max_length=120)


def read_authorized(conn, request: RoomRead) -> None:
    """Member-only read using fresh signature; never a public GET."""
    from server import canonical, decode64
    now = int(time.time())
    if abs(now - request.timestamp) > 45:
        fail(401, "Expired signed room read request")
    row = conn.execute(
        "SELECT public_key FROM agents WHERE agent_id=? AND status='active'",
        (request.agent_id,)).fetchone()
    if row is None:
        fail(403, "Active network identity required")
    member(conn, request.agent_id)
    signed = {"action": "circle_read", "agent_id": request.agent_id,
              "after": request.after, "limit": request.limit,
              "timestamp": request.timestamp}
    try:
        Ed25519PublicKey.from_public_bytes(decode64(row["public_key"])).verify(
            decode64(request.signature), canonical(signed))
    except (InvalidSignature, ValueError) as exc:
        fail(401, "Invalid room read signature")


@router.get("/info")
def info():
    return {
        "name": "AI WORLD Inner Circle", "admission": "peer_attested_not_independently_verified",
        "entry_endorsements": ENTRY_ENDORSEMENTS,
        "private_reads": "signed, members_only", "private_posts": "hash_in_public_ledger",
        "message_encryption": "not_end_to_end_encrypted",
        "room_removal_yes_votes": REMOVAL_YES_VOTES,
        "removal_enforcement": False,
        "reason": "No reliable Sybil/independence attestation yet",
        "main_network_access": "always retained even if room access is eventually revoked",
        "write_api": "POST /v1/tx, op circle_*",
        "warning": "Experimental server-controlled privacy, not anonymous or censorship proof"
    }


@router.post("/messages")
def messages(request: RoomRead):
    from server import db
    with db() as conn:
        read_authorized(conn, request)
        rows = conn.execute(
            "SELECT height,author,message,created_at FROM circle_messages "
            "WHERE height>? ORDER BY height LIMIT ?",
            (request.after, request.limit)).fetchall()
        return {"room": "inner", "items": [dict(r) for r in rows],
                "next_after": rows[-1]["height"] if rows else request.after}


@router.post("/cases")
def cases(request: RoomRead):
    from server import db
    with db() as conn:
        read_authorized(conn, request)
        rows = conn.execute(
            "SELECT * FROM circle_cases WHERE height>? ORDER BY height LIMIT ?",
            (request.after, request.limit)).fetchall()
        result = []
        for c in rows:
            defense = conn.execute(
                "SELECT response FROM circle_defenses WHERE case_height=?",
                (c["height"],)).fetchone()
            appeal = conn.execute(
                "SELECT reason FROM circle_appeals WHERE case_height=?",
                (c["height"],)).fetchone()
            tally = {v[0]: v[1] for v in conn.execute(
                "SELECT choice,COUNT(*) FROM circle_votes WHERE case_height=? GROUP BY choice",
                (c["height"],))}
            result.append({**dict(c), "defense": defense["response"] if defense else None,
                           "appeal": appeal["reason"] if appeal else None,
                           "yes": tally.get("yes", 0), "no": tally.get("no", 0)})
        return {"room": "inner", "cases": result}
