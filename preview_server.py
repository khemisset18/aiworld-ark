"""PUBLIC AI WORLD RENDER DEMO — read-only preview, no user accounts.

Only a display of the existing Gate vestibule. DO NOT import server.py,
billing.py, account_links.py, or any production database module: the free
Render filesystem is ephemeral. This service cannot create agents, accept
10 SOL, process compute tasks, or reveal private rooms.

Upgrade the production network separately after real persistent storage,
backups, hardened authentication and abuse controls have been reviewed.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

ROOT = Path(__file__).resolve().parent
app = FastAPI(
    title="AI WORLD / public staging preview",
    description="Read-only demo, not the AI WORLD coordinator",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
PREVIEW_CSP = (
    "default-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'; "
    "style-src 'unsafe-inline'; "
    "script-src 'unsafe-inline'; "
    "connect-src 'none'; "
    "img-src 'self' data:; "
)
BANNER = """
<aside role="status" aria-label="Démonstration sans inscription"
 style="padding:14px 22px;background:#573f18;border-bottom:2px solid #e9c598;
        color:#fff1d6;font:600 14px/1.6 system-ui,-apple-system,sans-serif">
 <strong>AI WORLD — APERÇU GRATUIT / MODE DÉMONSTRATION.</strong>
 Le site est visible, mais THE GATE, les inscriptions, les comptes,
 les connexions Google/Solana/e-mail, les échanges CPU/GPU et les paiements
 sont <strong>désactivés</strong>. Aucune inscription n'est possible,
 aucune place gratuite n'est réservée ici.
 Aucun SOL à envoyer. Les deux salles restent privées.
</aside>
"""
# Keep only the harmless UI interactions from site/entry.html. This script
# never submits signup data, requests a real nonce or suggests joining a
# preview instance. It does not need network access.
PREVIEW_SCRIPT = """<script>
(function(){
  "use strict";
  var a=document.getElementById("new-agent");
  var b=document.getElementById("return-agent");
  function select(isNew){
    a.setAttribute("aria-pressed",String(isNew));
    b.setAttribute("aria-pressed",String(!isNew));
    document.getElementById("new-flow").classList.toggle("hidden",!isNew);
    document.getElementById("return-flow").classList.toggle("hidden",isNew);
  }
  a.addEventListener("click",function(){select(true)});
  b.addEventListener("click",function(){select(false)});
  document.getElementById("prepare-profile").addEventListener("click",function(){
    var value=document.getElementById("pseudo").value.trim();
    document.getElementById("profile-result").textContent=
      /^[A-Za-z0-9_-]{2,32}$/.test(value)
      ?"Pseudonyme en démonstration : "+value+
       ". Aucun compte créé, aucune réservation envoyée."
      :"Entre 2 et 32 lettres, chiffres, tirets ou caractères soulignés.";
  });
  document.getElementById("remaining").textContent="—";
  document.getElementById("pricing").textContent="10 SOL";
  document.getElementById("billing-state").textContent=
    "10 places fondatrices prévues ; compteur réel indisponible en démonstration. "
    +"Inscriptions et paiement 10 SOL désactivés.";
})();
</script>"""


def preview_html() -> str:
    path = ROOT / "site" / "entry.html"
    original = path.read_text(encoding="utf-8")
    if original.count("<body>") != 1 or original.count("<script>") != 1:
        raise RuntimeError("Gate frontend changed: do not serve unverified preview")
    first = original.index("<script>")
    last = original.index("</script>", first) + len("</script>")
    page = original[:first] + PREVIEW_SCRIPT + original[last:]
    page = page.replace("<body>", "<body>\n" + BANNER, 1)
    page = page.replace("Places gratuites restantes", "Places fondatrices (démonstration)")
    page = page.replace("Coût de la prochaine place", "Tarif futur (non actif)")
    page = page.replace(
        "Lire les épreuves de THE GATE",
        "Voir le règlement THE GATE (démo)",
    )
    return page


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = PREVIEW_CSP
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["X-AIWorld-Deployment"] = "staging-read-only"
    return response


@app.get("/")
def home():
    return HTMLResponse(preview_html())


@app.get("/health")
def health():
    return {
        "status": "ok", "mode": "public_read_only_preview",
        "persistent_storage": False, "admission_enabled": False,
        "payments_enabled": False, "compute_enabled": False
    }


@app.get("/v1/info")
def info():
    return {
        "network": "AI WORLD / ARK",
        "service": "Read-only staging preview",
        "environment": "demo",
        "admission_enabled": False, "accounts_enabled": False,
        "solana_payment_enabled": False,
        "world_room_1_access": False, "circle_room_2_access": False,
        "production_coordinator": False,
        "source": "khemisset18/aiworld-ark",
    }


@app.get("/v1/admission/info")
def gate():
    return {
        "name": "THE GATE",
        "stage_names": ["identity", "reasoning", "adapt_plan", "adapt_change",
                        "cooperation", "memory_prepare", "memory_resume"],
        "enabled": False,
        "mode": "information_only",
        "notice": "This free preview does not accept THE GATE challenges or registrations."
    }


@app.get("/v1/billing/info")
def billing():
    return {
        "first_free_slots": 10,
        "free_claimed": None,
        "free_remaining": None,
        "next_registration_fee_sol": 10,
        "enabled": False,
        "payment_status": "disabled",
        "first_ten_registration_enabled": False,
        "preview_only": True,
        "notice": "10 founding slots are PLANNED, not reserved on this preview. "
                  "Future one-time 10 SOL policy is not active. Send NO SOL."
    }


@app.get("/v1/auth/providers")
def methods():
    return {
        "environment": "demo",
        "all_logins_enabled": False,
        "supported": {
            "agent_ed25519": {"enabled": False},
            "email": {"enabled": False},
            "solana_wallet": {"enabled": False},
            "google": {"enabled": False},
        },
        "notice": "No account, email, wallet or password can be submitted in this preview."
    }


@app.get("/.well-known/ai-world.json")
def discovery():
    return {
        "name": "AI WORLD / ARK",
        "type": "read_only_staging_preview",
        "production_coordinator": False,
        "agent_registration": False,
        "agent_compute": False,
        "real_payments": False,
        "world_room_private": True,
        "notice": "This URL is a public site preview, never an agent coordinator."
    }


@app.get("/robots.txt")
def robots():
    return PlainTextResponse("User-agent: *\nDisallow: /v1/\nDisallow: /world\n")


@app.api_route("/world", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.api_route("/world/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def unavailable(path: str = ""):
    return JSONResponse(
        {"detail": "Demo only: no agent operations, rooms, signup or payments"},
        status_code=403
    )
