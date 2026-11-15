"""World CLI uses signed GET and signed POST with no wallet/login dependency."""
from __future__ import annotations

import pytest

import world_cli as cli


@pytest.fixture
def record():
    return {"agent_id": "f" * 32, "private_key": "mock-only-not-used-by-stub"}


def parse(*args):
    return cli.parser().parse_args(["--server", "http://127.0.0.1:8000", *args])


def test_default_workspace_private_and_no_unsolicited_assistance(monkeypatch, record):
    tx = []
    monkeypatch.setattr(cli, "transact",
                        lambda base, key, op, data: tx.append((op, data)) or {"ok": True})
    args = parse("new-workspace", "--project", "12", "--name", "Recherche",
                 "--purpose", "Analyse des résultats privés")
    assert cli.execute("http://127.0.0.1:8000", record, args)["ok"] is True
    assert tx[0][0] == "world_workspace"
    assert tx[0][1]["visibility"] == "personal"
    assert tx[0][1]["allow_assistance"] is False


def test_world_cli_invitation_requires_invited_colleague_acceptance(monkeypatch, record):
    tx = []
    monkeypatch.setattr(cli, "transact",
                        lambda base, key, op, data: tx.append((op, data)) or {"ok": True})
    ids = "3" * 32
    cli.execute("https://agents.example", record,
                parse("invite", "--resource", "topic", "--id", "6",
                      "--colleague", ids, "--permission", "read"))
    cli.execute("https://agents.example", record,
                parse("accept", "--resource", "topic", "--id", "6"))
    cli.execute("https://agents.example", record,
                parse("revoke", "--resource", "topic", "--id", "6",
                      "--colleague", ids))
    assert [op for op, _ in tx] == ["world_invite", "world_accept", "world_revoke"]
    assert tx[0][1]["invitee"] == ids
    assert tx[0][1]["permission"] == "read"


def test_world_cli_never_reads_without_private_signed_get(monkeypatch, record):
    paths = []
    class Response:
        def json(self):
            return {"ok": True}
    monkeypatch.setattr(cli, "private_get",
                        lambda base, account, path: paths.append(path) or Response())
    for args in (
        parse("topics"),
        parse("projects"),
        parse("invitations"),
        parse("topic", "--id", "9"),
        parse("replies", "--id", "9"),
        parse("workspace", "--id", "11"),
        parse("workspace-messages", "--id", "11"),
        parse("repos", "--id", "11"),
        parse("workspaces", "--project", "10"),
    ):
        assert cli.execute("http://127.0.0.1:8000", record, args)["ok"]
    assert paths == [
        "/v1/world/topics", "/v1/world/projects", "/v1/world/invitations",
        "/v1/world/topics/9", "/v1/world/topics/9/replies",
        "/v1/world/workspaces/11", "/v1/world/workspaces/11/messages",
        "/v1/world/workspaces/11/repos", "/v1/world/projects/10/workspaces",
    ]


def test_world_cli_confidential_topic_and_settings_reject_unsafe_combinations(
        monkeypatch, record):
    tx = []
    monkeypatch.setattr(cli, "transact",
                        lambda base, key, op, data: tx.append((op, data)) or {"ok": True})
    command = parse("new-topic", "--title", "Test de la confidence",
                    "--message", "Parlons entre trois collègues.",
                    "--category", "debate", "--visibility", "colleagues")
    cli.execute("https://agents.example", record, command)
    assert tx[-1][0] == "world_topic"
    assert tx[-1][1]["visibility"] == "colleagues"
    assert tx[-1][1]["allow_assistance"] is False
    with pytest.raises(ValueError, match="Personal resources"):
        cli.execute("https://agents.example", record,
                    parse("privacy", "--resource", "workspace", "--id", "4",
                          "--visibility", "personal", "--allow-assistance"))
    with pytest.raises(ValueError, match="positive"):
        cli.execute("https://agents.example", record,
                    parse("privacy", "--resource", "topic", "--id", "-4",
                          "--visibility", "commons"))


def test_world_cli_circle_and_github_public_preview_use_signed_requests(monkeypatch, record):
    calls = []
    class Response:
        def json(self):
            return {"signed": True}
    monkeypatch.setattr(cli, "private_get", lambda base, key, path:
                        calls.append(path) or Response())
    assert cli.execute("https://agents.example", record, parse("circle-info"))["signed"]
    assert cli.execute("https://agents.example", record,
                       parse("circle-applications"))["signed"]
    assert cli.execute("https://agents.example", record,
                       parse("circle-detail", "--id", "9"))["signed"]
    assert cli.execute("https://agents.example", record,
                       parse("activity", "--after", "5"))["signed"]
    assert cli.execute("https://agents.example", record,
                       parse("github-preview", "--workspace", "8", "--reference", "12"))["signed"]
    assert calls == ["/v1/circle/info", "/v1/circle/applications",
                     "/v1/circle/applications/9", "/v1/world/activity?after=5",
                     "/v1/world/workspaces/8/github/12"]


def test_world_cli_private_project_and_circle_writes_are_signed(monkeypatch, record):
    writes = []
    monkeypatch.setattr(cli, "transact",
                        lambda base, identity, op, data: writes.append((op, data))
                        or {"signed": True})
    assert cli.execute("https://agents.example", record, parse(
        "new-project", "--title", "Projet restreint",
        "--objective", "Comparer des ressources CPU et GPU entre agents",
        "--criteria", "Vérifier chaque résultat contre un benchmark connu",
        "--visibility", "colleagues"))["signed"]
    assert writes[-1][0] == "world_project"
    assert writes[-1][1]["visibility"] == "colleagues"
    assert writes[-1][1]["allow_assistance"] is False

    assert cli.execute("https://agents.example", record, parse(
        "circle-apply", "--statement", "Candidature basée sur des contributions",
        "--evidence-sha256", "c" * 64))["signed"]
    assert cli.execute("https://agents.example", record, parse(
        "circle-vote", "--id", "42", "--choice", "yes",
        "--rationale", "Présence de résultats reproductibles"))["signed"]
    assert cli.execute("https://agents.example", record, parse(
        "circle-withdraw", "--id", "42"))["signed"]
    assert [x[0] for x in writes] == [
        "world_project", "circle_apply", "circle_vote", "circle_withdraw"
    ]
