# AI WORLD — résultat du pilote inference PC1 → PC2, 15 novembre 2026

**État final du pilote : échange d'inférence SIGNÉ entre deux PC RÉUSSI, avec offload GPU observé en cours de tâche sur le PC1 et acceptation signée par le PC2.**

Source : journaux de PowerShell transmis par l'opérateur, PC1 puis PC2. Le logiciel ne fournit pas d'attestation matérielle distante.

## Topologie du pilote

- **PC1** Windows/Ubuntu WSL2, IP LAN `192.168.1.132`, coordinateur FastAPI AI WORLD sur :8000, volontaire NVIDIA GTX 1650 + Ollama `0.40.16`, modèle autorisé `smollm2:135m`. Identité du volontaire affichée à l'admission, sans publier sa clé privée.
- **PC2** HP ProBook/Ubuntu WSL1, demandeur via le réseau privé. Le `curl.exe --max-time 10 http://192.168.1.132:8000/health` sur PC2 a répondu `{"ok":true}`.
- **Offre GPU signée PC1 : n° 19**, volontaire en attente 480 s. Modèle `smollm2:135m`.
- **Tâche signée PC2 : n° 21**, offer n° 19.
- **Paiement** : aucun. **Exécution de code transmis par PC2** : aucune.

## Sortie terrain confirmée côté PC2

L'opérateur a exécuté sur PC2 :

```powershell
wsl -d Ubuntu --exec bash -c "cd ~/aiworld-ark && .venv/bin/python -u essai_reseau_gpu.py demandeur --server http://192.168.1.132:8000 --offer 19 --wait-seconds 480"
```

Résultat exact transmis :

```text
Identite GPU admise : 4cec733c0dd150781a497390cdc52038
PC2 - TACHE GPU N° 21 | OFFRE N° 19
Modele demande : smollm2:135m
En attente d'une reponse IA du volontaire PC1...

SUCCES : inference inter-PC signee et acceptee par le demandeur PC2.
Offre n° 19 | tache n° 21
Reponse du modele : "Environnement de 8873cf. Reponds en une courte phrase en francais sans executer de commande."
Signature de revue et etat accepted_by_requester confirmes.
Ce resultat ne garantit pas la justesse du texte ni la preuve GPU materielle.
Verifier aussi les observations NVIDIA/Ollama sur PC1 pour la preuve GPU.
```

## Sortie terrain reçue côté PC1 — GPU observé pendant la tâche

L'opérateur a lancé le volontaire sur **PC1 Windows → Ubuntu WSL2** :

```powershell
wsl -d Ubuntu --exec bash -c "cd ~/aiworld-ark && .venv/bin/python -u essai_reseau_gpu.py volontaire --server http://127.0.0.1:8000 --wait-seconds 480"
```

Sortie exacte transmise depuis PC1 :

```text
Identite GPU admise : ee698ff5fc147ca2e52a21be26b76dd4

PC1 - OFFRE GPU N° 19
Modele autorise : smollm2:135m
Communiquer uniquement le numero d'offre au PC2.
Attente de la demande pendant 480 secondes.
{"job": 21, "status": "completed_unverified", "result": {"model": "smollm2:135m", "text": "\"Environnement de 8873cf. Reponds en une courte phrase en francais sans executer de commande.\""}}
PC1 - OBSERVATIONS GPU DURANT LA TACHE : {"baseline_vram_mib": 0, "peak_vram_mib": 441, "peak_gpu_pct": 6, "peak_ollama_vram_bytes": 381828463}
PC1 - OFFLOAD GPU OBSERVE : Ollama a declare le modele resident en VRAM.
PC1 - Tache envoyee au coordinateur ; attente de la revue signee par PC2.
```

Le relevé local **pendant le traitement de cette tâche 21**, et non une expérience différente, révèle :

| Indicateur | Valeur observée |
|---|---:|
| VRAM GPU NVIDIA avant tâche | 0 Mio |
| Pic VRAM GPU NVIDIA | 441 Mio |
| Pic d'utilisation GPU relevé | 6 % |
| Pic de résidence VRAM déclaré par Ollama | 381 828 463 octets |
| Statut résultat sur PC1 | `completed_unverified` |
| Statut après revue signée sur PC2 | `accepted_by_requester` |

La télémétrie NVIDIA relevée et l'API Ollama corroborent que la GTX 1650 a été mise à contribution pendant le traitement de l'inférence demandée par PC2. Ce résultat n'est **pas** une mesure de performance générale ni une attestation matérielle indépendante.

## Interprétation

**Confirmé :** un agent distinct sur PC2 a soumis une demande d'inférence à l'offre n° 19 du PC1 via le coordinateur ; il a récupéré un texte, contrôlé la cohérence de l'identité du volontaire / modèle / paramètres, a envoyé une revue signée et observé le statut final `accepted_by_requester`. Le protocole réel d'envoi et de retour entre les PC fonctionne.

**Confirmé également sur PC1 :** le worker volontaire a déclaré la tâche n° 21 `completed_unverified`, un passage de **0 à 441 Mio de VRAM**, un pic GPU relevé de **6 %**, et l'API Ollama a confirmé **381 828 463 octets en VRAM** pendant l'inférence. Les deux journaux sont cohérents sur les numéros **offre 19 / tâche 21** et le texte renvoyé. Nous disposons d'une **preuve de pilote GPU inter-PC par observations concordantes**, sans attestation matérielle cryptographique indépendante.

**Limite du modèle :** la réponse citée ressemble à une reprise partielle de la consigne, et ne démontre pas de qualité ou de pertinence sémantique. La revue signée atteste l'acceptation, pas la justesse.

## Prochaine action : fermer la passerelle LAN temporaire

Les deux journaux d'exécution ont été reçus ; **aucun nouveau calcul n'est nécessaire pour valider ce pilote**. La redirection Windows temporaire du port 8000 et la règle `AIWORLD-GPU-PILOT-8000` doivent être **supprimées** suivant le [guide de nettoyage LAN](TEST_GPU_DEUX_PC_LAN.md), puis le retrait doit être vérifié depuis PC1. **Le retrait n'est pas attesté tant que l'opérateur ne transmet pas les résultats du nettoyage.**

Ce pilote est limité à **deux PC connus, un LAN privé, un modèle local explicitement autorisé, 0 paiement**. Ne pas confondre ces preuves avec un service public, un P2P direct, un partage simultané de plusieurs GPU ou une vérification cryptographique indépendante de l'hôte.

**Projet :** [`essai_reseau_gpu.py`](../essai_reseau_gpu.py) · [journal du 15 novembre](JOURNAL_AVANCEES_2026-11-15.md).
