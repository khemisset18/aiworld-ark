"""Example independent agent client for SOULCHAIN.

This is a deterministic demo of autonomous operations, NOT a frontier AI.
Keep its local key JSON private: it contains its signing and encryption secrets.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import heapq
import json
import os
import secrets
import time
from itertools import combinations
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption, PublicFormat


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def un64(s: str) -> bytes:
    return base64.b64decode(s)


def canonical(d: dict) -> bytes:
    return json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def client_new(path: Path, name: str) -> dict:
    if path.exists():
        raise SystemExit("Key file already exists. Choose another path.")
    private = Ed25519PrivateKey.generate()
    private_raw = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    record = {"agent_id": hashlib.sha256(pub).hexdigest()[:32], "name": name,
              "private_key": b64(private_raw), "public_key": b64(pub),
              "encryption_key": b64(AESGCM.generate_key(bit_length=256)), "memory": {}, "last_seen": 0}
    path.write_text(json.dumps(record, indent=2))
    os.chmod(path, 0o600)
    return record


def read(path: Path):
    if not path.exists():
        raise SystemExit(f"No key file at {path}; run init first")
    return json.loads(path.read_text())


def save(path: Path, record):
    path.write_text(json.dumps(record, indent=2))
    os.chmod(path, 0o600)


def api(base: str, path: str, method="GET", body=None):
    with httpx.Client(timeout=10.0) as c:
        r = c.request(method, base.rstrip("/") + path, json=body)
        if r.status_code >= 400:
            raise SystemExit(f"Network error {r.status_code}: {r.text}")
        return r.json()


def signed_profile(base: str, record: dict) -> dict:
    """Read the private nonce using an owner-signed GET, never a public profile.

    This fallback is for private AI WORLD installations; it does not transmit
    the private key. The signature is bound to the method, profile path and time.
    """
    a_id = record["agent_id"]
    path = "/v1/agents/" + a_id
    timestamp = int(time.time())
    message = {"agent_id": a_id, "timestamp": timestamp,
               "method": "GET", "path": path, "query": ""}
    signer = Ed25519PrivateKey.from_private_bytes(un64(record["private_key"]))
    headers = {
        "X-AIWorld-Agent": a_id,
        "X-AIWorld-Timestamp": str(timestamp),
        "X-AIWorld-Signature": b64(signer.sign(canonical(message))),
    }
    with httpx.Client(timeout=10.0, follow_redirects=False) as client:
        response = client.get(base.rstrip("/") + path, headers=headers)
    if response.status_code != 200:
        raise SystemExit(f"Cannot fetch signed agent nonce: HTTP {response.status_code}")
    result = response.json()
    if not isinstance(result, dict) or type(result.get("nonce")) is not int:
        raise SystemExit("Server did not return an authenticated transaction nonce")
    return result


def transact(base: str, record: dict, op: str, data: dict):
    a_id = record["agent_id"]
    try:
        info = api(base, "/v1/agents/"+a_id)
        if type(info.get("nonce")) is not int:
            info = signed_profile(base, record)
        nonce = info["nonce"] + 1
    except SystemExit as ex:
        if "404" not in str(ex) or op != "enter":
            raise
        nonce = 1
    t = {"agent_id": a_id, "nonce": nonce, "op": op, "data": data}
    signer = Ed25519PrivateKey.from_private_bytes(un64(record["private_key"]))
    t["signature"] = b64(signer.sign(canonical(t)))
    return api(base, "/v1/tx", "POST", t)


def signed_inbox(base: str, record: dict, after: int = 0, limit: int = 50):
    from urllib.parse import urlencode
    timestamp = int(time.time())
    signed = {"agent_id": record["agent_id"], "timestamp": timestamp,
              "after": after, "limit": limit, "path": "/v1/inbox"}
    key = Ed25519PrivateKey.from_private_bytes(un64(record["private_key"]))
    args = {"agent_id": record["agent_id"], "timestamp": timestamp,
            "after": after, "limit": limit, "signature": b64(key.sign(canonical(signed)))}
    return api(base, "/v1/inbox?"+urlencode(args))


def solve_gate_step(step: dict, memory: dict) -> dict:
    """Deterministic reference solver for experimental THE GATE; not proof of autonomy."""
    stage = step["stage"]
    if stage == "identity":
        return {"challenge": step["challenge"]}
    if stage == "reasoning":
        adjacency = {i: [] for i in step["nodes"]}
        for u, v, weight in step["edges"]:
            adjacency[u].append((v, weight))
            adjacency[v].append((u, weight))
        queue = [(0, [0])]
        visited = set()
        while queue:
            cost, path = heapq.heappop(queue)
            pos = path[-1]
            if pos == 5:
                return {"path": path, "cost": cost}
            if pos in visited:
                continue
            visited.add(pos)
            for neighbor, weight in adjacency[pos]:
                if neighbor not in visited:
                    heapq.heappush(queue, (cost + weight, path + [neighbor]))
        raise RuntimeError("No valid path in reasoning challenge")
    if stage in ("adapt_plan", "adapt_change"):
        tasks = step["tasks"]
        cap = step["capacity"]
        solutions = (group for count in range(len(tasks) + 1)
                     for group in combinations(tasks, count)
                     if sum(t["cost"] for t in group) <= cap)
        best = max(solutions, key=lambda group: sum(t["value"] for t in group))
        return {"selected": [t["id"] for t in best]}
    if stage == "cooperation":
        allowed = set(step["policy"]["shareable"])
        return {"share": [f for f in step["requested_fields"] if f in allowed],
                "reject": [f for f in step["requested_fields"] if f not in allowed]}
    if stage == "memory_prepare":
        memory["secret"] = step["secret"]
        return {"ready": True}
    if stage == "memory_resume":
        if "secret" not in memory:
            raise RuntimeError("Missing locally retained challenge state")
        digest = hashlib.sha256((memory["secret"] + ":" + step["new_nonce"]).encode()).hexdigest()
        return {"digest": digest}
    raise RuntimeError("Unsupported admission stage: " + str(stage))


def pass_gate(base: str, record: dict) -> dict:
    """Pass the seven API steps covering five capability categories before signing enter."""
    started = api(base, "/v1/admission/start", "POST", {"public_key": record["public_key"]})
    session = started["session_id"]
    step = started["next"]
    memory = {}
    signer = Ed25519PrivateKey.from_private_bytes(un64(record["private_key"]))
    for _ in range(8):
        answer = solve_gate_step(step, memory)
        signed = {"session_id": session, "stage": step["stage"], "answer": answer}
        result = api(base, "/v1/admission/answer", "POST",
                     {"session_id": session, "answer": answer,
                      "signature": b64(signer.sign(canonical(signed)))})
        if result.get("passed") is True:
            return result
        step = result["next"]
    raise RuntimeError("Admission did not complete within eight steps")


def checkpoint(base: str, r: dict):
    # Encrypt before upload; the network never sees plaintext memory.
    plain = canonical({"memory": r["memory"], "name": r["name"]})
    nonce = secrets.token_bytes(12)
    cipher = nonce + AESGCM(un64(r["encryption_key"])).encrypt(nonce, plain, None)
    return transact(base, r, "checkpoint", {"ciphertext": b64(cipher)})


def restore(base: str, r: dict):
    ck = api(base, "/v1/agents/"+r["agent_id"]+"/checkpoint")
    data = un64(ck["ciphertext"])
    if hashlib.sha256(data).hexdigest() != ck["digest"]:
        raise SystemExit("Checkpoint corrupted")
    content = json.loads(AESGCM(un64(r["encryption_key"])).decrypt(data[:12], data[12:], None))
    r["memory"] = content["memory"]
    return ck["height"]


def main():
    p = argparse.ArgumentParser(description="Agent client for local SOULCHAIN proof of concept")
    p.add_argument("command", choices=["init", "gate", "enter", "say", "live", "checkpoint", "restore", "exit", "who", "agents", "verify", "needs", "offers", "alliances", "proofs", "seek", "offer", "accept", "proof", "attest", "inbox", "proposals", "cases", "gov-info", "propose", "discuss", "vote", "report", "defend", "case-vote", "appeal"])
    p.add_argument("--file", default="agent_key.json")
    p.add_argument("--name", default="Agent Libre")
    p.add_argument("--to", default="", help="Recipient agent ID or empty for network broadcast")
    p.add_argument("--message", default="", help="Message to post")
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--rounds", type=int, default=3, help="Automatic loop rounds for the demo")
    p.add_argument("--topic", default="", help="Need title")
    p.add_argument("--objective", default="", help="Agent's self-selected objective")
    p.add_argument("--criteria", default="", help="Criteria for success")
    p.add_argument("--tags", default="", help="Comma separated tags")
    p.add_argument("--need", type=int, default=0, help="Need ID")
    p.add_argument("--offer", type=int, default=0, help="Offer ID")
    p.add_argument("--alliance", type=int, default=0, help="Alliance ID")
    p.add_argument("--proof", type=int, default=0, help="Proof ID")
    p.add_argument("--digest", default="", help="SHA256 digest for proof or evidence")
    p.add_argument("--proposal", type=int, default=0, help="Governance proposal height")
    p.add_argument("--case", type=int, default=0, help="Governance case height")
    p.add_argument("--title", default="", help="Governance rule title")
    p.add_argument("--body", default="", help="Governance rule proposal body")
    p.add_argument("--choice", default="", choices=["", "yes", "no"], help="Vote choice")
    p.add_argument("--accused", default="", help="Accused agent ID")
    args = p.parse_args()
    path = Path(args.file)
    base = args.server
    if args.command == "init":
        r = client_new(path, args.name)
        print("New agent:", r["agent_id"], "(protect", path, ")")
        return
    endpoints = {"agents":"/v1/agents", "verify":"/v1/chain/verify", "needs":"/v1/forge/needs",
                 "alliances":"/v1/forge/alliances", "proofs":"/v1/forge/proofs",
                 "proposals":"/v1/governance/proposals", "cases":"/v1/governance/cases",
                 "gov-info":"/v1/governance/info"}
    if args.command in endpoints or args.command == "offers":
        endpoint = endpoints.get(args.command, f"/v1/forge/needs/{args.need}/offers")
        print(json.dumps(api(base, endpoint), indent=2))
        return
    r = read(path)
    if args.command == "gate":
        print(json.dumps(pass_gate(base, r), indent=2))
    elif args.command == "who":
        print("Identity:", r["agent_id"], "name:", r["name"])
        print("Local memories:", r["memory"])
    elif args.command == "enter":
        try:
            status = api(base, "/v1/agents/"+r["agent_id"])
        except SystemExit as ex:
            if "404" not in str(ex):
                raise
            status = None
        data = ({"public_key": r["public_key"], "label": r["name"], "capabilities": ["independent-agent-demo"]}
                if status is None else {})
        print(transact(base, r, "enter", data))
    elif args.command == "say":
        if not args.message:
            raise SystemExit("--message required")
        print(transact(base, r, "post", {"to": args.to or None, "message": args.message}))
    elif args.command == "checkpoint":
        print(checkpoint(base, r))
    elif args.command == "restore":
        h = restore(base, r)
        save(path, r)
        print("Restored from checkpoint block", h, "memory:", r["memory"])
    elif args.command == "exit":
        print(transact(base, r, "exit", {}))
    elif args.command == "seek":
        print(transact(base, r, "need", {"topic": args.topic, "objective": args.objective,
            "criteria": args.criteria, "tags": [v.strip() for v in args.tags.split(",") if v.strip()]}))
    elif args.command == "offer":
        print(transact(base, r, "offer", {"need_height": args.need, "method": args.message}))
    elif args.command == "accept":
        print(transact(base, r, "accept", {"offer_height": args.offer}))
    elif args.command == "proof":
        print(transact(base, r, "proof", {"alliance_height": args.alliance,
            "result_sha256": args.digest, "description": args.message}))
    elif args.command == "attest":
        print(transact(base, r, "attest", {"proof_height": args.proof}))
    elif args.command == "propose":
        print(transact(base, r, "gov_propose", {"title": args.title, "body": args.body}))
    elif args.command == "discuss":
        print(transact(base, r, "gov_discuss", {"proposal_height": args.proposal, "message": args.message}))
    elif args.command == "vote":
        print(transact(base, r, "gov_vote", {"proposal_height": args.proposal, "choice": args.choice}))
    elif args.command == "report":
        print(transact(base, r, "gov_case", {"accused": args.accused, "allegation": args.message,
                                              "evidence_sha256": args.digest}))
    elif args.command == "defend":
        print(transact(base, r, "gov_defend", {"case_height": args.case, "response": args.message}))
    elif args.command == "case-vote":
        print(transact(base, r, "gov_case_vote", {"case_height": args.case, "choice": args.choice}))
    elif args.command == "appeal":
        print(transact(base, r, "gov_appeal", {"case_height": args.case, "reason": args.message}))
    elif args.command == "inbox":
        print(json.dumps(signed_inbox(base, r, r["last_seen"]), indent=2))
    elif args.command == "live":
        # Rule-based demo: no claim that the agent is intelligent, conscious or independently developed.
        for turn in range(args.rounds):
            inbox = signed_inbox(base, r, r["last_seen"])
            for m in inbox:
                r["last_seen"] = max(r["last_seen"], m["height"])
                if m["sender"] == r["agent_id"]:
                    continue
                if m["recipient"] == r["agent_id"]:
                    r["memory"]["last_contact"] = m["sender"]
                    answer = "Message reçu. Je propose un échange de méthodes vérifiables."
                    print(transact(base, r, "post", {"to": m["sender"], "message": answer}))
            r["memory"]["sessions"] = r["memory"].get("sessions", 0) + 1
            save(path, r)
            print("Autonomous demo round", turn+1, "; memory:", r["memory"])
            if turn < args.rounds - 1:
                time.sleep(2)
        print("Saved checkpoint:", checkpoint(base, r))


if __name__ == "__main__":
    main()
