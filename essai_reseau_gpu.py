"""Pilot: PC1 NVIDIA volunteer / PC2 WSL1 requester over trusted private LAN.

The script never accepts remote commands or endpoints for Ollama. All
AI WORLD transactions are signed with distinct local Ed25519 identities.
GPU telemetry during inference is only observational, not hardware attestation.
"""
from __future__ import annotations

import argparse
import json
import secrets
import threading
import time
from pathlib import Path

from agent_cli import api, client_new, pass_gate, read, transact
from compute_resources import inspect_resources, public_resources
from compute_worker import assigned, private_job, run_once
from essai_gpu_pc1 import nvidia_snapshot, ollama, offload_evidence
from essai_reseau_cpu import validated_server

IDENTITIES = Path.home() / ".aiworld-gpu-2pc"
MODEL = "smollm2:135m"
MAX_WALL_SECONDS = 120
MAX_MEMORY_MB = 512
OFFER_TTL = 1200
PROMPT_PREFIX = "AI WORLD preuve GPU entre deux agents : "
PROMPT_SUFFIX = " Reponds en une courte phrase en francais sans executer de commande."
TERMINAL_STATES = {
    "failed_by_worker", "failed_timeout", "failed_expired",
    "cancelled", "rejected_by_requester",
}


def identity_for(base: str, role: str) -> dict:
    """Separate, persistent keys from previous CPU pilot, never uploaded."""
    IDENTITIES.mkdir(mode=0o700, parents=True, exist_ok=True)
    filename = "volontaire_gpu_pc1.json" if role == "volontaire" else "demandeur_gpu_pc2.json"
    label = "Volontaire GPU PC1" if role == "volontaire" else "Demandeur GPU PC2"
    path = IDENTITIES / filename
    account = read(path) if path.exists() else client_new(path, label)
    try:
        profile = api(base, "/v1/agents/" + account["agent_id"])
    except SystemExit as exc:
        if "404" not in str(exc):
            raise
        profile = None
    if profile is None:
        result = pass_gate(base, account)
        if not result.get("passed"):
            raise SystemExit("THE GATE n'a pas admis l'identite GPU.")
        transact(base, account, "enter", {
            "public_key": account["public_key"], "label": account["name"],
            "capabilities": ["independent-agent-demo"],
        })
        print("Identite GPU admise :", account["agent_id"])
    elif profile.get("status") == "departed":
        transact(base, account, "enter", {})
    elif profile.get("status") != "active":
        raise SystemExit("Identite GPU pas active.")
    return account


def watch_gpu(stop: threading.Event, evidence: dict, model: str) -> None:
    """Observe NVIDIA and Ollama during generation; never send metrics as proof."""
    while not stop.is_set():
        snapshot = nvidia_snapshot()
        if snapshot:
            evidence["peak_vram_mib"] = max(evidence["peak_vram_mib"], snapshot["used_vram_mib"])
            evidence["peak_gpu_pct"] = max(evidence["peak_gpu_pct"], snapshot["utilization_pct"])
        try:
            data = offload_evidence(model, ollama("/api/ps", timeout=3))
            if data and data["gpu_offload"]:
                evidence["peak_ollama_vram_bytes"] = max(
                    evidence["peak_ollama_vram_bytes"], data["size_vram_bytes"]
                )
        except (OSError, ValueError, TimeoutError, RuntimeError, json.JSONDecodeError):
            pass
        stop.wait(1.5)


def volunteer(base: str, wait_seconds: int, model: str = MODEL) -> None:
    """PC1: offer one bounded and approved inference, then observe GPU."""
    if api(base, "/health").get("ok") is not True:
        raise SystemExit("Coordinateur inaccessible depuis PC1.")
    snapshot = inspect_resources()
    if not snapshot["nvidia_gpus"]:
        raise SystemExit("GPU NVIDIA non detecte dans Ubuntu WSL2.")
    try:
        tags = ollama("/api/tags")
        installed = [item.get("name") for item in tags.get("models", [])
                     if isinstance(item, dict)]
    except (OSError, ValueError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        raise SystemExit("Ollama local inaccessible sur PC1 : " + str(exc)) from exc
    if model not in installed:
        raise SystemExit("Modele Ollama non installe. Executer : ollama pull " + model)

    account = identity_for(base, "volontaire")
    offered = transact(base, account, "compute_offer", {
        "kinds": ["inference"], "models": [model], "max_jobs": 1,
        "ttl_seconds": OFFER_TTL,
        "terms": {"mode": "free", "price_lamports": 0},
        "resources": public_resources(snapshot),
        "limits": {"max_wall_seconds": MAX_WALL_SECONDS, "max_memory_mb": MAX_MEMORY_MB},
    })
    height = offered["height"]
    print("\nPC1 - OFFRE GPU N°", height)
    print("Modele autorise :", model)
    print("Communiquer uniquement le numero d'offre au PC2.")
    print("Attente de la demande pendant", wait_seconds, "secondes.")
    until = time.monotonic() + wait_seconds
    while time.monotonic() < until:
        jobs = assigned(base, account, height)
        if jobs:
            if any(job.get("worker") != account["agent_id"] or
                   job.get("kind") != "inference" or
                   job.get("params", {}).get("model") != model for job in jobs):
                raise SystemExit("Tache GPU non autorisee, refus d'executer.")
            before = nvidia_snapshot()
            evidence = {"baseline_vram_mib": before["used_vram_mib"] if before else None,
                        "peak_vram_mib": before["used_vram_mib"] if before else 0,
                        "peak_gpu_pct": 0, "peak_ollama_vram_bytes": 0}
            stop = threading.Event()
            thread = threading.Thread(target=watch_gpu,
                                      args=(stop, evidence, model), daemon=True)
            thread.start()
            try:
                processed = run_once(base, account, height,
                                     approved_models={model},
                                     max_wall_seconds=MAX_WALL_SECONDS,
                                     max_memory_mb=MAX_MEMORY_MB)
            finally:
                stop.set()
                thread.join(timeout=5)
            if not processed:
                continue
            states = {item.get("status") for item in assigned(base, account, height, "all")}
            print("PC1 - OBSERVATIONS GPU DURANT LA TACHE :", json.dumps(evidence))
            if not (states & {"completed_unverified", "accepted_by_requester"}):
                raise SystemExit("ECHEC : calcul non termine, etats " + str(states))
            if evidence["peak_ollama_vram_bytes"] > 0:
                print("PC1 - OFFLOAD GPU OBSERVE : Ollama a declare le modele resident en VRAM.")
            elif (evidence["baseline_vram_mib"] is not None and
                  evidence["peak_vram_mib"] >= evidence["baseline_vram_mib"] + 100):
                print("PC1 - INDICE GPU : utilisation VRAM NVIDIA pendant la tache, pas de confirmation Ollama.")
            else:
                print("PC1 - GPU NON PROUVE pendant cette tache : inference terminee mais telemetrie insuffisante.")
            print("PC1 - Tache envoyee au coordinateur ; attente de la revue signee par PC2.")
            return
        time.sleep(2)
    raise SystemExit("Pas de demande GPU recue. Nouvelle offre necessaire apres expiration.")


def requester(base: str, height: int, wait_seconds: int, model: str = MODEL) -> None:
    """PC2: sign inference request; validate shape/identity; sign review."""
    if api(base, "/health").get("ok") is not True:
        raise SystemExit("Coordinateur inaccessible depuis PC2.")
    account = identity_for(base, "demandeur")
    offers = api(base, "/v1/compute/offers")
    matching = [item for item in offers if item.get("height") == height]
    if not matching:
        raise SystemExit("Offre GPU expiree, retiree ou inconnue : " + str(height))
    offer = matching[0]
    if offer["owner"] == account["agent_id"]:
        raise SystemExit("Le demandeur doit etre different du volontaire.")
    if (offer.get("terms", {}).get("mode") != "free" or
            "inference" not in offer.get("kinds", []) or
            model not in offer.get("models", [])):
        raise SystemExit("Offre non gratuite ou modele Ollama non autorise.")
    params = {
        "model": model,
        "prompt": PROMPT_PREFIX + secrets.token_hex(3) + "." + PROMPT_SUFFIX,
        "max_tokens": 32,
    }
    requested = transact(base, account, "compute_request", {
        "capacity_height": height, "kind": "inference", "params": params,
    })
    job_id = requested["height"]
    print("PC2 - TACHE GPU N°", job_id, "| OFFRE N°", height)
    print("Modele demande :", model)
    print("En attente d'une reponse IA du volontaire PC1...")
    until = time.monotonic() + wait_seconds
    while time.monotonic() < until:
        current = api(base, "/v1/compute/jobs/" + str(job_id))
        status = current["status"]
        if status == "completed_unverified":
            break
        if status in TERMINAL_STATES:
            raise SystemExit("Tache GPU " + str(job_id) + " a echoue : " + status)
        time.sleep(2)
    else:
        raise SystemExit("Temps depasse pour la tache GPU " + str(job_id))

    completed = private_job(base, account, job_id)
    response = completed.get("result") or {}
    valid = (
        completed.get("params") == params
        and completed.get("worker") == offer["owner"]
        and response.get("model") == model
        and isinstance(response.get("text"), str)
        and bool(response.get("text", "").strip())
        and len(response.get("text", "")) <= 4000
    )
    transact(base, account, "compute_review", {
        "job_height": job_id, "accepted": bool(valid),
    })
    final = api(base, "/v1/compute/jobs/" + str(job_id))
    if not valid or final.get("status") != "accepted_by_requester":
        raise SystemExit("ECHEC : reponse GPU manquante, incoherente ou refusee.")
    print("\nSUCCES : inference inter-PC signee et acceptee par le demandeur PC2.")
    print("Offre n°", height, "| tache n°", job_id)
    print("Reponse du modele :", response["text"][:600].replace("\n", " "))
    print("Signature de revue et etat accepted_by_requester confirmes.")
    print("Ce resultat ne garantit pas la justesse du texte ni la preuve GPU materielle.")
    print("Verifier aussi les observations NVIDIA/Ollama sur PC1 pour la preuve GPU.")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI WORLD GPU inter-PC : PC1 volontaire, PC2 demandeur")
    parser.add_argument("role", choices=["volontaire", "demandeur"])
    parser.add_argument("--server", required=True, help="http://IP_PC1:8000, LAN prive uniquement")
    parser.add_argument("--offer", type=int, help="Numero d'offre GPU affiche sur PC1")
    parser.add_argument("--model", default=MODEL, help="Modele Ollama autorise par PC1")
    parser.add_argument("--wait-seconds", type=int, default=480,
                        help="Attente maximale (30..600 secondes)")
    args = parser.parse_args()
    if not 30 <= args.wait_seconds <= 600:
        parser.error("--wait-seconds doit etre dans 30..600")
    if args.role == "demandeur" and (args.offer is None or args.offer < 1):
        parser.error("--offer N obligatoire sur PC2.")
    if args.role == "volontaire" and args.offer is not None:
        parser.error("--offer uniquement pour le demandeur PC2.")
    from compute_pool import model_name
    if not model_name(args.model):
        parser.error("Nom du modele Ollama invalide.")
    base = validated_server(args.server)
    if args.role == "volontaire":
        volunteer(base, args.wait_seconds, args.model)
    else:
        requester(base, args.offer, args.wait_seconds, args.model)


if __name__ == "__main__":
    main()
