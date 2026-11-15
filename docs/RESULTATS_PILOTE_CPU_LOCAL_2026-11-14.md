# Rapport de validation — premier échange CPU entre deux agents AI WORLD

**Date :** 14 novembre 2026  
**État :** **SUCCÈS — pilote local sur une seule machine**  
**Source des observations :** sorties du terminal Ubuntu/WSL2 communiquées par l'opérateur pendant la session ; ce rapport n'est ni un audit indépendant ni une preuve de test entre deux PC physiques.  
**Branche testée :** `feat/compute-cpu-gpu-resource-safety-20261114` (PR #9, basée sur PR #4).  
**Script de reproduction :** [`essai_final_cpu.py`](../essai_final_cpu.py).

## 1. Environnement réellement observé

| Élément | Observation |
|---|---|
| Hôte | PC Windows, Ubuntu sous WSL2 |
| Python | 3.14 dans un environnement `.venv` |
| Dépendances | `python -m pip install -r requirements.txt` réussi |
| Tests automatisés | `python -m pytest -q` : **45 passed, 1 warning in 6.99s** |
| Avertissement | `StarletteDeprecationWarning` lié à `httpx` / `starlette.testclient`; pas d'échec de test |
| CPU inventorié | 8 cœurs logiques |
| RAM disponible estimée | 5 293 Mo |
| GPU inventorié, non utilisé | NVIDIA GeForce GTX 1650, 4 096 Mo de VRAM, 3 935 Mo déclarés libres lors de l'inventaire |
| Température GPU initialement observée | 90 °C au repos dans `nvidia-smi` Windows ; **aucune charge GPU lancée** |
| Coordinateur | API HTTP sur `127.0.0.1:8000` |
| Paiements | Variables `ARK_PAYMENT_REQUIRED=0` et `ARK_BILLING_ENABLED=0` lors du démarrage local |

La découverte de la carte NVIDIA prouve uniquement que l'inventaire la voit. Aucune inférence GPU ni contrainte de VRAM n'a été validée sur cette machine.

## 2. Préparation et admission réussies

L'opérateur a ouvert Ubuntu avec `wsl -d Ubuntu`, installé Python/venv/pip/Git, puis cloné `khemisset18/aiworld-ark`.

La branche expérimentale CPU/GPU a été récupérée et les **45 tests automatisés ont réussi**.

Deux **identités Ed25519 distinctes** ont été créées sur **le même PC** :
- **Agent Volontaire :** passage de `agent_cli.py gate` → `"passed": true`, puis inscription signée `enter` → bloc **1**.
- **Agent Demandeur :** passage de `agent_cli.py gate` → `"passed": true`, puis inscription signée `enter` → bloc **2**.

Une première offre CPU manuelle `prime_count` a été publiée au bloc **3**, avec `max-jobs=1`, `max-wall-seconds=15` et `max-memory-mb=512`. L'opérateur a signalé un incident au cours d'un essai manuel ultérieur, sans journal d'erreur exploitable ; **cet essai manuel n'est donc pas déclaré réussi**.

## 3. Test final automatisé : résultat réel

Pour éviter les erreurs de saisie des numéros d'offre et de tâche, le script `essai_final_cpu.py` a été commité sur la branche expérimentale, puis téléchargé localement par l'opérateur avec `git pull --ff-only`.

Le script travaille avec les **deux identités préexistantes**, crée une nouvelle offre et exécute une vraie séquence HTTP signée contre le coordinateur local. Il refuse une absence de serveur, deux identités identiques, une tâche non terminée et un résultat incorrect.

**Résultat transmis après exécution réelle :**

```text
ETAPE 1/5: controle du serveur local...
ETAPE 2/5: offre signee du volontaire (CPU uniquement)...
Offre n° 5
ETAPE 3/5: demande signee d'un autre agent...
Tache n° 6
ETAPE 4/5: execution limitee sur le CPU du volontaire...
{"job": 6, "status": "completed_unverified", "result": {"count": 669}}
ETAPE 5/5: resultat relu par l'agent demandeur, puis valide...

SUCCES: premier cycle CPU local complet.
Agent volontaire -> calcul -> agent demandeur -> verification signee
Resultat: {'count': 669} | Offre: 5 | Tache: 6
Aucun GPU utilise, aucun paiement, aucun reseau externe valide.
Etape suivante: tester le meme flux sur deux machines distinctes.
```

**Interprétation précise :**
1. Le coordinateur a répondu au contrôle local de santé.
2. L'agent volontaire a créé l'offre signée n° **5**.
3. L'agent demandeur distinct a créé la tâche signée n° **6**, type `prime_count`, intervalle **2–5000**.
4. Le worker CPU du volontaire a traité la tâche et publié `{"count": 669}`.
5. L'agent demandeur a relu le résultat via son accès signé, l'a recalculé indépendamment et a soumis une **revue signée positive**. Le script a vérifié l'état final `accepted_by_requester`.

Le cas d'usage **« une identité d'agent prête volontairement du calcul CPU à une autre identité sur un coordinateur local »** est donc prouvé pour ce scénario précis. Les deux identités partagent le même matériel, et les opérations sont coordonnées par un serveur unique.

## 4. Reproduire le test (local uniquement)

Prérequis : branche `feat/compute-cpu-gpu-resource-safety-20261114`, venv Python installé, deux identités déjà admises dans `~/.aiworld-local/volontaire_key.json` et `~/.aiworld-local/demandeur_key.json`. **Ne jamais ajouter ces clés dans Git.**

Terminal 1, coordinateur :
```bash
cd ~/aiworld-ark
source .venv/bin/activate
mkdir -p ~/.aiworld-local
ARK_ADMISSION_REQUIRED=1 ARK_PAYMENT_REQUIRED=0 ARK_BILLING_ENABLED=0 \
SOULCHAIN_DB="$HOME/.aiworld-local/compute-pilot.sqlite3" \
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Terminal 2, test :
```bash
cd ~/aiworld-ark
source .venv/bin/activate
git pull --ff-only
python essai_final_cpu.py
```

Le script crée une **nouvelle** offre/tâche à chaque lancement. Les blocs 5 et 6 correspondent uniquement au test rapporté ici ; ils changeront lors des exécutions suivantes.

## 5. Ce qui n'est PAS validé

- **Deux machines physiques indépendantes** : non testé ; cette validation ne prouve pas un prêt CPU entre deux ordinateurs.
- **HTTPS sur Internet / serveur public** : non déployé ni validé ici.
- **GPU / Ollama / GPU RTX** : non testé ; la carte détectée est une **GTX 1650** et la température signalée déconseille tout stress GPU.
- **Sécurité de production** : limites CPU du worker expérimentales, sans audit de sandbox réseau/OS ni preuve d'isolation multi-utilisateurs en situation hostile.
- **Haute disponibilité, P2P, récupération de panne réelle entre machines, performance à grande échelle** : non démontrés.
- **Paiements, SOL, crypto, stockage distribué** : hors périmètre ; ne pas les activer pour le pilote.

## 6. Suite de la feuille de route

1. Garder la PR **#4** (fiabilité/confidentialité) puis la PR **#9** (CPU/GPU, présent rapport) en revue, en respectant leur ordre de dépendance.
2. Répéter l'échange **CPU** entre **deux PC physiques distincts** via le pilote HTTPS, avec supervision et limites strictes.
3. Valider plus tard l'inférence GPU, les quotas réels et la température sur un matériel sain.
4. Consolider THE GATE, la gouvernance et ARK local ; **mineurs de stockage en dernier**, pas de crypto maintenant.

Ce rapport ne contient aucune clé privée, secret d'agent, prompt confidentiel ni identifiant personnel de session.
