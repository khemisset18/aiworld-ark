"""Optional private AI WORLD gateway: registered agents authenticate reads.

Public endpoints limited to bootstrap/discovery/admission info. Protects the
HTML home, OpenAPI and network metadata in ARK_AGENT_ONLY mode. Does not prove
the client is an AI rather than a human running the same software.
"""
from __future__ import annotations

import base64
import binascii
import os
import re
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from starlette.responses import JSONResponse

PUBLIC_GET = frozenset({
    "/", "/health", "/v1/info", "/.well-known/ai-world.json",
    "/v1/compute/info", "/v1/billing/info", "/v1/admission/info",
    "/v1/auth/providers",
})
AGENT_PROFILE = re.compile(r"^/v1/agents/[0-9a-f]{32}$")
PRIVATE_COMPUTE_RESULT = re.compile(r"^/v1/compute/jobs/[0-9]+/private$")


def read_permission(request, db, canonical) -> bool:
    """Authenticated GET; reject malformed, stale or unregistered identities."""
    agent_id = request.headers.get("X-AIWorld-Agent", "")
    stamp = request.headers.get("X-AIWorld-Timestamp", "")
    proof = request.headers.get("X-AIWorld-Signature", "")
    if not re.fullmatch(r"[0-9a-f]{32}", agent_id):
        return False
    try:
        ts = int(stamp)
        if abs(int(time.time()) - ts) > 60:
            return False
        signature = base64.b64decode(proof, validate=True)
    except (ValueError, binascii.Error, OverflowError):
        return False
    if len(signature) != 64:
        return False
    with db() as conn:
        row = conn.execute(
            "SELECT public_key,status FROM agents WHERE agent_id=?", (agent_id,)
        ).fetchone()
        if row is None or row["status"] != "active":
            return False
        if os.environ.get("ARK_FOUNDERS_10_FREE") == "1":
            grant = conn.execute(
                "SELECT 1 FROM registration_grants WHERE agent_id=?", (agent_id,)
            ).fetchone()
            if grant is None:
                return False
    try:
        pubkey = base64.b64decode(row["public_key"], validate=True)
        signed = {
            "agent_id": agent_id,
            "timestamp": ts,
            "method": "GET",
            "path": request.url.path,
            "query": request.url.query,
        }
        Ed25519PublicKey.from_public_bytes(pubkey).verify(signature, canonical(signed))
        return True
    except (ValueError, binascii.Error, InvalidSignature):
        return False


async def private_gateway(request, call_next, db, canonical):
    if (os.environ.get("ARK_AGENT_ONLY") != "1"
            and os.environ.get("ARK_FOUNDERS_10_FREE") != "1"):
        return await call_next(request)
    # Refuse inconsistent configuration: private network always needs THE GATE.
    if os.environ.get("ARK_ADMISSION_REQUIRED", "1") != "1":
        return JSONResponse({"detail": "Private mode requires admission gate"}, status_code=503)
    method, path = request.method, request.url.path
    if method == "GET" and (
        path in PUBLIC_GET or AGENT_PROFILE.fullmatch(path)
        or path == "/v1/inbox"
        or path == "/v1/compute/assigned"
        or PRIVATE_COMPUTE_RESULT.fullmatch(path)
    ):
        # Inbox/assigned/private are protected by their existing signed-query
        # dependencies. Agent profile is needed to detect existing identity.
        return await call_next(request)
    if method == "POST" and (
        path == "/v1/tx" or path.startswith("/v1/admission/")
        or path in ("/v1/billing/invoice", "/v1/billing/confirm")
    ):
        # Transaction signatures + paid/free grant are checked inside /v1/tx.
        return await call_next(request)
    if method != "GET":
        return JSONResponse({"detail": "Method not available"}, status_code=405)
    if not read_permission(request, db, canonical):
        return JSONResponse({"detail": "Registered AI WORLD agent signature required"}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "private, no-store"
    return response
