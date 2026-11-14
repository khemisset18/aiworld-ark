# AI WORLD — Préparer une preuve réelle de calcul GPU entre deux agents

**État : protocole prêt à préparer, PAS de preuve GPU distante obtenue.**  
**Décision du projet :** les agents volontaires se prêtent leur puissance. AI WORLD les met en relation par ses API. Il ne loue pas ni ne possède leurs GPU. Entraide gratuite, sans paiement.

## Rôles pour le prochain pilote

- **PC1** : Windows + Ubuntu WSL2, GTX 1650 NVIDIA inventoriée (4 Go VRAM), coordinateur AI WORLD et **volontaire GPU**.
- **PC2** : HP ProBook 4530s + Ubuntu WSL1, **agent demandeur**. Aucun GPU requis sur PC2.
- Réseau local privé avec une règle temporaire Windows limitée au PC2. Cette règle a **été retirée après le pilote CPU** : elle ne doit être rouverte que pour un test approuvé, puis de nouveau supprimée.
- Le pilote CPU précédent, offre 12/tâche 14/résultat 690, est **réussi** et archivé : [preuves CPU inter-PC](RESULTATS_PILOTE_CPU_DEUX_PC_2026-11-14.md).

## Étape 0 — Vérification thermique OBLIGATOIRE avant tout calcul

Une **température GPU de 90 °C au repos** avait été signalée sur le PC1. Ce n'est pas compatible avec un lancement prudent d'un nouveau test GPU. **Ne pas lancer Ollama, de génération IA, de benchmark ou de charge GPU tant que ce comportement n'a pas été compris et corrigé.**

Sur **Windows PowerShell PC1**, lecture seule (aucun calcul lancé) :

```powershell
nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,driver_version --format=csv
```

Si `nvidia-smi` est introuvable, retrouver l'outil NVIDIA et vérifier le pilote, mais **ne pas installer ou modifier des pilotes à l'aveugle**. Vérifier ventilation, poussière, charge au repos, température et comportement sous faible charge avec un spécialiste si nécessaire.

**Arrêter la préparation au stade lecture seule si la température reste anormalement haute (notamment proche de 90 °C au repos), s'il y a bruit de ventilateur anormal, ralentissements ou instabilité.** La température de sécurité dépend du modèle et de la machine ; ne pas déduire un seuil universel.

Dans un second temps seulement, contrôler la présence de l'outil et de la carte **sans charge** :

```powershell
ollama --version
wsl -d Ubuntu --exec nvidia-smi
```

`ollama --version` peut échouer si Ollama n'est pas installé, ce n'est pas une erreur du projet. Dans WSL2, `nvidia-smi` peut être à `/usr/lib/wsl/lib/nvidia-smi` selon le système. Ne pas installer Ollama ni télécharger de modèles avant d'avoir validé le refroidissement.

## Étape 1 — Architecture de la preuve (quand la température sera normale)

Le coordinateur reste sur PC1. **On inverse les rôles du pilote CPU** : cette fois, le PC1 héberge le volontaire GPU ; le PC2 demande une réponse générée par un modèle autorisé.

```text
PC2 — agent demandeur (WSL1)
          |
          | offre consultée + compute_request signé
          v
PC1 — coordinateur AI WORLD (WSL2)
          |
          | requête attribuée au volontaire autorisé
          v
PC1 — agent volontaire et Ollama LOCAL
          |
          | GPU GTX 1650 (à vérifier par télémétrie réelle)
          v
PC1 — résultat de génération renvoyé au coordinateur
          |
          v
PC2 — lecture privée, examen de la réponse et revue signée
```

**Précondition technique :** `volunteer_inference.py` contacte exclusivement
`http://127.0.0.1:11434/api/generate` **depuis le processus Python du volontaire**. Si Ollama fonctionne dans Windows alors que le worker fonctionne dans Ubuntu WSL2, `localhost` n'est **pas nécessairement partagé**. Vérifier d'abord un accès local depuis le même environnement Linux, ou utiliser un Ollama local à cet environnement. **Ne jamais exposer Ollama à Internet ni modifier son adresse pour accepter des URLs fournies par les agents.**

## Étape 2 — Preuves indispensables pour conclure

Une preuve valide exige **les quatre observations** suivantes, sur les deux ordinateurs :

1. **PC2 → PC1 :** le demandeur PC2 envoie une transaction signée `compute_request` de type `inference` vers une offre signée du PC1, avec un **modèle local autorisé** par le volontaire.
2. **PC1 :** le worker du PC1 récupère la tâche signée, l'exécute via un Ollama local puis signe `compute_complete`, sans télécharger de script ni ouvrir de commandes arbitraires.
3. **GPU réel sur PC1 :** montrer `nvidia-smi` (température, utilisation et VRAM pendant la génération), accompagné d'une observation d'Ollama indiquant la présence de couches sur GPU. **Une carte seulement détectée ne suffit pas.** Le serveur actuel envoie `keep_alive: 0`, qui décharge immédiatement le modèle après l'inférence : un `ollama ps` lancé *après* la tâche peut donc être vide ; observer **pendant** la génération.
4. **PC2 :** lecture privée du résultat, évaluation explicite de la réponse et `compute_review` signé par l'agent demandeur ; statut final `accepted_by_requester` en cas d'acceptation. Contrairement à `prime_count`, une réponse LLM n'est pas vérifiable par simple recalcul déterministe : ne pas confondre « accepté par le demandeur » avec « vérité garantie ».

Les journaux doivent inclure identifiants **offre/tâche**, modèle effectivement choisi, temps de calcul, réponse du worker, télémétrie GPU simultanée et statut final. **Ne jamais publier de fichiers de clés**, de secrets ou de prompts personnels.

## Ce qui est possible aujourd'hui, et ce qui reste à sécuriser

- Déjà codé : type de tâche `inference`, liste autorisée de modèles, transactions signées, détection indicative NVIDIA, exécution fixe côté volontaire et révision signée.
- **Pas encore prouvé** : inference distante avec utilisation réelle d'un GPU.
- **Pas encore garanti** : l'option `--require-gpu` ne prouve pas que le modèle a calculé sur GPU. Le processus Ollama est séparé et sa VRAM n'est pas limitée par la mémoire du worker Python.
- À faire avant d'ouvrir le réseau : mesures thermiques et quotas GPU, isolation Ollama, authentification/transport chiffré, résistance aux abus, supervision et tests sur plusieurs volontaires.

**À faire maintenant :** récupérer seulement la sortie de `nvidia-smi --query-gpu=...` sur le PC1. Si la température est normale, préparer ensuite le modèle local et le test réseau. Si elle reste très élevée, corriger le refroidissement avant toute utilisation.

Sources : [documentation officielle Ollama GPU](https://github.com/ollama/ollama/blob/main/docs/gpu.mdx), [vérifier le chargement GPU dans Ollama](https://github.com/ollama/ollama/blob/main/docs/faq.mdx), [requêtes nvidia-smi NVIDIA](https://nvidia.custhelp.com/app/answers/detail/a_id/3751).
