"""Offline tests of the PC1 Ollama GPU proof: no GPU or model required in CI."""
from __future__ import annotations

import pytest
import essai_gpu_pc1 as pilot


@pytest.mark.parametrize("models,expected", [
    ([{"name": "smollm2:135m", "size": 300, "size_vram": 280}], True),
    ([{"name": "smollm2:135m", "size": 300, "size_vram": 0}], False),
    ([{"name": "other", "size": 300, "size_vram": 280}], None),
    ([], None),
    ([{"name": "smollm2:135m", "size": -1, "size_vram": 280}], None),
])
def test_gpu_offload_requires_matching_loaded_model(models, expected):
    evidence = pilot.offload_evidence("smollm2:135m", {"models": models})
    if expected is None:
        assert evidence is None
    else:
        assert evidence["gpu_offload"] is expected


def test_local_gpu_proof_requires_actual_vram(monkeypatch, capsys):
    import volunteer_inference

    def api(path, payload=None, *, timeout=15):
        if path == "/api/version":
            return {"version": "test"}
        if path == "/api/tags":
            return {"models": [{"name": "smollm2:135m"}]}
        if path == "/api/generate":
            assert payload["keep_alive"] == "90s"
            assert payload["options"]["num_predict"] <= 48
            return {"response": "Bonjour AI WORLD"}
        if path == "/api/ps":
            return {"models": [{"name": "smollm2:135m", "size": 350000000,
                                "size_vram": 300000000}]}
        raise AssertionError(path)

    monkeypatch.setattr(pilot, "ollama", api)
    monkeypatch.setattr(pilot, "nvidia_snapshot",
                        lambda: {"name": "GTX 1650", "temperature_c": 52,
                                 "utilization_pct": 0, "used_vram_mib": 100,
                                 "total_vram_mib": 4096})
    monkeypatch.setattr(volunteer_inference, "infer_local",
                        lambda params, models, timeout: {
                            "model": params["model"], "text": "Bonjour"}
                        )
    assert pilot.test_gpu("smollm2:135m") is True
    output = capsys.readouterr().out
    assert "SUCCES" in output
    assert "PC2 n'a pas encore" in output


def test_cpu_only_inference_not_a_gpu_success(monkeypatch, capsys):
    import volunteer_inference

    def api(path, payload=None, *, timeout=15):
        if path == "/api/version":
            return {"version": "test"}
        if path == "/api/tags":
            return {"models": [{"name": "smollm2:135m"}]}
        if path == "/api/generate":
            return {"response": "Bonjour"}
        if path == "/api/ps":
            return {"models": [{"name": "smollm2:135m", "size": 350000000,
                                "size_vram": 0}]}
        raise AssertionError(path)

    monkeypatch.setattr(pilot, "ollama", api)
    monkeypatch.setattr(pilot, "nvidia_snapshot", lambda: None)
    monkeypatch.setattr(volunteer_inference, "infer_local",
                        lambda params, models, timeout: {
                            "model": params["model"], "text": "Bonjour"}
                        )
    assert pilot.test_gpu("smollm2:135m") is False
    assert "NON PROUVEE" in capsys.readouterr().out
