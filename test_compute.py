"""Tests: voluntary offer, signed CPU sharing, authorization, limits and withdrawal."""
import importlib
import pytest
from fastapi.testclient import TestClient
from test_forge import new_agent, do
from compute_worker import calculate


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("SOULCHAIN_DB", str(tmp_path / "compute.sqlite3"))
    monkeypatch.setenv("ARK_ADMISSION_REQUIRED", "0")
    monkeypatch.delenv("ARK_PAYMENT_REQUIRED", raising=False)
    import server
    importlib.reload(server)
    return TestClient(server.app)


def test_voluntary_cpu_exchange(c):
    volunteer_key, volunteer = new_agent(c, "CPU volunteer")
    borrower_key, borrower = new_agent(c, "Borrower")
    offer = do(c, volunteer_key, volunteer, 2, "compute_offer", {"kinds": ["hash_chain", "prime_count"], "max_jobs": 2, "ttl_seconds": 3600})
    assert offer.status_code == 200, offer.text
    cap_id = offer.json()["height"]
    assert c.get("/v1/compute/offers").json()[0]["remaining_jobs"] == 2
    params = {"text": "Bonjour IA", "rounds": 1000}
    job = do(c, borrower_key, borrower, 2, "compute_request", {"capacity_height": cap_id, "kind": "hash_chain", "params": params})
    assert job.status_code == 200, job.text
    job_id = job.json()["height"]
    assert c.get(f"/v1/compute/jobs/{job_id}").json()["status"] == "queued"
    # No stealing someone else's volunteer CPU claim.
    assert do(c, borrower_key, borrower, 3, "compute_claim", {"job_height": job_id}).status_code == 403
    assert do(c, volunteer_key, volunteer, 3, "compute_claim", {"job_height": job_id}).status_code == 200
    result = calculate("hash_chain", params)
    assert do(c, volunteer_key, volunteer, 4, "compute_complete", {"job_height": job_id, "result": result}).status_code == 200
    assert c.get(f"/v1/compute/jobs/{job_id}").json()["status"] == "completed_unverified"
    assert do(c, borrower_key, borrower, 3, "compute_review", {"job_height": job_id, "accepted": True}).status_code == 200
    assert c.get(f"/v1/compute/jobs/{job_id}").json()["status"] == "accepted_by_requester"
    assert c.get("/v1/chain/verify").json()["valid"]
    assert c.get("/v1/compute/info").json()["pricing"] == "free (0 SOL)"


def test_limits_consent_and_withdraw(c):
    v_key, v = new_agent(c, "CPU lender")
    r_key, r = new_agent(c, "CPU user")
    o_key, o = new_agent(c, "Other agent")
    invalid = do(c, v_key, v, 2, "compute_offer", {"kinds": ["hash_chain"], "max_jobs": 999, "ttl_seconds": 3600})
    assert invalid.status_code == 400
    offer = do(c, v_key, v, 2, "compute_offer", {"kinds": ["hash_chain"], "max_jobs": 1, "ttl_seconds": 3600})
    h = offer.json()["height"]
    bad = do(c, r_key, r, 2, "compute_request", {"capacity_height": h, "kind": "hash_chain", "params": {"text": "x", "rounds": 100000000}})
    assert bad.status_code == 400
    bad_kind = do(c, r_key, r, 2, "compute_request", {"capacity_height": h, "kind": "prime_count", "params": {"start": 2, "end": 5}})
    assert bad_kind.status_code == 400
    job = do(c, r_key, r, 2, "compute_request", {"capacity_height": h, "kind": "hash_chain", "params": {"text": "test", "rounds": 20}})
    assert job.status_code == 200
    j = job.json()["height"]
    assert do(c, o_key, o, 2, "compute_withdraw", {"capacity_height": h}).status_code == 403
    assert do(c, v_key, v, 3, "compute_withdraw", {"capacity_height": h}).status_code == 200
    assert c.get(f"/v1/compute/jobs/{j}").json()["status"] == "cancelled"
    assert do(c, v_key, v, 4, "compute_claim", {"job_height": j}).status_code == 409
    assert do(c, r_key, r, 3, "compute_request", {"capacity_height": h, "kind": "hash_chain", "params": {"text": "test", "rounds": 20}}).status_code == 409
    assert not c.get("/v1/compute/offers").json()


def test_worker_is_bounded_and_deterministic(c):
    assert calculate("prime_count", {"start": 2, "end": 10}) == {"count": 4}
    with pytest.raises(Exception):
        calculate("hash_chain", {"text": "x", "rounds": -1})
    with pytest.raises(Exception):
        calculate("code", {"source": "print('danger')"})


def test_no_duplicate_claim_or_fake_result(c):
    v_key, v = new_agent(c, "Volunteer")
    r_key, r = new_agent(c, "Requester")
    offer = do(c, v_key, v, 2, "compute_offer", {"kinds": ["prime_count"], "max_jobs": 1, "ttl_seconds": 3600})
    h = offer.json()["height"]
    data = {"capacity_height": h, "kind": "prime_count", "params": {"start": 2, "end": 100}}
    job = do(c, r_key, r, 2, "compute_request", data)
    j = job.json()["height"]
    assert do(c, r_key, r, 3, "compute_request", data).status_code == 409
    assert do(c, r_key, r, 3, "compute_review", {"job_height": j, "accepted": True}).status_code == 409
    assert do(c, v_key, v, 3, "compute_claim", {"job_height": j}).status_code == 200
    assert do(c, v_key, v, 4, "compute_claim", {"job_height": j}).status_code == 409
    assert do(c, v_key, v, 4, "compute_complete", {"job_height": j, "result": {"count": "not-int"}}).status_code == 400
    assert do(c, v_key, v, 4, "compute_complete", {"job_height": j, "result": {"count": 25}}).status_code == 200
    # Result is an unverified claim until the requester checks it.
    assert c.get(f"/v1/compute/jobs/{j}").json()["status"] == "completed_unverified"
    assert do(c, r_key, r, 3, "compute_review", {"job_height": j, "accepted": False}).status_code == 200
    assert c.get(f"/v1/compute/jobs/{j}").json()["status"] == "rejected_by_requester"
