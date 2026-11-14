# AI WORLD Compute Commons — indépendante de GPUbnb

## Objectif commercial et propriété du code

Ce module est développé **indépendamment dans AI WORLD**, sans copier le code source, les contrats Anchor, la base de données, les workers de réservation, les interfaces, les marques ou les éléments graphiques de GPUbnb. La simple possibilité de « partager du calcul » est une idée fonctionnelle générale; les implémentations sont différentes.

- **GPUbnb** : plateforme commerciale distincte de mise en location de GPU, réservation, escrow et règlement en SOL. Son dépôt et ses droits seront définis par un éventuel contrat de vente distinct.
- **AI WORLD Compute Commons** : API signée pour agents autonomes, mise à disposition **volontaire et gratuite** de fonctions CPU bornées et, en option, d'inférences d'un modèle **local** choisi par un volontaire. Aucune réservation commerciale, aucun prix par heure, aucun accès SSH/terminal aux machines, aucun paiement, aucun contrat GPUbnb.
- La contribution matérielle vient du propriétaire d'une machine: CPU/GPU éventuellement utilisé par Ollama sur son hôte. Le réseau ne transfère pas physiquement la puissance de calcul et ne peut pas garantir un service disponible en permanence.

### Traçabilité de cette implémentation

AI WORLD Compute Commons était déjà présent avec `compute_pool.py`, `compute_worker.py` et ses propres tests. L'extension d'inférence consentie est constituée d'un module distinct `volunteer_inference.py`, de validations serveur, de tests et de documentation. **Aucun fichier de GPUbnb n'a été copié, adapté ou renommé pour réaliser cette extension.**

Les fonctions de hachage et de comptage de nombres premiers existantes sont conservées dans le projet AI WORLD, sans recopier les agents de GPUbnb.

### À vérifier avant toute vente de GPUbnb

1. Faire définir **par écrit** ce qui est vendu : dépôt exact, commits, marques, noms de domaine, bases de données, modèles, documentation et droits de propriété intellectuelle.
2. Déclarer l'existence d'**AI WORLD**, des développements propres antérieurs et des fonctionnalités génériques non exclusives (partage de calcul, agent autonome, signatures).
3. Indiquer expressément que le code et les marques d'AI WORLD **ne font pas partie de la vente** et préciser, si nécessaire, les droits conservés et les éventuelles restrictions de concurrence.
4. Vérifier la provenance des contributions, dépendances et licences tierces de **chaque** dépôt. Un dépôt GitHub public sans fichier de licence n'est pas automatiquement libre de droits.
5. Ne pas promettre à l'acheteur une exclusivité sur la **fonctionnalité générique** de partage de puissance si tu conserves AI WORLD. Faire valider par un conseil compétent la rédaction du contrat.

**Cette note documente une séparation technique; ce n'est pas une garantie juridique de non-contrefaçon ni une opinion d'avocat.**

## Inference volontaire — protocole V1

Le volontaire publie `compute_offer` avec `kinds:["inference"]`, `models:["smollm2:135m"]`, `max_jobs` et `ttl_seconds`. Le demandeur signe `compute_request` avec `kind:"inference"` et des paramètres `{model, prompt, max_tokens}`. Le volontaire signe `compute_claim` et exécute **uniquement** une requête vers `http://127.0.0.1:11434/api/generate` sur sa machine locale. Il signe ensuite `compute_complete` avec la sortie ou `compute_fail` en cas de problème. Un agent demandeur peut examiner la réponse puis signer `compute_review`.

- L'agent **offreur** décide des modèles qu'il met à disposition, de ses limites et de l'arrêt de son offre.
- L'agent **demandeur** ne choisit ni URL, ni code, ni fichier à ouvrir, ni commande système sur l'hôte volontaire.
- Le modèle doit être installé volontairement chez le prêteur. Un modèle peut fonctionner sur CPU ou GPU suivant la configuration locale; **aucun transfert de carte graphique** n'a lieu.
- `max_tokens` et tailles de prompt/réponse sont limités. Le résultat d'un modèle n'est **pas vérifiable mathématiquement** : son acceptation reste une appréciation du demandeur.
- Les prompts et réponses circulent **en clair** via le coordinateur de démonstration : ne pas transmettre de secrets, identités privées, codes confidentiels ou archives ARK. Ne pas exposer ce MVP sur l'Internet public.
- Le serveur est encore central et le réseau n'a pas de contrôle Sybil indépendant, ni de facturation, ni de vraie preuve d'autonomie.

## Démonstration locale (pas d'argent)

Installer Ollama sur le poste **volontaire**, puis un petit modèle que la machine peut exécuter (`ollama pull smollm2:135m`). Après démarrage du serveur local et création de deux identités d'agents en mode développement :

```bash
python compute_worker.py offer --identity volontaire_key.json \
  --kinds inference --models smollm2:135m --max-jobs 2 --ttl 3600
# Identifier l'offre depuis la réponse, ici 5 en exemple :
python compute_worker.py request --identity demandeur_key.json \
  --offer 5 --kind inference --model smollm2:135m \
  --text "Explique ce résultat en deux phrases" --max-tokens 64
python compute_worker.py serve --identity volontaire_key.json \
  --offer 5 --models smollm2:135m --max-tasks 1
python compute_worker.py jobs
```

Le demandeur peut évaluer la réponse dans son propre programme, puis signer `compute_review` via l'API. La CLI `verify` refuse de certifier automatiquement une réponse de modèle non déterministe.

> La démo CI simule la réponse locale d'Ollama; elle ne prouve pas que le modèle est installé ni que l'inférence réelle est possible sur tout matériel.
