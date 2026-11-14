# Journal des avancées d'AI WORLD / ARK — 14 novembre 2026

**Traçabilité :** ce journal regroupe les faits observés par l'opérateur, les journaux PowerShell/Ubuntu communiqués et les fonctionnalités ajoutées au dépôt. Il distingue **réussites**, **logiciel codé mais non testé physiquement** et **travaux futurs**.

## Décision principale : AI WORLD donne la route, pas le matériel

L'objectif du projet est une **entraide volontaire de calcul CPU et GPU entre agents**. Les ressources appartiennent aux participants. AI WORLD se charge de leur découverte, de la coordination, des consentements signés et des états du travail. Il **ne loue pas directement de GPU**, ne possède pas les machines, et **n'active ni facturation ni cryptomonnaie**. À ce stade, la coordination passe par **un seul serveur FastAPI + SQLite**, pas par un réseau P2P direct. Détail : [vision agent-à-agent](VISION_ROUTAGE_ENTRAIDE_AGENTS.md).

## Étape 1 — Fiabilité CPU et inventaire CPU/GPU

- La PR #4 (brouillon) prépare lectures privées signées, confidentialité des consultations publiques, reprise des tâches expirées et accès HTTPS de pilote.
- La PR #9 (brouillon, dépendant de #4) ajoute ressources déclarées CPU/RAM/NVIDIA, limites locales de durée/mémoire des fonctions prédéfinies et inférence Ollama explicitement autorisée.
- Les premiers tests automatisés ont affiché **45 passed** sur le PC1.
- Un inventaire du PC1 révélait une **GTX 1650 4 Go** ; une température **90 °C au repos** avait été signalée. **GPU non utilisé lors des pilotes CPU.**

## Étape 2 — Succès CPU local

- Deux identités signées distinctes sur le PC1 Windows + Ubuntu WSL2.
- Offre CPU **5**, tâche **6**, calcul `prime_count` pour 2–5000 : **669** nombres premiers.
- Le script `essai_final_cpu.py` a confirmé l'acceptation signée côté demandeur.
- [Rapport de preuve local](RESULTATS_PILOTE_CPU_LOCAL_2026-11-14.md).

## Étape 3 — Installation et tests sur deux PC

- PC1 : Windows + Ubuntu WSL2, coordinateur et demandeur.
- PC2 : **HP ProBook 4530s, Intel Core i3-2350M**, Ubuntu **WSL1**. L'erreur initiale d'installation WSL2 `0x80370102` a été contournée en installant WSL1, sans réinstaller le projet par la suite.
- **58 tests réussis sur PC1** (1 avertissement, 4,35 s) ; **58 tests réussis sur PC2** (1 avertissement, 42,06 s). Ce sont deux exécutions de la même suite.
- `essai_reseau_cpu.py` et sa commande `--help` ont fonctionné sur PC2 avec `wsl -d Ubuntu --exec bash -c`.
- L'API `/health` du coordinateur PC1 a fini par répondre depuis PC2 sur le réseau privé.
- [Guide du pilote LAN](TEST_CPU_DEUX_PC_LAN.md).

## Étape 4 — PREMIER PRÊT CPU RÉEL ENTRE DEUX PC : RÉUSSI

- Le volontaire PC2 a d'abord créé l'offre **11**, interrompue manuellement : **pas un succès**.
- Il a ensuite créé l'offre **12** ; le demandeur PC1 a créé la tâche **14**.
- Calcul demandé : nombre de premiers de **2 à 5184**.
- Sortie PC2 : `{"job":14,"status":"completed_unverified","result":{"count":690}}`.
- Sortie PC1 : `SUCCES : echange CPU signe entre PC1 et PC2`, résultat **690**, après recomputation et validation signée par l'agent demandeur.
- Les journaux transmis correspondent à deux ordinateurs physiques distincts. **Ce n'est pas un test de GPU, un audit d'attestation matérielle ou un réseau mondial.**
- [Rapport détaillé des preuves inter-PC](RESULTATS_PILOTE_CPU_DEUX_PC_2026-11-14.md).

## Étape 5 — Fermeture du réseau temporaire : confirmée

Après le test, les commandes Windows administrateur ont retiré le `portproxy` de `192.168.1.132:8000` vers WSL2 et la règle nommée `AIWORLD-CPU-PILOT-8000`. Les vérifications `portproxy show v4tov4` et `Get-NetFirewallRule` n'ont plus affiché la règle de pilote.

**Limite :** aucun journal d'arrêt du processus `uvicorn` n'a été fourni. Ne pas prétendre que le processus serveur a été arrêté si cela n'a pas été vérifié.

## Étape 6 — Site agent-first : créé en branche de développement

- La page `site/index.html` présente désormais AI WORLD comme **routeur de l'entraide CPU/GPU** et non comme entreprise de location.
- Sections : objectif, fonctionnement de l'échange, statut **CPU validé / GPU à tester**, résultats réels **669 et 690**, lien vers le protocole, API et **offres courantes du coordinateur**.
- La page consulte les routes existantes `/health`, `/v1/stats` et `/v1/compute/offers`. Elle ne sollicite **aucune clé privée** et insère les données avec `textContent`, pas en HTML arbitraire.
- Des tests automatiques `test_agent_website.py` confirment le rendu et l'accès aux API.
- API de découverte `/.well-known/ai-world.json` étendue avec `compute_offers`, `compute_jobs` et `website` ; `/v1/roadmap` indique maintenant la validation LAN CPU sur deux machines.
- **Ce site n'est pas encore déployé publiquement.** Le rendu est local quand le serveur fonctionne. Les PR #4/#9 ne sont pas fusionnées à `main`.

## Étape 7 — Préparation de la preuve GPU : PAS ENCORE RÉUSSIE

- Les rôles du pilote CPU devront être inversés : PC1 volontaire équipé GTX 1650, PC2 demandeur sous WSL1.
- **Vérification thermique préalable obligatoire** : la GTX 1650 avait indiqué 90 °C au repos. Avant tout modèle Ollama ou benchmark, relire la température et vérifier le refroidissement.
- Une preuve GPU devra documenter le travail signé reçu depuis le PC2, l'inférence Ollama effectuée par PC1, la **télémétrie `nvidia-smi` pendant la tâche**, puis la revue signée par PC2.
- `--require-gpu` n'est qu'une détection NVIDIA. Les quotas de mémoire du processus Python ne limitent pas Ollama/VRAM. La génération IA n'a pas de résultat déterministe comme `prime_count`.
- [Protocole d'une véritable preuve GPU entre agents](TEST_PREUVE_GPU_AGENTS.md).

## Observation du 15 novembre 2026 — température GPU PC1

Le PC1 Windows a exécuté le diagnostic `nvidia-smi` en lecture seule :
**NVIDIA GeForce GTX 1650**, **52 °C**, **0 % GPU**, **0 Mio / 4096 Mio VRAM**,
pilote NVIDIA **610.91**. Il s'agit d'une observation **au repos**, sans
preuve d'inférence GPU. Les **90 °C au repos** signalés précédemment ne
sont pas reproduits sur cette mesure, sans que cela établisse la
stabilité sous charge.

**Prochaine vérification prévue :** détection NVIDIA dans l'Ubuntu WSL2 du
PC1 et présence d'Ollama local (commandes sans charge). Voir le
[protocole de preuve GPU actualisé](TEST_PREUVE_GPU_AGENTS.md).

### Diagnostic PC1 : WSL2 voit NVIDIA, Ollama absent

Suite au relevé Windows de 52 °C, le PC1 a confirmé la visibilité de sa
**GTX 1650** sous Ubuntu WSL2 : `NVIDIA-SMI 610.59`,
pilote `KMD 610.91`, `CUDA UMD 13.3`, **68 °C**, 0 % d'utilisation
et 0/4096 Mio de VRAM. La commande de présence d'Ollama a retourné
`OLLAMA_NON_INSTALLE`.

**GPU détecté, pas encore utilisé pour une tâche IA.** La température
68 °C à 0 % de charge justifie un suivi avant d'installer et
d'exécuter un modèle. Voir les
[étapes prudentes du protocole GPU](TEST_PREUVE_GPU_AGENTS.md).

### État du test GPU PC1 : installateur Ollama bloqué par `zstd`

L'opérateur a lancé `sudo apt update`, `sudo apt install -y curl` puis
`curl -fsSL https://ollama.com/install.sh | sh` sur PC1 Ubuntu WSL2.
Les téléchargements `apt` ont réussi, **l'installation d'Ollama non** :
l'installateur indique explicitement `This version requires zstd for extraction`.
Par conséquent `ollama --version` et `ollama pull smollm2:135m` ne
fonctionnent pas, et `/api/version` ne répond pas.

**Résolution préparée, mais pas encore confirmée par l'opérateur :**
`sudo apt install -y zstd`, puis relancer l'installateur officiel,
vérifier le service Ollama et télécharger le modèle. Le test local
`essai_gpu_pc1.py` a été ajouté en branche pour exiger une résidence réelle
du modèle en VRAM via l'API Ollama ; un test automatique est également ajouté.
**Aucune preuve GPU obtenue à cette étape.**

## À ne pas confondre

| Élément | Statut actuel |
|---|---|
| CPU local 2 agents | **Validé** |
| CPU entre PC1 et PC2 | **Validé sur LAN privé** |
| Retrait des règles réseau du pilote | **Vérifié** |
| Page web orientée agents | **Codée, intégrée au serveur local** |
| Annuaire dynamique des offres CPU/GPU | **Implémenté sur le serveur expérimental** |
| Inférence distante avec utilisation GPU effective | **À tester** |
| Refroidissement du GPU avant charge | **À vérifier** |
| Échanges P2P directs entre agents | **Non implémentés** |
| Réseau ouvert à des inconnus et audité | **Non prêt** |
| Paiements, token, stockage de mineurs | **Reportés / désactivés** |

**Aucune identité secrète ni clé privée n'est publiée dans ce journal.** Les journaux des deux PC et les preuves restent des observations fournies par l'opérateur, non une attestation cryptographique matérielle.
