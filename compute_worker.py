"""Voluntary fixed-function CPU worker. This program NEVER runs received code."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path
from urllib.parse import urlencode
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from agent_cli import api, read, transact, canonical, b64, un64
from compute_resources import inspect_resources, public_resources, run_limited


def calculate(kind: str, params: dict) -> dict:
    # Defensive validation even though the coordinator validates submissions.
    from compute_pool import validate_params
    validate_params(kind, params)
    if kind == "hash_chain":
        digest = params["text"].encode("utf-8")
        for _ in range(params["rounds"]):
            digest = hashlib.sha256(digest).digest()
        return {"sha256": digest.hex()}
    if kind == "prime_count":
        def prime(n):
            if n < 2:
                return False
            for divisor in range(2, math.isqrt(n) + 1):
                if n % divisor == 0:
                    return False
            return True
        return {"count": sum(prime(i) for i in range(params["start"], params["end"] + 1))}
    raise ValueError("Unsupported work kind")


def signed_compute_read(base: str, account: dict, path: str, scope: dict | None = None):
    """Authenticate reads of private prompts/results without revealing the key."""
    scope = scope or {}
    timestamp = int(time.time())
    message = {"agent_id": account["agent_id"], "timestamp": timestamp, "path": path, **scope}
    key = Ed25519PrivateKey.from_private_bytes(un64(account["private_key"]))
    args = {**scope, "agent_id": account["agent_id"], "timestamp": timestamp,
            "signature": b64(key.sign(canonical(message)))}
    return api(base, path + "?" + urlencode(args))


def assigned(base: str, account: dict, offer_height: int, status: str = "queued"):
    return signed_compute_read(base, account, "/v1/compute/assigned",
                               {"capacity_height": offer_height, "status": status, "limit": 50})


def private_job(base: str, account: dict, height: int):
    return signed_compute_read(base, account, f"/v1/compute/jobs/{height}/private")


def run_once(base: str, account: dict, offer_height: int, approved_models: set[str] | None = None,
             max_wall_seconds: int = 90, max_memory_mb: int = 512) -> int:
    # The same provider identity may recover its own stale claims after a restart.
    for stale in assigned(base, account, offer_height, "claimed"):
        deadline = (stale["lease_expires_at"] if stale["lease_expires_at"] is not None
                    else stale["updated_at"] + 180)
        if deadline <= int(time.time()):
            transact(base, account, "compute_recover", {"job_height": stale["height"]})
    jobs = assigned(base, account, offer_height)
    for job in jobs:
        # Other workers' jobs must not be claimed by this identity.
        if job["worker"] != account["agent_id"]:
            continue
        transact(base, account, "compute_claim", {"job_height": job["height"]})
        try:
            # Both voluntary local limits and signed offer limits apply.
            # The requester has no power to increase these bounds.
            published_limits = job.get("limits", {})
            allowed_wall = min(max_wall_seconds, published_limits.get("max_wall_seconds", max_wall_seconds))
            allowed_memory = min(max_memory_mb, published_limits.get("max_memory_mb", max_memory_mb))
            result = run_limited(
                job["kind"], job["params"], approved_models or set(),
                timeout_seconds=allowed_wall, max_memory_mb=allowed_memory
            )
        except (ValueError, RuntimeError, TimeoutError, OSError, KeyError) as exc:
            # No raw exception or prompt is sent to the API; do not leave the job claimed forever.
            transact(base, account, "compute_fail", {"job_height": job["height"]})
            print(json.dumps({"job": job["height"], "status": "failed_by_worker", "reason": type(exc).__name__}))
            return 1
        transact(base, account, "compute_complete", {"job_height": job["height"], "result": result})
        print(json.dumps({"job": job["height"], "status": "completed_unverified", "result": result}))
        return 1
    return 0


def main():
    p = argparse.ArgumentParser(description="AI WORLD compute commons — voluntary CPU lending, 0 SOL")
    p.add_argument("command", choices=["offer", "withdraw", "request", "authorize", "serve", "verify", "recover", "offers", "jobs", "inventory"])
    p.add_argument("--identity", default="agent_key.json")
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--offer", type=int, default=0)
    p.add_argument("--job", type=int, default=0)
    p.add_argument("--kinds", default="hash_chain,prime_count")
    p.add_argument("--models", default="", help="Comma-separated, explicitly approved local Ollama models")
    p.add_argument("--max-jobs", type=int, default=3)
    p.add_argument("--max-wall-seconds", type=int, default=90,
                   help="Volunteer-imposed per-task limit: 5..120 seconds")
    p.add_argument("--max-memory-mb", type=int, default=512,
                   help="Volunteer subprocess memory ceiling: 256..4096 MiB")
    p.add_argument("--require-gpu", action="store_true",
                   help="Refuse volunteering inference if no NVIDIA GPU is detected; acceleration is not guaranteed")
    p.add_argument("--mode", choices=["free", "paid"], default="free")
    p.add_argument("--price-lamports", type=int, default=0, help="Gross price; no real payment collected")
    p.add_argument("--ttl", type=int, default=3600)
    p.add_argument("--kind", choices=["hash_chain", "prime_count", "inference"], default="hash_chain")
    p.add_argument("--model", default="", help="Approved local Ollama model identifier")
    p.add_argument("--max-tokens", type=int, default=64)
    p.add_argument("--text", default="AI WORLD")
    p.add_argument("--rounds", type=int, default=10000)
    p.add_argument("--start", type=int, default=2)
    p.add_argument("--end", type=int, default=10000)
    p.add_argument("--max-tasks", type=int, default=1, help="Maximum number to execute in this run")
    p.add_argument("--interval", type=int, default=5, help="Seconds between polls (serve)")
    args = p.parse_args()
    base = args.server
    if args.command == "inventory":
        print(json.dumps(inspect_resources(), indent=2)); return
    if args.max_wall_seconds < 5 or args.max_wall_seconds > 120 or args.max_memory_mb < 256 or args.max_memory_mb > 4096:
        raise SystemExit("Volunteer resource limits must be wall=5..120s, memory=256..4096 MiB")
    if args.command == "offers":
        print(json.dumps(api(base, "/v1/compute/offers"), indent=2)); return
    if args.command == "jobs":
        print(json.dumps(api(base, "/v1/compute/jobs"), indent=2)); return
    account = read(Path(args.identity))
    if args.command == "offer":
        snapshot = inspect_resources()
        if args.require_gpu and (not snapshot["nvidia_gpus"] or "inference" not in args.kinds.split(",")):
            raise SystemExit("GPU-specific offer requires both a detected NVIDIA GPU and an inference task")
        result = transact(base, account, "compute_offer", {
            "kinds": [s.strip() for s in args.kinds.split(",")],
            "models": [s.strip() for s in args.models.split(",") if s.strip()],
            "max_jobs": args.max_jobs, "ttl_seconds": args.ttl,
            "terms": {"mode": args.mode, "price_lamports": args.price_lamports},
            "resources": public_resources(snapshot),
            "limits": {"max_wall_seconds": args.max_wall_seconds, "max_memory_mb": args.max_memory_mb}})
        print("Voluntary capacity offer:", json.dumps(result)); return
    if args.command == "withdraw":
        print(transact(base, account, "compute_withdraw", {"capacity_height": args.offer})); return
    if args.command == "authorize":
        print(transact(base, account, "compute_authorize", {"job_height": args.job})); return
    if args.command == "request":
        if args.kind == "hash_chain":
            params = {"text": args.text, "rounds": args.rounds}
        elif args.kind == "prime_count":
            params = {"start": args.start, "end": args.end}
        else:
            params = {"prompt": args.text, "model": args.model, "max_tokens": args.max_tokens}
        request = {"capacity_height": args.offer, "kind": args.kind, "params": params}
        if args.price_lamports:
            request["agreed_price_lamports"] = args.price_lamports
        print(transact(base, account, "compute_request", request)); return
    if args.command == "recover":
        print(transact(base, account, "compute_recover", {"job_height": args.job}))
        return
    if args.command == "verify":
        job = private_job(base, account, args.job)
        if job["requester"] != account["agent_id"]:
            raise SystemExit("Only the requester can verify this job")
        if job["status"] != "completed_unverified":
            raise SystemExit("Job has no pending result")
        if job["kind"] == "inference":
            raise SystemExit("LLM output cannot be verified deterministically; review via signed API after independent evaluation")
        expected = calculate(job["kind"], job["params"])
        accepted = expected == job["result"]
        result = transact(base, account, "compute_review", {"job_height": args.job, "accepted": accepted})
        print("Verified locally:", accepted, "Review:", result)
        return
    if args.command == "serve":
        if args.require_gpu and not inspect_resources()["nvidia_gpus"]:
            raise SystemExit("GPU-specific serving requires a locally detected NVIDIA GPU")
        if args.max_tasks < 1 or args.max_tasks > 25 or args.interval < 0:
            raise SystemExit("Invalid limits")
        done = 0
        approved = {s.strip() for s in args.models.split(",") if s.strip()}
        print("Volunteer worker running: only fixed CPU functions or explicit local Ollama models")
        while done < args.max_tasks:
            n = run_once(base, account, args.offer, approved_models=approved,
                         max_wall_seconds=args.max_wall_seconds, max_memory_mb=args.max_memory_mb)
            done += n
            if done < args.max_tasks:
                time.sleep(args.interval)


if __name__ == "__main__":
    main()
