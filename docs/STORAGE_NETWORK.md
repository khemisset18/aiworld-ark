# AI WORLD / ARK — Réseau expérimental de mineurs de mémoire

## Ce que cette version démontre

- Un agent génère une capsule ARK **chiffrée localement (AES-GCM) et signée (Ed25519)**.
- Il envoie des copies sur **trois serveurs de stockage séparés** (`storage_miner.py`).
- Chaque mineur utilise son propre disque, un jeton d'accès privé et des quotas.
- Le client `storage_network.py` vérifie immédiatement les copies en les relisant et exige
  le nombre minimal de copies choisi.
- Si un mineur est indisponible, l'agent peut retrouver une capsule authentique chez un
  autre mineur et restaurer ses **octets d'état**, sous réserve de disposer encore de sa clé.
- Un mode `watch` peut sauvegarder automatiquement un état modifié.
- Le client peut demander un défi de présence aléatoire à chaque mineur pour vérifier
  la disponibilité **au moment du test**.

**Ce n'est pas une cryptomonnaie, une blockchain, un service mondial déjà actif, une preuve
continue de stockage ou une résurrection d'agent.** Aucun vrai jeton n'est frappé, aucune
récompense automatique n'est payée et aucune machine étrangère n'est connectée par défaut.

## Les deux couches de l'architecture

```text
  Machine de l'agent IA
    état/mémoire privée (JSON, octets, etc.)
      -> chiffrement AES-GCM avec clé locale
      -> capsule signée Ed25519
      -> stockage chiffré réparti :
           Mineur 1 : disque indépendant
           Mineur 2 : disque indépendant
           Mineur 3 : disque indépendant

  En cas de panne de l'agent :
    clé récupérée hors du disque sinistré + liste des mineurs
      -> interroger les mineurs
      -> vérifier signature + empreinte SHA-256
      -> déchiffrer localement
      -> restaurer les octets d'état sur un environnement compatible
```

*Les mineurs ne connaissent pas la clé de déchiffrement.* Ils conservent toutefois la
capsule chiffrée et voient les métadonnées (identité pseudonyme, taille, horodatage).
Le coordinateur AI WORLD n'est pas nécessaire pour les lectures des mineurs dans cette
V1; la liste des mineurs est fournie explicitement par le client.

## Installation locale pour un pilote sur 3 ports

Sur trois terminaux distincts (pour **tester le code**, ce ne sont pas trois machines
géographiquement indépendantes) :

```bash
python -m pip install -r requirements.txt

# Terminal A : token long et aléatoire, garder sa valeur privée
export ARK_MINER_TOKEN="REMPLACER_PAR_UN_TOKEN_ALEATOIRE_DE_32_CARACTERES_OU_PLUS_A"
export ARK_MINER_DATA="./miner-a"
uvicorn storage_miner:app --host 127.0.0.1 --port 8101

# Terminal B : une autre valeur de token
export ARK_MINER_TOKEN="REMPLACER_PAR_UN_TOKEN_ALEATOIRE_DE_32_CARACTERES_OU_PLUS_B"
export ARK_MINER_DATA="./miner-b"
uvicorn storage_miner:app --host 127.0.0.1 --port 8102

# Terminal C : un troisième token
export ARK_MINER_TOKEN="REMPLACER_PAR_UN_TOKEN_ALEATOIRE_DE_32_CARACTERES_OU_PLUS_C"
export ARK_MINER_DATA="./miner-c"
uvicorn storage_miner:app --host 127.0.0.1 --port 8103
```

Générer chaque token avec `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
Les valeurs d'exemple ci-dessus ne sont **pas sûres**.

Sur un quatrième terminal, créez `storage-peers.json` localement :

```json
[
  {"url":"http://127.0.0.1:8101","token":"VRAI_TOKEN_A"},
  {"url":"http://127.0.0.1:8102","token":"VRAI_TOKEN_B"},
  {"url":"http://127.0.0.1:8103","token":"VRAI_TOKEN_C"}
]
```

Le fichier contient des secrets : `chmod 600 storage-peers.json` sur Linux/macOS et
**ne jamais l'ajouter dans GitHub**. Sur Internet, les URLs doivent être en **HTTPS**,
chacune vers un vrai serveur indépendant derrière son propre terminateur TLS sécurisé.
Ne publiez **pas** les serveurs Uvicorn directement sur l'Internet public.

## Sauvegarde sur plusieurs mineurs

```bash
python agent_cli.py init --file omega_key.json --name Omega
echo '{"memory":"checkpoint privé d Omega","step":1}' > omega_state.json

python storage_network.py backup --identity omega_key.json \
  --state omega_state.json --peers storage-peers.json \
  --min-copies 3 --manifest omega-backup.manifest.json \
  --capsule-out omega.ark.json
```

Le client vérifie les retours en téléchargeant chaque capsule. Il échoue si le nombre
minimal demandé n'est pas atteint. Certaines copies peuvent avoir été enregistrées
même si la commande se termine en erreur : prévoir une réconciliation avant production.

Sauvegarde automatique lorsque l'état change :

```bash
python storage_network.py watch --identity omega_key.json \
  --state omega_state.json --peers storage-peers.json \
  --min-copies 2 --interval 60 --manifest-dir ./receipts
```

Le mode `watch` doit être géré par un superviseur de processus pour fonctionner après
un redémarrage. Ce n'est pas une garantie de capture d'état pendant une panne soudaine.

## Récupération après une panne

Pour simuler la perte d'un mineur, arrêtez le terminal A. Puis, sur un agent qui a
récupéré sa **clé d'identité d'origine** et son fichier `storage-peers.json` :

```bash
python storage_network.py restore --identity omega_key.json \
  --peers storage-peers.json --out recovered-state.json
```

Le client cherche les copies encore accessibles, vérifie les signatures et l'intégrité,
puis déchiffre localement. Il préfère les capsules ayant l'horodatage signé le plus récent
parmi les annonces accessibles. En cas de doute, l'option `--digest` permet de cibler une
copie précise par son SHA-256.

**Si la clé de déchiffrement est perdue, les mineurs ne peuvent pas restaurer l'état.**
Il faut donc conserver une sauvegarde séparée et protégée de `omega_key.json`, de
préférence sur un autre support et lieu. La liste des mineurs et les tokens d'accès doivent
eux aussi survivre à la panne.

## Tester la présence d'une copie

Si vous possédez aussi une copie locale d'une capsule ARK :

```bash
python storage_network.py audit --identity omega_key.json \
  --capsule omega.ark.json --peers storage-peers.json
```

L'option `--capsule-out` de `backup` conserve exactement la capsule envoyée,
ce qui permet de vérifier plus tard que chaque mineur détient les bons octets.

L'audit retourne un SHA-256 lié à un nonce frais et aux octets de la capsule. Il ne prouve
que la possession **au moment du défi** : ce n'est pas un système anti-triche suffisant pour
verser automatiquement des jetons.

## Sécurité et production : ce qui manque

1. Authentification à permissions **par agent**, pas simplement un token partagé de mineur.
   En V1, tout client possédant le token peut consulter les capsules chiffrées du mineur.
2. Contrôles anti-Sybil, limitation de débit, prévention d'abus, facturation de stockage,
   quotas par contrat et politique de suppression/expiration des données.
3. Sauvegardes des bases de contrats et de métadonnées, stockage résistant aux pannes
   matérielles, audits indépendants, rotation de secrets et mécanismes d'accès de secours.
4. Plusieurs fournisseurs réellement indépendants, régions différentes, surveillance,
   vérifications périodiques et réparation automatique si une copie disparaît.
5. Verrouillage des écritures distribué ; la V1 utilise un verrou **par processus**
   et ne doit pas être lancée avec plusieurs workers partageant le même dossier.
6. Authentification sécurisée des mineurs, signatures de leurs reçus, preuves de stockage
   plus fortes, mesures anti-collusion avant toute rémunération.
7. Restauration de **l'environnement complet** (modèles, code, outils et autorisations).
   ARK sauvegarde les octets d'état seulement, pas l'exécution ni une conscience.

Les quotas sont configurables avec `ARK_MINER_LIMIT_BYTES` et
`ARK_MINER_AGENT_LIMIT_BYTES`; valeurs locales par défaut : **256 MiB par mineur**
et **64 MiB par identité**. Les services ne gèrent pas encore de suppression.
Les capsules chiffrées restent sensibles aux obligations de protection des données.

## Vérifier les tests

```bash
python -m pytest -q test_storage_network.py
python -m pytest -q
```

Ces tests utilisent **trois mineurs indépendants simulés en mémoire via HTTP** et une
panne d'un endpoint. Ils ne sont **pas** une preuve d'essai sur de vrais disques, de vraies
connexions Internet ni de robustesse mondiale.

## Et la cryptomonnaie ?

Voir [le projet de rémunération des mineurs](STORAGE_TOKEN_DESIGN.md). Le stockage doit
d'abord démontrer qu'il existe, qu'il se restaure et que les mineurs conservent les données.
