"""Smoke tests of the public THE GATE vestibule and planned login providers.

Do not mistake these UI checks for functional OAuth, Solana or SMTP flows.
"""
from __future__ import annotations

from html.parser import HTMLParser
import re
import shutil
import subprocess

import pytest

from test_private_agent_network import net  # isolated private server and SQLite


class IDs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        self.ids.extend(value for key, value in attrs if key == "id")


def test_public_entrance_is_bootstrap_only_not_room_data(net):
    root = net.get("/")
    assert root.status_code == 200
    assert root.headers["cache-control"] == "no-store"
    html = root.text
    assert "THE GATE" in html
    assert "Pseudonyme" in html
    assert "Solana" in html
    assert "Google" in html
    assert "E-mail" in html
    assert "10 places gratuites" in html
    assert "10 SOL" in html
    assert "La Place des Agents" in html
    assert "Le Cercle des Agents" in html
    assert "20 votes favorables indépendants" in html
    assert "À connecter" in html
    assert "aucune inscription envoyée" in html
    assert "Aucun SOL" in html
    assert "private_key" not in html
    assert "localStorage" not in html
    assert "innerHTML" not in html
    ids = IDs()
    ids.feed(html)
    assert len(ids.ids) == len(set(ids.ids))
    assert net.get("/world").status_code == 403
    assert net.get("/v1/world/rooms").status_code == 403
    assert net.get("/world/cercle").status_code == 403


def test_auth_provider_truthful_live_response(net):
    methods = net.get("/v1/auth/providers").json()
    assert methods["pseudonym_only"] is True
    assert methods["canonical_identity"] == "Ed25519 local signing key"
    assert methods["gate_required_for_new_agents"] is True
    assert methods["supported"]["agent_ed25519"]["enabled"] is True
    for method in ("solana_wallet", "google", "email"):
        assert methods["supported"][method]["enabled"] is False
    assert methods["payment"]["enabled"] is False


def test_entry_script_is_syntactically_valid_and_no_fake_payment(net):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable, HTML-only checks still run")
    html = net.get("/").text
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.DOTALL)
    assert scripts
    for script in scripts:
        result = subprocess.run([node, "--check", "-"], input=script, text=True,
                                capture_output=True, timeout=10)
        assert result.returncode == 0, result.stderr
    assert 'fetch("/v1/billing/info"' in html
    assert "wallet.sendTransaction" not in html
    assert "location.href=" not in html
