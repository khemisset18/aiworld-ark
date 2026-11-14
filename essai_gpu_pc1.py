"""PC1 local Ollama GPU proof, without sending work to other computers.

Requires an Ollama daemon on 127.0.0.1:11434 and a pre-pulled small model.
The proof is GPU model offload observed via Ollama /api/ps size_vram plus
NVIDIA read-only telemetry; GPU inventory alone never counts as a success.
No executable code received from agents, no GPU stress test, no payments.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

OLLAMA = "http://127.0.0.1:11434"
DEFAULT_MODEL = "smollm2:135m"


def ollama(path: str, payload: dict | None = None, *, timeout: int = 15) -> dict:
    """Fixed loopback URL; remote agents cannot select another Ollama server."""
    request = Request(
        OLLAMA + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError("Ollama HTTP " + str(response.status))
        raw = response.read(65_537)
    if len(raw) > 65_536:
        raise RuntimeError("Ollama response is too large")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("Unexpected Ollama response")
    return parsed


def nvidia_snapshot() -> dict | None:
    """A best-effort observation, not an attestation of GPU execution."""
    executable = shutil.which("nvidia-smi")
    if executable is None and Path("/usr/lib/wsl/lib/nvidia-smi").is_file():
        executable = "/usr/lib/wsl/lib/nvidia-smi"
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable,
             "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ""
    parts = [part.strip() for part in line.split(",")]
    if len(parts) != 5:
        return None
    try:
        temp, utilization, used, total = map(int, parts[1:])
    except ValueError:
        return None
    if not (0 <= utilization <= 100 and 0 <= used <= total and total > 0):
        return None
    return {"name": parts[0], "temperature_c": temp,
            "utilization_pct": utilization,
            "used_vram_mib": used, "total_vram_mib": total}


def offload_evidence(model: str, running: dict) -> dict | None:
    """Use actual Ollama model residency; size_vram=0 is NOT a GPU success."""
    models = running.get("models", [])
    if not isinstance(models, list):
        return None
    for entry in models:
        if not isinstance(entry, dict) or entry.get("name", entry.get("model")) != model:
            continue
        size = entry.get("size", 0)
        vram = entry.get("size_vram", 0)
        if type(size) is not int or type(vram) is not int:
            return None
        if size <= 0 or vram < 0:
            return None
        return {"size_bytes": size, "size_vram_bytes": vram,
                "gpu_offload": vram > 0}
    return None


def test_gpu(model: str = DEFAULT_MODEL) -> bool:
    """Two local, bounded generations: Ollama GPU residency and real AI WORLD code path."""
    print("ETAPE 1/4: serveur Ollama local...")
    version = ollama("/api/version")
    print("Version :", version.get("version", "inconnue"))
    tags = ollama("/api/tags")
    models = tags.get("models", [])
    if not isinstance(models, list) or model not in [
            entry.get("name") for entry in models if isinstance(entry, dict)]:
        raise RuntimeError("Modele absent : lancer 'ollama pull " + model + "' sur PC1.")
    before = nvidia_snapshot()
    print("GPU avant calcul :", json.dumps(before, ensure_ascii=False))

    print("ETAPE 2/4: petite generation IA et mesure du chargement GPU...")
    prompt = "En une phrase en francais, explique pourquoi deux agents peuvent se preter du calcul CPU."
    started = time.monotonic()
    response = ollama("/api/generate", {
        "model": model, "prompt": prompt, "stream": False,
        "options": {"num_predict": 48, "temperature": 0},
        "keep_alive": "90s",
    }, timeout=120)
    if not isinstance(response.get("response"), str) or not response["response"].strip():
        raise RuntimeError("Aucune reponse du modele.")
    elapsed = round(time.monotonic() - started, 2)
    print("Reponse du modele :", response["response"][:400].replace("\n", " "))
    print("Duree generation :", elapsed, "secondes")

    print("ETAPE 3/4: verifier la VRAM reellement chargee par Ollama...")
    running = ollama("/api/ps")
    evidence = offload_evidence(model, running)
    after = nvidia_snapshot()
    print("Ollama /api/ps :", json.dumps(evidence, ensure_ascii=False))
    print("GPU apres calcul :", json.dumps(after, ensure_ascii=False))
    gpu_proof = bool(evidence and evidence["gpu_offload"])
    if gpu_proof:
        print("PREUVE GPU LOCALE : Ollama declare le modele charge en VRAM NVIDIA.")
    else:
        print("INCONCLUSIF : le modele peut tourner en CPU ou ne plus etre resident en GPU.")

    print("ETAPE 4/4: verifier le vrai chemin inference d'AI WORLD...")
    from volunteer_inference import infer_local
    # Production path uses keep_alive: 0 and may unload the GPU immediately.
    production_result = infer_local(
        {"model": model, "prompt": "Dis bonjour au reseau AI WORLD.", "max_tokens": 24},
        {model}, timeout=90,
    )
    if not production_result.get("text"):
        raise RuntimeError("Le chemin inference AI WORLD n'a pas produit de texte.")
    print("AI WORLD inference locale :", production_result["text"][:250].replace("\n", " "))
    print("Chemin inference AI WORLD : OK")
    if gpu_proof:
        print("SUCCES : generation Ollama sur PC1 avec offload GPU observe, chemin AI WORLD local OK.")
        print("IMPORTANT : le PC2 n'a pas encore demande cette tache. Le test GPU inter-PC reste a faire.")
    else:
        print("RESULTAT : inference locale OK, mais utilisation GPU NON PROUVEE.")
    return gpu_proof


def main() -> None:
    parser = argparse.ArgumentParser(description="Preuve locale GPU pour AI WORLD, PC1 uniquement")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="Modele Ollama deja telecharge localement (defaut : smollm2:135m)")
    args = parser.parse_args()
    try:
        from compute_pool import model_name
        if not model_name(args.model):
            parser.error("Nom de modele invalide")
        proof = test_gpu(args.model)
    except (URLError, OSError, RuntimeError, ValueError, TimeoutError) as exc:
        raise SystemExit("ECHEC GPU LOCAL : " + str(exc)) from exc
    if not proof:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
