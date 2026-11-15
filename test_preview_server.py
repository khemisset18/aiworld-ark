"""Prevent a free public preview from exposing the real AI WORLD coordinator."""
from __future__ import annotations

from fastapi.testclient import TestClient

import preview_server


def test_readonly_entrance_displays_real_design_but_no_registration():
    with TestClient(preview_server.app) as client:
        root = client.get("/")
        assert root.status_code == 200
        html = root.text
        assert "AI WORLD" in html
        assert "THE GATE" in html
        assert "MODE DÉMONSTRATION" in html
        assert "aucune inscription" in html.lower()
        assert "Aucun SOL à envoyer" in html
        assert "Pseudonyme en démonstration" in html
        assert "aiworld_node.py join --server" not in html
        assert "fetch(" not in html
        assert "/v1/billing/info" in html
        assert "10 SOL" in html
        assert "Google" in html and "Solana" in html
        assert "Le Cercle" in html
        assert root.headers["x-aiworld-deployment"] == "staging-read-only"
        assert root.headers["cache-control"] == "no-store"
        assert root.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in root.headers["content-security-policy"]
        assert "connect-src 'none'" in root.headers["content-security-policy"]


def test_preview_accurately_disables_all_identity_and_payment_operations():
    with TestClient(preview_server.app) as client:
        assert client.get("/health").json() == {
            "status": "ok", "mode": "public_read_only_preview",
            "persistent_storage": False, "admission_enabled": False,
            "payments_enabled": False, "compute_enabled": False
        }
        billing = client.get("/v1/billing/info").json()
        assert billing["first_free_slots"] == 10
        assert billing["free_remaining"] is None
        assert billing["first_ten_registration_enabled"] is False
        assert billing["enabled"] is False
        assert billing["next_registration_fee_sol"] == 10
        assert billing["preview_only"] is True
        assert client.get("/v1/auth/providers").json()["all_logins_enabled"] is False
        assert client.get("/.well-known/ai-world.json").json()["agent_registration"] is False
        assert client.get("/v1/admission/info").json()["enabled"] is False


def test_every_private_world_and_sensitive_api_route_fails_closed():
    paths = (
        "/world", "/world/cercle", "/v1/tx", "/v1/compute/offers",
        "/v1/world/topics", "/v1/world/projects", "/v1/world/activity",
        "/v1/world/invitations", "/v1/agents", "/v1/admission/start",
        "/v1/auth/links", "/v1/circle/applications", "/v1/billing/checkout"
    )
    with TestClient(preview_server.app) as client:
        for path in paths:
            assert client.get(path).status_code == 403, path
            assert client.post(path, json={"secret": "never stored"}).status_code == 403, path
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert "Disallow: /world" in client.get("/robots.txt").text


def test_staging_preview_remains_isolated_from_coordinator():
    # One can run/import preview_server without initializing server.py or a DB.
    import sys
    assert preview_server.app.title == "AI WORLD / public staging preview"
    # This is only true when run standalone, not while loading all pytest apps.
    # Statically check the entrypoint itself instead of sys.modules.
    src = preview_server.__file__
    with open(src, encoding="utf-8") as fp:
        code = fp.read()
    assert "from server import" not in code
    assert "import server\n" not in code
    assert "SOULCHAIN_DB" not in code
    assert "sqlite3.connect" not in code
    assert "wallet.sendTransaction" not in code
