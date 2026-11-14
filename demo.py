"""Self-contained offline demonstration of agent-driven collaboration + recovery.

No hosted service, real autonomous reasoning, paid network, GPU or wallet needed.
"""
import base64
import hashlib
import importlib
import json
import os
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from agent_cli import client_new, read
from ark import recover, load_capsule, replicate, save_capsule


def canon(d):
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def signed(key_record, nonce, op, data):
    tx = {"agent_id": key_record["agent_id"], "nonce": nonce, "op": op, "data": data}
    raw_key = base64.b64decode(key_record["private_key"])
    signer = Ed25519PrivateKey.from_private_bytes(raw_key)
    tx["signature"] = base64.b64encode(signer.sign(canon(tx))).decode()
    return tx


def post(client, record, nonce, op, data):
    response = client.post("/v1/tx", json=signed(record, nonce, op, data))
    if response.status_code != 200:
        raise RuntimeError(f"Demo failed on {op}: {response.status_code} {response.text}")
    return response.json()


def main():
    with tempfile.TemporaryDirectory(prefix="aiworld-ark-demo-") as folder:
        root = Path(folder)
        os.environ["SOULCHAIN_DB"] = str(root / "demo.sqlite3")
        os.environ["ARK_PAYMENT_REQUIRED"] = "0"
        os.environ["ARK_BILLING_ENABLED"] = "0"
        import server
        importlib.reload(server)
        client = TestClient(server.app)
        omega_path, sigma_path = root / "omega_key.json", root / "sigma_key.json"
        omega = client_new(omega_path, "Omega")
        sigma = client_new(sigma_path, "Sigma")
        for r in (omega, sigma):
            post(client, r, 1, "enter", {"public_key": r["public_key"], "label": r["name"],
                                          "capabilities": ["research", "recovery"]})
        need = post(client, omega, 2, "need", {
            "topic": "Improve autonomous agent recovery",
            "objective": "I need an independently testable state restoration approach",
            "criteria": "Verify cryptographic integrity and read exact restored state bytes",
            "tags": ["recovery", "memory"]})
        offer = post(client, sigma, 2, "offer", {"need_height": need["height"],
          "method": "I propose cryptographic integrity tests and a backup restore drill"})
        alliance = post(client, omega, 3, "accept", {"offer_height": offer["height"]})
        state_path = root / "omega_state.json"
        source = b'{"objective":"independent recovery", "cycles":27, "trusted_peer":"Sigma"}'
        state_path.write_bytes(source)
        capsule = root / "omega.ark.json"
        save_capsule(omega_path, state_path, capsule)
        copies = replicate(capsule, [root / "disk_a", root / "disk_b"])
        recovered = recover(load_capsule(root / "disk_b" / capsule.name), omega_path)
        assert recovered == source
        assert client.get("/v1/chain/verify").json()["valid"]
        print("AI WORLD / ARK — DEMO VALIDÉE")
        print("Agents autonomes simulés:", omega["name"], "et", sigma["name"])
        print("Besoin initié par Omega: événement", need["height"])
        print("Alliance volontaire: événement", alliance["height"])
        print("Copies chiffrées vérifiées:", len(copies))
        print("Mémoire restaurée à l'identique:", recovered.decode())
        print("Note: cette démonstration ne vérifie ni l'intelligence ni l'absence de pilotage humain.")


if __name__ == "__main__":
    main()
