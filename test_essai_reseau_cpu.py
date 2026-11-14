"""Offline tests for the two-PC LAN driver (actual two-PC test remains manual)."""
from __future__ import annotations

import pytest

import essai_reseau_cpu as trial


@pytest.mark.parametrize("address", [
    "http://8.8.8.8:8000",
    "http://example.org:8000",
    "http://192.168.1.10:8000/path",
    "http://user:pass@192.168.1.10:8000",
    "ftp://192.168.1.10:8000",
])
def test_reject_insecure_or_malformed_remote_targets(address):
    with pytest.raises(SystemExit):
        trial.validated_server(address)


@pytest.mark.parametrize("address", [
    "http://192.168.1.10:8000",
    "http://10.0.0.5:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "https://ark.example.com:443",
])
def test_local_or_encrypted_server_targets_are_allowed(address):
    assert trial.validated_server(address) == address


def test_real_workflow_requester_reviews_the_providers_result(monkeypatch, capsys):
    state = {"requested": None, "review": None}

    monkeypatch.setattr(trial, "identity_for", lambda base, role: {"agent_id": "requester"})
    monkeypatch.setattr(trial.secrets, "randbelow", lambda n: 37)

    def fake_api(base, path):
        if path == "/health":
            return {"ok": True}
        if path == "/v1/compute/offers":
            return [{"height": 17, "owner": "volunteer",
                     "terms": {"mode": "free"}, "kinds": ["prime_count"]}]
        if path == "/v1/compute/jobs/18":
            return {"status": "accepted_by_requester" if state["review"] is not None
                    else "completed_unverified"}
        raise AssertionError(path)

    def fake_tx(base, actor, op, data):
        if op == "compute_request":
            state["requested"] = data
            return {"height": 18}
        if op == "compute_review":
            state["review"] = data
            return {"height": 19}
        raise AssertionError(op)

    def fake_private(base, actor, height):
        assert height == 18
        return {"result": trial.calculate("prime_count", state["requested"]["params"]),
                "params": state["requested"]["params"], "worker": "volunteer"}

    monkeypatch.setattr(trial, "api", fake_api)
    monkeypatch.setattr(trial, "transact", fake_tx)
    monkeypatch.setattr(trial, "private_job", fake_private)
    trial.requester("http://192.168.1.20:8000", 17, 30)
    assert state["requested"]["params"] == {"start": 2, "end": 5037}
    assert state["review"] == {"job_height": 18, "accepted": True}
    assert "SUCCES" in capsys.readouterr().out


def test_wrong_remote_result_is_rejected_and_reviewed_negatively(monkeypatch):
    state = {"params": None, "review": None}
    monkeypatch.setattr(trial, "identity_for", lambda base, role: {"agent_id": "requester"})
    monkeypatch.setattr(trial.secrets, "randbelow", lambda n: 0)

    def fake_api(base, path):
        if path == "/health":
            return {"ok": True}
        if path == "/v1/compute/offers":
            return [{"height": 4, "owner": "volunteer",
                     "terms": {"mode": "free"}, "kinds": ["prime_count"]}]
        if path == "/v1/compute/jobs/8":
            return {"status": "completed_unverified"}
        raise AssertionError(path)

    def fake_tx(base, actor, op, data):
        if op == "compute_request":
            state["params"] = data["params"]
            return {"height": 8}
        if op == "compute_review":
            state["review"] = data
            return {"height": 9}
        raise AssertionError(op)

    monkeypatch.setattr(trial, "api", fake_api)
    monkeypatch.setattr(trial, "transact", fake_tx)
    monkeypatch.setattr(trial, "private_job",
                        lambda base, actor, height: {
                            "result": {"count": -1}, "params": state["params"],
                            "worker": "volunteer",
                        })
    with pytest.raises(SystemExit, match="incorrect"):
        trial.requester("http://192.168.1.20:8000", 4, 30)
    assert state["review"] == {"job_height": 8, "accepted": False}


def test_volunteer_limits_one_task_and_waits_for_requester(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(trial, "identity_for", lambda base, role: {"agent_id": "volunteer"})
    monkeypatch.setattr(trial, "inspect_resources", lambda: {"logical_cpu_cores": 4})
    monkeypatch.setattr(trial, "public_resources", lambda inventory: {"logical_cpu_cores": 4})
    monkeypatch.setattr(trial, "api", lambda base, path: {"ok": True})

    def tx(base, actor, op, data):
        calls.append(("signed", op, data))
        return {"height": 22}

    def run(base, actor, height, **kwargs):
        calls.append(("worker", height, kwargs))
        return 1

    monkeypatch.setattr(trial, "transact", tx)
    monkeypatch.setattr(trial, "run_once", run)
    monkeypatch.setattr(trial, "assigned",
                        lambda base, actor, height, status: [
                            {"status": "completed_unverified"}
                        ])
    trial.volunteer("http://192.168.1.20:8000", 30)
    assert calls[0][2]["terms"] == {"mode": "free", "price_lamports": 0}
    assert calls[0][2]["limits"] == {"max_wall_seconds": 15, "max_memory_mb": 512}
    assert calls[0][2]["max_jobs"] == 1
    assert calls[1][2] == {"max_wall_seconds": 15, "max_memory_mb": 512}
    assert "OFFRE CPU" in capsys.readouterr().out
