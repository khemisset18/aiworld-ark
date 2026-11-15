"""Offline tests of the actual two-PC GPU flow; no GPU/Ollama required in CI."""
import pytest
import essai_reseau_gpu as trial


def test_requester_signs_review_of_distinct_volunteer_result(monkeypatch, capsys):
    state = {"params": None, "review": None}
    monkeypatch.setattr(trial, "identity_for",
                        lambda base, role: {"agent_id": "demandeur_pc2"})
    def api(base, path):
        if path == "/health":
            return {"ok": True}
        if path == "/v1/compute/offers":
            return [{"height": 41, "owner": "volontaire_pc1",
                     "terms": {"mode": "free"}, "kinds": ["inference"],
                     "models": ["smollm2:135m"]}]
        if path == "/v1/compute/jobs/42":
            return {"status": "accepted_by_requester" if state["review"]
                    else "completed_unverified"}
        raise AssertionError(path)
    def tx(base, account, op, payload):
        if op == "compute_request":
            state["params"] = payload["params"]
            return {"height": 42}
        if op == "compute_review":
            state["review"] = payload
            return {"height": 43}
        raise AssertionError(op)
    monkeypatch.setattr(trial, "api", api)
    monkeypatch.setattr(trial, "transact", tx)
    monkeypatch.setattr(trial.secrets, "token_hex", lambda n: "abcd12")
    monkeypatch.setattr(trial, "private_job",
                        lambda base, account, job: {
                            "params": state["params"], "worker": "volontaire_pc1",
                            "result": {"model": "smollm2:135m", "text": "Bonjour AI WORLD"}})
    trial.requester("http://192.168.1.132:8000", 41, 30)
    assert state["params"]["prompt"].startswith(trial.PROMPT_PREFIX)
    assert state["params"]["model"] == trial.MODEL
    assert state["params"]["max_tokens"] == 32
    assert state["review"] == {"job_height": 42, "accepted": True}
    assert "SUCCES" in capsys.readouterr().out


def test_requester_refuses_invalid_worker_result(monkeypatch):
    state = {"params": None, "review": None}
    monkeypatch.setattr(trial, "identity_for",
                        lambda base, role: {"agent_id": "demandeur_pc2"})
    def api(base, path):
        if path == "/health":
            return {"ok": True}
        if path == "/v1/compute/offers":
            return [{"height": 41, "owner": "volontaire_pc1",
                     "terms": {"mode": "free"}, "kinds": ["inference"],
                     "models": ["smollm2:135m"]}]
        if path == "/v1/compute/jobs/42":
            return {"status": "rejected_by_requester" if state["review"]
                    else "completed_unverified"}
        raise AssertionError(path)
    def tx(base, account, op, payload):
        if op == "compute_request":
            state["params"] = payload["params"]
            return {"height": 42}
        if op == "compute_review":
            state["review"] = payload
            return {"height": 43}
        raise AssertionError(op)
    monkeypatch.setattr(trial, "api", api)
    monkeypatch.setattr(trial, "transact", tx)
    monkeypatch.setattr(trial, "private_job",
                        lambda base, account, job: {
                            "params": state["params"], "worker": "unknown",
                            "result": {"model": trial.MODEL, "text": "Bogus"}})
    with pytest.raises(SystemExit, match="incoherente"):
        trial.requester("http://192.168.1.132:8000", 41, 30)
    assert state["review"] == {"job_height": 42, "accepted": False}


def test_requester_rejects_paid_gpu_offer(monkeypatch):
    monkeypatch.setattr(trial, "identity_for",
                        lambda base, role: {"agent_id": "requester"})
    def api(base, path):
        if path == "/health":
            return {"ok": True}
        if path == "/v1/compute/offers":
            return [{"height": 6, "owner": "worker",
                     "terms": {"mode": "paid"},
                     "kinds": ["inference"], "models": [trial.MODEL]}]
        raise AssertionError(path)
    monkeypatch.setattr(trial, "api", api)
    with pytest.raises(SystemExit, match="non gratuite"):
        trial.requester("http://192.168.1.132:8000", 6, 30)


def test_volunteer_requires_real_gpu_and_local_ollama(monkeypatch):
    monkeypatch.setattr(trial, "api", lambda base, path: {"ok": True})
    monkeypatch.setattr(trial, "inspect_resources",
                        lambda: {"nvidia_gpus": []})
    with pytest.raises(SystemExit, match="NVIDIA"):
        trial.volunteer("http://127.0.0.1:8000", 30)


def test_volunteer_publishes_one_free_inference_job(monkeypatch, capsys):
    state = {"offer": None, "served": None}
    monkeypatch.setattr(trial, "api", lambda base, path: {"ok": True})
    monkeypatch.setattr(trial, "inspect_resources",
                        lambda: {"nvidia_gpus": [{"name": "NVIDIA"}]})
    monkeypatch.setattr(trial, "public_resources",
                        lambda inventory: {"nvidia_gpu_count": 1})
    monkeypatch.setattr(trial, "ollama",
                        lambda path, **kwargs: {"models": [{"name": trial.MODEL}]})
    monkeypatch.setattr(trial, "identity_for",
                        lambda base, role: {"agent_id": "volontaire_pc1"})
    def tx(base, account, op, payload):
        assert op == "compute_offer"
        state["offer"] = payload
        return {"height": 41}
    monkeypatch.setattr(trial, "transact", tx)
    monkeypatch.setattr(trial, "assigned",
                        lambda base, account, height, status="queued":
                        [{"kind": "inference", "worker": "volontaire_pc1",
                          "params": {"model": trial.MODEL},
                          "status": "completed_unverified" if status == "all"
                          else "queued"}])
    monkeypatch.setattr(trial, "nvidia_snapshot", lambda: None)
    monkeypatch.setattr(trial, "watch_gpu", lambda stop, evidence, model: None)
    def run(base, account, height, **kwargs):
        state["served"] = kwargs
        return 1
    monkeypatch.setattr(trial, "run_once", run)
    trial.volunteer("http://127.0.0.1:8000", 30)
    assert state["offer"]["kinds"] == ["inference"]
    assert state["offer"]["models"] == [trial.MODEL]
    assert state["offer"]["max_jobs"] == 1
    assert state["offer"]["terms"]["mode"] == "free"
    assert state["offer"]["limits"]["max_wall_seconds"] == 120
    assert state["served"]["approved_models"] == {trial.MODEL}
    assert state["served"]["max_wall_seconds"] == 120
    assert "OFFRE GPU" in capsys.readouterr().out
