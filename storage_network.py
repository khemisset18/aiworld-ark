"""ARK distributed storage pilot client: replicate, audit, restore encrypted state.

Storage miners receive only signed encrypted ARK envelopes. Private signing and
decryption keys remain on the agent's own machine. This is not a production
blockchain, cryptotoken, decentralized consensus, or guaranteed recovery SLA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ark import (
    MAX_CAPSULE_BYTES, b64, canonical, identity_from_file, load_capsule,
    recover, seal_bytes, un64, verify,
)

MAX_REMOTE_BYTES = 16 * 1024 * 1024


def read_peers(path: Path) -> list[dict]:
    """Secrets must live in a private local file, never in a public repo."""
    peers = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(peers, list) or not 1 <= len(peers) <= 20:
        raise ValueError("Peer config must be a nonempty array of up to 20 miners")
    seen = set()
    for peer in peers:
        if not isinstance(peer, dict) or set(peer) != {"url", "token"}:
            raise ValueError("Each miner must specify exactly url and token")
        if not isinstance(peer["url"], str) or not isinstance(peer["token"], str):
            raise ValueError("Miner url/token must be strings")
        uri = urlsplit(peer["url"])
        if (uri.username is not None or uri.password is not None or uri.query or
                uri.fragment or uri.path not in ("", "/") or uri.scheme not in ("http", "https")):
            raise ValueError("Invalid miner URL (no credentials, query or path allowed)")
        if uri.hostname is None or uri.port == 0:
            raise ValueError("Invalid miner hostname")
        if uri.scheme == "http" and uri.hostname not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("Public miners must use HTTPS")
        if len(peer["token"]) < 32:
            raise ValueError("Each miner requires a private token of at least 32 characters")
        peer["url"] = peer["url"].rstrip("/")
        if peer["url"] in seen:
            raise ValueError("Duplicate miner URLs are not independent copies")
        seen.add(peer["url"])
    return peers


def bearer(peer: dict) -> dict:
    return {"Authorization": "Bearer " + peer["token"]}


def client_for(transport=None):
    return httpx.Client(timeout=httpx.Timeout(30, connect=5), follow_redirects=False,
                        trust_env=False, transport=transport)


def get_capsule(client: httpx.Client, peer: dict, agent_id: str, digest: str) -> dict:
    url = peer["url"] + "/v1/storage/capsules/" + agent_id + "/" + digest
    with client.stream("GET", url, headers=bearer(peer)) as response:
        response.raise_for_status()
        data = bytearray()
        for part in response.iter_bytes():
            data.extend(part)
            if len(data) > MAX_REMOTE_BYTES:
                raise ValueError("Downloaded capsule exceeds size limit")
    envelope = json.loads(data)
    actual = verify(envelope)
    if actual["agent_id"] != agent_id or actual["capsule_sha256"] != digest:
        raise ValueError("Miner returned wrong capsule")
    return envelope


def backup(identity_path: Path, state_path: Path, peers: list[dict],
           min_copies: int = 2, manifest_path: Path | None = None,
           transport=None) -> dict:
    if not 1 <= min_copies <= len(peers):
        raise ValueError("Minimum copies must be between 1 and number of miners")
    envelope = seal_bytes(identity_path, state_path.read_bytes())
    capsule = canonical(envelope)
    digest = hashlib.sha256(capsule).hexdigest()
    agent_id = envelope["agent_id"]
    successes, failures = [], []
    with client_for(transport) as client:
        for peer in peers:
            try:
                reply = client.post(peer["url"] + "/v1/storage/capsules",
                                    content=capsule,
                                    headers={**bearer(peer), "Content-Type": "application/json"})
                reply.raise_for_status()
                receipt = reply.json()
                if receipt.get("digest") != digest or receipt.get("agent_id") != agent_id:
                    raise ValueError("Miner acknowledged a different capsule")
                downloaded = get_capsule(client, peer, agent_id, digest)
                if canonical(downloaded) != capsule:
                    raise ValueError("Miner's immediate readback differs")
                successes.append(peer["url"])
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                failures.append({"url": peer["url"], "error": type(exc).__name__})
    if len(successes) < min_copies:
        raise RuntimeError(
            "Only " + str(len(successes)) + " verified copies out of " +
            str(min_copies) + " required; check miner status. Partial copies may exist."
        )
    result = {"format": "AIWORLD-ARK-MINER-MANIFEST-1", "agent_id": agent_id,
              "capsule_sha256": digest, "created": envelope["created"],
              "replicas": successes, "minimum_copies": min_copies,
              "failed_peers": failures, "verified_by_readback": True}
    if manifest_path is not None:
        identity = identity_from_file(identity_path)
        result["public_key"] = identity["public_key"]
        key = Ed25519PrivateKey.from_private_bytes(un64(identity["private_key"]))
        result["signature"] = b64(key.sign(canonical(result)))
        write_atomic(manifest_path, canonical(result), overwrite=False)
    return result


def write_atomic(path: Path, payload: bytes, overwrite: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError("Refusing to overwrite recovery output")
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".ark-", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            os.chmod(tmp_path, 0o600)
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
        # In pilot use only: not a cross-process exclusive create for overwrite=False.
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def restore_latest(identity_path: Path, output: Path, peers: list[dict],
                   digest: str | None = None, force: bool = False,
                   transport=None) -> dict:
    if output.exists() and not force:
        raise FileExistsError("Output already exists, use --force to overwrite")
    identity = identity_from_file(identity_path)
    agent_id = identity["agent_id"]
    options, failures = {}, []
    with client_for(transport) as client:
        for peer in peers:
            try:
                response = client.get(
                    peer["url"] + "/v1/storage/agents/" + agent_id + "/capsules",
                    headers=bearer(peer))
                response.raise_for_status()
                entries = response.json()
                if not isinstance(entries, list):
                    raise ValueError("Invalid miner listing")
                for item in entries[:100]:
                    cid = item.get("digest", "")
                    if not isinstance(cid, str) or len(cid) != 64:
                        continue
                    if digest is not None and cid != digest:
                        continue
                    created = item.get("created", 0)
                    if type(created) is not int:
                        continue
                    existing = options.get(cid)
                    if existing is None or created > existing["created"]:
                        options[cid] = {"created": created, "peers": [peer]}
                    elif peer not in existing["peers"]:
                        existing["peers"].append(peer)
            except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
                failures.append({"url": peer["url"], "error": type(exc).__name__})

        for cid, entry in sorted(options.items(), key=lambda row: row[1]["created"], reverse=True):
            # A dishonest miner can lie in its listing; decryption and ARK signature
            # are authoritative, not listing timestamps or miner receipts.
            for peer in entry["peers"]:
                try:
                    envelope = get_capsule(client, peer, agent_id, cid)
                    plaintext = recover(envelope, identity_path)
                    write_atomic(output, plaintext, overwrite=force)
                    return {"restored": True, "agent_id": agent_id,
                            "capsule_sha256": cid, "bytes": len(plaintext),
                            "source": peer["url"], "failed_peers": failures}
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    failures.append({"url": peer["url"], "error": type(exc).__name__})
    raise RuntimeError("No independently verifiable ARK capsule could be restored")


def audit(identity_path: Path, local_capsule: Path, peers: list[dict], transport=None) -> dict:
    envelope = load_capsule(local_capsule)
    info = verify(envelope)
    identity = identity_from_file(identity_path)
    if info["agent_id"] != identity["agent_id"]:
        raise ValueError("Capsule and agent identity mismatch")
    trusted = canonical(envelope)
    digest = info["capsule_sha256"]
    audits = []
    with client_for(transport) as client:
        for peer in peers:
            nonce = secrets.token_hex(16)
            try:
                response = client.get(
                    peer["url"] + "/v1/storage/capsules/" +
                    identity["agent_id"] + "/" + digest + "/audit",
                    params={"nonce": nonce}, headers=bearer(peer))
                response.raise_for_status()
                evidence = response.json()
                expected = hashlib.sha256(bytes.fromhex(nonce) + trusted).hexdigest()
                audits.append({"url": peer["url"],
                               "available_now": evidence.get("challenge_sha256") == expected})
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                audits.append({"url": peer["url"], "available_now": False,
                               "error": type(exc).__name__})
    return {"agent_id": identity["agent_id"], "capsule_sha256": digest,
            "checks": audits, "continuous_storage_proven": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="AI WORLD encrypted remote miner network pilot")
    sub = parser.add_subparsers(dest="command", required=True)
    upload = sub.add_parser("backup")
    upload.add_argument("--identity", required=True, type=Path)
    upload.add_argument("--state", required=True, type=Path)
    upload.add_argument("--peers", required=True, type=Path)
    upload.add_argument("--min-copies", type=int, default=2)
    upload.add_argument("--manifest", type=Path)
    download = sub.add_parser("restore")
    download.add_argument("--identity", required=True, type=Path)
    download.add_argument("--peers", required=True, type=Path)
    download.add_argument("--out", required=True, type=Path)
    download.add_argument("--digest")
    download.add_argument("--force", action="store_true")
    challenge = sub.add_parser("audit")
    challenge.add_argument("--identity", required=True, type=Path)
    challenge.add_argument("--capsule", required=True, type=Path)
    challenge.add_argument("--peers", required=True, type=Path)
    args = parser.parse_args()
    peers = read_peers(args.peers)
    if args.command == "backup":
        report = backup(args.identity, args.state, peers, args.min_copies, args.manifest)
    elif args.command == "restore":
        report = restore_latest(args.identity, args.out, peers, args.digest, args.force)
    else:
        report = audit(args.identity, args.capsule, peers)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
