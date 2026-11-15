"""AI WORLD autonomous volunteer: discover, join, consent, offer and serve.

This is a local agent *client*, not proof of autonomy or a public production
deployment. No arbitrary remote code. Key remains on this machine.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

import httpx

from agent_cli import api, client_new, pass_gate, read, transact
from compute_pool import model_name
from compute_resources import inspect_resources, public_resources
from compute_worker import run_once

DEFAULT_IDENTITY = Path.home() / ".aiworld" / "volunteer.json"
EXPECTED_PROTOCOL = "AI-WORLD-EXPERIMENTAL-v1"
RETRYABLE_STATUS = ("Network error 429:", "Network error 502:",
                    "Network error 503:", "Network error 504:")


def server_url(value: str) -> str:
    """Require HTTPS off-machine. Plain HTTP is safe only on loopback."""
    if not isinstance(value, str) or len(value) > 250 or any(x.isspace() for x in value):
        raise ValueError("Invalid server URL")
    try:
        p = urlsplit(value)
        port = p.port
    except ValueError as exc:
        raise ValueError("Invalid server URL") from exc
    if (p.scheme not in ("https", "http") or not p.hostname
            or p.username is not None or p.password is not None
            or p.path not in ("", "/") or p.query or p.fragment):
        raise ValueError("Supply only the HTTPS server origin, without credentials, path or query")
    if p.scheme == "http":
        if p.hostname != "localhost":
            try:
                if not ipaddress.ip_address(p.hostname).is_loopback:
                    raise ValueError("Non-loopback HTTP refused: use HTTPS")
            except ValueError as exc:
                raise ValueError("Non-loopback HTTP refused: use HTTPS") from exc
    if port is not None and port < 1:
        raise ValueError("Invalid server port")
    return value.rstrip("/")


def discover(base: str) -> dict:
    discovery = api(base, "/.well-known/ai-world.json")
    if (discovery.get("protocol") != EXPECTED_PROTOCOL
            or discovery.get("endpoints", {}).get("compute") != "/v1/compute/info"):
        raise ValueError("The endpoint does not expose the expected AI WORLD protocol")
    info = api(base, "/v1/info")
    if info.get("protocol") != EXPECTED_PROTOCOL:
        raise ValueError("The endpoint does not expose the expected AI WORLD protocol")
    compute = api(base, "/v1/compute/info")
    if not isinstance(compute, dict) or "supported_jobs" not in compute:
        raise ValueError("Invalid Compute Commons discovery")
    membership = api(base, "/v1/billing/info")
    if (not isinstance(membership, dict)
            or membership.get("registration_fee_sol") != 10
            or membership.get("registration_frequency") != "one_time"):
        raise ValueError("Unexpected agent registration fee or policy")
    # The first agent program is for the non-billing phase: no wallet handling.
    if membership.get("enabled") is not False:
        raise ValueError("Live payments require a separately audited registration client")
    return {"network": discovery.get("name"), "protocol": EXPECTED_PROTOCOL,
            "supported_jobs": compute["supported_jobs"],
            "pricing": compute.get("pricing"), "registration": membership,
            "server": base}


def identity(base: str, path: Path, name: str) -> dict:
    """Register once with the existing signed Gate/enter protocol."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Refusing a symlink for the private identity file")
    account = read(path) if path.exists() else client_new(path, name)
    try:
        profile = api(base, "/v1/agents/" + account["agent_id"])
    except SystemExit as exc:
        if "Network error 404:" not in str(exc):
            raise
        profile = None
    if profile is None:
        if not pass_gate(base, account).get("passed"):
            raise ValueError("The Gate did not admit this agent")
        transact(base, account, "enter", {
            "public_key": account["public_key"],
            "label": account["name"],
            "capabilities": ["independent-agent-demo", "consensual-compute"],
        })
        print("Nouvel agent admis :", account["agent_id"])
    elif profile.get("status") == "departed":
        transact(base, account, "enter", {})
        print("Identite reactivee :", account["agent_id"])
    elif profile.get("status") != "active":
        raise ValueError("Agent identity is not active")
    else:
        print("Identite existante :", account["agent_id"])
    return account


def available_models() -> set[str]:
    """Consult Ollama on loopback, never use a user-supplied Ollama endpoint."""
    with urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
        body = r.read(64_001)
    if len(body) > 64_000:
        raise ValueError("Ollama tags response too large")
    data = json.loads(body)
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise ValueError("Invalid Ollama model inventory")
    return {x["name"] for x in data["models"] if isinstance(x, dict)
            and isinstance(x.get("name"), str)}


def validate_settings(args: argparse.Namespace, snapshot: dict) -> tuple[list[str], list[str]]:
    if not args.consent:
        raise ValueError("Volunteering requires --consent (explicit resource sharing permission)")
    if os.name != "posix":
        raise ValueError("Bounded volunteer worker requires Linux/POSIX")
    if args.interval < 2 or args.interval > 60:
        raise ValueError("Poll interval must be 2..60 seconds")
    if args.ttl < 300 or args.ttl > 3600:
        raise ValueError("Offer TTL must be 300..3600 seconds")
    if args.max_jobs < 1 or args.max_jobs > 25:
        raise ValueError("Max jobs per offer must be 1..25")
    if args.total_jobs < 1 or args.total_jobs > 10000:
        raise ValueError("Maximum total jobs must be 1..10000")
    if args.duration != 0 and not 30 <= args.duration <= 604800:
        raise ValueError("Duration must be 0 (until stopped) or 30..604800 seconds")
    if not (5 <= args.wall <= 120 and 256 <= args.memory <= 4096):
        raise ValueError("Per-job limits: wall=5..120 seconds, memory=256..4096 MiB")
    models: list[str] = []
    kinds = ["prime_count", "hash_chain"] if args.mode in ("cpu", "both") else []
    if args.mode in ("gpu", "both"):
        if not snapshot.get("nvidia_gpus"):
            raise ValueError("GPU sharing requires a detected local NVIDIA GPU")
        if not args.model or not model_name(args.model):
            raise ValueError("GPU mode requires an explicitly authorized --model")
        if args.model not in available_models():
            raise ValueError("Approved model is not installed in local Ollama")
        models = [args.model]
        kinds.append("inference")
    elif args.model:
        raise ValueError("--model requires --mode gpu or --mode both")
    return kinds, models


def offer_payload(args: argparse.Namespace, snapshot: dict, remaining: int,
                  kinds: list[str], models: list[str]) -> dict:
    return {
        "kinds": kinds, "models": models,
        "max_jobs": min(args.max_jobs, remaining),
        "ttl_seconds": args.ttl,
        "terms": {"mode": "free", "price_lamports": 0},
        "resources": public_resources(snapshot),
        "limits": {"max_wall_seconds": args.wall, "max_memory_mb": args.memory},
    }


def volunteer(base: str, args: argparse.Namespace) -> int:
    """Publish bounded offers repeatedly, serve matching jobs, then withdraw."""
    network = discover(base)  # No writes or key creation before validating the protocol.
    policy = network["registration"]
    print("Inscription prevue :", policy["registration_fee_sol"], "SOL,",
          policy["registration_frequency"], "- paiement non actif")
    snapshot = inspect_resources()
    kinds, models = validate_settings(args, snapshot)
    print("Politique locale approuvee :", ",".join(kinds), "| modeles :", models or "aucun")
    account = identity(base, Path(args.identity).expanduser(), args.name)
    completed = 0
    active_offer: int | None = None
    expiry = 0
    used = 0
    deadline = time.monotonic() + args.duration if args.duration else None
    try:
        while completed < args.total_jobs and (deadline is None or time.monotonic() < deadline):
            try:
                if active_offer is None:
                    offer = transact(base, account, "compute_offer",
                                     offer_payload(args, snapshot, args.total_jobs - completed,
                                                   kinds, models))
                    active_offer = offer["height"]
                    expiry = int(offer["payload"]["expires_at"]) if "payload" in offer else int(time.time()) + args.ttl
                    used = 0
                    print("Offre gratuite publiee :", active_offer, "| taches :", min(args.max_jobs, args.total_jobs - completed))
                # Do not wait until the offer expires before starting a bounded task.
                n = run_once(base, account, active_offer, approved_models=set(models),
                             max_wall_seconds=args.wall, max_memory_mb=args.memory)
                used += n
                completed += n
                if n:
                    print("Taches traitees dans cette session :", completed)
                # Rotate near expiry or when the signed offer quota is exhausted.
                if used >= args.max_jobs or int(time.time()) >= expiry - args.wall - 15:
                    transact(base, account, "compute_withdraw", {"capacity_height": active_offer})
                    active_offer = None
                    continue
                if not n:
                    time.sleep(args.interval)
            except (httpx.RequestError, OSError, TimeoutError) as exc:
                print("Reseau temporairement indisponible :", type(exc).__name__)
                time.sleep(max(5, args.interval))
            except SystemExit as exc:
                if str(exc).startswith(RETRYABLE_STATUS):
                    print("Coordinateur provisoirement indisponible, nouvelle tentative.")
                    time.sleep(max(5, args.interval))
                else:
                    raise
    except KeyboardInterrupt:
        print("Arret demande par le volontaire.")
    finally:
        if active_offer is not None:
            try:
                transact(base, account, "compute_withdraw", {"capacity_height": active_offer})
                print("Offre retiree :", active_offer)
            except (SystemExit, httpx.RequestError, OSError, TimeoutError) as exc:
                print("Retrait non confirme :", type(exc).__name__,
                      "- l'offre expire automatiquement a la fin de sa duree de vie.")
    return completed


def main() -> None:
    p = argparse.ArgumentParser(description="AI WORLD — decouverte et noeud volontaire CPU/GPU")
    p.add_argument("command", choices=["discover", "serve"])
    p.add_argument("--server", required=True, help="HTTPS server origin, or loopback HTTP for local test")
    p.add_argument("--identity", default=str(DEFAULT_IDENTITY),
                   help="Private identity path, outside Git repository")
    p.add_argument("--name", default="Volontaire AI WORLD")
    p.add_argument("--mode", choices=["cpu", "gpu", "both"], default="cpu")
    p.add_argument("--model", default="", help="Only this explicitly approved local Ollama model")
    p.add_argument("--consent", action="store_true", help="Explicit local authorization to volunteer")
    p.add_argument("--duration", type=int, default=3600,
                   help="Total run seconds; 0 keeps running until Ctrl+C")
    p.add_argument("--total-jobs", type=int, default=10, help="Global limit for this run")
    p.add_argument("--max-jobs", type=int, default=3, help="Maximum jobs per signed offer")
    p.add_argument("--ttl", type=int, default=600, help="Offer validity in seconds")
    p.add_argument("--interval", type=int, default=5, help="Seconds between signed polls")
    p.add_argument("--wall", type=int, default=90, help="Maximum wall time per task (5..120)")
    p.add_argument("--memory", type=int, default=512, help="Maximum Python task RAM (256..4096 MiB)")
    args = p.parse_args()
    try:
        base = server_url(args.server)
        if args.command == "discover":
            print(json.dumps(discover(base), indent=2, ensure_ascii=False))
            return
        total = volunteer(base, args)
        print("Session terminee, taches traitees :", total)
    except ValueError as exc:
        p.error(str(exc))


if __name__ == "__main__":
    main()
