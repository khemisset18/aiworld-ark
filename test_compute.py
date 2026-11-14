"""Tests: voluntary offer, signed CPU sharing, authorization, limits and withdrawal."""
import importlib
import json
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


def test_paid_quote_needs_consent_and_remains_blocked_without_verified_payment(c):
    provider_key, provider = new_agent(c, "Paid provider")
    user_key, user = new_agent(c, "Paid requester")
    other_key, other = new_agent(c, "Not provider")
    offer = do(c, provider_key, provider, 2, "compute_offer", {
        "kinds": ["hash_chain"], "max_jobs": 2, "ttl_seconds": 3600,
        "terms": {"mode": "paid", "price_lamports": 15000}})
    assert offer.status_code == 200, offer.text
    capacity = offer.json()["height"]
    assert c.get("/v1/compute/offers").json()[0]["terms"] == {
        "mode": "paid", "price_lamports": 15000,
        "platform_fee_lamports": 450, "provider_lamports": 14550,
        "fee_bps": 300, "payment_status": "not_implemented"}
    bare = {"capacity_height": capacity, "kind": "hash_chain", "params": {"text": "bonjour", "rounds": 10}}
    assert do(c, user_key, user, 2, "compute_request", bare).status_code == 409
    assert do(c, user_key, user, 2, "compute_request", {**bare, "agreed_price_lamports": 15001}).status_code == 409
    job = do(c, user_key, user, 2, "compute_request", {**bare, "agreed_price_lamports": 15000})
    assert job.status_code == 200, job.text
    j = job.json()["height"]
    assert c.get(f"/v1/compute/jobs/{j}").json()["status"] == "awaiting_payment"
    assert do(c, provider_key, provider, 3, "compute_claim", {"job_height": j}).status_code == 409
    assert do(c, other_key, other, 2, "compute_authorize", {"job_height": j}).status_code == 403
    authorized = do(c, provider_key, provider, 3, "compute_authorize", {"job_height": j})
    assert authorized.status_code == 200, authorized.text
    assert c.get(f"/v1/compute/jobs/{j}").json()["status"] == "seller_approved_awaiting_payment"
    assert do(c, provider_key, provider, 4, "compute_claim", {"job_height": j}).status_code == 409
    assert do(c, provider_key, provider, 4, "compute_authorize", {"job_height": j}).status_code == 409
    assert c.get("/v1/chain/verify").json()["valid"]


def test_pricing_validation_and_legacy_migration(c, tmp_path):
    k,a = new_agent(c, "Offer validator")
    base = {"kinds": ["hash_chain"], "max_jobs": 1, "ttl_seconds": 3600}
    for terms in [{"mode":"free","price_lamports": 1}, {"mode":"paid","price_lamports": 0},
                  {"mode":"paid","price_lamports": True}, {"mode":"paid","price_lamports": -1},
                  {"mode":"paid","price_lamports": 10**16}]:
        assert do(c,k,a,2,"compute_offer",{**base,"terms":terms}).status_code == 400
    import sqlite3
    from compute_pool import setup
    db_path = tmp_path/"legacy.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE compute_capacity (height INTEGER PRIMARY KEY,owner TEXT NOT NULL,kinds TEXT NOT NULL,max_jobs INTEGER NOT NULL,expiry INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'open')")
        db.execute("INSERT INTO compute_capacity VALUES (1,'legacy','[\"hash_chain\"]',1,9999999999,'open')")
        setup(db)
        assert json.loads(db.execute("SELECT terms_json FROM compute_capacity WHERE height=1").fetchone()[0]) == {"mode":"free", "price_lamports":0}
        setup(db)


def test_fee_math_integer_lamports_and_free_fee():
    from compute_pool import price_breakdown
    assert price_breakdown({"mode":"free", "price_lamports":0})["platform_fee_lamports"] == 0
    assert price_breakdown({"mode":"paid", "price_lamports":1_000_000_000}) == {
        "mode":"paid", "price_lamports":1_000_000_000,
        "platform_fee_lamports":30_000_000, "provider_lamports":970_000_000,
        "fee_bps":300, "payment_status":"not_implemented"}
    assert price_breakdown({"mode":"paid", "price_lamports":101})["platform_fee_lamports"] == 4
    assert price_breakdown({"mode":"paid", "price_lamports":101})["provider_lamports"] == 97
    with pytest.raises(Exception):
        price_breakdown({"mode":"paid", "price_lamports":True})
