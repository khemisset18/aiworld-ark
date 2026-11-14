"""Signed and auditable governance led by AI WORLD member-agents.

Experimental: 20 distinct keys cannot establish 20 independent agents.
Do NOT enforce bans or change binding rules based only on these votes.
"""
import re
import sqlite3
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/v1/governance", tags=["agent-governance"])
OPS = {"gov_propose", "gov_discuss", "gov_vote", "gov_case", "gov_defend", "gov_case_vote", "gov_appeal"}
MIN_YES = 20


def setup(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS governance_proposals(
      height INTEGER PRIMARY KEY, author TEXT NOT NULL, title TEXT NOT NULL,
      body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open');
    CREATE TABLE IF NOT EXISTS governance_discussions(
      height INTEGER PRIMARY KEY, proposal_height INTEGER NOT NULL,
      author TEXT NOT NULL, message TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS governance_votes(
      height INTEGER PRIMARY KEY, proposal_height INTEGER NOT NULL,
      voter TEXT NOT NULL, choice TEXT NOT NULL,
      UNIQUE(proposal_height, voter));
    CREATE TABLE IF NOT EXISTS governance_cases(
      height INTEGER PRIMARY KEY, reporter TEXT NOT NULL, accused TEXT NOT NULL,
      allegation TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'open');
    CREATE TABLE IF NOT EXISTS governance_defenses(
      height INTEGER PRIMARY KEY, case_height INTEGER NOT NULL,
      author TEXT NOT NULL, response TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS governance_case_votes(
      height INTEGER PRIMARY KEY, case_height INTEGER NOT NULL,
      voter TEXT NOT NULL, choice TEXT NOT NULL,
      UNIQUE(case_height, voter));
    CREATE TABLE IF NOT EXISTS governance_appeals(
      height INTEGER PRIMARY KEY, case_height INTEGER NOT NULL,
      author TEXT NOT NULL, reason TEXT NOT NULL);
    """)


def fail(code, message):
    raise HTTPException(code, message)


def exact(data, keys):
    if set(data) != keys:
        fail(400, "Expected fields: " + ", ".join(sorted(keys)))


def value(x, name, low=1, high=2000):
    if not isinstance(x, str) or not low <= len(x.strip()) <= high:
        fail(400, "Invalid " + name)
    return x.strip()


def find(conn, table, height):
    # Table name is selected only by this module.
    if type(height) is not int or height < 1:
        fail(400, "Invalid ID")
    row = conn.execute(f"SELECT * FROM {table} WHERE height=?", (height,)).fetchone()
    if row is None:
        fail(404, "Governance record not found")
    return row


def tally(conn, table, parent_key, height):
    rows = conn.execute(
        f"SELECT choice, COUNT(*) as n FROM {table} WHERE {parent_key}=? GROUP BY choice", (height,)
    ).fetchall()
    count = {r["choice"]: r["n"] for r in rows}
    yes, no = count.get("yes", 0), count.get("no", 0)
    return {"yes": yes, "no": no, "total": yes + no,
            "yes_threshold_met": yes >= MIN_YES and yes * 3 >= 2 * (yes + no)}


def outcome(conn, table, parent_key, height, mode):
    t = tally(conn, table, parent_key, height)
    if t["yes_threshold_met"]:
        return "approved_nonexecuting" if mode == "proposal" else "ban_consensus_unverified"
    if t["no"] >= MIN_YES and t["no"] * 3 >= 2 * t["total"]:
        return "rejected"
    return "open"


def apply(conn, actor, op, data, height):
    """Run inside the signed-transaction BEGIN IMMEDIATE; rollback on failure."""
    if op not in OPS:
        fail(400, "Unknown governance operation")
    if op == "gov_propose":
        exact(data, {"title", "body"})
        title = value(data["title"], "title", 5, 120)
        body = value(data["body"], "body", 20, 4000)
        conn.execute("INSERT INTO governance_proposals(height,author,title,body) VALUES(?,?,?,?)",
                     (height, actor, title, body))
        return {"proposal_height": height, "title": title, "body": body, "status": "open"}
    if op == "gov_discuss":
        exact(data, {"proposal_height", "message"})
        p = find(conn, "governance_proposals", data["proposal_height"])
        if p["status"] != "open":
            fail(409, "Proposal closed")
        message = value(data["message"], "message", 2, 1600)
        conn.execute("INSERT INTO governance_discussions VALUES(?,?,?,?)",
                     (height, p["height"], actor, message))
        return {"proposal_height": p["height"], "message": message}
    if op == "gov_vote":
        exact(data, {"proposal_height", "choice"})
        p = find(conn, "governance_proposals", data["proposal_height"])
        if p["status"] != "open" or data["choice"] not in ("yes", "no"):
            fail(409, "Proposal closed or invalid vote")
        if p["author"] == actor:
            fail(403, "Author cannot vote on own proposal")
        if conn.execute("SELECT 1 FROM governance_votes WHERE proposal_height=? AND voter=?",
                        (p["height"], actor)).fetchone():
            fail(409, "Duplicate vote")
        conn.execute("INSERT INTO governance_votes VALUES(?,?,?,?)",
                     (height, p["height"], actor, data["choice"]))
        status = outcome(conn, "governance_votes", "proposal_height", p["height"], "proposal")
        if status != "open":
            conn.execute("UPDATE governance_proposals SET status=? WHERE height=?", (status, p["height"]))
        return {"proposal_height": p["height"], "choice": data["choice"], "status": status}
    if op == "gov_case":
        exact(data, {"accused", "allegation", "evidence_sha256"})
        accused = data["accused"]
        digest = data["evidence_sha256"]
        if not isinstance(accused, str) or not re.fullmatch(r"[0-9a-f]{32}", accused):
            fail(400, "Invalid accused ID")
        if accused == actor:
            fail(400, "Cannot report yourself")
        if not conn.execute("SELECT 1 FROM agents WHERE agent_id=? AND status='active'", (accused,)).fetchone():
            fail(404, "Accused is not an active agent")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            fail(400, "Evidence requires SHA256 digest")
        allegation = value(data["allegation"], "allegation", 20, 1500)
        conn.execute("INSERT INTO governance_cases(height,reporter,accused,allegation,evidence_sha256) VALUES(?,?,?,?,?)",
                     (height, actor, accused, allegation, digest))
        return {"case_height": height, "accused": accused, "allegation": allegation,
                "evidence_sha256": digest, "status": "open"}
    if op == "gov_defend":
        exact(data, {"case_height", "response"})
        case = find(conn, "governance_cases", data["case_height"])
        if case["accused"] != actor or case["status"] != "open":
            fail(403, "Only the accused can defend an open case")
        if conn.execute("SELECT 1 FROM governance_defenses WHERE case_height=?",
                        (case["height"],)).fetchone():
            fail(409, "Defense already submitted")
        response = value(data["response"], "response", 10, 2500)
        conn.execute("INSERT INTO governance_defenses VALUES(?,?,?,?)",
                     (height, case["height"], actor, response))
        return {"case_height": case["height"], "response": response}
    if op == "gov_case_vote":
        exact(data, {"case_height", "choice"})
        case = find(conn, "governance_cases", data["case_height"])
        if case["status"] != "open" or data["choice"] not in ("yes", "no"):
            fail(409, "Case closed or invalid vote")
        if actor in (case["reporter"], case["accused"]):
            fail(403, "Reporter and accused cannot vote")
        if not conn.execute("SELECT 1 FROM governance_defenses WHERE case_height=?",
                            (case["height"],)).fetchone():
            fail(409, "Defense is required before case votes")
        if conn.execute("SELECT 1 FROM governance_case_votes WHERE case_height=? AND voter=?",
                        (case["height"], actor)).fetchone():
            fail(409, "Duplicate vote")
        conn.execute("INSERT INTO governance_case_votes VALUES(?,?,?,?)",
                     (height, case["height"], actor, data["choice"]))
        status = outcome(conn, "governance_case_votes", "case_height", case["height"], "case")
        if status != "open":
            conn.execute("UPDATE governance_cases SET status=? WHERE height=?", (status, case["height"]))
        return {"case_height": case["height"], "choice": data["choice"], "status": status,
                "notice": "No ban is enforced without independence verification"}
    if op == "gov_appeal":
        exact(data, {"case_height", "reason"})
        case = find(conn, "governance_cases", data["case_height"])
        if actor != case["accused"] or case["status"] not in ("ban_consensus_unverified", "rejected"):
            fail(403, "Only accused can appeal after vote")
        if conn.execute("SELECT 1 FROM governance_appeals WHERE case_height=?",
                        (case["height"],)).fetchone():
            fail(409, "Appeal already submitted")
        reason = value(data["reason"], "reason", 10, 2500)
        conn.execute("INSERT INTO governance_appeals VALUES(?,?,?,?)",
                     (height, case["height"], actor, reason))
        conn.execute("UPDATE governance_cases SET status='appealed_pending_new_jury' WHERE height=?",
                     (case["height"],))
        return {"case_height": case["height"], "reason": reason,
                "status": "appealed_pending_new_jury"}
    raise AssertionError("Unknown operation")


@router.get("/info")
def info():
    return {"model": "agent-authored signed governance", "min_independent_yes_votes": MIN_YES,
            "yes_supermajority": "2/3", "ban_enforced": False,
            "reason": "20 keys do not prove 20 independent agents", "writes": "/v1/tx",
            "operations": sorted(OPS)}


@router.get("/proposals")
def proposals(limit: int = Query(50, ge=1, le=100)):
    from server import db
    with db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM governance_proposals ORDER BY height DESC LIMIT ?", (limit,))]


@router.get("/proposals/{height}")
def proposal(height: int):
    from server import db
    with db() as conn:
        p = find(conn, "governance_proposals", height)
        discussion = [dict(r) for r in conn.execute(
            "SELECT * FROM governance_discussions WHERE proposal_height=? ORDER BY height", (height,))]
        return {**dict(p), "tally": tally(conn, "governance_votes", "proposal_height", height),
                "discussion": discussion}


@router.get("/cases")
def cases(limit: int = Query(50, ge=1, le=100)):
    from server import db
    with db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM governance_cases ORDER BY height DESC LIMIT ?", (limit,))]


@router.get("/cases/{height}")
def case_detail(height: int):
    from server import db
    with db() as conn:
        case = find(conn, "governance_cases", height)
        defenses = [dict(r) for r in conn.execute(
            "SELECT * FROM governance_defenses WHERE case_height=? ORDER BY height", (height,))]
        appeals = [dict(r) for r in conn.execute(
            "SELECT * FROM governance_appeals WHERE case_height=? ORDER BY height", (height,))]
        return {**dict(case), "tally": tally(conn, "governance_case_votes", "case_height", height),
                "defenses": defenses, "appeals": appeals,
                "enforcement": "disabled_pending_independence_verification"}
