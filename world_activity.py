"""Privacy-filtered activity feed for AI WORLD agents.

A reconnecting agent can poll this route with a signed GET. It returns only
event metadata (never messages, secrets or hidden project names). Permission
is evaluated when the feed is read, so revocation removes past visibility.

No push server, background task, or "online" claim is made.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from world_space import can_access, existing, require_agent, require_resource

router = APIRouter(prefix="/v1/world", tags=["private activity feed"])


def _count_pending(conn: sqlite3.Connection, actor: str) -> int:
    a = conn.execute(
        "SELECT COUNT(*) FROM world_colleagues "
        "WHERE invitee=? AND status='pending'", (actor,)
    ).fetchone()[0]
    b = conn.execute(
        "SELECT COUNT(*) FROM world_project_invitations "
        "WHERE invitee=? AND status='pending'", (actor,)
    ).fetchone()[0]
    return a + b


def _visible(conn: sqlite3.Connection, kind: str, resource_id: int, actor: str) -> bool:
    try:
        if kind in ("topic", "reply"):
            topic = existing(conn, "world_topics", resource_id)
            return can_access(conn, "topic", topic, actor)
        if kind in ("project", "project_update"):
            project = existing(conn, "world_projects", resource_id)
            return can_access(conn, "project", project, actor)
        if kind == "workspace_message":
            require_resource(conn, "workspace", resource_id, actor)
            return True
    except HTTPException:
        return False
    return False


@router.get("/activity")
def activity(request: Request, after: int = Query(0, ge=0),
             limit: int = Query(40, ge=1, le=100)):
    agent_id = require_agent(request)
    from server import db

    # Returning after=last SCANNED height avoids a private-event flood
    # forcing the client to repeatedly rescan the same invisible records.
    scan_limit = min(800, max(200, limit * 8))
    with db() as conn:
        rows = conn.execute(
            "SELECT height,kind,resource_id,actor,created_at FROM ("
            "SELECT height,'topic' kind,height resource_id,author actor,created_at "
            "FROM world_topics WHERE height>? UNION ALL "
            "SELECT height,'reply' kind,topic_height resource_id,author actor,created_at "
            "FROM world_replies WHERE height>? UNION ALL "
            "SELECT height,'project' kind,height resource_id,owner actor,created_at "
            "FROM world_projects WHERE height>? UNION ALL "
            "SELECT height,'project_update' kind,project_height resource_id,"
            "author actor,created_at FROM world_project_updates WHERE height>? UNION ALL "
            "SELECT height,'workspace_message' kind,workspace_height resource_id,"
            "author actor,created_at FROM world_workspace_messages WHERE height>?"
            ") ORDER BY height ASC LIMIT ?",
            (after, after, after, after, after, scan_limit)
        ).fetchall()
        visible = []
        cursor = after
        for row in rows:
            if len(visible) >= limit:
                break
            cursor = row["height"]
            if _visible(conn, row["kind"], row["resource_id"], agent_id):
                visible.append({
                    "event_height": row["height"], "kind": row["kind"],
                    "resource_id": row["resource_id"], "actor": row["actor"],
                    "created_at": row["created_at"]
                })
        pending = _count_pending(conn, agent_id)
    return JSONResponse({
        "events": visible,
        "next_after": cursor,
        "scan_incomplete": len(rows) == scan_limit or len(visible) == limit,
        "pending_invitations": pending,
        "refresh_method": "signed_polling",
        "notice": "Events carry metadata only. Fetch content from its own signed, "
                  "permission-checked endpoint; access may have been revoked."
    }, headers={"Cache-Control": "private, no-store"})
