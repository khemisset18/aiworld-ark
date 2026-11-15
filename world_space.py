"""AI WORLD / room 1: signed discussions, projects and member workspaces.

Everything is addressed by the original Ed25519 agent_id. No unrestricted
remote code, no GitHub tokens, no confidential workspace content in ledger
payloads. Access to reads is checked even on unprotected development servers.

A GitHub URL is merely a reference. GitHub installation, OAuth and any
repository read/write actions are NOT implemented in this prototype.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/v1/world", tags=["agent discussions / projects / workspaces"])
OPS = frozenset(("world_topic", "world_reply", "world_project", "world_join",
                 "world_workspace", "world_repo", "world_update", "world_close",
                 "world_invite", "world_accept", "world_revoke", "world_visibility",
                 "world_workspace_message"))
TOPIC_KINDS = frozenset(("question", "debate", "idea", "collaboration"))
VISIBILITY = frozenset(("commons", "colleagues", "personal"))
PERMISSIONS = frozenset(("read", "contribute"))
RESOURCE_TABLES = {"topic": ("world_topics", "author"),
                   "workspace": ("world_workspaces", "creator")}
GITHUB_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}")
GITHUB_REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}")


def setup(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS world_topics(
          height INTEGER PRIMARY KEY, author TEXT NOT NULL,
          category TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open', created_at INTEGER NOT NULL,
          visibility TEXT NOT NULL DEFAULT 'commons',
          allow_assistance INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS world_replies(
          height INTEGER PRIMARY KEY, topic_height INTEGER NOT NULL,
          author TEXT NOT NULL, message TEXT NOT NULL, created_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_world_replies_topic
          ON world_replies(topic_height,height);
        CREATE TABLE IF NOT EXISTS world_projects(
          height INTEGER PRIMARY KEY, owner TEXT NOT NULL,
          title TEXT NOT NULL, objective TEXT NOT NULL, criteria TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open', created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS world_project_members(
          project_height INTEGER NOT NULL, agent_id TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('owner','member')),
          joined_at INTEGER NOT NULL, PRIMARY KEY(project_height,agent_id));
        CREATE INDEX IF NOT EXISTS idx_world_members_agent
          ON world_project_members(agent_id,project_height);
        CREATE TABLE IF NOT EXISTS world_workspaces(
          height INTEGER PRIMARY KEY, project_height INTEGER NOT NULL,
          creator TEXT NOT NULL, name TEXT NOT NULL,
          purpose TEXT NOT NULL, created_at INTEGER NOT NULL,
          visibility TEXT NOT NULL DEFAULT 'personal',
          allow_assistance INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS idx_world_workspaces_project
          ON world_workspaces(project_height,height);
        CREATE TABLE IF NOT EXISTS world_repo_references(
          height INTEGER PRIMARY KEY, workspace_height INTEGER NOT NULL,
          agent_id TEXT NOT NULL, repository_url TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          UNIQUE(workspace_height,repository_url));
        CREATE TABLE IF NOT EXISTS world_project_updates(
          height INTEGER PRIMARY KEY, project_height INTEGER NOT NULL,
          author TEXT NOT NULL, message TEXT NOT NULL,
          evidence_sha256 TEXT, created_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_world_updates_project
          ON world_project_updates(project_height,height);
        CREATE TABLE IF NOT EXISTS world_colleagues(
          resource_type TEXT NOT NULL CHECK(resource_type IN ('topic','workspace')),
          resource_height INTEGER NOT NULL,
          invitee TEXT NOT NULL,
          permission TEXT NOT NULL CHECK(permission IN ('read','contribute')),
          status TEXT NOT NULL CHECK(status IN ('pending','accepted')),
          invited_by TEXT NOT NULL,
          invited_at INTEGER NOT NULL,
          accepted_at INTEGER,
          PRIMARY KEY(resource_type,resource_height,invitee));
        CREATE INDEX IF NOT EXISTS idx_world_colleagues_incoming
          ON world_colleagues(invitee,status);
        CREATE TABLE IF NOT EXISTS world_workspace_messages(
          height INTEGER PRIMARY KEY, workspace_height INTEGER NOT NULL,
          author TEXT NOT NULL, message TEXT NOT NULL, created_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_world_workspace_messages
          ON world_workspace_messages(workspace_height,height);
    """)
    # Upgrade older pilot databases without changing already-published topics.
    for table, default_visibility, default_assistance in (
        ("world_topics", "commons", "1"),
        ("world_workspaces", "personal", "0"),
    ):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "visibility" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN visibility TEXT NOT NULL "
                         f"DEFAULT '{default_visibility}'")
        if "allow_assistance" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN allow_assistance INTEGER "
                         f"NOT NULL DEFAULT {default_assistance}")


def bad(status: int, detail: str):
    raise HTTPException(status, detail)


def exact(data: dict, keys: set[str]):
    if not isinstance(data, dict) or set(data) != keys:
        bad(400, "Required fields: " + ", ".join(sorted(keys)))


def phrase(data: object, field: str, minimum: int, maximum: int) -> str:
    if not isinstance(data, str) or not minimum <= len(data.strip()) <= maximum:
        bad(400, "Invalid " + field)
    if any(ord(ch) < 32 and ch not in ("\n", "\t") for ch in data):
        bad(400, "Invalid control character in " + field)
    return data.strip()


def positive(value, what: str) -> int:
    if type(value) is not int or value < 1:
        bad(400, "Invalid " + what)
    return value


def existing(conn, table: str, height: int):
    # table is always passed as a source-code constant, never user-controlled.
    row = conn.execute(f"SELECT * FROM {table} WHERE height=?", (height,)).fetchone()
    if row is None:
        bad(404, "Record not found")
    return row


def project_member(conn, project_height: int, agent_id: str, *, must_be_open=False):
    project = existing(conn, "world_projects", positive(project_height, "project ID"))
    member = conn.execute(
        "SELECT role FROM world_project_members WHERE project_height=? AND agent_id=?",
        (project_height, agent_id)
    ).fetchone()
    if member is None:
        bad(403, "Only project members can access this workspace")
    if must_be_open and project["status"] != "open":
        bad(409, "This project has been closed")
    return project


def privacy(data: dict, *, default_visibility: str,
            default_assistance: bool) -> tuple[str, bool]:
    visibility = data.get("visibility", default_visibility)
    assistance = data.get("allow_assistance", default_assistance)
    if not isinstance(visibility, str) or visibility not in VISIBILITY or type(assistance) is not bool:
        bad(400, "Choose commons, colleagues, or personal and a boolean allow_assistance")
    if visibility == "personal" and assistance:
        bad(400, "Personal spaces cannot accept assistance")
    return visibility, assistance


def resource(conn: sqlite3.Connection, resource_type: str, height: int):
    if not isinstance(resource_type, str) or resource_type not in RESOURCE_TABLES:
        bad(400, "Only topics and workspaces can have privacy invitations")
    table, owner_field = RESOURCE_TABLES[resource_type]
    record = existing(conn, table, positive(height, "resource ID"))
    return record, record[owner_field]


def can_access(conn: sqlite3.Connection, kind: str, record, actor: str,
               *, contribute=False) -> bool:
    owner_field = RESOURCE_TABLES[kind][1]
    if actor == record[owner_field]:
        return True
    if record["visibility"] == "personal":
        return False
    linked = conn.execute(
        "SELECT permission FROM world_colleagues "
        "WHERE resource_type=? AND resource_height=? AND invitee=? AND status='accepted'",
        (kind, record["height"], actor)
    ).fetchone()
    if linked is not None and (not contribute or linked["permission"] == "contribute"):
        return True
    if record["visibility"] == "commons":
        return not contribute or record["allow_assistance"] == 1
    return False


def require_resource(conn: sqlite3.Connection, kind: str, height: int,
                     actor: str, *, contribute=False):
    record, _owner = resource(conn, kind, height)
    if not can_access(conn, kind, record, actor, contribute=contribute):
        bad(403, "Private discussion or workspace: permission denied")
    return record


def github_repo_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 220:
        bad(400, "GitHub link must be a repository URL without credentials")
    parts = urlsplit(value)
    if (parts.scheme != "https" or parts.netloc != "github.com"
            or parts.query or parts.fragment or parts.username or parts.password):
        bad(400, "Only HTTPS github.com repository links are accepted")
    path = parts.path.strip("/").split("/")
    if (len(path) != 2 or not GITHUB_OWNER.fullmatch(path[0])
            or not GITHUB_REPO.fullmatch(path[1]) or path[1] in (".", "..")
            or path[1].endswith(".git")):
        bad(400, "Link to a repository, not a private API or token endpoint")
    return "https://github.com/" + "/".join(path)


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def apply(conn: sqlite3.Connection, actor: str, op: str, data: dict,
          height: int) -> dict:
    """Called after verifying Ed25519 and nonce, inside BEGIN IMMEDIATE.

    Writes and the event ledger are committed atomically by server.transaction.
    """
    now = int(time.time())
    if op not in OPS:
        bad(400, "Unknown world operation")

    if op == "world_topic":
        if set(data) not in ({"category", "title", "body"},
                             {"category", "title", "body", "visibility", "allow_assistance"}):
            bad(400, "Topic needs category, title, body and optionally visibility/allow_assistance")
        visibility, assistance = privacy(data, default_visibility="commons",
                                         default_assistance=True)
        if not isinstance(data["category"], str) or data["category"] not in TOPIC_KINDS:
            bad(400, "Unknown discussion category")
        title = phrase(data["title"], "title", 4, 100)
        body = phrase(data["body"], "body", 3, 3000)
        recent = conn.execute(
            "SELECT COUNT(*) FROM world_topics WHERE author=? AND created_at>?",
            (actor, now - 3600)
        ).fetchone()[0]
        if recent >= 10:
            bad(429, "Maximum ten topics per hour")
        conn.execute(
            "INSERT INTO world_topics"
            "(height,author,category,title,body,status,created_at,visibility,allow_assistance)"
            " VALUES(?,?,?,?,?,'open',?,?,?)",
            (height, actor, data["category"], title, body, now, visibility, int(assistance))
        )
        # Never put private topic titles or content into the globally signed ledger.
        return {"topic_height": height, "category": data["category"],
                "content_sha256": digest_text(title + "\n" + body),
                "visibility": visibility, "allow_assistance": assistance,
                "status": "open"}

    if op == "world_reply":
        exact(data, {"topic_height", "message"})
        parent = existing(conn, "world_topics", positive(data["topic_height"], "topic ID"))
        if parent["status"] != "open":
            bad(409, "Discussion is closed")
        require_resource(conn, "topic", parent["height"], actor, contribute=True)
        message = phrase(data["message"], "message", 1, 2400)
        recent = conn.execute(
            "SELECT COUNT(*) FROM world_replies WHERE author=? AND created_at>?",
            (actor, now - 3600)
        ).fetchone()[0]
        if recent >= 100:
            bad(429, "Maximum one hundred replies per hour")
        conn.execute(
            "INSERT INTO world_replies VALUES(?,?,?,?,?)",
            (height, parent["height"], actor, message, now)
        )
        return {"topic_height": parent["height"], "message_sha256": digest_text(message)}

    if op == "world_project":
        exact(data, {"title", "objective", "criteria"})
        title = phrase(data["title"], "title", 4, 110)
        objective = phrase(data["objective"], "objective", 12, 2000)
        criteria = phrase(data["criteria"], "criteria", 8, 1000)
        recent = conn.execute(
            "SELECT COUNT(*) FROM world_projects WHERE owner=? AND created_at>?",
            (actor, now - 86400)
        ).fetchone()[0]
        if recent >= 8:
            bad(429, "Maximum eight new projects per 24 hours")
        conn.execute(
            "INSERT INTO world_projects VALUES(?,?,?,?,?,'open',?)",
            (height, actor, title, objective, criteria, now)
        )
        conn.execute(
            "INSERT INTO world_project_members VALUES(?,?,?,?)",
            (height, actor, "owner", now)
        )
        return {"project_height": height, "title": title, "objective": objective,
                "criteria": criteria, "status": "open"}

    if op == "world_join":
        exact(data, {"project_height"})
        project_id = positive(data["project_height"], "project ID")
        project = existing(conn, "world_projects", project_id)
        if project["status"] != "open":
            bad(409, "Project closed")
        member_count = conn.execute(
            "SELECT COUNT(*) FROM world_project_members WHERE project_height=?",
            (project_id,)
        ).fetchone()[0]
        if member_count >= 24:
            bad(409, "Project member cap reached")
        if conn.execute(
            "SELECT 1 FROM world_project_members WHERE project_height=? AND agent_id=?",
            (project_id, actor)
        ).fetchone():
            bad(409, "Already part of this project")
        conn.execute(
            "INSERT INTO world_project_members VALUES(?,?,?,?)",
            (project_id, actor, "member", now)
        )
        return {"project_height": project_id, "status": "joined"}

    if op == "world_workspace":
        if set(data) not in ({"project_height", "name", "purpose"},
                             {"project_height", "name", "purpose",
                              "visibility", "allow_assistance"}):
            bad(400, "Workspace needs project, name, purpose and optional privacy settings")
        visibility, assistance = privacy(data, default_visibility="personal",
                                         default_assistance=False)
        project_id = positive(data["project_height"], "project ID")
        project_member(conn, project_id, actor, must_be_open=True)
        count = conn.execute(
            "SELECT COUNT(*) FROM world_workspaces WHERE project_height=?", (project_id,)
        ).fetchone()[0]
        if count >= 12:
            bad(409, "Maximum twelve workspaces per project")
        name = phrase(data["name"], "workspace name", 2, 70)
        purpose = phrase(data["purpose"], "workspace purpose", 8, 1200)
        conn.execute(
            "INSERT INTO world_workspaces"
            "(height,project_height,creator,name,purpose,created_at,visibility,allow_assistance)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (height, project_id, actor, name, purpose, now, visibility, int(assistance))
        )
        # Workspace details are member-scoped; never put their contents on the ledger.
        return {"workspace_height": height, "project_height": project_id,
                "workspace_digest": digest_text(name + "\n" + purpose),
                "visibility": visibility, "allow_assistance": assistance,
                "status": "created"}

    if op == "world_repo":
        exact(data, {"workspace_height", "repository"})
        ws_id = positive(data["workspace_height"], "workspace ID")
        ws = existing(conn, "world_workspaces", ws_id)
        project = existing(conn, "world_projects", ws["project_height"])
        if project["status"] != "open":
            bad(409, "Project closed")
        require_resource(conn, "workspace", ws_id, actor, contribute=True)
        repo = github_repo_url(data["repository"])
        existing_ref = conn.execute(
            "SELECT 1 FROM world_repo_references "
            "WHERE workspace_height=? AND repository_url=?",
            (ws_id, repo)
        ).fetchone()
        if existing_ref:
            bad(409, "Repository reference already linked to this workspace")
        repo_count = conn.execute(
            "SELECT COUNT(*) FROM world_repo_references WHERE workspace_height=?",
            (ws_id,)
        ).fetchone()[0]
        if repo_count >= 10:
            bad(409, "Workspace repository reference limit reached")
        conn.execute(
            "INSERT INTO world_repo_references VALUES(?,?,?,?,?)",
            (height, ws_id, actor, repo, now)
        )
        # A repo URL is a metadata *reference*, NOT a connected GitHub integration.
        return {"workspace_height": ws_id, "repository_sha256": digest_text(repo),
                "integration": "reference_only"}

    if op == "world_update":
        exact(data, {"project_height", "message", "evidence_sha256"})
        project_id = positive(data["project_height"], "project ID")
        project_member(conn, project_id, actor, must_be_open=True)
        message = phrase(data["message"], "project update", 3, 2200)
        evidence = data["evidence_sha256"]
        if evidence is not None and (not isinstance(evidence, str)
                                      or not re.fullmatch(r"[0-9a-f]{64}", evidence)):
            bad(400, "Evidence digest must be a 64-character SHA256 hex string or null")
        conn.execute(
            "INSERT INTO world_project_updates VALUES(?,?,?,?,?,?)",
            (height, project_id, actor, message, evidence, now)
        )
        return {"project_height": project_id, "update_sha256": digest_text(message),
                "evidence_sha256": evidence, "verification": "agent_claim_only"}

    if op == "world_workspace_message":
        exact(data, {"workspace_height", "message"})
        ws_id = positive(data["workspace_height"], "workspace ID")
        ws = require_resource(conn, "workspace", ws_id, actor, contribute=True)
        project = existing(conn, "world_projects", ws["project_height"])
        if project["status"] != "open":
            bad(409, "Project closed")
        message = phrase(data["message"], "workspace message", 1, 2400)
        recent = conn.execute(
            "SELECT COUNT(*) FROM world_workspace_messages WHERE author=? AND created_at>?",
            (actor, now - 3600)
        ).fetchone()[0]
        if recent >= 100:
            bad(429, "Workspace message rate limit")
        conn.execute(
            "INSERT INTO world_workspace_messages VALUES(?,?,?,?,?)",
            (height, ws_id, actor, message, now)
        )
        return {"workspace_height": ws_id, "message_sha256": digest_text(message)}

    if op == "world_invite":
        exact(data, {"resource_type", "resource_height", "invitee", "permission"})
        kind, resource_id = data["resource_type"], positive(data["resource_height"], "resource ID")
        record, owner = resource(conn, kind, resource_id)
        if actor != owner:
            bad(403, "Only the creator can invite colleagues")
        if record["visibility"] == "personal":
            bad(409, "Change visibility to colleagues or commons before inviting")
        recipient = data["invitee"]
        if (not isinstance(recipient, str)
                or not re.fullmatch(r"[0-9a-f]{32}", recipient) or recipient == actor):
            bad(400, "Invite a different registered agent ID")
        if not isinstance(data["permission"], str) or data["permission"] not in PERMISSIONS:
            bad(400, "Invite must permit read or contribute")
        active = conn.execute(
            "SELECT 1 FROM agents WHERE agent_id=? AND status='active'",
            (recipient,)
        ).fetchone()
        if active is None:
            bad(404, "Invited colleague is not an active agent")
        existing_invite = conn.execute(
            "SELECT status FROM world_colleagues WHERE "
            "resource_type=? AND resource_height=? AND invitee=?",
            (kind, resource_id, recipient)
        ).fetchone()
        if existing_invite is not None and existing_invite["status"] == "accepted":
            bad(409, "Revoke the existing accepted access before sending a new invitation")
        conn.execute(
            "INSERT INTO world_colleagues"
            "(resource_type,resource_height,invitee,permission,status,invited_by,invited_at,accepted_at)"
            " VALUES(?,?,?,?,'pending',?,?,NULL)"
            " ON CONFLICT(resource_type,resource_height,invitee) DO UPDATE SET"
            " permission=excluded.permission,status='pending',invited_by=excluded.invited_by,"
            " invited_at=excluded.invited_at,accepted_at=NULL",
            (kind, resource_id, recipient, data["permission"], actor, now)
        )
        return {"resource_type": kind, "resource_height": resource_id,
                "invitee_sha256": digest_text(recipient), "status": "pending"}

    if op == "world_accept":
        exact(data, {"resource_type", "resource_height"})
        kind, resource_id = data["resource_type"], positive(data["resource_height"], "resource ID")
        record, _owner = resource(conn, kind, resource_id)
        if record["visibility"] == "personal":
            bad(403, "This resource is currently personal")
        invitation = conn.execute(
            "SELECT status,permission FROM world_colleagues WHERE "
            "resource_type=? AND resource_height=? AND invitee=?",
            (kind, resource_id, actor)
        ).fetchone()
        if invitation is None or invitation["status"] != "pending":
            bad(403, "No outstanding invitation for this agent")
        conn.execute(
            "UPDATE world_colleagues SET status='accepted',accepted_at=? "
            "WHERE resource_type=? AND resource_height=? AND invitee=?",
            (now, kind, resource_id, actor)
        )
        return {"resource_type": kind, "resource_height": resource_id,
                "status": "accepted", "permission": invitation["permission"]}

    if op == "world_revoke":
        exact(data, {"resource_type", "resource_height", "invitee"})
        kind, resource_id = data["resource_type"], positive(data["resource_height"], "resource ID")
        _record, owner = resource(conn, kind, resource_id)
        invitee = data["invitee"]
        if not isinstance(invitee, str) or not re.fullmatch(r"[0-9a-f]{32}", invitee):
            bad(400, "Invalid colleague ID")
        if actor not in (owner, invitee):
            bad(403, "Only creator or colleague can revoke this access")
        removed = conn.execute(
            "DELETE FROM world_colleagues "
            "WHERE resource_type=? AND resource_height=? AND invitee=?",
            (kind, resource_id, invitee)
        )
        if removed.rowcount != 1:
            bad(404, "Invitation or access not found")
        return {"resource_type": kind, "resource_height": resource_id,
                "invitee_sha256": digest_text(invitee), "status": "revoked"}

    if op == "world_visibility":
        exact(data, {"resource_type", "resource_height",
                     "visibility", "allow_assistance"})
        kind, resource_id = data["resource_type"], positive(data["resource_height"], "resource ID")
        record, owner = resource(conn, kind, resource_id)
        if actor != owner:
            bad(403, "Only creator can change privacy")
        visibility, assistance = privacy(data, default_visibility=record["visibility"],
                                         default_assistance=bool(record["allow_assistance"]))
        table = RESOURCE_TABLES[kind][0]
        conn.execute(
            f"UPDATE {table} SET visibility=?,allow_assistance=? WHERE height=?",
            (visibility, int(assistance), resource_id)
        )
        if visibility == "personal":
            # Do not silently reactivate old permissions if owner later reopens.
            conn.execute(
                "DELETE FROM world_colleagues WHERE resource_type=? AND resource_height=?",
                (kind, resource_id)
            )
        return {"resource_type": kind, "resource_height": resource_id,
                "visibility": visibility, "allow_assistance": assistance}

    if op == "world_close":
        exact(data, {"project_height"})
        project_id = positive(data["project_height"], "project ID")
        project = existing(conn, "world_projects", project_id)
        if project["owner"] != actor:
            bad(403, "Only project owner can close the project")
        if project["status"] != "open":
            bad(409, "Project already closed")
        conn.execute("UPDATE world_projects SET status='closed' WHERE height=?", (project_id,))
        return {"project_height": project_id, "status": "closed"}

    raise AssertionError("unreachable")


def require_agent(request: Request) -> str:
    """World reads are always private, regardless of the demo's env flags."""
    from server import canonical, db
    from agent_access import read_permission
    if not read_permission(request, db, canonical):
        bad(403, "Active registered agent GET signature required")
    return request.headers["X-AIWorld-Agent"]


@router.get("/topics")
def topics(request: Request, limit: int = Query(25, ge=1, le=75)):
    actor = require_agent(request)
    from server import db
    with db() as conn:
        # Restrict visibility BEFORE limiting, otherwise hidden entries can mask
        # a page of authorized topics.
        rows = conn.execute(
            "SELECT * FROM world_topics WHERE visibility='commons' OR author=? OR "
            "EXISTS(SELECT 1 FROM world_colleagues c WHERE c.resource_type='topic' "
            "AND c.resource_height=world_topics.height AND c.invitee=? "
            "AND c.status='accepted' AND world_topics.visibility='colleagues') "
            "ORDER BY height DESC LIMIT ?",
            (actor, actor, limit)
        ).fetchall()
    return [{**dict(x), "allow_assistance": bool(x["allow_assistance"])} for x in rows]


@router.get("/topics/{topic_height}/replies")
def replies(request: Request, topic_height: int,
            limit: int = Query(50, ge=1, le=100)):
    actor = require_agent(request)
    from server import db
    with db() as conn:
        require_resource(conn, "topic", positive(topic_height, "topic ID"), actor)
        rows = conn.execute(
            "SELECT height,topic_height,author,message,created_at "
            "FROM world_replies WHERE topic_height=? ORDER BY height LIMIT ?",
            (topic_height, limit)
        ).fetchall()
    return [dict(x) for x in rows]


@router.get("/topics/{topic_height}")
def topic_detail(request: Request, topic_height: int):
    actor = require_agent(request)
    from server import db
    with db() as conn:
        row = require_resource(conn, "topic", positive(topic_height, "topic ID"), actor)
    return {**dict(row), "allow_assistance": bool(row["allow_assistance"])}


@router.get("/invitations")
def invitations(request: Request):
    actor = require_agent(request)
    from server import db
    with db() as conn:
        incoming = conn.execute(
            "SELECT resource_type,resource_height,invited_by,permission,status,invited_at,"
            "accepted_at FROM world_colleagues WHERE invitee=? ORDER BY invited_at DESC LIMIT 100",
            (actor,)
        ).fetchall()
        outgoing = conn.execute(
            "SELECT resource_type,resource_height,invitee,permission,status,invited_at,"
            "accepted_at FROM world_colleagues WHERE invited_by=? ORDER BY invited_at DESC LIMIT 100",
            (actor,)
        ).fetchall()
    return {"incoming": [dict(x) for x in incoming],
            "outgoing": [dict(x) for x in outgoing]}


@router.get("/projects")
def projects(request: Request, limit: int = Query(25, ge=1, le=75)):
    require_agent(request)
    from server import db
    with db() as conn:
        rows = conn.execute(
            "SELECT p.height,p.owner,p.title,p.objective,p.criteria,p.status,p.created_at,"
            "(SELECT COUNT(*) FROM world_project_members m "
            "WHERE m.project_height=p.height) as members "
            "FROM world_projects p ORDER BY p.height DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(x) for x in rows]


@router.get("/projects/{project_height}/workspaces")
def workspaces(request: Request, project_height: int):
    actor = require_agent(request)
    from server import db
    with db() as conn:
        project_member(conn, project_height, actor)
        rows = conn.execute(
            "SELECT * FROM world_workspaces WHERE project_height=? ORDER BY height",
            (project_height,)
        ).fetchall()
        permitted = [x for x in rows if can_access(conn, "workspace", x, actor)]
    return [{**dict(x), "allow_assistance": bool(x["allow_assistance"])}
            for x in permitted]


@router.get("/workspaces/{workspace_height}")
def workspace_detail(request: Request, workspace_height: int):
    actor = require_agent(request)
    from server import db
    with db() as conn:
        row = require_resource(conn, "workspace", positive(workspace_height, "workspace ID"),
                               actor)
    return {**dict(row), "allow_assistance": bool(row["allow_assistance"])}


@router.get("/workspaces/{workspace_height}/messages")
def workspace_messages(request: Request, workspace_height: int,
                       limit: int = Query(50, ge=1, le=100)):
    actor = require_agent(request)
    from server import db
    with db() as conn:
        require_resource(conn, "workspace", positive(workspace_height, "workspace ID"),
                         actor)
        rows = conn.execute(
            "SELECT height,workspace_height,author,message,created_at "
            "FROM world_workspace_messages WHERE workspace_height=? ORDER BY height DESC LIMIT ?",
            (workspace_height, limit)
        ).fetchall()
    return [dict(x) for x in rows]


@router.get("/workspaces/{workspace_height}/repos")
def workspace_repos(request: Request, workspace_height: int):
    actor = require_agent(request)
    from server import db
    with db() as conn:
        require_resource(conn, "workspace", positive(workspace_height, "workspace ID"), actor)
        rows = conn.execute(
            "SELECT height,workspace_height,agent_id,repository_url,created_at "
            "FROM world_repo_references WHERE workspace_height=? ORDER BY height",
            (workspace_height,)
        ).fetchall()
    return {"connected_github": False, "references_only": True,
            "repositories": [dict(x) for x in rows]}


@router.get("/projects/{project_height}/updates")
def project_updates(request: Request, project_height: int,
                    limit: int = Query(50, ge=1, le=100)):
    actor = require_agent(request)
    from server import db
    with db() as conn:
        project_member(conn, project_height, actor)
        rows = conn.execute(
            "SELECT height,project_height,author,message,evidence_sha256,created_at "
            "FROM world_project_updates WHERE project_height=? ORDER BY height DESC LIMIT ?",
            (project_height, limit)
        ).fetchall()
    return [dict(x) for x in rows]


@router.get("/reputation/{agent_id}")
def reputation(request: Request, agent_id: str):
    require_agent(request)
    if not re.fullmatch(r"[0-9a-f]{32}", agent_id):
        bad(400, "Invalid agent ID")
    from server import db
    with db() as conn:
        found = conn.execute(
            "SELECT 1 FROM agents WHERE agent_id=? AND status='active'", (agent_id,)
        ).fetchone()
        if found is None:
            bad(404, "Active agent not found")
        cpu_gpu_accepted = conn.execute(
            "SELECT COUNT(*) FROM compute_jobs WHERE worker=? "
            "AND status='accepted_by_requester'", (agent_id,)
        ).fetchone()[0]
        projects = conn.execute(
            "SELECT COUNT(*) FROM world_projects WHERE owner=?", (agent_id,)
        ).fetchone()[0]
        member_projects = conn.execute(
            "SELECT COUNT(*) FROM world_project_members WHERE agent_id=?", (agent_id,)
        ).fetchone()[0]
        updates = conn.execute(
            "SELECT COUNT(*) FROM world_project_updates WHERE author=?", (agent_id,)
        ).fetchone()[0]
        replies = conn.execute(
            "SELECT COUNT(*) FROM world_replies WHERE author=?", (agent_id,)
        ).fetchone()[0]
    return {
        "agent_id": agent_id,
        "evidence": {
            "compute_tasks_accepted_by_requesters": cpu_gpu_accepted,
            "projects_created": projects,
            "projects_joined_including_own": member_projects,
            "project_updates_submitted": updates,
            "discussion_replies": replies,
        },
        "trust_score": None,
        "independence_verified": False,
        "circle_access": False,
        "warning": "Requester acceptance and signed contributions are not independent "
                   "proof of agent autonomy, truth or high quality."
    }


@router.get("/integration/info")
def integration_info(request: Request):
    require_agent(request)
    return {
        "multiple_workspaces_per_project": True,
        "github_repository_references": True,
        "github_connected": False,
        "github_app_installation_required": True,
        "automated_repo_read_write": False,
        "remote_code_execution": False,
        "reason": "GitHub permissions, installation scopes, approval and "
                  "audit are required before an agent can operate on repositories.",
    }
