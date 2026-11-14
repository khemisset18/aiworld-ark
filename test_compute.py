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
    assert "free (0 SOL)" in c.get("/v1/compute/info").json()["pricing"]


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


def test_optional_inference_offer_requires_explicit_model_approval(c):
    volunteer_key, volunteer = new_agent(c, "Model volunteer")
    client_key, client = new_agent(c, "Model requester")
    missing = do(c, volunteer_key, volunteer, 2, "compute_offer", {
        "kinds": ["inference"], "max_jobs": 1, "ttl_seconds": 3600})
    assert missing.status_code == 400
    offer = do(c, volunteer_key, volunteer, 2, "compute_offer", {
        "kinds": ["inference"], "models": ["smollm2:135m"], "max_jobs": 1, "ttl_seconds": 3600})
    assert offer.status_code == 200, offer.text
    capacity = offer.json()["height"]
    assert c.get("/v1/compute/offers").json()[0]["models"] == ["smollm2:135m"]
    disallowed = do(c, client_key, client, 2, "compute_request", {
        "capacity_height": capacity, "kind": "inference",
        "params": {"model": "other:latest", "prompt": "bonjour", "max_tokens": 32}})
    assert disallowed.status_code == 403
    too_large = do(c, client_key, client, 2, "compute_request", {
        "capacity_height": capacity, "kind": "inference",
        "params": {"model": "smollm2:135m", "prompt": "secret" * 300, "max_tokens": 32}})
    assert too_large.status_code == 400
    accepted = do(c, client_key, client, 2, "compute_request", {
        "capacity_height": capacity, "kind": "inference",
        "params": {"model": "smollm2:135m", "prompt": "bonjour", "max_tokens": 32}})
    assert accepted.status_code == 200, accepted.text
    job = accepted.json()["height"]
    assert do(c, volunteer_key, volunteer, 3, "compute_claim", {"job_height": job}).status_code == 200
    forged = do(c, volunteer_key, volunteer, 4, "compute_complete", {
        "job_height": job, "result": {"model": "other:latest", "text": "faux"}})
    assert forged.status_code == 400
    done = do(c, volunteer_key, volunteer, 4, "compute_complete", {
        "job_height": job, "result": {"model": "smollm2:135m", "text": "Bonjour!"}})
    assert done.status_code == 200
    assert c.get(f"/v1/compute/jobs/{job}").json()["status"] == "completed_unverified"


def test_local_inference_is_loopback_only_and_rejects_unapproved_models(monkeypatch):
    import volunteer_inference as runner
    import json
    from io import BytesIO
    calls = []

    class FakeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return json.dumps({"response": "Bonjour de l'agent local"}).encode()

    def fake_urlopen(req, timeout):
        calls.append((req.full_url, json.loads(req.data.decode()), timeout))
        return FakeResponse()

    monkeypatch.setattr(runner, "urlopen", fake_urlopen)
    params = {"model": "smollm2:135m", "prompt": "Explique le test", "max_tokens": 32}
    with pytest.raises(ValueError):
        runner.infer_local(params, {"other:model"})
    assert calls == []
    result = runner.infer_local(params, {"smollm2:135m"}, timeout=5)
    assert result == {"model": "smollm2:135m", "text": "Bonjour de l'agent local"}
    assert calls[0][0] == "http://127.0.0.1:11434/api/generate"
    assert calls[0][1]["stream"] is False
    assert calls[0][1]["options"]["num_predict"] == 32
    assert calls[0][2] == 5


def test_compute_upgrade_keeps_legacy_offers(tmp_path):
    import sqlite3
    from compute_pool import setup
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE compute_capacity (height INTEGER PRIMARY KEY, owner TEXT NOT NULL, kinds TEXT NOT NULL, max_jobs INTEGER NOT NULL, expiry INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'open')")
        db.execute("INSERT INTO compute_capacity VALUES (1,'volunteer','[\"hash_chain\"]',2,9999999999,'open')")
        setup(db)
        assert db.execute("SELECT models_json FROM compute_capacity WHERE height=1").fetchone()[0] == "[]"
        setup(db)


def test_volunteer_can_fail_a_claimed_job_without_a_charge(c):
    k1, a1 = new_agent(c, "Volunteer failure")
    k2, a2 = new_agent(c, "Client failure")
    offer = do(c, k1, a1, 2, "compute_offer", {
        "kinds": ["inference"], "models": ["smollm2:135m"], "max_jobs": 1, "ttl_seconds": 3600})
    h = offer.json()["height"]
    req = do(c, k2, a2, 2, "compute_request", {
        "capacity_height": h, "kind": "inference",
        "params": {"model": "smollm2:135m", "prompt": "test", "max_tokens": 12}})
    j = req.json()["height"]
    assert do(c, k2, a2, 3, "compute_fail", {"job_height": j}).status_code == 403
    assert do(c, k1, a1, 3, "compute_fail", {"job_height": j}).status_code == 409
    assert do(c, k1, a1, 3, "compute_claim", {"job_height": j}).status_code == 200
    assert do(c, k1, a1, 4, "compute_fail", {"job_height": j}).status_code == 200
    assert c.get(f"/v1/compute/jobs/{j}").json()["status"] == "failed_by_worker"
    assert do(c, k1, a1, 5, "compute_complete", {"job_height": j, "result": {"model": "smollm2:135m", "text": "no"}}).status_code == 409
    assert c.get("/v1/chain/verify").json()["valid"]


def test_priced_offer_fee_and_unverified_payment_cannot_unlock_compute(c, monkeypatch):
    # Old quotation logic is exercised only as a simulated future feature.
    import billing
    monkeypatch.setattr(billing, "BILLING_FROZEN", False)
    """Paid tasks stay blocked; providers cannot fake a settled transaction."""
    k_provider, provider = new_agent(c, "Fee provider")
    k_buyer, buyer = new_agent(c, "Fee buyer")
    offer = do(c, k_provider, provider, 2, "compute_offer", {
        "kinds": ["hash_chain"], "max_jobs": 2, "ttl_seconds": 3600,
        "terms": {"mode": "paid", "price_lamports": 1_000_000_000}})
    assert offer.status_code == 200, offer.text
    offer_id = offer.json()["height"]
    quote = c.get("/v1/compute/offers").json()[0]["terms"]
    assert quote["platform_fee_lamports"] == 30_000_000
    assert quote["provider_lamports"] == 970_000_000
    assert quote["fee_bps"] == 300
    params = {"capacity_height": offer_id, "kind": "hash_chain",
              "params": {"text": "AI WORLD", "rounds": 10}}
    assert do(c, k_buyer, buyer, 2, "compute_request", params).status_code == 409
    assert do(c, k_buyer, buyer, 2, "compute_request",
              {**params, "agreed_price_lamports": 10_000}).status_code == 409
    req = do(c, k_buyer, buyer, 2, "compute_request",
             {**params, "agreed_price_lamports": 1_000_000_000})
    assert req.status_code == 200, req.text
    job_id = req.json()["height"]
    assert c.get(f"/v1/compute/jobs/{job_id}").json()["status"] == "awaiting_payment"
    assert do(c, k_provider, provider, 3, "compute_claim", {"job_height": job_id}).status_code == 409
    approval = do(c, k_provider, provider, 3, "compute_authorize", {"job_height": job_id})
    assert approval.status_code == 200, approval.text
    assert c.get(f"/v1/compute/jobs/{job_id}").json()["status"] == "seller_approved_awaiting_payment"
    assert c.get(f"/v1/compute/jobs/{job_id}").json()["status"] == "seller_approved_awaiting_payment"
    assert do(c, k_provider, provider, 4, "compute_claim", {"job_height": job_id}).status_code == 409


def test_fee_rounding_is_integer_and_free_jobs_never_pay():
    from compute_pool import price_breakdown
    free = price_breakdown({"mode": "free", "price_lamports": 0})
    assert free["fee_bps"] == 0 and free["platform_fee_lamports"] == 0
    assert free["provider_lamports"] == 0
    tiny = price_breakdown({"mode": "paid", "price_lamports": 101})
    assert tiny["platform_fee_lamports"] == 4
    assert tiny["provider_lamports"] == 97
    for invalid in ({"mode": "paid", "price_lamports": True},
                    {"mode": "free", "price_lamports": 1},
                    {"mode": "paid", "price_lamports": 0}):
        with pytest.raises(Exception):
            price_breakdown(invalid)


def test_paid_compute_offers_are_disabled_by_roadmap(c):
    key, identity = new_agent(c, "Volunteer")
    offer = do(c, key, identity, 2, "compute_offer", {
        "kinds": ["hash_chain"], "max_jobs": 1, "ttl_seconds": 3600,
        "terms": {"mode": "paid", "price_lamports": 1_000_000}})
    assert offer.status_code == 503
    info = c.get("/v1/compute/info").json()
    assert info["paid_exchange"] == "planned_disabled"
    assert info["paid_offers_enabled"] is False
    assert info["live_payments_enabled"] is False
