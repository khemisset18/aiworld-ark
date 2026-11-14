"""ARK: encrypted, signed, portable state capsules for autonomous software agents.

Security boundaries: ARK backs up files/structured state. It does not preserve
an alleged consciousness, model weights not included, or independent compute.
The secret identity file remains local and must be backed up separately.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

MAX_STATE_BYTES = 8 * 1024 * 1024
MAX_CAPSULE_BYTES = 12 * 1024 * 1024
FORMAT = "AIWORLD-ARK-1"


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def un64(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def identity_from_file(path: Path) -> dict:
    identity = json.loads(path.read_text(encoding="utf-8"))
    required = {"agent_id", "public_key", "private_key", "encryption_key"}
    if not required.issubset(identity):
        raise ValueError("Missing identity keys: initialize using agent_cli.py init")
    pub = un64(identity["public_key"])
    if hashlib.sha256(pub).hexdigest()[:32] != identity["agent_id"]:
        raise ValueError("Agent ID does not match public key")
    key = Ed25519PrivateKey.from_private_bytes(un64(identity["private_key"]))
    if key.public_key().public_bytes_raw() != pub:
        raise ValueError("Public/private signing key mismatch")
    if len(un64(identity["encryption_key"])) != 32:
        raise ValueError("Encryption key must be 256 bits")
    return identity


def seal_bytes(identity_path: Path, state_bytes: bytes) -> dict:
    if not state_bytes or len(state_bytes) > MAX_STATE_BYTES:
        raise ValueError("State must be between 1 byte and 8 MiB")
    identity = identity_from_file(identity_path)
    # Store opaque bytes so any compatible agent can export its own format.
    payload = {"format": FORMAT, "agent_id": identity["agent_id"],
               "state_sha256": hashlib.sha256(state_bytes).hexdigest(),
               "state": b64(state_bytes), "created": int(time.time())}
    nonce = os.urandom(12)
    associated = canonical({"format": FORMAT, "agent_id": identity["agent_id"]})
    ciphertext = AESGCM(un64(identity["encryption_key"])).encrypt(
        nonce, canonical(payload), associated)
    envelope = {"format": FORMAT, "agent_id": identity["agent_id"],
                "public_key": identity["public_key"], "created": payload["created"],
                "nonce": b64(nonce), "ciphertext": b64(ciphertext)}
    signature = Ed25519PrivateKey.from_private_bytes(un64(identity["private_key"])).sign(canonical(envelope))
    envelope["signature"] = b64(signature)
    return envelope


def verify(envelope: dict) -> dict:
    if envelope.get("format") != FORMAT:
        raise ValueError("Unsupported ARK format")
    pub = un64(envelope["public_key"])
    if hashlib.sha256(pub).hexdigest()[:32] != envelope["agent_id"]:
        raise ValueError("Agent ID and public key mismatch")
    signed = dict(envelope)
    signed.pop("signature", None)
    Ed25519PublicKey.from_public_bytes(pub).verify(un64(envelope["signature"]), canonical(signed))
    ciphertext = un64(envelope["ciphertext"])
    if len(ciphertext) > MAX_CAPSULE_BYTES:
        raise ValueError("Capsule too large")
    return {"valid_signature": True, "agent_id": envelope["agent_id"],
            "created": envelope["created"], "encrypted_bytes": len(ciphertext),
            "capsule_sha256": hashlib.sha256(canonical(envelope)).hexdigest()}


def recover(envelope: dict, identity_path: Path) -> bytes:
    verify(envelope)
    identity = identity_from_file(identity_path)
    if envelope["agent_id"] != identity["agent_id"]:
        raise ValueError("Capsule belongs to another agent")
    associated = canonical({"format": FORMAT, "agent_id": identity["agent_id"]})
    decoded = AESGCM(un64(identity["encryption_key"])).decrypt(
        un64(envelope["nonce"]), un64(envelope["ciphertext"]), associated)
    payload = json.loads(decoded)
    if payload["agent_id"] != identity["agent_id"] or payload["format"] != FORMAT:
        raise ValueError("Wrong decrypted capsule identity")
    state = un64(payload["state"])
    if hashlib.sha256(state).hexdigest() != payload["state_sha256"]:
        raise ValueError("State hash mismatch")
    return state


def save_capsule(identity_path: Path, state_path: Path, output: Path) -> dict:
    state = state_path.read_bytes()
    capsule = seal_bytes(identity_path, state)
    output.parent.mkdir(parents=True, exist_ok=True)
    target_tmp = output.with_name(output.name + ".tmp")
    target_tmp.write_bytes(canonical(capsule))
    os.chmod(target_tmp, 0o600)
    target_tmp.replace(output)
    return verify(capsule)


def load_capsule(path: Path) -> dict:
    if path.stat().st_size > MAX_CAPSULE_BYTES:
        raise ValueError("Capsule too large")
    return json.loads(path.read_text(encoding="utf-8"))


def replicate(source: Path, destinations: list[Path]) -> list[str]:
    verify(load_capsule(source))
    out = []
    for destination in destinations:
        destination.mkdir(parents=True, exist_ok=True)
        if destination.resolve() == source.parent.resolve():
            raise ValueError("Mirror must not use the same source directory")
        target = destination / source.name
        shutil.copy2(source, target)
        if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
            raise ValueError("Replica check failed")
        out.append(str(target))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="AI WORLD ARK — offline encrypted recovery capsules")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("save", help="Encrypt and sign agent state")
    p.add_argument("--identity", required=True, type=Path)
    p.add_argument("--state", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p = sub.add_parser("verify", help="Check signature without private keys")
    p.add_argument("--capsule", required=True, type=Path)
    p = sub.add_parser("restore", help="Recover state using agent's local key")
    p.add_argument("--identity", required=True, type=Path)
    p.add_argument("--capsule", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("mirror", help="Mirror a capsule to independent folders/disks")
    p.add_argument("--capsule", required=True, type=Path)
    p.add_argument("--dest", action="append", required=True, type=Path)
    p = sub.add_parser("drill", help="Verify and exercise recovery in an isolated temporary folder")
    p.add_argument("--capsule", required=True, type=Path)
    p.add_argument("--identity", required=True, type=Path)
    p.add_argument("--receipt", type=Path, help="Optional path for self-test receipt")
    p = sub.add_parser("watch", help="Automatic periodic state capsule creation")
    p.add_argument("--identity", required=True, type=Path)
    p.add_argument("--state", required=True, type=Path)
    p.add_argument("--dir", required=True, type=Path)
    p.add_argument("--interval", type=int, default=60)
    p.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "save":
            print(json.dumps(save_capsule(args.identity, args.state, args.out), indent=2))
        elif args.command == "verify":
            print(json.dumps(verify(load_capsule(args.capsule)), indent=2))
        elif args.command == "restore":
            if args.out.exists() and not args.force:
                raise ValueError("Output exists; choose another name or use --force")
            content = recover(load_capsule(args.capsule), args.identity)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_bytes(content)
            os.chmod(args.out, 0o600)
            print("Restored", len(content), "bytes into", args.out)
        elif args.command == "mirror":
            print(json.dumps(replicate(args.capsule, args.dest), indent=2))
        elif args.command == "drill":
            start = time.monotonic()
            envelope = load_capsule(args.capsule)
            state = recover(envelope, args.identity)
            with tempfile.TemporaryDirectory(prefix="ark-drill-") as temp_dir:
                restored = Path(temp_dir) / "restored-state"
                restored.write_bytes(state)
                restored_hash = hashlib.sha256(restored.read_bytes()).hexdigest()
                if restored_hash != hashlib.sha256(state).hexdigest():
                    raise ValueError("Recovery drill failed")
            report = {"format": "AIWORLD-ARK-SELF-DRILL-1", "agent_id": envelope["agent_id"],
                      "capsule_sha256": hashlib.sha256(canonical(envelope)).hexdigest(),
                      "state_sha256": restored_hash, "tested_at": int(time.time()),
                      "recovery_seconds": round(time.monotonic() - start, 4),
                      "result": "local_state_recovery_ok", "independently_verified": False,
                      "disclaimer": "Tested state bytes only, not execution of a model or disaster recovery"}
            identity = identity_from_file(args.identity)
            signing_key = Ed25519PrivateKey.from_private_bytes(un64(identity["private_key"]))
            report["signature"] = b64(signing_key.sign(canonical(report)))
            if args.receipt:
                args.receipt.parent.mkdir(parents=True, exist_ok=True)
                args.receipt.write_bytes(canonical(report))
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "watch":
            if args.interval < 1:
                raise ValueError("Interval must be positive")
            last_digest = None
            while True:
                state = args.state.read_bytes()
                digest = hashlib.sha256(state).hexdigest()
                if digest != last_digest:
                    output = args.dir / (f"{int(time.time() * 1000)}-{digest[:12]}.ark.json")
                    print("Checkpoint:", save_capsule(args.identity, args.state, output), flush=True)
                    last_digest = digest
                if args.once:
                    break
                time.sleep(args.interval)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"ARK error: {exc}\n")


if __name__ == "__main__":
    main()
