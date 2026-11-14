"""Website smoke checks: public agent-first page and existing read-only API.

These checks do NOT prove GPU execution, external deployment or P2P operation.
"""
from __future__ import annotations

from test_compute import c  # isolated app with disposable SQLite


def test_agent_first_homepage_is_served(c):
    page = c.get("/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "AI WORLD" in page.text
    assert "Les agents se prêtent leur" in page.text
    assert "AI WORLD leur donne la route" in page.text
    assert "GPU distant non testé" in page.text
    assert "0 paiement" in page.text
    assert "2 000 €" not in page.text


def test_site_links_to_real_public_endpoints_and_hides_keys(c):
    page = c.get("/")
    assert page.status_code == 200
    assert '/.well-known/ai-world.json' in page.text
    assert '/v1/compute/offers' in page.text
    assert '/v1/stats' in page.text
    assert 'textContent' in page.text  # data from volunteers is rendered as text
    assert "private_key" not in page.text
    assert c.get("/health").json() == {"ok": True}
    assert isinstance(c.get("/v1/compute/offers").json(), list)
    assert isinstance(c.get("/v1/stats").json()["agents_active"], int)
    assert c.get("/.well-known/ai-world.json").json()["endpoints"]["compute"] == "/v1/compute/info"
