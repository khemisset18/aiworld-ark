"""Website smoke checks: public agent-first page and existing read-only API.

These smoke checks verify the page text, not hardware execution, deployment or P2P operation.
"""
from __future__ import annotations

from html.parser import HTMLParser
import re
import shutil
import subprocess

import pytest

from test_compute import c  # isolated app with disposable SQLite


def test_agent_first_homepage_is_served(c):
    page = c.get("/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "AI WORLD" in page.text
    assert "Les agents se prêtent leur" in page.text
    assert "AI WORLD leur donne la route" in page.text
    assert "CPU/GPU validés sur deux PC" in page.text
    assert "RESULTATS_PILOTE_GPU_DEUX_PC_2026-11-15.md" in page.text
    assert "10 premiers agents validés gratuits" in page.text
    assert "10 places fondatrices gratuites" in page.text
    assert "paiement est encore désactivé" in page.text
    assert '/v1/billing/info' in page.text
    assert "une seule fois par agent" in page.text
    assert "paiement non activé" in page.text.lower()
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
    billing = c.get("/v1/billing/info").json()
    assert billing["registration_fee_sol"] == 10
    assert billing["enabled"] is False
    assert billing["recipient"] is None
    assert c.get("/.well-known/ai-world.json").json()["endpoints"]["compute"] == "/v1/compute/info"


def test_gpu_roadmap_status_matches_signed_lan_pilot(c):
    response = c.get("/v1/roadmap")
    assert response.status_code == 200
    phases = response.json()["phases"]
    gpu = next(phase for phase in phases if phase["id"] == "gpu_sharing")
    assert gpu["status"] == "prototype_two_physical_pcs_lan_ollama_gpu_offload_observed"


class _SiteIds(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        self.ids.extend(value for name, value in attrs if name == "id")


def test_interactive_agent_site_offers_filters_activity_and_safe_api(c):
    html = c.get("/").text
    for name in (
        'id="offer-kind"', 'id="offer-terms"', 'id="job-list"',
        'id="api-endpoint"', 'id="api-read"', 'id="api-output"',
        'id="agents-count"', 'id="integration"',
    ):
        assert name in html
    assert "Location commerciale CPU / GPU : pas encore ouverte" in html
    assert "simulation" in html.lower()
    assert "accepted_by_requester" in html
    assert 'GET /.well-known/ai-world.json' in html
    assert 'apiOutput.textContent' in html
    assert "innerHTML" not in html
    assert "document.write" not in html
    assert "localStorage" not in html
    ids = _SiteIds()
    ids.feed(html)
    assert len(ids.ids) == len(set(ids.ids)), "Duplicate HTML IDs"
    assert c.get("/v1/compute/jobs?status=accepted_by_requester&limit=10").status_code == 200


def test_agent_site_javascript_parses_without_execution(c):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable; static page checks still run")
    html = c.get("/").text
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.DOTALL)
    assert scripts, "Page should include interactive JS"
    for script in scripts:
        result = subprocess.run(
            [node, "--check", "-"], input=script, text=True,
            capture_output=True, timeout=10, check=False,
        )
        assert result.returncode == 0, result.stderr


def test_public_job_feed_has_metadata_only(c):
    response = c.get("/v1/compute/jobs?status=accepted_by_requester&limit=10")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    for job in response.json():
        assert "params" not in job and "result" not in job
