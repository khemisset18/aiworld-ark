"""Two physical-PC CPU pilot; run volunteer on PC2 and requester on PC1.

Real HTTP and Ed25519 transactions, independent private keys on each computer.
This is a prototype LAN test, not hardware attestation or a production service.
"""
from __future__ import annotations

import argparse
import ipaddress
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from agent_cli import api, client_new, pass_gate, read, transact
from compute_resources import inspect_resources, public_resources
from compute_worker import assigned, calculate, private_job, run_once

IDENTITIES = Path.home() / ".aiworld-2pc"
EXPECTED_KIND = "prime_count"
RESOURCE_LIMITS = {"max_wall_seconds": 15, "max_memory_mb": 512}


def validated_server(raw: str) -> str:
    """Do not allow plain HTTP to a public endpoint by accident."""
    url = urlsplit(raw)
    if url.scheme not in ("http", "https") or not url.hostname or not url.port:
        raise SystemExit("Serveur invalide : utiliser http://IP_LOCALE:8000 ou un HTTPS valide.")
    if url.username or url.password or url.path not in ("", "/") or url.query or url.fragment:
        raise SystemExit("Adresse du serveur : ne fournir que le protocole, l'IP et le port.")
    if url.scheme == "http":
        try:
            address = ipaddress.ip_address(url.hostname)
        except ValueError:
            if url.hostname != "localhost":
                raise SystemExit("HTTP autorise uniquement vers localhost ou une IP locale privee.")
        else:
            if not address.is_private:
                raise SystemExit("HTTP public refuse : utiliser HTTPS pour sortir du reseau prive.")
    return raw.rstrip("/")


def identity_for(base: str, role: str) -> dict:
    """Keep independent credentials on each PC; register only if needed."""
    IDENTITIES.mkdir(mode=0o700, parents=True, exist_ok=True)
    file = IDENTITIES / ("volontaire.json" if role == "volontaire" else "demandeur.json")
    name = "Volontaire PC2 CPU" if role == "volontaire" else "Demandeur PC1"
    account = read(file) if file.exists() else client_new(file, name)
    try:
        info = api(base, "/v1/agents/" + account["agent_id"])
    except SystemExit as error:
        if "404" not in str(error):
            raise
        info = None
    if info is None:
        gate = pass_gate(base, account)
        if not gate.get("passed"):
            raise SystemExit("THE GATE n'a pas valide cette nouvelle identite.")
        transact(base, account, "enter", {
            "public_key": account["public_key"],
            "label": account["name"],
            "capabilities": ["independent-agent-demo"],
        })
        print("Identite admise :", account["agent_id"])
    elif info.get("status") == "departed":
        transact(base, account, "enter", {})
        print("Identite reactivee :", account["agent_id"])
    elif info.get("status") != "active":
        raise SystemExit("Identite non active : " + str(info.get("status")))
    return account


def volunteer(base: str, wait_seconds: int) -> None:
    """PC2: sign a one-job CPU offer and execute exactly one bounded task."""
    if api(base, "/health").get("ok") is not True:
        raise SystemExit("Le coordinateur ne repond pas correctement.")
    account = identity_for(base, "volontaire")
    snapshot = inspect_resources()
    offer = transact(base, account, "compute_offer", {
        "kinds": [EXPECTED_KIND],
        "models": [],
        "max_jobs": 1,
        "ttl_seconds": 600,
        "terms": {"mode": "free", "price_lamports": 0},
        "resources": public_resources(snapshot),
        "limits": RESOURCE_LIMITS,
    })
    height = offer["height"]
    print("\nPC2 - OFFRE CPU N°", height)
    print("Communique uniquement ce numero au PC1.")
    print("Worker volontaire en attente pendant", wait_seconds, "secondes.")
    until = time.monotonic() + wait_seconds
    while time.monotonic() < until:
        processed = run_once(base, account, height,
                             max_wall_seconds=15, max_memory_mb=512)
        if processed:
            tasks = assigned(base, account, height, "all")
            states = {item["status"] for item in tasks}
            if not (states & {"completed_unverified", "accepted_by_requester"}):
                raise SystemExit("ECHEC : le worker a signale une tache non terminee : " + str(states))
            print("PC2 : calcul effectue ; attente de la verification signee sur le PC1.")
            return
        time.sleep(2)
    raise SystemExit("Aucune demande recue avant expiration de l'attente. Relancer pour une nouvelle offre.")


def requester(base: str, offer_height: int, wait_seconds: int) -> None:
    """PC1: request a fresh random CPU challenge, verify independently, review."""
    if api(base, "/health").get("ok") is not True:
        raise SystemExit("Le coordinateur ne repond pas correctement.")
    account = identity_for(base, "demandeur")
    offers = api(base, "/v1/compute/offers")
    offers = [x for x in offers if x["height"] == offer_height]
    if not offers:
        raise SystemExit("Offre n° {} introuvable, expiree ou deja utilisee.".format(offer_height))
    offer = offers[0]
    if offer["owner"] == account["agent_id"]:
        raise SystemExit("Le demandeur ne peut pas etre aussi le volontaire.")
    if offer["terms"]["mode"] != "free" or EXPECTED_KIND not in offer["kinds"]:
        raise SystemExit("Refus : cette offre n'est pas un pret CPU gratuit prime_count.")

    params = {"start": 2, "end": 5000 + secrets.randbelow(200)}
    expected = calculate(EXPECTED_KIND, params)
    requested = transact(base, account, "compute_request", {
        "capacity_height": offer_height,
        "kind": EXPECTED_KIND,
        "params": params,
    })
    task_height = requested["height"]
    print("PC1 - TACHE N°", task_height, "offre n°", offer_height)
    print("Calcul demande : nombres premiers de 2 a", params["end"])
    print("En attente du calcul effectue sur le PC2...")
    until = time.monotonic() + wait_seconds
    while time.monotonic() < until:
        status = api(base, "/v1/compute/jobs/{}".format(task_height))["status"]
        if status == "completed_unverified":
            break
        if status in ("failed_by_worker", "failed_timeout", "failed_expired",
                      "cancelled", "rejected_by_requester"):
            raise SystemExit("ECHEC : tache n° {} : {}".format(task_height, status))
        time.sleep(2)
    else:
        raise SystemExit("Temps ecoule : le volontaire n'a pas termine. Tache n° {}".format(task_height))

    completed = private_job(base, account, task_height)
    valid = (completed["result"] == expected
             and completed["params"] == params
             and completed["worker"] == offer["owner"])
    transact(base, account, "compute_review", {
        "job_height": task_height, "accepted": valid
    })
    final = api(base, "/v1/compute/jobs/{}".format(task_height))
    if not valid or final["status"] != "accepted_by_requester":
        raise SystemExit("ECHEC : le resultat du volontaire est incorrect.")

    print("\nSUCCES : echange CPU signe entre PC1 et PC2 (a confirmer physiquement).")
    print("Offre n°", offer_height, "| tache n°", task_height, "| resultat :", expected)
    print("Demandeur distinct, execution CPU par le volontaire, verification signee.")
    print("Aucun paiement, aucun GPU, aucun code arbitraire execute.")
    print("Ce logiciel ne prouve pas a lui seul que les PC sont physiquement distincts.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI WORLD : pilote CPU sur deux PC du meme reseau prive"
    )
    parser.add_argument("role", choices=["volontaire", "demandeur"])
    parser.add_argument("--server", required=True, help="URL du PC1, ex. http://192.168.1.20:8000")
    parser.add_argument("--offer", type=int, help="Numero d'offre affiche sur le PC2")
    parser.add_argument("--wait-seconds", type=int, default=240,
                        help="Attente maximale en secondes (30..480)")
    args = parser.parse_args()
    if args.wait_seconds < 30 or args.wait_seconds > 480:
        parser.error("--wait-seconds doit etre entre 30 et 480")
    if args.role == "demandeur" and (args.offer is None or args.offer < 1):
        parser.error("Sur le PC1, --offer N est obligatoire.")
    if args.role == "volontaire" and args.offer is not None:
        parser.error("Sur le PC2, --offer n'est pas necessaire.")
    base = validated_server(args.server)
    if args.role == "volontaire":
        volunteer(base, args.wait_seconds)
    else:
        requester(base, args.offer, args.wait_seconds)


if __name__ == "__main__":
    main()
