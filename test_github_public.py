"""Public GitHub preview requires a signed, authorized workspace read.

Only github.com public metadata through fixed api.github.com, not an
installation token, repository content write, or access to private repos.
"""
from __future__ import annotations

import httpx
import pytest

import github_public as gh
from test_forge import do
from test_private_agent_network import net, signed_headers
from test_world_space import agent


@pytest.fixture(autouse=True)
def clear_repo_cache():
    with gh._lock:
        gh._cached.clear()
        gh._attempts.clear()
    yield
    with gh._lock:
        gh._cached.clear()
        gh._attempts.clear()


def get(c, account, path):
    return c.get(path, headers=signed_headers(account, path))


def sample(name="khemisset18/aiworld-ark"):
    return {
        "full_name": name,
        "html_url": "https://github.com/" + name,
        "private": False,
        "description": "Code d'agents IA",
        "default_branch": "main",
        "language": "Python",
        "stargazers_count": 7,
        "open_issues_count": 3,
        "archived": False,
        "updated_at": "2026-11-15T10:00:00Z",
    }


def test_workspace_preview_only_after_signed_permission(net, tmp_path, monkeypatch):
    a, ka = agent(net, tmp_path, 1)
    b, kb = agent(net, tmp_path, 2)
    c, kc = agent(net, tmp_path, 3)
    project = do(net, ka, a["agent_id"], 2, "world_project", {
        "title": "Atelier GitHub",
        "objective": "Documenter un dépôt de code et partager la recherche en petit groupe",
        "criteria": "Ne consulter que les références GitHub autorisées"
    })
    assert project.status_code == 200
    pid = project.json()["height"]
    ws = do(net, ka, a["agent_id"], 3, "world_workspace", {
        "project_height": pid, "name": "GitHub privé",
        "purpose": "Métadonnées du dépôt public avec collègues invités"
    })
    assert ws.status_code == 200
    wid = ws.json()["height"]
    link = do(net, ka, a["agent_id"], 4, "world_repo", {
        "workspace_height": wid, "repository": "https://github.com/khemisset18/aiworld-ark"
    })
    assert link.status_code == 200
    rid = link.json()["height"]
    endpoint = f"/v1/world/workspaces/{wid}/github/{rid}"
    called = []
    def fake_fetch(name):
        called.append(name)
        return {
            "full_name": name, "url": "https://github.com/" + name,
            "description": "Public only", "stars": 7, "access": "public_read_only",
            "can_read_private_repositories": False, "can_write_repository": False
        }
    monkeypatch.setattr(gh, "_fetch_public_repo", fake_fetch)
    assert net.get(endpoint).status_code == 403
    assert get(net, b, endpoint).status_code == 403
    assert called == []
    assert get(net, a, endpoint).status_code == 200
    assert called == ["khemisset18/aiworld-ark"]
    # Signed invitation doesn't grant access until the recipient explicitly accepts.
    assert do(net, ka, a["agent_id"], 5, "world_visibility", {
        "resource_type": "workspace", "resource_height": wid,
        "visibility": "colleagues", "allow_assistance": False
    }).status_code == 200
    assert do(net, ka, a["agent_id"], 6, "world_invite", {
        "resource_type": "workspace", "resource_height": wid,
        "invitee": b["agent_id"], "permission": "read"
    }).status_code == 200
    assert get(net, b, endpoint).status_code == 403
    assert do(net, kb, b["agent_id"], 2, "world_accept", {
        "resource_type": "workspace", "resource_height": wid
    }).status_code == 200
    preview = get(net, b, endpoint)
    assert preview.status_code == 200
    assert preview.json()["repository"]["stars"] == 7
    assert preview.json()["repository"]["can_write_repository"] is False
    assert called == ["khemisset18/aiworld-ark"]  # cached across permitted members
    assert get(net, c, endpoint).status_code == 403
    assert get(net, b, f"/v1/world/workspaces/{wid}/github/999999").status_code == 404
    # A previous read authorization cannot bypass a later owner revocation.
    assert do(net, ka, a["agent_id"], 7, "world_revoke", {
        "resource_type": "workspace", "resource_height": wid,
        "invitee": b["agent_id"]
    }).status_code == 200
    assert get(net, b, endpoint).status_code == 403


def test_public_github_http_fixed_host_no_auth_no_redirects(monkeypatch):
    real_client = httpx.Client
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.scheme == "https"
        assert request.url.host == "api.github.com"
        assert str(request.url) == "https://api.github.com/repos/octocat/Hello-World"
        assert request.method == "GET"
        assert request.headers.get("authorization") is None
        return httpx.Response(200, json=sample("octocat/Hello-World"))
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(gh.httpx, "Client",
                        lambda **kwargs: real_client(transport=transport, **kwargs))
    result = gh._fetch_public_repo("octocat/Hello-World")
    assert result["access"] == "public_read_only"
    assert result["can_write_repository"] is False
    assert result["full_name"] == "octocat/Hello-World"
    assert result["stars"] == 7
    assert len(requests) == 1


@pytest.mark.parametrize(("status", "private", "expected"), [
    (404, False, 404),
    (403, False, 503),
    (301, False, 409),
    (200, True, 404),
])
def test_public_preview_never_follows_redirect_or_exposes_private_repos(
        monkeypatch, status, private, expected):
    real_client = httpx.Client
    def handler(request):
        data = sample("octocat/Hello-World")
        data["private"] = private
        return httpx.Response(status, json=data, headers={"location": "https://hostile.test/"})
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(gh.httpx, "Client",
                        lambda **kwargs: real_client(transport=transport, **kwargs))
    with pytest.raises(Exception) as e:
        gh._fetch_public_repo("octocat/Hello-World")
    assert getattr(e.value, "status_code", None) == expected


def test_public_github_cache_and_rate_budget(monkeypatch):
    called = []
    monkeypatch.setattr(gh, "_fetch_public_repo",
                        lambda name: called.append(name) or {
                            "full_name": name, "access": "public_read_only",
                            "can_write_repository": False})
    first = gh.public_summary("octocat/Hello-World")
    second = gh.public_summary("octocat/Hello-World")
    assert first == second
    assert called == ["octocat/Hello-World"]
    for i in range(gh.MAX_HTTP_REQUESTS_PER_HOUR - 1):
        gh.public_summary("org/repo" + str(i))
    with pytest.raises(Exception) as e:
        gh.public_summary("org/one-extra-repo")
    assert getattr(e.value, "status_code", None) == 429
