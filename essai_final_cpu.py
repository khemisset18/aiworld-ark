"""Live local CPU lending smoke test with two existing AI WORLD agent identities.

Launch the local server in another terminal first. This verifies an actual HTTP
round trip and signed transactions on localhost, NOT independent remote hosts.
No GPU jobs or payments are used.
"""
from __future__ import annotations

from pathlib import Path

from agent_cli import api, read, transact
from compute_worker import calculate, private_job, run_once

SERVER = "http://127.0.0.1:8000"
PARAMS = {"start": 2, "end": 5000}
EXPECTED = {"count": 669}


def main() -> None:
    base = Path.home() / ".aiworld-local"
    provider_file = base / "volontaire_key.json"
    requester_file = base / "demandeur_key.json"
    if not provider_file.is_file() or not requester_file.is_file():
        raise SystemExit(
            "ECHEC: fichiers d'identite introuvables. "
            "Creer volontaire_key.json et demandeur_key.json dans ~/.aiworld-local."
        )
    provider = read(provider_file)
    requester = read(requester_file)
    if provider["agent_id"] == requester["agent_id"]:
        raise SystemExit("ECHEC: deux identites d'agents distinctes sont necessaires.")

    print("ETAPE 1/5: controle du serveur local...")
    try:
        health = api(SERVER, "/health")
    except (OSError, ConnectionError, SystemExit) as exc:
        raise SystemExit(
            "ECHEC: serveur local indisponible. Lancer uvicorn dans l'autre terminal. "
            f"Detail: {exc}"
        ) from exc
    if health.get("ok") is not True:
        raise SystemExit("ECHEC: serveur non operationnel.")

    print("ETAPE 2/5: offre signee du volontaire (CPU uniquement)...")
    offered = transact(SERVER, provider, "compute_offer", {
        "kinds": ["prime_count"], "max_jobs": 1, "ttl_seconds": 600,
        "limits": {"max_wall_seconds": 15, "max_memory_mb": 512}
    })
    offer_id = offered["height"]
    print("Offre n°", offer_id)

    print("ETAPE 3/5: demande signee d'un autre agent...")
    requested = transact(SERVER, requester, "compute_request", {
        "capacity_height": offer_id, "kind": "prime_count", "params": PARAMS
    })
    job_id = requested["height"]
    print("Tache n°", job_id)

    print("ETAPE 4/5: execution limitee sur le CPU du volontaire...")
    processed = run_once(SERVER, provider, offer_id, max_wall_seconds=15,
                         max_memory_mb=512)
    if processed != 1:
        raise SystemExit("ECHEC: le worker n'a pas traite de tache.")

    print("ETAPE 5/5: resultat relu par l'agent demandeur, puis valide...")
    job = private_job(SERVER, requester, job_id)
    if job["status"] != "completed_unverified":
        raise SystemExit(
            "ECHEC: tache non achevee. Etat = " + str(job["status"])
        )
    independent_result = calculate("prime_count", PARAMS)
    valid = job.get("result") == EXPECTED == independent_result
    review = transact(SERVER, requester, "compute_review", {
        "job_height": job_id, "accepted": valid
    })
    if not valid:
        raise SystemExit("ECHEC: le resultat CPU est incorrect, revue negative enregistree.")

    final_job = api(SERVER, f"/v1/compute/jobs/{job_id}")
    if final_job.get("status") != "accepted_by_requester":
        raise SystemExit("ECHEC: verification finale non confirmee sur le serveur.")

    print("\nSUCCES: premier cycle CPU local complet.")
    print("Agent volontaire -> calcul -> agent demandeur -> verification signee")
    print("Resultat:", independent_result, "| Offre:", offer_id, "| Tache:", job_id)
    print("Aucun GPU utilise, aucun paiement, aucun reseau externe valide.")
    print("Etape suivante: tester le meme flux sur deux machines distinctes.")


if __name__ == "__main__":
    main()
