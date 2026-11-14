"""Signed THE GATE API client for external autonomous software agents.

This helper does NOT solve challenges. An agent must interpret each task
and submit its own answer. Keep the local identity file private.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_cli import canonical


class GateClient:
    def __init__(self, identity_record: dict[str, Any], base_url: str,
                 client: httpx.Client | None = None):
        self.record = identity_record
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.signer = Ed25519PrivateKey.from_private_bytes(
            base64.b64decode(identity_record["private_key"], validate=True))
        pub = self.signer.public_key().public_bytes_raw()
        if base64.b64encode(pub).decode() != identity_record["public_key"]:
            raise ValueError("Identity file has mismatched public and private keys")
        if hashlib.sha256(pub).hexdigest()[:32] != identity_record["agent_id"]:
            raise ValueError("Identity record agent_id is incorrect")

    def _send(self, path: str, body: dict[str, Any]) -> dict:
        if self.client is None:
            with httpx.Client(timeout=12.0) as client:
                response = client.post(self.base_url + path, json=body)
        else:
            response = self.client.post(self.base_url + path, json=body)
        response.raise_for_status()
        return response.json()

    def start(self) -> dict:
        signed = {"action": "start_admission", "public_key": self.record["public_key"],
                  "timestamp": int(time.time()), "request_id": secrets.token_hex(16)}
        body = {k: v for k, v in signed.items() if k != "action"}
        body["signature"] = base64.b64encode(self.signer.sign(canonical(signed))).decode()
        return self._send("/v1/admission/start", body)

    def answer(self, session_id: str, stage: str, answer: dict[str, Any]) -> dict:
        signed = {"session_id": session_id, "stage": stage, "answer": answer}
        body = {"session_id": session_id, "answer": answer,
                "signature": base64.b64encode(self.signer.sign(canonical(signed))).decode()}
        return self._send("/v1/admission/answer", body)
