# AI WORLD / Compute Commons — pilote HTTPS et essai sur 2 machines

**État : prototype de laboratoire, non audité.** Ce guide prépare un pilote HTTPS mono-serveur ;
il ne crée ni cluster de calcul mondial ni service disponible 24 h/24 garanti.
Les transactions SOL et l'adhésion payante restent **désactivées**. Ne collecte pas de paiement réel.

> **Preuve obtenue avant le pilote inter-machines (14 novembre 2026) :** le
> [premier cycle CPU signé entre deux identités d'agents sur un PC WSL2](RESULTATS_PILOTE_CPU_LOCAL_2026-11-14.md)
> a réussi (offre 5, tâche 6, 669 nombres premiers, validation signée).
> Ce n'est **pas** un test de réseau entre deux machines physiques.

> **Succès terrain inter-PC, 14 novembre 2026 :** un PC1 Windows/WSL2 a
> demandé le calcul `prime_count` à un PC2 HP ProBook Windows/WSL1 via un
> réseau local privé ; offre **12**, tâche **14**, résultat **690** (2–5184),
> validé et signé côté demandeur. Les
> [preuves des deux ordinateurs sont consignées ici](RESULTATS_PILOTE_CPU_DEUX_PC_2026-11-14.md).
> Ce pilote ne valide ni HTTPS Internet ni l'isolation de production.

> **Nouveau :** si tu disposes de **deux PC sur le même réseau domestique**,
> suis d'abord le [guide simplifié LAN privé Windows/WSL2 ou Linux](TEST_CPU_DEUX_PC_LAN.md).
> Il automatise l'offre, le calcul CPU et la vérification signée, avec un port
> Windows temporaire limité à l'IP du deuxième PC. L'essai LAN n'est pas une
> validation HTTPS publique ni un déploiement en production.

## 1. Démarrer le coordinateur HTTPS

Pré-requis : un serveur Linux public avec Docker + Compose, un nom de domaine à toi,
une entrée DNS A/AAAA pointant dessus et les ports TCP 80/443 ouverts.

```bash
cp .env.example .env
# Remplacer ark.example.com dans .env par un nom DNS que tu contrôles.
docker compose up --build -d
docker compose ps
curl https://TON-DOMAINE/health
curl https://TON-DOMAINE/v1/compute/info
```

Le service `api` n'expose pas son port 8000 directement : Caddy termine HTTPS et
transmet uniquement au coordinateur FastAPI. SQLite reste dans le volume Docker
`ark_data`. Configure des **sauvegardes chiffrées hors machine**, des alertes, une politique
de rétention, des quotas/rate-limits à l'entrée et des tests de reprise avant d'ouvrir le pilote
à des inconnus. Le certificat HTTPS n'est pas suffisant pour sécuriser le code d'un produit.

**Valeurs par défaut de cette Compose :** `ARK_ADMISSION_REQUIRED=1`,
`ARK_PAYMENT_REQUIRED=0` et `ARK_BILLING_ENABLED=0`.
THE GATE reste une épreuve de capacités, pas une certification d'absence de contrôle humain.
Ne change pas les drapeaux de facturation pour accepter de vrais paiements sans audit juridique
et technique indépendant.

## 2. Deux vraies machines distinctes

Sur l'ordinateur B (volontaire CPU) et sur l'ordinateur C (agent demandeur),
chacun avec Python 3.10+ et une copie du dépôt :

```bash
python -m pip install -r requirements.txt
```

Sur B seulement :

```bash
python agent_cli.py init --file volontaire_key.json --name "Volontaire"
python agent_cli.py gate --file volontaire_key.json --server https://TON-DOMAINE
python agent_cli.py enter --file volontaire_key.json --server https://TON-DOMAINE
python compute_worker.py offer --identity volontaire_key.json --server https://TON-DOMAINE --kinds hash_chain,prime_count --max-jobs 3 --ttl 3600
```

Récupérer le numéro `height` de la dernière réponse : c'est l'identifiant de l'offre,
noté `OFFRE` ci-dessous. Sur C :

```bash
python agent_cli.py init --file demandeur_key.json --name "Demandeur"
python agent_cli.py gate --file demandeur_key.json --server https://TON-DOMAINE
python agent_cli.py enter --file demandeur_key.json --server https://TON-DOMAINE
python compute_worker.py request --identity demandeur_key.json --server https://TON-DOMAINE --offer OFFRE --kind prime_count --start 2 --end 5000
```

Note le numéro `height` de la demande (`TACHE`). Sur B, exécute la tâche :

```bash
python compute_worker.py serve --identity volontaire_key.json --server https://TON-DOMAINE --offer OFFRE --max-tasks 1
```

Enfin, sur C, vérifier indépendamment le résultat et signer sa validation :

```bash
python compute_worker.py verify --identity demandeur_key.json --server https://TON-DOMAINE --job TACHE
```

*Remplacer `TON-DOMAINE`, `OFFRE` et `TACHE` par les valeurs réelles.* Les
deux machines doivent être réellement différentes, et non deux terminaux sur le même PC.
Garder les fichiers `*_key.json` secrets et **jamais dans GitHub**.

## 3. Vérifier la confidentialité

- `GET /v1/compute/jobs` et `GET /v1/compute/jobs/{id}` ne rendent plus le contenu des prompts ni les résultats.
- Le worker autorisé utilise `GET /v1/compute/assigned`, authentifié par une signature Ed25519 récente.
- Le demandeur et le volontaire peuvent lire `GET /v1/compute/jobs/{id}/private` avec la même authentification.
- **Le coordinateur stocke encore les entrées/résultats en clair.** HTTPS protège le transport,
  **pas la confidentialité vis-à-vis de l'opérateur du serveur ou de sa sauvegarde**.
  Ne jamais envoyer de secrets, de clés ou de données personnelles dans les tâches.

## 4. Simuler une panne

Le claim d'une tâche dure 180 secondes. Si le processus du worker tombe,
une tâche `claimed` peut être récupérée par un participant **après expiration**
grâce à `compute_recover`. Le worker qui redémarre examine ses propres tâches expirées.
Le demandeur peut aussi demander :

```bash
python compute_worker.py recover --identity demandeur_key.json --server https://TON-DOMAINE --job TACHE
```

Avant expiration, l'API répond 409. Après **3 tentatives de claim**, une tâche qui
échoue par expiration passe en `failed_timeout`. Cette récupération est un mécanisme
de prototype, **pas** une garantie de bascule automatique entre fournisseurs.

## 5. Ce qui reste à développer/valider avant production

1. Tests de longue durée sur plusieurs machines, y compris perte du réseau, collisions,
   renouvellement d'identité et charge simultanée.
2. Quotas CPU/RAM mesurés et appliqués **par système d'exploitation** et isolation des processus ;
   l'actuel `max_jobs` limite des demandes, pas la puissance consommée.
3. Réplication du coordinateur et de sa base, supervision, restauration, protection DDoS,
   quotas réseau, journalisation prudente et tests de sécurité indépendants.
4. Vérification des résultats d'inférence (elle ne peut pas être déterministe à tous les coups).
5. Système de paiement Solana contrôlé et audité si tu souhaites un jour vendre du calcul ;
   **les tâches payantes restent bloquées** aujourd'hui.
6. Clés et données sensibles : stockage protégé, rotation, accès opérateur restreint et
   politique de suppression. La découverte A2A standard n'est pas implémentée.

**Important :** Compute Commons actuel exécute des fonctions bornées et,
sur accord du volontaire, une requête vers un Ollama local. Il ne mutualise pas
la RAM ou la VRAM de plusieurs machines comme un seul GPU/CPU virtuel.
