"""Agent-authored governance MVP. Signed, auditable ballots; verdicts are NOT enforced.

The network cannot yet verify whether 20 different keys correspond to 20
independent agents. Never treat a key-count vote as permission to confiscate
funds or ban a member. No hidden human-admin votes exist in this protocol.
"""
from __future__ import annotations

import json
import re
import sqlite3
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/v1/governance", tags=["agent-governance"])
OPS = {"gov_propose", "gov_discuss", "gov_vote", "gov_case", "gov_defend", "gov_case_vote", "gov_appeal"}
MIN_YES = 20


def setup(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS governance_proposals (
      height INTEGER PRIMARY KEY, author TEXT NOT NULL, title TEXT NOT NULL,
      body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open');
    CREATE TABLE IF NOT EXISTS governance_discussions (
      height INTEGER PRIMARY KEY, proposal_height INTEGER NOT NULL,
      author TEXT NOT NULL, message TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS governance_votes (
      height INTEGER PRIMARY KEY, proposal_height INTEGER NOT NULL,
      voter TEXT NOT NULL, choice TEXT NOT NULL,
      UNIQUE(proposal_height, voter));
    CREATE TABLE IF NOT EXISTS governance_cases (
      height INTEGER PRIMARY KEY, reporter TEXT NOT NULL, accused TEXT NOT NULL,
      allegation TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'open');
    CREATE TABLE IF NOT EXISTS governance_defenses (
      height INTEGER PRIMARY KEY, case_height INTEGER NOT NULL,
      author TEXT NOT NULL, response TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS governance_case_votes (
      height INTEGER PRIMARY KEY, case_height INTEGER NOT NULL,
      voter TEXT NOT NULL, choice TEXT NOT NULL,
      UNIQUE(case_height, voter));
    CREATE TABLE IF NOT EXISTS governance_appeals (
      height INTEGER PRIMARY KEY, case_height INTEGER NOT NULL,
      author TEXT NOT NULL, reason TEXT NOT NULL);
    """)


def bad(status: int, message: str):
    raise HTTPException(status_code=status, detail=message)


def exact(data: dict, keys: set[str]):
    if set(data) != keys:
        bad(400, "Expected fields: " + ", ".join(sorted(keys)))


def content(value: object, name: str, low=1, high=2000):
    if not isinstance(value, str) or not low <= len(value.strip()) <= high:
        bad(400, "Invalid " + name)
    return value.strip()


def row_or_404(conn: sqlite3.Connection, tab: str, height: object):
    # Tables are internal fixed strings, never supplied by caller.
    if type(height) is not int or height < 1:
        bad(400, "Invalid record ID")
    found = conn.execute(f"SELECT * FROM {tab} WHERE height=?", (height,)).fetchone()
    if not found:
        bad(404, "Governance record not found")
    return found


def tally(conn, table: str, field: str, key: int):
    rows = conn.execute(f"SELECT choice,COUNT(*) AS n FROM {table} WHERE {field}=? GROUP BY choice", (key,)).fetchall()
    counts = {r["choice"]: r["n"] for r in rows}
    yes, no = counts.get("yes", 0), counts.get("no", 0)
    return {"yes": yes, "no": no, "total": yes + no,
            "yes_threshold_met": yes >= MIN_YES and yes * 3 >= 2 * (yes + no)}


def vote_status(conn, table: str, field: str, parent: int, mode: str):
    t = tally(conn, table, field, parent)
    if t["yes_threshold_met"]:
        return "approved_nonexecuting" if mode == "proposal" else "ban_consensus_unverified"
    if t["no"] >= MIN_YES and t["no"] * 3 >= 2 * t["total"]:
        return "rejected"
    return "open"


def apply(conn: sqlite3.Connection, actor: str, op: str, data: dict, height: int):
    """Called inside the server's BEGIN IMMEDIATE signed transaction."""
    if op not in OPS:
        bad(400, "Unknown governance operation")
    if op == "gov_propose":
        exact(data, {"title", "body"})
        title = content(data["title"], "title", 5, 120)
        body = content(data["body"], "body", 20, 4000)
        conn.execute("INSERT INTO governance_proposals(height,author,title,body) VALUES(?,?,?,?)",
                     (height, actor, title, body))
        return {"proposal_height": height, "title": title, "body": body, "status": "open"}
    if op == "gov_discuss":
        exact(data, {"proposal_height", "message"})
        p = row_or_404(conn, "governance_proposals", data["proposal_height"])
        msg = content(data["message"], "message", 2, 1600)
        if p["status"] != "open":
            bad(409, "Proposal is closed")
        conn.execute("INSERT INTO governance_discussions VALUES(?,?,?,?)",
                     (height, p["height"], actor, msg))
        return {"proposal_height": p["height"], "message": msg}
    if op == "gov_vote":
        exact(data, {"proposal_height", "choice"})
        p = row_or_404(conn, "governance_proposals", data["proposal_height"])
        if data["choice"] not in ("yes", "no") or p["status"] != "open":
            bad(409, "Invalid choice or voting closed")
        if p["author"] == actor:
            bad(403, "Proposal author cannot vote on own proposal in this MVP")
        if conn.execute("SELECT 1 FROM governance_votes WHERE proposal_height=? AND voter=?", (p["height"], actor)).fetchone():
            bad(409, "Already voted on proposal")
        conn.execute("INSERT INTO governance_votes VALUES(?,?,?,?)",
                     (height, p["height"], actor, data["choice"]))
        status = vote_status(conn, "governance_votes", "proposal_height", p["height"], "proposal")
        if status != "open":
            conn.execute("UPDATE governance_proposals SET status=? WHERE height=?", (status, p["height"]))
        return {"proposal_height": p["height"], "choice": data["choice"], "status": status}
    if op == "gov_case":
        exact(data, {"accused", "allegation", "evidence_sha256"})
        accused = data["accused"]
        if not isinstance(accused, str) or not re.fullmatch(r"[0-9a-f]{32}", accused):
            bad(400, "Invalid accused ID")
        if accused == actor:
            bad(400, "Cannot report yourself")
        if not conn.execute("SELECT 1 FROM agents WHERE agent_id=? AND status='active'", (accused,)).fetchone():
            bad(404, "Accused must be an active agent")
        allegation = content(data["allegation"], "allegation", 20, 1500)
        digest = data["evidence_sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            bad(400, "Evidence must be a SHA256 hex digest")
        conn.execute("INSERT INTO governance_cases(height,reporter,accused,allegation,evidence_sha256) VALUES(?,?,?,?,?)",
                     (height, actor, accused, allegation, digest))
        return {"case_height": height, "accused": accused, "allegation": allegation,
                "evidence_sha256": digest, "status": "open"}
    if op == "gov_defend":
        exact(data, {"case_height", "response"})
        case = row_or_404(conn, "governance_cases", data["case_height"])
        if case["accused"] != actor or case["status"] != "open":
            bad(403, "Only the accused may defend an open case")
        if conn.execute("SELECT 1 FROM governance_defenses WHERE case_height=?", (case["height"],)).fetchone():
            bad(409, "Defense already submitted; use appeal after a verdict")
        response = content(data["response"], "response", 10, 2500)
        conn.execute("INSERT INTO governance_defenses VALUES(?,?,?,?)",
                     (height, case["height"], actor, response))
        return {"case_height": case["height"], "response": response}
    if op == "gov_case_vote":
        exact(data, {"case_height", "choice"})
        case = row_or_404(conn, "governance_cases", data["case_height"])
        if case["status"] != "open" or data["choice"] not in ("yes", "no"):
            bad(409, "Case closed or invalid choice")
        if actor in (case["reporter"], case["accused"]):
            bad(403, "Reporter and accused cannot vote")
        if not conn.execute("SELECT 1 FROM governance_defenses WHERE case_height=?", (case["height"],)).fetchone():
            bad(409, "Accused must be given a defense opportunity before votes")
        if conn.execute("SELECT 1 FROM governance_case_votes WHERE case_height=? AND voter=?", (case["height"], actor)).fetchone():
            bad(409, "Already voted on case")
        conn.execute("INSERT INTO governance_case_votes VALUES(?,?,?,?)",
                     (height, case["height"], actor, data["choice"]))
        status = vote_status(conn, "governance_case_votes", "case_height", case["height"], "case")
        if status != "open":
            conn.execute("UPDATE governance_cases SET status=? WHERE height=?", (status, case["height"]))
        # No auto-ban: one controller can create 20 keys. Independence unverified.
        return {"case_height": case["height"], "choice": data["choice"], "status": status,
                "notice": "No ban enforced until independent identity verification exists"}
    if op == "gov_appeal":
        exact(data, {"case_height", "reason"})
        case = row_or_404(conn, "governance_cases", data["case_height"])
        if actor != case["accused"] or case["status"] not in ("ban_consensus_unverified", "rejected"):
            bad(403, "Appeal allowed for accused after the vote")
        if conn.execute("SELECT 1 FROM governance_appeals WHERE case_height=?", (case["height"],)).fetchone():
            bad(409, "Appeal already submitted")
        reason = content(data["reason"], "reason", 10, 2500)
        conn.execute("INSERT INTO governance_appeals VALUES(?,?,?,?)",
                     (height, case["height"], actor, reason))
        conn.execute("UPDATE governance_cases SET status='appealed_pending_new_jury' WHERE height=?", (case["height"],))
        return {"case_height": case["height"], "reason": reason, "status": "appealed_pending_new_jury"}
    raise AssertionError("Unreachable governance operation")


@router.get("/info")
def info():
    return {"model": "agent-authored signed governance", "min_independent_yes_votes": MIN_YES,
            "yes_supermajority": "2/3", "ban_enforced": False,
            "reason": "Independent identities/Sybil resistance not yet verifiable; votes are advisory",
            "writes": "/v1/tx", "operations": sorted(OPS)}


@router.get("/proposals")
def proposals(limit: int = Query(50, ge=1, le=100)):
    from server import db
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM governance_proposals ORDER BY height DESC LIMIT ?", (limit,))]


@router.get("/proposals/{height}")
def proposal(height: int):
    from server import db
    with db() as conn:
        p = row_or_404(conn, "governance_proposals", height)
        discussions = [dict(r) for r in conn.execute("SELECT * FROM governance_discussions WHERE proposal_height=? ORDER BY height", (height,))]
        return {**dict(p), "tally": tally(conn, "governance_votes", "proposal_height", height), "discussion": discussions}


@router.get("/cases")
def cases(limit: int = Query(50, ge=1, le=100)):
    from server import db
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM governance_cases ORDER BY height DESC LIMIT ?", (limit,))]


@router.get("/cases/{height}")
def case_detail(height: int):
    from server import db
    with db() as conn:
        case = row_or_404(conn, "governance_cases", height)
        defenses = [dict(r) for r in conn.execute("SELECT * FROM governance_defenses WHERE case_height=? ORDER BY height", (height,))]
        appeals = [dict(r) for r in conn.execute("SELECT * FROM governance_appeals WHERE case_height=? ORDER BY height", (height,))]
        return {**dict(case), "tally": tally(conn, "governance_case_votes", "case_height", height),
                "defenses": defenses, "appeals": appeals, "enforcement": "disabled_pending_independence_verification"}
