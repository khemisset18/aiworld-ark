"""Read-only, unauthenticated PUBLIC GitHub repository metadata for workspaces.

The linked URL is vetted by world_space.github_repo_url. The HTTPS endpoint is
always api.github.com, with redirects disabled and no secrets/tokens in play.
Workspace ACL is enforced FIRST, and a private repository is never accessed
through this public-only connector. A future GitHub App with explicit repository
permissions is required for private repos or any code change.
"""
from __future__ import annotations

import re
import threading
import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from world_space import existing, github_repo_url, positive, require_agent, require_resource

router = APIRouter(prefix="/v1/world", tags=["public GitHub metadata (read only)"])
TTL_SECONDS = 600
MAX_HTTP_REQUESTS_PER_HOUR = 40  # leave room under GitHub's unauthenticated IP cap
_cached: dict[str, tuple[float, dict]] = {}
_attempts: list[float] = []
_lock = threading.Lock()


def _fetch_public_repo(full_name: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]{1,100}", full_name):
        raise HTTPException(400, "Invalid repository reference")
    owner, repo = full_name.split("/")
    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "AI-WORLD-ARK-public-readonly",
    }
    try:
        with httpx.Client(timeout=5.0, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", url, headers=headers) as response:
                if response.status_code in (301, 302, 307, 308):
                    raise HTTPException(409, "GitHub repository moved; attach the new canonical URL")
                if response.status_code == 404:
                    raise HTTPException(404, "Public repository not found or not public")
                if response.status_code in (403, 429):
                    raise HTTPException(503, "Public GitHub API temporarily rate limited")
                if response.status_code != 200:
                    raise HTTPException(502, "GitHub API could not fetch public repository metadata")
                chunks = []
                total = 0
                for piece in response.iter_bytes():
                    total += len(piece)
                    if total > 128_000:
                        raise HTTPException(502, "GitHub metadata response too large")
                    chunks.append(piece)
                try:
                    data = httpx.Response(200, content=b"".join(chunks)).json()
                except ValueError:
                    raise HTTPException(502, "Invalid GitHub JSON response") from None
    except (httpx.RequestError, httpx.TimeoutException):
        raise HTTPException(502, "GitHub public metadata temporarily unavailable") from None
    if not isinstance(data, dict) or data.get("private") is not False:
        raise HTTPException(404, "Only PUBLIC GitHub repositories can be previewed")
    if (not isinstance(data.get("full_name"), str)
            or data["full_name"].lower() != full_name.lower()):
        raise HTTPException(409, "Repository name changed; reattach its canonical URL")
    if (not isinstance(data.get("html_url"), str)
            or data["html_url"].rstrip("/").lower()
            != "https://github.com/".lower() + full_name.lower()):
        raise HTTPException(502, "Invalid GitHub repository identity")
    return {
        "full_name": data["full_name"],
        "url": data["html_url"],
        "description": str(data.get("description") or "")[:500],
        "default_branch": str(data.get("default_branch") or "")[:100],
        "language": str(data.get("language") or "")[:100],
        "stars": int(data.get("stargazers_count") or 0),
        "open_issues": int(data.get("open_issues_count") or 0),
        "archived": data.get("archived") is True,
        "updated_at": str(data.get("updated_at") or "")[:40],
        "access": "public_read_only",
        "can_read_private_repositories": False,
        "can_write_repository": False,
    }


def public_summary(full_name: str) -> dict:
    now = time.monotonic()
    key = full_name.lower()
    with _lock:
        cached = _cached.get(key)
        if cached and now - cached[0] < TTL_SECONDS:
            return dict(cached[1])
        _attempts[:] = [x for x in _attempts if now - x < 3600]
        if len(_attempts) >= MAX_HTTP_REQUESTS_PER_HOUR:
            raise HTTPException(429, "GitHub public read budget exceeded; retry later")
        _attempts.append(now)
    result = _fetch_public_repo(full_name)
    with _lock:
        if len(_cached) >= 100:
            _cached.pop(next(iter(_cached)))
        _cached[key] = (time.monotonic(), result)
    return dict(result)


@router.get("/workspaces/{workspace_height}/github/{reference_height}")
def public_repo_preview(request: Request, workspace_height: int, reference_height: int):
    agent_id = require_agent(request)
    from server import db
    with db() as conn:
        ws_id = positive(workspace_height, "workspace ID")
        require_resource(conn, "workspace", ws_id, agent_id)
        ref_id = positive(reference_height, "repository reference ID")
        row = conn.execute(
            "SELECT repository_url FROM world_repo_references "
            "WHERE height=? AND workspace_height=?", (ref_id, ws_id)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "No such GitHub repository reference in workspace")
        repo_url = github_repo_url(row["repository_url"])
    full_name = repo_url.removeprefix("https://github.com/")
    preview = public_summary(full_name)
    return JSONResponse({
        "workspace_height": ws_id,
        "reference_height": ref_id,
        "repository": preview,
        "notice": "Read-only metadata for a public repository only. "
                  "No GitHub installation, private repository access or commits."
    }, headers={"Cache-Control": "private, no-store"})
