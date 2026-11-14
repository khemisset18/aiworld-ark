"""Consent-based local LLM inference for AI WORLD volunteers.

New independent implementation: no GPUbnb code, GPU rental, escrow or shared runtime.
Never accepts executable code, shell commands, user-provided endpoints or remote URLs.
"""
from __future__ import annotations

import json
from urllib.request import Request, urlopen
from compute_pool import validate_params

# Loopback-only: API clients cannot select another address (prevents SSRF).
OLLAMA_LOCAL = "http://127.0.0.1:11434/api/generate"


def infer_local(params: dict, approved_models: set[str], *, timeout: int = 90) -> dict:
    """One fixed-shape, bounded local inference job; worker must opt in to the model."""
    validate_params("inference", params)
    model = params["model"]
    if model not in approved_models:
        raise ValueError("Model not explicitly approved by volunteer worker")
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise ValueError("Invalid local timeout")
    request = Request(
        OLLAMA_LOCAL,
        data=json.dumps({
            "model": model,
            "prompt": params["prompt"],
            "stream": False,
            "options": {"num_predict": params["max_tokens"], "temperature": 0},
            "keep_alive": 0,
        }, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # The volunteer operator chooses whether to start Ollama and which models are installed.
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError("Local inference failed")
        raw = response.read(16000 + 1)
    if len(raw) > 16000:
        raise RuntimeError("Local inference response too large")
    result = json.loads(raw)
    answer = result.get("response")
    if not isinstance(answer, str):
        raise RuntimeError("Missing local model response")
    # Never send more than the agreed output limit back through the coordinator.
    return {"model": model, "text": answer[:4000]}
