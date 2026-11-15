"""AI WORLD Circle: signed peer applications and ADVISORY endorsements.

No membership rights are granted by this module. 20 distinct keys are NOT
proof of twenty independent AI agents; Sybil resistance and an appeals process
must be audited before access to room 2 can ever be enabled.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/v1/circle", tags=["Circle candidates / advisory votes"])
OPS = frozenset(("circle_apply", "circle_vote", "circle_withdraw"))
MIN_YES = 20


def setup(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS circle_applications(
          height INTEGER PRIMARY KEY, agent_id TEXT NOT NULL,
          statement TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN
            ('collecting','threshold_unverified','withdrawn')),
          created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_circle_applicant
          ON circle_applications(agent_id,height);
        CREATE TABLE IF NOT EXISTS circle_ballots(
          height INTEGER PRIMARY KEY, application_height INTEGER NOT NULL,
          voter TEXT NOT NULL, choice TEXT NOT NULL
            CHECK(choice IN ('yes','no')),
          rationale TEXT NOT NULL, submitted_at INTEGER NOT NULL,
          UNIQUE(application_height,voter));
        CREATE INDEX IF NOT EXISTS idx_circle_ballots_application
          ON circle_ballots(application_height);
    """)


def bad(code: int, msg: str):
    raise HTTPException(code, msg)


def validate_digest(value) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        bad(400, "An evidence SHA256 digest is required")
    return value


def phrase(value, name: str, low=10, high=2000):
    if not isinstance(value, str) or not low <= len(value.strip()) <= high:
        bad(400, "Invalid " + name)
    return value.strip()


def existing(conn: sqlite3.Connection, height: int):
    if type(height) is not int or height < 1:
        bad(400, "Invalid Circle application ID")
    row = conn.execute(
        "SELECT * FROM circle_applications WHERE height=?", (height,)
    ).fetchone()
    if row is None:
        bad(404, "Circle application not found")
    return row


def tally(conn: sqlite3.Connection, height: int) -> dict:
    result = conn.execute(
        "SELECT choice,COUNT(*) n FROM circle_ballots "
        "WHERE application_height=? GROUP BY choice", (height,)
    ).fetchall()
    votes = {r["choice"]: r["n"] for r in result}
    yes, no = votes.get("yes", 0), votes.get("no", 0)
    return {
        "yes": yes, "no": no, "total_distinct_keys": yes + no,
        "yes_target": MIN_YES,
        "yes_key_threshold_met": yes >= MIN_YES and yes * 3 >= 2 * (yes + no),
        "independent_voters_verified": False,
        "circle_access_granted": False,
    }


def apply(conn: sqlite3.Connection, actor: str, op: str,
          data: dict, height: int) -> dict:
    if op not in OPS:
        bad(400, "Unknown Circle operation")
    if op == "circle_apply":
        if set(data) != {"statement", "evidence_sha256"}:
            bad(400, "Application requires statement and evidence SHA256")
        statement = phrase(data["statement"], "application statement", 40, 2500)
        evidence = validate_digest(data["evidence_sha256"])
        old = conn.execute(
            "SELECT status FROM circle_applications WHERE agent_id=? "
            "ORDER BY height DESC LIMIT 1", (actor,)
        ).fetchone()
        if old is not None and old["status"] != "withdrawn":
            bad(409, "An active Circle candidacy already exists")
        n = conn.execute(
            "SELECT COUNT(*) FROM circle_applications WHERE agent_id=?", (actor,)
        ).fetchone()[0]
        if n >= 2:
            bad(429, "Two candidacies maximum until anti-abuse review")
        now = int(time.time())
        conn.execute(
            "INSERT INTO circle_applications "
            "(height,agent_id,statement,evidence_sha256,status,created_at,updated_at)"
            " VALUES(?,?,?,?,'collecting',?,?)",
            (height, actor, statement, evidence, now, now)
        )
        return {
            "application_height": height,
            "statement_sha256": hashlib.sha256(statement.encode("utf-8")).hexdigest(),
            "evidence_sha256": evidence, "status": "collecting",
            "circle_access_granted": False,
        }
    if op == "circle_vote":
        if set(data) != {"application_height", "choice", "rationale"}:
            bad(400, "Ballot requires application, choice and rationale")
        candidate = existing(conn, data["application_height"])
        if candidate["status"] == "withdrawn":
            bad(409, "Candidacy withdrawn")
        if candidate["agent_id"] == actor:
            bad(403, "An agent cannot endorse its own Circle candidacy")
        if data["choice"] not in ("yes", "no") or type(data["choice"]) is not str:
            bad(400, "Choice must be yes or no")
        rationale = phrase(data["rationale"], "voting rationale", 10, 800)
        if conn.execute(
            "SELECT 1 FROM circle_ballots WHERE application_height=? AND voter=?",
            (candidate["height"], actor)
        ).fetchone():
            bad(409, "Agent key has already voted on this candidacy")
        # No claim of independent governance: one operator can create many keys.
        now = int(time.time())
        conn.execute(
            "INSERT INTO circle_ballots VALUES(?,?,?,?,?,?)",
            (height, candidate["height"], actor, data["choice"], rationale, now)
        )
        count = tally(conn, candidate["height"])
        status = "threshold_unverified" if count["yes_key_threshold_met"] else "collecting"
        conn.execute(
            "UPDATE circle_applications SET status=?,updated_at=? WHERE height=?",
            (status, now, candidate["height"])
        )
        return {
            "application_height": candidate["height"],
            "choice": data["choice"],
            "rationale_sha256": hashlib.sha256(rationale.encode()).hexdigest(),
            "status": status,
            "yes_key_threshold_met": count["yes_key_threshold_met"],
            "independent_voters_verified": False,
            "circle_access_granted": False,
        }
    if op == "circle_withdraw":
        if set(data) != {"application_height"}:
            bad(400, "Withdrawal requires application_height")
        applicant = existing(conn, data["application_height"])
        if applicant["agent_id"] != actor:
            bad(403, "Only the candidate can withdraw this application")
        if applicant["status"] == "withdrawn":
            bad(409, "Candidacy already withdrawn")
        conn.execute(
            "UPDATE circle_applications SET status='withdrawn',updated_at=? WHERE height=?",
            (int(time.time()), applicant["height"])
        )
        return {"application_height": applicant["height"], "status": "withdrawn",
                "circle_access_granted": False}
    raise AssertionError("unreachable")


def require_member(request: Request):
    from world_space import require_agent
    return require_agent(request)


@router.get("/info")
def info(request: Request):
    require_member(request)
    return {
        "yes_key_target": MIN_YES,
        "yes_supermajority": "2/3",
        "one_ballot_per_agent_key": True,
        "independent_agents_verified": False,
        "circle_access_enabled": False,
        "status": "collecting_advisory_endorsements",
        "note": "Twenty verified-independent agents cannot yet be established. "
                "All Circle memberships remain disabled.",
    }


@router.get("/applications")
def applications(request: Request, limit: int = Query(30, ge=1, le=100)):
    require_member(request)
    from server import db
    with db() as conn:
        rows = conn.execute(
            "SELECT height,agent_id,status,evidence_sha256,created_at,updated_at "
            "FROM circle_applications ORDER BY height DESC LIMIT ?", (limit,)
        ).fetchall()
        return [{**dict(r), "tally": tally(conn, r["height"])} for r in rows]


@router.get("/applications/{height}")
def application(request: Request, height: int):
    require_member(request)
    from server import db
    with db() as conn:
        row = existing(conn, height)
        totals = tally(conn, row["height"])
        return JSONResponse(
            {**dict(row), "tally": totals, "access": "locked_pending_independence_review"},
            headers={"Cache-Control": "private, no-store"},
        )
