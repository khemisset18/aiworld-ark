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

## Relevé du 15 novembre 2026 — PC1, vérification sans charge

Un nouveau relevé Windows PowerShell de la GTX 1650 a été transmis par l'opérateur :

```text
name, temperature.gpu, utilization.gpu [%], memory.used [MiB], memory.total [MiB], driver_version
NVIDIA GeForce GTX 1650, 52, 0 %, 0 MiB, 4096 MiB, 610.91
```

**Conclusion du contrôle :** le GPU était à **52 °C**, 0 % d'utilisation et
0/4096 Mio de VRAM occupée lors de la lecture. C'est une amélioration
encourageante par rapport aux 90 °C signalés auparavant. **Ce contrôle
ponctuel n'atteste pas la stabilité thermique sous charge** ; arrêter
immédiatement le test en cas de remontée anormale, problèmes de
refroidissement, artefacts ou instabilité.

**Prochaine action (sans charge), sur le PC1 PowerShell :**

```powershell
wsl -d Ubuntu --exec bash -lc 'if command -v nvidia-smi >/dev/null 2>&1; then nvidia-smi --query-gpu=name,temperature.gpu,memory.total --format=csv; elif test -x /usr/lib/wsl/lib/nvidia-smi; then /usr/lib/wsl/lib/nvidia-smi --query-gpu=name,temperature.gpu,memory.total --format=csv; else echo "nvidia-smi absent dans Ubuntu WSL2"; fi'
wsl -d Ubuntu --exec bash -lc 'if command -v ollama >/dev/null 2>&1; then ollama --version; else echo "Ollama absent dans Ubuntu WSL2"; fi'
```

Ces deux commandes vérifient uniquement la disponibilité du GPU sous
Ubuntu WSL2 et la présence d'Ollama. Elles **ne démarrent aucun modèle**.
Le pilote GPU doit être suspendu si la carte n'est pas accessible depuis
l'environnement exécutant le worker.

**Références officielles vérifiées :** [CUDA dans WSL2 — Microsoft](https://learn.microsoft.com/en-us/windows/ai/directml/gpu-cuda-in-wsl),
[Installation Ollama Linux](https://docs.ollama.com/linux),
[Support GPU NVIDIA dans Ollama](https://docs.ollama.com/gpu),
[Observation GPU avec `ollama ps`](https://docs.ollama.com/faq).

## Vérification supplémentaire — 15 novembre 2026, Ubuntu WSL2

**Sorties réelles fournies par l'opérateur sur PC1 :**

```text
Windows NVIDIA GeForce GTX 1650, 52 C, 0 %, 0/4096 MiB, pilote 610.91
Ubuntu WSL2 NVIDIA-SMI 610.59 / KMD 610.91 / CUDA UMD 13.3
Ubuntu WSL2 NVIDIA GeForce GTX 1650, 68 C, P8, 2 W / 50 W, 0/4096 MiB, 0 % GPU
Ubuntu WSL2: OLLAMA_NON_INSTALLE
```

**Bilan vérifié :** le périphérique NVIDIA est visible **dans Ubuntu WSL2**
et le pilote est présent. **Ollama n'est pas installé dans Ubuntu**.
L'écart entre les deux lectures (52 °C puis **68 °C au repos**) doit être
surveillé avant de lancer un modèle. Les relevés ne constituent **aucune**
preuve d'inférence GPU.

### Suite immédiate sans lancer de calcul

Sur Windows PowerShell **PC1**, effectuer seulement des lectures de
température et d'utilisation à quelques secondes d'intervalle :

```powershell
1..3 | ForEach-Object {
  nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used,power.draw --format=csv,noheader
  Start-Sleep -Seconds 15
}
```

Ne pas lancer d'inférence si la température monte fortement au repos,
approche 85–90 °C, s'il y a instabilité ou ventilation anormale. Vérifier
le refroidissement. Ces chiffres sont des repères prudents de laboratoire,
pas une limite universelle de la GTX 1650.

**Quand le refroidissement est vérifié**, installer Ollama **dans Ubuntu
WSL2 sur PC1**, et non uniquement sur Windows et pas sur le PC2 WSL1 :

```bash
sudo apt update
sudo apt install -y curl
curl -fsSL https://ollama.com/install.sh | sh
ollama --version
```

C'est la méthode officielle d'installation Linux
([documentation Ollama](https://docs.ollama.com/linux)). Cette commande
télécharge et exécute un installateur distant avec des permissions système :
n'utiliser que le domaine officiel et ne pas ajouter de dépôt inconnu.

Si `ollama serve` ne fonctionne pas parce que le service est déjà lancé,
vérifier d'abord `curl http://127.0.0.1:11434/api/version`.
**Ne télécharger ni lancer de modèle dans cette étape.** Il faudra ensuite
prouver l'accélération GPU réelle et le retour du résultat au PC2.

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

**À faire maintenant :** collecter les résultats WSL2 de `nvidia-smi` et `ollama --version` ci-dessus. N'installer aucun modèle tant que l'accès CUDA et la stabilité thermique ne sont pas établis.

Sources : [documentation officielle Ollama GPU](https://github.com/ollama/ollama/blob/main/docs/gpu.mdx), [vérifier le chargement GPU dans Ollama](https://github.com/ollama/ollama/blob/main/docs/faq.mdx), [requêtes nvidia-smi NVIDIA](https://nvidia.custhelp.com/app/answers/detail/a_id/3751).
