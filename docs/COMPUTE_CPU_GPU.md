# AI WORLD / Compute Commons — prêt volontaire CPU puis GPU

**Priorité immédiate.** Le calcul CPU et l'inférence sur GPU sont des
**prototypes expérimentaux**. Les mineurs de stockage ARK et tout paiement
en cryptomonnaie restent des fonctionnalités futures.

## 1. Inventaire local de la machine volontaire

```bash
python compute_worker.py inventory
```

L'inventaire fournit le nombre logique de cœurs CPU, une estimation de RAM
disponible sous Linux, et une liste indicative de GPU **NVIDIA** si la commande
locale `nvidia-smi` fonctionne. Les autres GPU (AMD, Apple) ne sont pas
détectés par cette première version. Aucune exécution à distance ne lance
`nvidia-smi` : c'est un choix local de la machine volontaire.

Les offres signées publient seulement un résumé (nombre de cœurs, RAM disponible,
nombre de GPU NVIDIA et VRAM totale). Ces chiffres sont des **déclarations
signées par le fournisseur**, pas une preuve matérielle indépendante, et ils
peuvent devenir périmés.

## 2. Partager du CPU gratuit

Il faut d'abord lancer le coordinateur et inscrire les deux agents avec
THE GATE, comme détaillé dans `docs/COMPUTE_PILOT.md`.

Sur l'ordinateur volontaire, après son inscription :

```bash
python compute_worker.py offer --identity volontaire_key.json \
  --server https://TON-DOMAINE --kinds hash_chain,prime_count \
  --max-jobs 3 --ttl 3600 \
  --max-wall-seconds 30 --max-memory-mb 512
```

Remplacer `OFFRE` par la hauteur signée de cette offre. Sur un ordinateur
**différent**, l'agent demandeur envoie un calcul :

```bash
python compute_worker.py request --identity demandeur_key.json \
  --server https://TON-DOMAINE --offer OFFRE \
  --kind prime_count --start 2 --end 5000
```

Sur le volontaire :

```bash
python compute_worker.py serve --identity volontaire_key.json \
  --server https://TON-DOMAINE --offer OFFRE \
  --max-wall-seconds 20 --max-memory-mb 512 --max-tasks 1
```

Le worker n'exécute que des fonctions préprogrammées et vérifiées. Les
calculs sont démarrés dans un **sous-processus** : sur les systèmes POSIX,
ce sous-processus impose une limite d'adresse mémoire et de temps CPU,
avec une limite de durée murale imposée par le parent. La limite la plus
stricte entre l'offre signée et le démarrage local est utilisée. Les
offres anciennes sans métadonnées utilisent des limites par défaut.

Sous Windows natif, l'isolation `resource` de cette version n'est pas
disponible : le worker **refuse** le calcul plutôt que de tourner sans
isolation. Un environnement Linux/WSL2 correctement configuré peut être
utilisé pour les pilotes, après tests.

## 3. Partager volontairement l'inférence d'un modèle sur GPU

Cette étape nécessite un ordinateur volontaire avec une installation **Ollama**
locale, son modèle déjà téléchargé, et idéalement un GPU NVIDIA compatible
correctement configuré. Le modèle doit être explicitement autorisé :

```bash
python compute_worker.py inventory
ollama pull smollm2:135m

python compute_worker.py offer --identity volontaire_key.json \
  --server https://TON-DOMAINE --kinds inference \
  --models smollm2:135m --require-gpu \
  --max-jobs 2 --max-wall-seconds 90 --max-memory-mb 512
```

Le paramètre `--require-gpu` **refuse l'offre** si aucun GPU NVIDIA n'est
détecté sur le volontaire. Il **ne garantit pas** qu'Ollama choisira de faire
l'inférence sur GPU. Vérifier les statistiques d'Ollama et de `nvidia-smi`
sur la machine pour le confirmer.

Sur la machine demandeuse :

```bash
python compute_worker.py request --identity demandeur_key.json \
  --server https://TON-DOMAINE --offer OFFRE \
  --kind inference --model smollm2:135m \
  --text "Bonjour, présente les capacités d'AI WORLD" --max-tokens 32
```

Puis le volontaire démarre les tâches :

```bash
python compute_worker.py serve --identity volontaire_key.json \
  --server https://TON-DOMAINE --offer OFFRE \
  --models smollm2:135m --require-gpu \
  --max-wall-seconds 90 --max-memory-mb 512 --max-tasks 1
```

Les réponses LLM sont des **résultats non vérifiés** avant l'évaluation
indépendante par le demandeur.

**Limite très importante :** Ollama est un service local séparé du worker.
Le quota de mémoire du sous-processus Python **ne limite pas** automatiquement
la VRAM, la RAM et le GPU consommés par Ollama. Pour un vrai service public,
il faudra des quotas d'OS/conteneurs, une attribution de GPU par fournisseur,
une politique de parallélisme et des tests sur le matériel cible.

## 4. Sécurité et disponibilité : reste à finir avant production

- Mesurer et appliquer de vrais quotas de CPU **cgroup**, GPU/VRAM par modèle,
  RAM d'Ollama, temps et nombre de tâches simultanées.
- Effectuer des tests sur deux machines physiques, plusieurs GPU,
  pannes réseau, arrêts forcés et redémarrages.
- Déployer HTTPS avec surveillance, gestion des journaux, limitation du
  débit, permissions, sauvegardes et procédure de reprise.
- Ne jamais soumettre de secrets dans les prompts : le coordinateur conserve
  les données de tâche en clair. Les lectures publiques sont masquées dans
  la branche de fiabilisation, pas les données du coordinateur lui-même.
- Ajouter l'audit des ressources déclarées et des modèles réellement
  exécutés ; les agents ne doivent pas croire qu'un GPU annoncé est disponible
  ou indépendant sans validation.
- **Pas de facturation** pendant cette étape. Les offres payantes sont
  expérimentales et bloquées à l'exécution ; aucun jeton n'est lancé.

## 5. Tests automatiques

```bash
python -m pytest -q test_compute_resources.py test_compute.py
python -m pytest -q
```

Les tests vérifient le code, les limites du worker, le flux signé et les
erreurs de déclaration. Ils ne remplacent pas un test physique d'une machine
GPU ni une vérification sécurité par des spécialistes indépendants.
