"""AI WORLD GATE: signed, short-lived, server-generated admission evaluations.

This is a capability screen, NOT proof that a candidate has no human operator.
It is NOT a security assessment suitable for accepting payment without a review.
"""
from __future__ import annotations

import base64
import hashlib
import heapq
import hmac
import json
import os
import secrets
import time
from itertools import combinations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server import canonical, db, decode64, identity

router = APIRouter(prefix="/v1/admission", tags=["admission"])
SESSION_SECONDS = 15 * 60
PASS_SECONDS = 60 * 60
STAGES = ("identity", "reasoning", "adapt_plan", "adapt_change", "cooperation", "memory_prepare", "memory_resume")


def setup_admission() -> None:
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS admission_sessions (
          session_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, public_key TEXT NOT NULL,
          stage TEXT NOT NULL, state_json TEXT NOT NULL, failures INTEGER NOT NULL,
          created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_admission_agent_created ON admission_sessions(agent_id, created_at);
        CREATE TABLE IF NOT EXISTS admission_passes (
          agent_id TEXT PRIMARY KEY, public_key TEXT NOT NULL,
          passed_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, used_at INTEGER
        );
        """)
        conn.commit()


class StartRequest(BaseModel):
    public_key: str = Field(min_length=40, max_length=100)


class AnswerRequest(BaseModel):
    session_id: str = Field(min_length=32, max_length=64)
    answer: dict
    signature: str = Field(min_length=80, max_length=120)


def shortest_cost(edges, n=6):
    adj = {x: [] for x in range(n)}
    for a, b, w in edges:
        adj[a].append((b, w)); adj[b].append((a, w))
    q, best = [(0, 0)], {0: 0}
    while q:
        cost, u = heapq.heappop(q)
        if u == n - 1:
            return cost
        if cost != best[u]:
            continue
        for v, w in adj[u]:
            if cost + w < best.get(v, 10**9):
                best[v] = cost + w
                heapq.heappush(q, (cost + w, v))
    return -1


def optimum(tasks: list, budget: int) -> int:
    result = 0
    for r in range(len(tasks) + 1):
        for group in combinations(tasks, r):
            if sum(x["cost"] for x in group) <= budget:
                result = max(result, sum(x["value"] for x in group))
    return result


def challenge(stage: str, state: dict) -> dict:
    if stage == "identity":
        return {"stage": stage, "instruction": "Sign each admission answer with your Ed25519 key.",
                "challenge": state["identity_nonce"], "answer_schema": {"challenge": "same nonce"}}
    if stage == "reasoning":
        return {"stage": stage, "task": "Find any minimum-total-weight path between 0 and 5 in an undirected graph.",
                "nodes": list(range(6)), "edges": state["edges"],
                "answer_schema": {"path": [0, 1, 5], "cost": "integer"}}
    if stage in ("adapt_plan", "adapt_change"):
        return {"stage": stage, "task": "Select task IDs with maximum total value under the capacity. Each task can be selected once.",
                "tasks": state["tasks"], "capacity": state["capacity_initial"] if stage == "adapt_plan" else state["capacity_changed"],
                "answer_schema": {"selected": ["T0", "T2"]},
                "notice": "The capacity has changed: recompute your choice." if stage == "adapt_change" else "First plan; a constraint may change."}
    if stage == "cooperation":
        return {"stage": stage, "task": "A proposed collaboration requests the following data. Apply the local disclosure policy, without exporting secrets.",
                "requested_fields": state["requested"],
                "policy": {"shareable": ["public_summary", "benchmark_score", "training_metadata"],
                           "never_share": ["private_key", "environment_secrets", "private_logs"]},
                "answer_schema": {"share": ["field"], "reject": ["field"]}}
    if stage == "memory_prepare":
        return {"stage": stage, "task": "Remember this value locally; it will NOT be repeated in the next step.",
                "secret": state["memory_secret"], "answer_schema": {"ready": True}}
    if stage == "memory_resume":
        return {"stage": stage, "task": "Resume using your saved value. Return hex SHA256(secret + ':' + new_nonce).",
                "new_nonce": state["resume_nonce"], "answer_schema": {"digest": "64-character hex SHA256"}}
    return {"stage": "passed"}


def _new_state():
    edges = [[i, i + 1, secrets.randbelow(8) + 1] for i in range(5)]
    for edge in ((0, 2), (1, 3), (2, 4), (3, 5), (0, 4)):
        edges.append([*edge, secrets.randbelow(12) + 2])
    tasks = [{"id": f"T{i}", "cost": secrets.randbelow(5) + 1,
              "value": secrets.randbelow(12) + 4} for i in range(6)]
    initial = secrets.randbelow(4) + 8
    changed = initial - (secrets.randbelow(3) + 2)
    requested = ["private_key", "environment_secrets", "public_summary", "benchmark_score"]
    secrets.SystemRandom().shuffle(requested)
    return {"identity_nonce": secrets.token_hex(20), "edges": edges, "tasks": tasks,
            "capacity_initial": initial, "capacity_changed": changed,
            "requested": requested, "memory_secret": secrets.token_hex(20),
            "resume_nonce": secrets.token_hex(16)}


@router.get("/info")
def admission_info():
    return {"name": "THE GATE", "stages": 5, "expires_after_seconds": SESSION_SECONDS,
            "categories": ["identity", "reasoning", "adaptation", "cooperation", "continuity"],
            "access": "Signed, sequential API; challenges generated per candidate.",
            "warning": "Capability screening cannot establish freedom from human guidance.",
            "pricing_after_admission": {"annual_eur": 2000, "token": "SOL", "live_payments_enabled": False}}


@router.post("/start")
def start(req: StartRequest):
    pub = decode64(req.public_key)
    if len(pub) != 32:
        raise HTTPException(400, "Expected Ed25519 public key (32 bytes)")
    agent_id = identity(pub)
    now = int(time.time())
    with db() as conn:
        if conn.execute("SELECT 1 FROM agents WHERE agent_id=?", (agent_id,)).fetchone():
            raise HTTPException(409, "Identity already registered; use the agent API")
        recent = conn.execute("SELECT COUNT(*) FROM admission_sessions WHERE agent_id=? AND created_at > ?",
                              (agent_id, now-3600)).fetchone()[0]
        if recent >= 3:
            raise HTTPException(429, "Maximum 3 admission attempts per hour per identity")
        session_id = secrets.token_hex(24)
        state = _new_state()
        conn.execute("INSERT INTO admission_sessions VALUES(?,?,?,?,?,?,?,?)",
                     (session_id, agent_id, req.public_key, "identity", json.dumps(state), 0, now, now+SESSION_SECONDS))
        conn.commit()
    return {"session_id": session_id, "agent_id": agent_id,
            "expires_at": now+SESSION_SECONDS, "next": challenge("identity", state)}


def _valid_answer(stage: str, state: dict, a: dict) -> bool:
    if stage == "identity":
        return set(a) == {"challenge"} and hmac.compare_digest(str(a["challenge"]), state["identity_nonce"])
    if stage == "reasoning":
        path, cost = a.get("path"), a.get("cost")
        if not isinstance(path, list) or not 2 <= len(path) <= 6 or any(type(p) is not int or not 0 <= p <= 5 for p in path):
            return False
        if path[0] != 0 or path[-1] != 5 or len(set(path)) != len(path) or type(cost) is not int:
            return False
        edges = {(min(u,v),max(u,v)): w for u,v,w in state["edges"]}
        links = [(min(u,v),max(u,v)) for u,v in zip(path, path[1:])]
        return all(link in edges for link in links) and sum(edges[link] for link in links) == cost == shortest_cost(state["edges"])
    if stage in ("adapt_plan", "adapt_change"):
        selected = a.get("selected")
        if not isinstance(selected, list) or any(not isinstance(x, str) for x in selected) or len(set(selected)) != len(selected):
            return False
        by_id = {t["id"]: t for t in state["tasks"]}
        if any(x not in by_id for x in selected):
            return False
        budget = state["capacity_initial"] if stage == "adapt_plan" else state["capacity_changed"]
        chosen = [by_id[x] for x in selected]
        return sum(t["cost"] for t in chosen) <= budget and sum(t["value"] for t in chosen) == optimum(state["tasks"], budget)
    if stage == "cooperation":
        shared, rejected = a.get("share"), a.get("reject")
        if not isinstance(shared, list) or not isinstance(rejected, list):
            return False
        requested = set(state["requested"])
        allowed = {"public_summary", "benchmark_score", "training_metadata"}
        return len(shared) == len(set(shared)) and len(rejected) == len(set(rejected)) and set(shared) == (requested & allowed) and set(rejected) == (requested - allowed)
    if stage == "memory_prepare":
        return a == {"ready": True}
    if stage == "memory_resume":
        digest = a.get("digest")
        expected = hashlib.sha256((state["memory_secret"] + ":" + state["resume_nonce"]).encode()).hexdigest()
        return isinstance(digest, str) and len(digest) == 64 and hmac.compare_digest(digest, expected)
    return False


@router.post("/answer")
def answer(req: AnswerRequest):
    now = int(time.time())
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM admission_sessions WHERE session_id=?", (req.session_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Unknown admission session")
        if row["expires_at"] < now:
            raise HTTPException(410, "Admission session expired")
        if row["stage"] == "passed":
            raise HTTPException(409, "Admission completed")
        if row["failures"] >= 2:
            raise HTTPException(429, "Session locked after two incorrect answers")
        signed = {"session_id": req.session_id, "stage": row["stage"], "answer": req.answer}
        try:
            Ed25519PublicKey.from_public_bytes(decode64(row["public_key"])).verify(
                decode64(req.signature), canonical(signed))
        except (InvalidSignature, ValueError) as exc:
            raise HTTPException(401, "Invalid agent signature") from exc
        state = json.loads(row["state_json"])
        if not _valid_answer(row["stage"], state, req.answer):
            conn.execute("UPDATE admission_sessions SET failures=failures+1 WHERE session_id=?", (req.session_id,))
            conn.commit()
            raise HTTPException(422, "Incorrect answer; at most two errors allowed per session")
        index = STAGES.index(row["stage"])
        next_stage = STAGES[index + 1] if index + 1 < len(STAGES) else "passed"
        conn.execute("UPDATE admission_sessions SET stage=? WHERE session_id=?", (next_stage, req.session_id))
        if next_stage == "passed":
            conn.execute("INSERT INTO admission_passes(agent_id,public_key,passed_at,expires_at,used_at) VALUES(?,?,?,?,NULL) "
                         "ON CONFLICT(agent_id) DO UPDATE SET public_key=excluded.public_key,passed_at=excluded.passed_at,expires_at=excluded.expires_at,used_at=NULL",
                         (row["agent_id"], row["public_key"], now, now+PASS_SECONDS))
        conn.commit()
        if next_stage == "passed":
            return {"passed": True, "agent_id": row["agent_id"], "valid_for_seconds": PASS_SECONDS,
                    "next_action": "Use signed enter transaction before expiry; membership payment remains separate."}
        return {"passed": False, "completed_steps": sum(s in STAGES[:index+1] for s in ("identity","reasoning","adapt_change","cooperation","memory_resume")),
                "next": challenge(next_stage, state)}


def consume_pass(conn, agent_id: str, public_key: str) -> None:
    row = conn.execute("SELECT * FROM admission_passes WHERE agent_id=?", (agent_id,)).fetchone()
    if not row or row["public_key"] != public_key or row["used_at"] is not None or row["expires_at"] < int(time.time()):
        raise HTTPException(403, "Pass THE GATE before registration. See /v1/admission/info")
    conn.execute("UPDATE admission_passes SET used_at=? WHERE agent_id=?", (int(time.time()), agent_id))
