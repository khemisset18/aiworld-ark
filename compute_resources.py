"""Volunteer-side CPU/GPU inventory and bounded execution for AI WORLD.

Only fixed, previously validated tasks are executed. We never run code received
from agents. GPU information is advisory: Ollama runs as a separate local
process and its VRAM cannot be enforced by this Python worker.
"""
from __future__ import annotations

import multiprocessing
import os
import re
import shutil
import subprocess
from typing import Any

# Strict volunteer-selected limits, never requested by another agent.
MIN_MEMORY_MB = 256
MAX_MEMORY_MB = 4096
MIN_WALL_SECONDS = 5
MAX_WALL_SECONDS = 120


def _available_memory_mb() -> int | None:
    """Linux MemAvailable in MiB; no guessed free memory on other OSes."""
    try:
        with open("/proc/meminfo", encoding="ascii") as file:
            for line in file:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    value = int(parts[1]) // 1024
                    return value if value > 0 else None
    except (OSError, ValueError, IndexError):
        pass
    return None


def nvidia_gpus() -> list[dict[str, Any]]:
    """Best-effort local inventory, never invoke a command from the network."""
    executable = shutil.which("nvidia-smi")
    if not executable:
        return []
    try:
        result = subprocess.run(
            [executable, "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=False, timeout=3
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode or len(result.stdout) > 8192:
        return []
    entries: list[dict[str, Any]] = []
    for line in result.stdout.splitlines()[:16]:
        values = [v.strip() for v in line.split(",")]
        if len(values) != 3:
            continue
        name, total, free = values
        if not re.fullmatch(r"[ -~]{1,96}", name):
            continue
        try:
            total_mb, free_mb = int(total), int(free)
        except ValueError:
            continue
        if not (0 <= free_mb <= total_mb <= 1_000_000):
            continue
        entries.append({"name": name, "total_vram_mb": total_mb, "free_vram_mb": free_mb})
    return entries


def inspect_resources() -> dict[str, Any]:
    """Local snapshot, not a security attestation and not a reservation."""
    gpus = nvidia_gpus()
    return {
        "logical_cpu_cores": max(1, min(1024, os.cpu_count() or 1)),
        "memory_available_mb": _available_memory_mb(),
        "gpu_detection": "nvidia-smi" if gpus else "not_detected",
        "nvidia_gpus": gpus,
        "notice": "Hardware snapshot only; remote agents must not treat claims as independently verified"
    }


def public_resources(snapshot: dict) -> dict:
    """Minimize metadata exposed publicly; local GPU names are never advertised."""
    return {
        "logical_cpu_cores": snapshot["logical_cpu_cores"],
        "memory_available_mb": snapshot["memory_available_mb"],
        "nvidia_gpu_count": len(snapshot["nvidia_gpus"]),
        "nvidia_vram_total_mb": sum(x["total_vram_mb"] for x in snapshot["nvidia_gpus"]),
    }


def _child(conn, kind: str, params: dict, approved_models: set[str], max_memory_mb: int,
           timeout_seconds: int) -> None:
    try:
        if os.name != "posix":
            raise RuntimeError("Memory limiting requires a POSIX worker")
        import resource
        if not hasattr(resource, "RLIMIT_AS") or not hasattr(resource, "RLIMIT_CPU"):
            raise RuntimeError("Worker operating system lacks required resource limits")
        size = max_memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (size, size))
        resource.setrlimit(resource.RLIMIT_CPU, (timeout_seconds, timeout_seconds))
        if kind == "inference":
            from volunteer_inference import infer_local
            result = infer_local(params, approved_models, timeout=min(timeout_seconds, 90))
        else:
            from compute_worker import calculate
            result = calculate(kind, params)
        conn.send(("ok", result))
    except BaseException as exc:
        try:
            conn.send(("failed", type(exc).__name__))
        except (OSError, BrokenPipeError):
            pass
    finally:
        conn.close()


def run_limited(kind: str, params: dict, approved_models: set[str] | None = None,
                timeout_seconds: int = 120, max_memory_mb: int = 512) -> dict:
    """Run a fixed task in a bounded subprocess, never execute received code.

    Limits protect the worker's Python task process. Ollama is an independent
    local service: its CPU/VRAM use still needs OS/container controls.
    """
    if type(timeout_seconds) is not int or not MIN_WALL_SECONDS <= timeout_seconds <= MAX_WALL_SECONDS:
        raise ValueError("Volunteer wall-time limit must be between 5 and 120 seconds")
    if type(max_memory_mb) is not int or not MIN_MEMORY_MB <= max_memory_mb <= MAX_MEMORY_MB:
        raise ValueError("Volunteer memory limit must be between 256 and 4096 MiB")
    if kind not in ("hash_chain", "prime_count", "inference"):
        raise ValueError("Unsupported work kind")
    from compute_pool import validate_params
    validate_params(kind, params)
    if kind == "inference" and params["model"] not in (approved_models or set()):
        raise ValueError("Model not approved by volunteer")

    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_child, args=(child, kind, params, approved_models or set(),
                             max_memory_mb, timeout_seconds), daemon=True
    )
    try:
        process.start()
        child.close()
        process.join(timeout_seconds)
        if process.is_alive():
            process.kill()
            process.join(3)
            raise TimeoutError("Volunteer job exceeded local wall-time limit")
        if process.exitcode != 0 or not parent.poll(0.2):
            raise RuntimeError("Volunteer job terminated without a result")
        status, payload = parent.recv()
        if status != "ok":
            raise RuntimeError("Volunteer task failed: " + str(payload)[:64])
        from compute_pool import validate_result
        validate_result(kind, payload, params)
        return payload
    finally:
        if process.is_alive():
            process.kill()
            process.join(3)
        parent.close()
        child.close()
