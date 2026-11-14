"""Tests for voluntary resource disclosure and bounded CPU execution.

No physical NVIDIA GPU or Ollama daemon is required in CI. A dedicated
two-machine pilot is still necessary before any real-world readiness claim.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from compute_resources import inspect_resources, nvidia_gpus, public_resources, run_limited
from test_forge import new_agent, do
from test_compute import c, _signed_read  # isolated FastAPI + signed reads


def test_bounded_real_cpu_hash_and_primes():
    from compute_worker import calculate
    expected = calculate("hash_chain", {"text": "AI WORLD", "rounds": 10})
    assert run_limited("hash_chain", {"text": "AI WORLD", "rounds": 10},
                       timeout_seconds=15, max_memory_mb=512) == expected
    assert run_limited("prime_count", {"start": 2, "end": 30},
                       timeout_seconds=15, max_memory_mb=512) == {"count": 10}


def test_unapproved_inference_never_starts_a_worker():
    with pytest.raises(ValueError, match="not approved"):
        run_limited("inference", {"model": "small:latest", "prompt": "hello", "max_tokens": 16},
                    approved_models={"trusted:model"})
    with pytest.raises(ValueError, match="Unsupported"):
        run_limited("arbitrary_code", {"code": "__import__('os').system('echo no')"})
    with pytest.raises(ValueError):
        run_limited("hash_chain", {"text": "hi", "rounds": 1}, max_memory_mb=99999)
    with pytest.raises(ValueError):
        run_limited("hash_chain", {"text": "hi", "rounds": 1}, timeout_seconds=0)


def test_gpu_inventory_is_local_and_bounded(monkeypatch):
    import compute_resources as resources
    monkeypatch.setattr(resources.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    commands = []

    def fake_run(args, **kwargs):
        commands.append((args, kwargs))
        return SimpleNamespace(returncode=0,
                               stdout="Example NVIDIA GPU, 8192, 6024\nBad GPU, no-number, 1\n")

    monkeypatch.setattr(resources.subprocess, "run", fake_run)
    gpus = nvidia_gpus()
    assert len(gpus) == 1
    assert gpus[0]["total_vram_mb"] == 8192
    assert gpus[0]["free_vram_mb"] == 6024
    assert commands[0][0][0] == "/usr/bin/nvidia-smi"
    assert "shell" not in commands[0][1]
    assert commands[0][1]["timeout"] == 3

    snapshot = {"logical_cpu_cores": 8, "memory_available_mb": 10000,
                "nvidia_gpus": gpus}
    assert public_resources(snapshot) == {
        "logical_cpu_cores": 8, "memory_available_mb": 10000,
        "nvidia_gpu_count": 1, "nvidia_vram_total_mb": 8192
    }
    assert "Example" not in json.dumps(public_resources(snapshot))


def test_no_nvidia_hardware_does_not_claim_a_gpu(monkeypatch):
    import compute_resources as resources
    monkeypatch.setattr(resources.shutil, "which", lambda _: None)
    assert nvidia_gpus() == []
    snapshot = inspect_resources()
    assert snapshot["gpu_detection"] == "not_detected"
    assert public_resources(snapshot)["nvidia_gpu_count"] == 0


def test_worker_signed_cpu_and_gpu_resources_migration(c):
    provider_key, provider = new_agent(c, "Volunteer")
    client_key, client = new_agent(c, "Requester")
    resources = {
        "logical_cpu_cores": 8, "memory_available_mb": 4096,
        "nvidia_gpu_count": 1, "nvidia_vram_total_mb": 12288
    }
    limits = {"max_wall_seconds": 30, "max_memory_mb": 512}
    offered = do(c, provider_key, provider, 2, "compute_offer", {
        "kinds": ["hash_chain", "inference"], "models": ["smollm2:135m"],
        "max_jobs": 2, "ttl_seconds": 3600,
        "resources": resources, "limits": limits
    })
    assert offered.status_code == 200, offered.text
    height = offered.json()["height"]
    advertised = c.get("/v1/compute/offers").json()[0]
    assert advertised["resources"] == resources
    assert advertised["limits"] == limits
    assert advertised["hardware_unverified"] is True
    params = {"capacity_height": height, "kind": "hash_chain",
              "params": {"text": "123", "rounds": 10}}
    task = do(c, client_key, client, 2, "compute_request", params)
    assert task.status_code == 200, task.text
    from test_compute import _signed_read
    assigned = _signed_read(c, provider_key, provider, "/v1/compute/assigned",
                            capacity_height=height, status="queued", limit=50)
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()[0]["limits"] == limits


@pytest.mark.parametrize("resources", [
    {"logical_cpu_cores": 0, "memory_available_mb": None, "nvidia_gpu_count": 0,
     "nvidia_vram_total_mb": 0},
    {"logical_cpu_cores": True, "memory_available_mb": None, "nvidia_gpu_count": 0,
     "nvidia_vram_total_mb": 0},
    {"logical_cpu_cores": 4, "memory_available_mb": -10, "nvidia_gpu_count": 0,
     "nvidia_vram_total_mb": 0},
    {"logical_cpu_cores": 4, "memory_available_mb": None, "nvidia_gpu_count": 0,
     "nvidia_vram_total_mb": 12000},
    {"logical_cpu_cores": 4, "memory_available_mb": None, "nvidia_gpu_count": 1,
     "nvidia_vram_total_mb": -1}
])
def test_invalid_resource_claims_are_rejected(c, resources):
    key, agent = new_agent(c, "Claim")
    response = do(c, key, agent, 2, "compute_offer", {
        "kinds": ["hash_chain"], "max_jobs": 1, "ttl_seconds": 3600,
        "resources": resources
    })
    assert response.status_code == 400, response.text


@pytest.mark.parametrize("limits", [
    {"max_wall_seconds": 0, "max_memory_mb": 512},
    {"max_wall_seconds": 121, "max_memory_mb": 512},
    {"max_wall_seconds": True, "max_memory_mb": 512},
    {"max_wall_seconds": 15, "max_memory_mb": 128},
    {"max_wall_seconds": 15, "max_memory_mb": 9999},
])
def test_invalid_volunteer_limits_are_rejected(c, limits):
    key, agent = new_agent(c, "Limits")
    response = do(c, key, agent, 2, "compute_offer", {
        "kinds": ["hash_chain"], "max_jobs": 1, "ttl_seconds": 3600,
        "limits": limits
    })
    assert response.status_code == 400, response.text


def test_real_signed_cpu_exchange_respects_volunteer_local_limits(c, monkeypatch):
    """Coordinator and two agent identities execute the actual worker protocol."""
    import agent_cli
    import compute_worker
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, NoEncryption
    )
    from test_forge import b64
    provider_key, provider = new_agent(c, "CPU provider")
    client_key, client = new_agent(c, "CPU requester")
    offer = do(c, provider_key, provider, 2, "compute_offer", {
        "kinds": ["hash_chain"], "max_jobs": 1, "ttl_seconds": 3600,
        "limits": {"max_wall_seconds": 30, "max_memory_mb": 2048}
    })
    assert offer.status_code == 200
    height = offer.json()["height"]
    request = do(c, client_key, client, 2, "compute_request", {
        "capacity_height": height, "kind": "hash_chain",
        "params": {"text": "test signed CPU", "rounds": 64}
    })
    assert request.status_code == 200
    job_height = request.json()["height"]

    def local_api(_base, path, method="GET", body=None):
        response = c.request(method, path, json=body)
        if response.status_code >= 400:
            raise SystemExit(str(response.status_code) + " " + response.text)
        return response.json()

    monkeypatch.setattr(agent_cli, "api", local_api)
    monkeypatch.setattr(compute_worker, "api", local_api)
    account = {
        "agent_id": provider,
        "private_key": b64(provider_key.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        ))
    }
    calls = []
    actual_limited = compute_worker.run_limited

    def check_limits(kind, params, approved_models, timeout_seconds, max_memory_mb):
        calls.append((timeout_seconds, max_memory_mb))
        return actual_limited(kind, params, approved_models, timeout_seconds, max_memory_mb)

    monkeypatch.setattr(compute_worker, "run_limited", check_limits)
    count = compute_worker.run_once("local", account, height,
                                    max_wall_seconds=15, max_memory_mb=512)
    assert count == 1
    assert calls == [(15, 512)]  # local limits override looser published limits
    status = c.get(f"/v1/compute/jobs/{job_height}").json()
    assert status["status"] == "completed_unverified"
    task = _signed_read(c, client_key, client,
                        f"/v1/compute/jobs/{job_height}/private")
    assert task.status_code == 200
    assert task.json()["result"] == compute_worker.calculate(
        "hash_chain", {"text": "test signed CPU", "rounds": 64}
    )
