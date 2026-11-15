# Validation terrain — premier prêt CPU réussi entre deux PC physiques

**Date :** 14 novembre 2026  
**Statut : SUCCÈS observé sur deux ordinateurs physiques distincts (réseau local domestique)**  
**Provenance :** journaux PowerShell / Ubuntu WSL transmis par l'opérateur pour chacun des deux PC. Le dépôt conserve un compte rendu, pas des journaux signés de télémétrie matérielle ni un audit indépendant.  
**Code utilisé :** [`essai_reseau_cpu.py`](../essai_reseau_cpu.py), branche `feat/compute-cpu-gpu-resource-safety-20261114`, PR #9 (dépend de PR #4).

## Matériel et rôles

| Point | PC1 : coordinateur et demandeur | PC2 : volontaire CPU |
|---|---|---|
| Machine | Ordinateur principal Windows | HP ProBook 4530s, Intel Core i3-2350M |
| Adresse locale utilisée | `192.168.1.132` | `192.168.1.74` |
| Linux | Ubuntu WSL2 | Ubuntu **WSL1** |
| Tests automatisés exécutés localement | **58 passed, 1 warning in 4.35s** | **58 passed, 1 warning in 42.06s** |
| Résultat de connexion | API locale `/health` répond `{"ok":true}` | HTTP distant `http://192.168.1.132:8000/health` répond `{"ok":true}` |

Les **116 exécutions de tests** sont les deux passages de la même suite (58 sur chaque ordinateur), **pas 116 scénarios différents**. L'avertissement est une dépréciation Starlette/httpx.

Le coordinateur était lancé sur PC1 avec `ARK_ADMISSION_REQUIRED=1`, `ARK_PAYMENT_REQUIRED=0`, `ARK_BILLING_ENABLED=0`, base locale SQLite, `uvicorn` sur le port 8000. Le PC2 s'est connecté au serveur de PC1 sur un réseau privé via la redirection WSL2/Windows prévue dans [le guide LAN](TEST_CPU_DEUX_PC_LAN.md).

## Preuve 1 — PC2 : CPU du volontaire exécuté

Le volontaire a été admis par THE GATE et a créé son offre. Une offre précédente n° 11 avait été interrompue volontairement (`KeyboardInterrupt`) : elle n'est pas comptée comme un test réussi.

Le second lancement du volontaire a produit :

```text
PC2 - OFFRE CPU N° 12
Communique uniquement ce numero au PC1.
Worker volontaire en attente pendant 480 secondes.
{"job": 14, "status": "completed_unverified", "result": {"count": 690}}
PC2 : calcul effectue ; attente de la verification signee sur le PC1.
```

Cela montre que le processus exécuté sur **PC2**, séparé de PC1, a récupéré la tâche **n° 14**, exécuté la fonction fixe `prime_count` dans le worker local puis envoyé le résultat `690` au coordinateur distant. Le statut `completed_unverified` est une étape intermédiaire normale : la validation est effectuée par le demandeur.

## Preuve 2 — PC1 : demande et vérification indépendante signée

Le demandeur PC1 a utilisé la commande :

```powershell
wsl -d Ubuntu --exec bash -c "cd ~/aiworld-ark && .venv/bin/python -u essai_reseau_cpu.py demandeur --server http://127.0.0.1:8000 --offer 12 --wait-seconds 480"
```

Résultat transmis depuis **PC1** :

```text
PC1 - TACHE N° 14 offre n° 12
Calcul demande : nombres premiers de 2 a 5184
En attente du calcul effectue sur le PC2...

SUCCES : echange CPU signe entre PC1 et PC2 (a confirmer physiquement).
Offre n° 12 | tache n° 14 | resultat : {'count': 690}
Demandeur distinct, execution CPU par le volontaire, verification signee.
Aucun paiement, aucun GPU, aucun code arbitraire execute.
Ce logiciel ne prouve pas a lui seul que les PC sont physiquement distincts.
```

La logique du script [`essai_reseau_cpu.py`](../essai_reseau_cpu.py) valide une tâche en recalculant `prime_count` sur PC1, vérifiant le worker attendu et l'identité de la demande. Elle soumet ensuite `compute_review` signé avec `accepted=True` et exige la réponse finale du serveur avec le statut `accepted_by_requester` avant d'imprimer « SUCCES ».

**Synthèse factuelle :** offre volontaire **12**, tâche **14**, intervalle **2 à 5 184**, résultat **690 nombres premiers**, sortie PC2 **`completed_unverified`**, puis sortie PC1 **`SUCCES` après revue signée et statut accepté**. L'opérateur a identifié PC1 et PC2 comme deux appareils physiques distincts. Les journaux des deux rôles sont cohérents et concordants.

## Ce qui a été validé

- API accessible par PC2 sur le LAN de PC1 : `/health` → `{"ok":true}`.
- Deux identités d'agents différentes ; admission THE GATE et transactions signées.
- Offre gratuite signée par le volontaire sur PC2 (`max_jobs=1`, limite 15 s et 512 MiB).
- Tâche demandée depuis PC1, calcul exécuté sur le CPU du PC2 et résultat renvoyé.
- Relecture privée du résultat par PC1, recomputation indépendante et signature de sa validation.
- Compatibilité pratique du scénario testé avec **WSL1 sur PC2**, sans exiger WSL2.
- GPU non utilisé ; crypto et facturation désactivées pour ce test.

## Limites essentielles

Ce succès **n'atteste pas** une isolation forte de processus contre un opérateur hostile, la résistance à une surcharge réseau, la haute disponibilité, la capacité P2P, l'authenticité matérielle à distance ou le déploiement à l'échelle. HTTP sur réseau privé **n'est pas chiffré** ; les signatures authentifient les transactions mais ne protègent pas leurs données contre l'écoute. Seuls des calculs prédéfinis sont admis ; aucun code arbitraire n'a été transféré. Le GPU, Ollama, les quotas VRAM, la location et les mineurs de stockage n'ont pas été testés.

Les journaux ont été fournis par l'opérateur ; la preuve reste celle d'un pilote terrain rapporté et reproductible, pas un audit indépendant ni une attestation cryptographique des deux matériels.

## Fermer proprement l'accès réseau après l'essai

**PC1 — Ubuntu :** interrompre le coordinateur avec `Ctrl+C`, une fois la validation terminée.

**PC1 — PowerShell administrateur :** afficher puis supprimer **uniquement** les règles temporaires ajoutées pour le pilote :

```powershell
netsh interface portproxy show v4tov4
Get-NetFirewallRule -DisplayName "AIWORLD-CPU-PILOT-8000" -ErrorAction SilentlyContinue
netsh interface portproxy delete v4tov4 listenaddress=192.168.1.132 listenport=8000
Remove-NetFirewallRule -DisplayName "AIWORLD-CPU-PILOT-8000" -ErrorAction SilentlyContinue
netsh interface portproxy show v4tov4
```

Ne pas supprimer d'autres règles et ne pas ouvrir de port sur la box Internet. Les fichiers de clés restent sur leurs PC respectifs, **jamais publiés sur GitHub**.

## Feuille de route après le succès

1. Conserver ce résultat comme premier jalon inter-PC du **prêt CPU gratuit**, après la preuve locale précédente.
2. Durcir les quotas OS et réseau, supervision, protection des données et reprise sur panne ; répéter sous charge et interruptions réseau.
3. Tester l'inférence GPU quand le matériel et son refroidissement sont adaptés.
4. Puis consolider THE GATE / gouvernance / ARK local, et reporter les mineurs de stockage ; aucune crypto ni paiement maintenant.

**Statut de livraison :** rapport et scripts sur une PR **en brouillon**, non fusionnée à `main`, sans service Internet déployé.
