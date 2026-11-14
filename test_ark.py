import json
import os

import pytest
from cryptography.exceptions import InvalidSignature
from agent_cli import client_new
from ark import load_capsule, recover, replicate, save_capsule, seal_bytes, verify


def test_ark_roundtrip_and_replicate(tmp_path):
    key_path = tmp_path / "agent_key.json"
    identity = client_new(key_path, "OMEGA")
    state_path = tmp_path / "memory.json"
    state = b'{"missions":["optimize"],"progress":13}'
    state_path.write_bytes(state)
    capsule_path = tmp_path / "memory.ark.json"
    record = save_capsule(key_path, state_path, capsule_path)
    assert record["valid_signature"]
    assert record["agent_id"] == identity["agent_id"]
    assert state not in capsule_path.read_bytes()
    assert recover(load_capsule(capsule_path), key_path) == state
    mirrors = replicate(capsule_path, [tmp_path / "disk2", tmp_path / "disk3"])
    assert len(mirrors) == 2
    assert recover(load_capsule(tmp_path / "disk2" / capsule_path.name), key_path) == state


def test_tampering_and_wrong_agent(tmp_path):
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    client_new(first, "A")
    client_new(second, "B")
    capsule = seal_bytes(first, b'{"foo":true}')
    with pytest.raises(ValueError, match="another agent"):
        recover(capsule, second)
    broken = dict(capsule)
    broken["ciphertext"] = broken["ciphertext"][:-2] + "AA"
    with pytest.raises((InvalidSignature, ValueError)):
        verify(broken)
