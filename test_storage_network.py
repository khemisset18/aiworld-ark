"""End-to-end tests for signed ARK capsules copied across independent miner disks."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_cli import client_new
from ark import canonical, seal_bytes, verify
from storage_miner import create_app
from storage_network import audit, backup, read_peers, restore_latest, verify_manifest, watch_state


def make_network(tmp_path):
    hosts = ["miner-a.test", "miner-b.test", "miner-c.test"]
    token_values = ["A" * 40, "B" * 40, "C" * 40]
    apps = {
        name: TestClient(create_app(root=tmp_path / ("disk-" + name),
                                    token=token,
                                    limit_bytes=64 * 1024 * 1024,
                                    per_agent_bytes=32 * 1024 * 1024))
        for name, token in zip(hosts, token_values)
    }
    down = set()

    def handler(request: httpx.Request):
        hostname = request.url.host
        if hostname in down:
            return httpx.Response(503, json={"detail": "miner offline"})
        local = apps[hostname].request(
            request.method, str(request.url.raw_path.decode()),
            content=request.content, headers=dict(request.headers))
        return httpx.Response(local.status_code, content=local.content,
                              headers={"content-type": local.headers.get("content-type", "application/json")})

    peers = [{"url": "https://" + host, "token": token}
             for host, token in zip(hosts, token_values)]
    return peers, apps, down, httpx.MockTransport(handler)


def test_three_independent_copies_and_restore_when_miner_offline(tmp_path):
    peers, apps, down, transport = make_network(tmp_path)
    identity_path = tmp_path / "identity.json"
    record = client_new(identity_path, "Recovery agent")
    state = b'{"memory":"agent has a private plan","cycles":14}'
    source = tmp_path / "state.json"
    source.write_bytes(state)
    manifest = tmp_path / "backup-manifest.json"
    capsule_path = tmp_path / "original.ark.json"

    saved = backup(identity_path, source, peers, min_copies=3,
                   manifest_path=manifest, transport=transport, capsule_path=capsule_path)
    assert len(saved["replicas"]) == 3
    assert saved["agent_id"] == record["agent_id"]
    assert "private plan" not in canonical(seal_bytes(identity_path, state)).decode()
    signed = json.loads(manifest.read_text())
    assert signed["capsule_sha256"] == saved["capsule_sha256"]
    assert len(signed["signature"]) > 64
    assert verify_manifest(manifest)["capsule_sha256"] == saved["capsule_sha256"]
    assert "token" not in manifest.read_text()
    assert verify(json.loads(capsule_path.read_text()))["capsule_sha256"] == saved["capsule_sha256"]
    checks = audit(identity_path, capsule_path, peers, transport=transport)
    assert all(item["available_now"] for item in checks["checks"])
    assert checks["continuous_storage_proven"] is False

    for host in apps:
        listing = apps[host].get("/v1/storage/agents/" + record["agent_id"] + "/capsules",
                                 headers={"Authorization": "Bearer " + peers[list(apps).index(host)]["token"]})
        assert listing.status_code == 200
        assert listing.json()[0]["digest"] == saved["capsule_sha256"]

    down.add("miner-a.test")
    failed_checks = audit(identity_path, capsule_path, peers, transport=transport)
    assert sum(item["available_now"] for item in failed_checks["checks"]) == 2
    output = tmp_path / "restored.json"
    restored = restore_latest(identity_path, output, peers, transport=transport)
    assert restored["restored"] is True
    assert restored["source"] in ("https://miner-b.test", "https://miner-c.test")
    assert output.read_bytes() == state
    with pytest.raises(FileExistsError):
        restore_latest(identity_path, output, peers, transport=transport)


def test_miner_rejects_unsigned_unencrypted_and_unauthorized_capsules(tmp_path):
    token = "T" * 40
    miner = TestClient(create_app(tmp_path / "miner", token=token))
    identity_path = tmp_path / "identity.json"
    agent = client_new(identity_path, "Agent")
    envelope = seal_bytes(identity_path, b"Secret never passed to miner in plaintext")
    auth = {"Authorization": "Bearer " + token}
    assert miner.get("/health").json()["ready"] is True
    assert miner.post("/v1/storage/capsules", json=envelope).status_code == 401
    good = miner.post("/v1/storage/capsules", json=envelope, headers=auth)
    assert good.status_code == 201, good.text
    digest = good.json()["digest"]
    assert good.json()["already_present"] is False
    assert miner.post("/v1/storage/capsules", json=envelope, headers=auth).json()["already_present"] is True
    assert miner.get(f"/v1/storage/capsules/{agent['agent_id']}/{digest}").status_code == 401

    tampered = dict(envelope, ciphertext=envelope["ciphertext"][:-4] + "AAAA")
    assert miner.post("/v1/storage/capsules", json=tampered, headers=auth).status_code == 400
    assert miner.post("/v1/storage/capsules", json={"state": "plaintext"}, headers=auth).status_code == 400
    assert miner.get(f"/v1/storage/capsules/{agent['agent_id']}/{'0'*64}", headers=auth).status_code == 404

    nonce = "01" * 16
    proof = miner.get(
        f"/v1/storage/capsules/{agent['agent_id']}/{digest}/audit",
        params={"nonce": nonce}, headers=auth)
    raw = canonical(envelope)
    assert proof.status_code == 200
    assert proof.json()["challenge_sha256"] == hashlib.sha256(bytes.fromhex(nonce) + raw).hexdigest()


def test_no_false_claim_when_not_enough_copies(tmp_path):
    peers, _, down, transport = make_network(tmp_path)
    down.update(["miner-b.test", "miner-c.test"])
    identity_path = tmp_path / "agent.json"
    client_new(identity_path, "Agent")
    state = tmp_path / "state.json"
    state.write_bytes(b"lost-cluster-demo")
    manifest = tmp_path / "not-written.json"
    with pytest.raises(RuntimeError, match="Only 1 verified copies"):
        backup(identity_path, state, peers, 2, manifest, transport)
    assert not manifest.exists()


def test_client_protocol_rejects_public_http_and_duplicate_miners(tmp_path):
    file = tmp_path / "miners.json"
    token = "X" * 40
    file.write_text(json.dumps([{"url": "http://remote.test:8080", "token": token}]))
    with pytest.raises(ValueError, match="HTTPS"):
        read_peers(file)
    file.write_text(json.dumps([
        {"url": "https://miner.test", "token": token},
        {"url": "https://miner.test/", "token": token}
    ]))
    with pytest.raises(ValueError, match="Duplicate"):
        read_peers(file)
    file.write_text(json.dumps([{"url": "http://127.0.0.1:8101", "token": token}]))
    assert read_peers(file)[0]["url"] == "http://127.0.0.1:8101"


def test_restore_requires_original_decryption_key(tmp_path):
    peers, _, _, transport = make_network(tmp_path)
    first_identity = tmp_path / "agent1.json"
    other_identity = tmp_path / "agent2.json"
    client_new(first_identity, "First")
    client_new(other_identity, "Other")
    state = tmp_path / "original.json"
    state.write_bytes(b"protected agent state")
    backup(first_identity, state, peers, min_copies=2, transport=transport)
    with pytest.raises(RuntimeError, match="No independently verifiable"):
        restore_latest(other_identity, tmp_path / "wrong.json", peers, transport=transport)
    assert not (tmp_path / "wrong.json").exists()


def test_watch_once_replicates_state_and_signs_manifest(tmp_path):
    peers, _, _, transport = make_network(tmp_path)
    identity = tmp_path / "watching.json"
    agent = client_new(identity, "Watching agent")
    state = tmp_path / "memory.json"
    state.write_bytes(b'{"memory":"checkpoint"}')
    manifests = tmp_path / "receipts"
    watch_state(identity, state, peers, min_copies=2, interval=5,
                once=True, manifest_dir=manifests, transport=transport)
    receipts = list(manifests.glob("*.manifest.json"))
    assert len(receipts) == 1
    signed = verify_manifest(receipts[0])
    assert signed["agent_id"] == agent["agent_id"]
    assert len(signed["replicas"]) == 3
