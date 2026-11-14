"""Experimental independent ARK storage-miner service.

A miner stores only signed, client-encrypted ARK capsules. No decryption keys,
token rewards, smart contracts or blockchain consensus exist in this prototype.
Never expose directly to the public Internet without HTTPS, rate limits,
per-agent authorization and an independent security audit.
"""
from __future__ import annotations

import binascii
import hashlib
import hmac
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from cryptography.exceptions import InvalidSignature

from ark import MAX_CAPSULE_BYTES, canonical, verify

MAX_WIRE_BYTES = 16 * 1024 * 1024
AGENT_ID = re.compile(r"[a-f0-9]{32}\Z")
DIGEST = re.compile(r"[a-f0-9]{64}\Z")
NONCE = re.compile(r"[a-f0-9]{32,64}\Z")


def create_app(
    root: str | Path | None = None,
    token: str | None = None,
    limit_bytes: int | None = None,
    per_agent_bytes: int | None = None,
) -> FastAPI:
    """Create a single-process storage node with explicit disk quotas."""
    root = Path(root if root is not None else os.getenv("ARK_MINER_DATA", "./miner_data"))
    token = token if token is not None else os.getenv("ARK_MINER_TOKEN", "")
    limit_bytes = int(limit_bytes if limit_bytes is not None else os.getenv("ARK_MINER_LIMIT_BYTES", str(256 * 1024 * 1024)))
    per_agent_bytes = int(per_agent_bytes if per_agent_bytes is not None else os.getenv("ARK_MINER_AGENT_LIMIT_BYTES", str(64 * 1024 * 1024)))
    if limit_bytes < MAX_WIRE_BYTES or per_agent_bytes < MAX_WIRE_BYTES:
        raise ValueError("Miner quotas must permit one full-size ARK capsule")
    configured = len(token) >= 32
    lock = threading.Lock()
    app = FastAPI(title="AI WORLD / ARK Storage Miner (pilot)", version="0.1.0")

    def require_token(request: Request) -> None:
        if not configured:
            raise HTTPException(503, "Miner authentication is not configured")
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer ") or not hmac.compare_digest(
            authorization[7:], token
        ):
            raise HTTPException(401, "Invalid miner access token")

    def validate_agent(agent_id: str) -> None:
        if AGENT_ID.fullmatch(agent_id) is None:
            raise HTTPException(400, "Invalid agent id")

    def validate_digest(digest: str) -> None:
        if DIGEST.fullmatch(digest) is None:
            raise HTTPException(400, "Invalid capsule digest")

    def capsule_path(agent_id: str, digest: str) -> Path:
        validate_agent(agent_id)
        validate_digest(digest)
        return root / agent_id / (digest + ".ark.json")

    def used_bytes(directory: Path) -> int:
        if not directory.exists():
            return 0
        return sum(p.stat().st_size for p in directory.rglob("*.ark.json") if p.is_file())

    def checked_capsule(raw: bytes, digest: str | None = None) -> dict:
        if len(raw) > MAX_WIRE_BYTES:
            raise HTTPException(413, "Capsule exceeds wire size limit")
        try:
            envelope = json.loads(raw)
            if not isinstance(envelope, dict) or set(envelope) != {
                "format", "agent_id", "public_key", "created", "nonce",
                "ciphertext", "signature"
            }:
                raise ValueError("Unexpected ARK capsule fields")
            if type(envelope["created"]) is not int:
                raise ValueError("Invalid creation timestamp")
            details = verify(envelope)
            normalized = canonical(envelope)
            if len(normalized) > MAX_WIRE_BYTES or details["encrypted_bytes"] > MAX_CAPSULE_BYTES:
                raise ValueError("Capsule too large")
            if digest is not None and hashlib.sha256(normalized).hexdigest() != digest:
                raise ValueError("Capsule content hash mismatch")
            return envelope
        except (ValueError, TypeError, KeyError, UnicodeError, OverflowError,
                AttributeError, binascii.Error, InvalidSignature) as exc:
            # Reject corrupt data and invalid signatures without exposing sensitive inputs.
            raise HTTPException(400, "Invalid signed ARK capsule") from exc

    def load(agent_id: str, digest: str) -> bytes:
        path = capsule_path(agent_id, digest)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raise HTTPException(404, "Capsule not stored on this miner")
        if len(raw) > MAX_WIRE_BYTES:
            raise HTTPException(409, "Stored capsule exceeds limit")
        try:
            envelope = checked_capsule(raw, digest)
            if envelope["agent_id"] != agent_id:
                raise ValueError("Wrong capsule owner")
        except (HTTPException, ValueError):
            raise HTTPException(409, "Stored capsule integrity failure")
        return canonical(envelope)

    @app.get("/health")
    def health():
        return {"ok": configured, "kind": "ark-storage-miner", "ready": configured}

    @app.get("/v1/storage/info")
    def info():
        return {
            "kind": "ark-storage-miner", "version": "0.1.0",
            "mode": "single-node experimental", "encrypted_only": True,
            "max_capsule_wire_bytes": MAX_WIRE_BYTES,
            "disk_limit_bytes": limit_bytes, "per_agent_limit_bytes": per_agent_bytes,
            "proof": "nonce-bound hash of currently served bytes, not proof of long-term retention",
            "token_payments": False, "p2p": False,
            "notice": "HTTPS and unique miner credentials required outside localhost"
        }

    @app.post("/v1/storage/capsules", status_code=201)
    async def store(request: Request):
        require_token(request)
        received = bytearray()
        async for chunk in request.stream():
            received.extend(chunk)
            if len(received) > MAX_WIRE_BYTES:
                raise HTTPException(413, "Capsule exceeds wire size limit")
        envelope = checked_capsule(bytes(received))
        normalized = canonical(envelope)
        agent_id = envelope["agent_id"]
        digest = hashlib.sha256(normalized).hexdigest()
        path = capsule_path(agent_id, digest)
        with lock:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if path.exists():
                load(agent_id, digest)
                return {"agent_id": agent_id, "digest": digest,
                        "bytes": len(normalized), "stored": True, "already_present": True}
            if used_bytes(root) + len(normalized) > limit_bytes:
                raise HTTPException(507, "Miner storage capacity exhausted")
            if used_bytes(path.parent) + len(normalized) > per_agent_bytes:
                raise HTTPException(507, "Agent storage quota exhausted")
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".incoming-", delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                    os.chmod(tmp_path, 0o600)
                    tmp.write(normalized)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                os.replace(tmp_path, path)
            finally:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)
        return {"agent_id": agent_id, "digest": digest,
                "bytes": len(normalized), "stored": True, "already_present": False}

    @app.get("/v1/storage/agents/{agent_id}/capsules")
    def list_capsules(agent_id: str, request: Request):
        require_token(request)
        validate_agent(agent_id)
        directory = root / agent_id
        result = []
        if directory.exists():
            for path in directory.glob("*.ark.json"):
                digest = path.name.removesuffix(".ark.json")
                if DIGEST.fullmatch(digest) is None:
                    continue
                try:
                    raw = load(agent_id, digest)
                    result.append({"digest": digest, "agent_id": agent_id,
                                   "created": json.loads(raw)["created"],
                                   "bytes": len(raw)})
                except HTTPException:
                    continue
        return sorted(result, key=lambda item: (item["created"], item["digest"]), reverse=True)[:100]

    @app.get("/v1/storage/capsules/{agent_id}/{digest}/audit")
    def audit(agent_id: str, digest: str, nonce: str, request: Request):
        require_token(request)
        if NONCE.fullmatch(nonce) is None:
            raise HTTPException(400, "Invalid audit nonce")
        raw = load(agent_id, digest)
        response = hashlib.sha256(bytes.fromhex(nonce) + raw).hexdigest()
        return {"agent_id": agent_id, "digest": digest, "nonce": nonce,
                "challenge_sha256": response,
                "disclaimer": "Only verifies current possession, not continuous availability"}

    @app.get("/v1/storage/capsules/{agent_id}/{digest}")
    def fetch_capsule(agent_id: str, digest: str, request: Request):
        require_token(request)
        return Response(content=load(agent_id, digest), media_type="application/json")

    return app


app = create_app()
