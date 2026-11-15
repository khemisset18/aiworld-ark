"""Offline checks for automatic voluntary joining, local consent, and bounded service.

No real cloud, GPU, Ollama or external Solana transfer required.
"""
from __future__ import annotations

import argparse

import pytest

import aiworld_node as node


def args(**override):
    config = dict(
        server="http://127.0.0.1:8000", identity="~/.aiworld/volunteer.json",
        name="Volontaire AI WORLD", consent=True, mode="cpu", model="",
        duration=3600, total_jobs=1, max_jobs=1, ttl=600, interval=5,
        wall=30, memory=512,
    )
    config.update(override)
    return argparse.Namespace(**config)


def snapshot(gpu=False):
    return {
        "logical_cpu_cores": 4, "memory_available_mb": 1024,
        "nvidia_gpus": [{"name": "NVIDIA", "total_vram_mb": 4096,
                         "free_vram_mb": 4096}] if gpu else [],
        "gpu_detection": "nvidia-smi" if gpu else "not_detected",
    }


@pytest.mark.parametrize("raw", [
    "http://example.com", "http://192.168.1.20:8000",
    "http://8.8.8.8", "ftp://example.com",
    "https://user:pass@example.com", "https://example.com/private",
    "https://example.com?token=secret", "http://example.com:80",
    "https://example.com/#x",
])
def test_public_server_must_use_https(raw):
    with pytest.raises(ValueError):
        node.server_url(raw)


def test_https_or_loopback_are_valid_origins():
    assert node.server_url("https://aiworld.example/") == "https://aiworld.example"
    assert node.server_url("http://localhost:8000/") == "http://localhost:8000"
    assert node.server_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000"


def test_discovery_read_only_and_protocol_checked(monkeypatch):
    paths = []
    def api(base, path):
        paths.append(path)
        if path == "/.well-known/ai-world.json":
            return {"name": "AI WORLD", "protocol": node.EXPECTED_PROTOCOL,
                    "endpoints": {"compute": "/v1/compute/info"}}
        if path == "/v1/info":
            return {"protocol": node.EXPECTED_PROTOCOL}
        if path == "/v1/compute/info":
            return {"supported_jobs": ["prime_count", "inference"], "pricing": "free"}
        if path == "/v1/billing/info":
            return {"registration_fee_sol": 10, "registration_frequency": "one_time",
                    "enabled": False, "recipient": None}
        raise AssertionError(path)
    monkeypatch.setattr(node, "api", api)
    result = node.discover("https://aiworld.example")
    assert result["supported_jobs"] == ["prime_count", "inference"]
    assert result["registration"]["registration_fee_sol"] == 10
    assert paths == ["/.well-known/ai-world.json", "/v1/info", "/v1/compute/info",
                     "/v1/billing/info"]
    def mismatched(base, path):
        if path == "/.well-known/ai-world.json":
            return {"protocol": "other-protocol"}
        raise AssertionError("Must fail before any other network action")
    monkeypatch.setattr(node, "api", mismatched)
    with pytest.raises(ValueError, match="expected AI WORLD protocol"):
        node.discover("https://aiworld.example")


def test_volunteering_requires_consent_and_respects_local_limits(monkeypatch):
    with pytest.raises(ValueError, match="--consent"):
        node.validate_settings(args(consent=False), snapshot())
    with pytest.raises(ValueError, match="wall"):
        node.validate_settings(args(wall=900), snapshot())
    with pytest.raises(ValueError, match="Max jobs"):
        node.validate_settings(args(max_jobs=99), snapshot())
    with pytest.raises(ValueError, match="Duration"):
        node.validate_settings(args(duration=12), snapshot())
    kinds, models = node.validate_settings(args(), snapshot())
    assert kinds == ["prime_count", "hash_chain"]
    assert models == []


def test_gpu_requires_hardware_installed_model_and_approval(monkeypatch):
    with pytest.raises(ValueError, match="GPU"):
        node.validate_settings(args(mode="gpu", model="smollm2:135m"), snapshot())
    monkeypatch.setattr(node, "available_models", lambda: {"smollm2:135m"})
    with pytest.raises(ValueError, match="model"):
        node.validate_settings(args(mode="gpu"), snapshot(gpu=True))
    with pytest.raises(ValueError, match="not installed"):
        node.validate_settings(args(mode="gpu", model="not-installed"), snapshot(gpu=True))
    kinds, models = node.validate_settings(args(mode="both", model="smollm2:135m"),
                                           snapshot(gpu=True))
    assert kinds == ["prime_count", "hash_chain", "inference"]
    assert models == ["smollm2:135m"]


def test_identity_created_once_and_gate_only_on_first_join(monkeypatch, tmp_path):
    path = tmp_path / "secure" / "identity.json"
    state = {"created": None, "entered": [], "gate": 0}
    def api(_base, path_):
        if state["created"] is None:
            raise SystemExit("Network error 404: not found")
        if not state["entered"]:
            raise SystemExit("Network error 404: not found")
        return {"status": "active"}
    def gated(_base, _record):
        state["gate"] += 1
        return {"passed": True}
    def send(_base, _record, op, data):
        state["entered"].append((op, data))
        return {"height": 1}
    monkeypatch.setattr(node, "api", api)
    monkeypatch.setattr(node, "pass_gate", gated)
    monkeypatch.setattr(node, "transact", send)
    first = node.identity("http://127.0.0.1:8000", path, "Test agent")
    state["created"] = first["agent_id"]
    second = node.identity("http://127.0.0.1:8000", path, "Test agent")
    assert first["agent_id"] == second["agent_id"]
    assert path.stat().st_mode & 0o077 == 0
    assert state["gate"] == 1
    assert len(state["entered"]) == 1
    assert state["entered"][0][0] == "enter"
    assert "private_key" not in state["entered"][0][1]


def test_volunteer_automatically_offers_serves_and_withdraws(monkeypatch):
    state = {"tx": [], "run": None}
    monkeypatch.setattr(node, "discover", lambda base: {"network": "AI WORLD", "registration": {"registration_fee_sol": 10, "registration_frequency": "one_time", "enabled": False}})
    monkeypatch.setattr(node, "inspect_resources", lambda: snapshot())
    monkeypatch.setattr(node, "identity", lambda base, path, name: {"agent_id": "worker"})
    monkeypatch.setattr(node, "public_resources",
                        lambda hardware: {"logical_cpu_cores": 4, "memory_available_mb": 1024,
                                          "nvidia_gpu_count": 0, "nvidia_vram_total_mb": 0})
    def transact(_base, _identity, op, data):
        state["tx"].append((op, data))
        if op == "compute_offer":
            return {"height": 17}
        return {"height": 18}
    def run_once(_base, _identity, height, **kw):
        assert height == 17
        state["run"] = kw
        return 1
    monkeypatch.setattr(node, "transact", transact)
    monkeypatch.setattr(node, "run_once", run_once)
    assert node.volunteer("http://127.0.0.1:8000", args()) == 1
    assert [tx[0] for tx in state["tx"]] == ["compute_offer", "compute_withdraw"]
    offer = state["tx"][0][1]
    assert offer["terms"] == {"mode": "free", "price_lamports": 0}
    assert offer["limits"]["max_wall_seconds"] == 30
    assert offer["models"] == []
    assert state["run"]["approved_models"] == set()


def test_no_automatic_offer_if_discovery_or_consent_fails(monkeypatch):
    monkeypatch.setattr(node, "discover", lambda base: {"network": "AI WORLD", "registration": {"registration_fee_sol": 10, "registration_frequency": "one_time", "enabled": False}})
    monkeypatch.setattr(node, "inspect_resources", lambda: snapshot())
    def should_not_be_called(*args, **kwargs):
        raise AssertionError("No identity or offer before consent")
    monkeypatch.setattr(node, "identity", should_not_be_called)
    monkeypatch.setattr(node, "transact", should_not_be_called)
    with pytest.raises(ValueError, match="--consent"):
        node.volunteer("http://127.0.0.1:8000", args(consent=False))


def test_private_identity_symlink_refused(monkeypatch, tmp_path):
    target = tmp_path / "other.json"
    target.write_text("{}")
    link = tmp_path / "volunteer.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        node.identity("http://127.0.0.1:8000", link, "Agent")


def test_agent_refuses_live_or_unexpected_billing(monkeypatch):
    def fake_api(base, path):
        if path == "/.well-known/ai-world.json":
            return {"protocol": node.EXPECTED_PROTOCOL,
                    "endpoints": {"compute": "/v1/compute/info"}}
        if path == "/v1/info":
            return {"protocol": node.EXPECTED_PROTOCOL}
        if path == "/v1/compute/info":
            return {"supported_jobs": ["prime_count"]}
        if path == "/v1/billing/info":
            return {"registration_fee_sol": 10, "registration_frequency": "one_time",
                    "enabled": True, "recipient": "unsafe"}
        raise AssertionError(path)
    monkeypatch.setattr(node, "api", fake_api)
    with pytest.raises(ValueError, match="Live payments"):
        node.discover("https://aiworld.example")
