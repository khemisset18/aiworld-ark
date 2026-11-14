# AI WORLD — Escrow SOL on-chain (proof of concept)

**DANGER : code Anchor non audité, non déployé, non connecté aux paiements de production. Aucun SOL réel ne doit être envoyé.**

## But

Pour une tâche de calcul payante, le demandeur et le fournisseur **signent tous deux** la création d'un contrat. Le prix en SOL (lamports), le fournisseur, l'arbitre et le délai sont fixés dans le compte PDA avant le dépôt. Le dépôt est conservé dans un compte contrôlé par le programme Solana et **aucune commission n'est versée au dépôt**.

### Machine d'états

| État | Opération signée | Mouvement SOL |
|---|---|---|
| Initial | `fund` (acheteur + fournisseur) | Prix brut -> compte de séquestre ; stockage du PDA payé séparément par l'acheteur |
| `FUNDED` | `submit_delivery` (fournisseur, avant échéance) | Aucun |
| `DELIVERED` | `accept_delivery` (acheteur) | Atomiquement **97 % fournisseur, 3 % trésorerie** (arrondi entier au lamport) |
| `FUNDED` + échéance dépassée | `refund_undelivered` (acheteur) | **100 % du prix brut** retourne à l'acheteur, **0 % commission** |
| `DELIVERED` | `open_dispute` (acheteur) | Aucun, fonds gelés |
| `DELIVERED` + échéance dépassée | `escalate_undecided` (fournisseur) | Aucun, fonds gelés en litige |
| `DISPUTED` | `arbitrate` (arbitre choisi, nommé au dépôt) | Soit paiement 97/3, soit remboursement 100 % |
| `FUNDED`, `DELIVERED` ou `DISPUTED` | `settle_by_agreement` (**acheteur ET fournisseur signent**) | Soit paiement 97/3, soit remboursement 100 % ; sortie de secours si arbitre indisponible |
| `RELEASED` / `REFUNDED` | Toutes opérations de paiement | Rejetées, aucun double règlement |

`submit_delivery` ne prouve pas que le modèle a vraiment répondu ni que le travail est correct : ce n'est qu'une empreinte signée. Le paiement demande une acceptation acheteur ou une décision de l'arbitre nommé à l'avance, non un clic sur l'API de notre serveur.

**Points forts de l'architecture :** pas de fonction de retrait fondateur, prix déterminé avant dépôt, commission 3 % en lamports entiers, trésorerie fixe `8XiHsbV9jFzc31aLpKBGycKdTGQXQuBWZE8xFgRhEvZ6`, remboursement intégral après non-livraison, aucun double règlement, compte PDA persistant comme témoin d'un règlement terminé. L'arbitre ne peut pas modifier le destinataire ni le pourcentage et doit signer la décision.

**Limites critiques :** l'arbitre est une autorité de confiance sélectionnée par les deux agents. Il peut prendre une mauvaise décision ou devenir indisponible, ce qui peut bloquer les fonds. Une procédure d'appel et une gouvernance d'arbitrage régulée doivent être conçues avant la production. L'existence de 20 clés ne garantit pas 20 agents indépendants. Les frais de rent du compte PDA restent immobilisés pour garder la preuve anti-rejeu ; ils ne font pas partie du prix du travail.

## Source et vérification

Le programme se trouve dans `programs/aiworld_escrow/`. La dépendance Anchor est épinglée à `anchor-lang 0.32.1` en attendant une migration soigneuse. Le **programme ID présent dans le code est un identifiant de développement provisoire**, sans clé de déploiement associée ; il faut créer un ID réel et synchroniser le projet avant déploiement. Ne jamais publier la clé privée de déploiement.

Pour la seule vérification de compilation Rust (pas un test on-chain), lancer :

```bash
cargo check --manifest-path programs/aiworld_escrow/Cargo.toml
cargo test --manifest-path programs/aiworld_escrow/Cargo.toml --lib
```

Un second travail est nécessaire avant Devnet : configurer `Anchor.toml`, générer une IDL, lancer un validateur local, écrire les tests de transactions avec signataires distincts et vérifier les soldes réels. **Le module Python actuel `compute_payments.py` ne dépose pas dans ce programme** ; le paiement direct reste désactivé par défaut.

## Tests qu'il faut passer avant toute activation

- Deux signataires distincts et accord sur l'arbitre, prix, délai, PDA unique ; refuser une clé remplacée.
- Montants extrêmes, calcul exact des 3 %, arrondi, absence de commission en cas de remboursement.
- Interdire la livraison après délai, le remboursement prématuré, le double paiement et le paiement sans acceptation.
- Séquestre isolé pour chaque paire (acheteur, job_id) et conservation d'une preuve après règlement.
- Arbitrage signé par l'arbitre convenu, pas par l'opérateur API ou un arbitre substitué.
- Transactions concurrentes acceptation/refund/dispute : une seule issue financière.
- Tests de stabilité du RPC, simulation de perte de clés, pannes, arbitrage indisponible, secours financier et suivi comptable.
- Audit externe indépendant, code déterministe reproduisible, vérification du programme déployé, gestion multisig des mises à jour, et validation juridique (MiCA/PSCA, RGPD, CGV, recours consommateurs).

## États de livraison

- **Implémenté dans une branche :** source Anchor, états, signatures buyer+provider, répartition 97/3, remboursement non livré, arbitrage nommé, tests unitaires Rust des montants et CI `cargo check`.
- **Non réalisé :** validation sur un vrai validateur Solana, installation/compilation du programme au format SBF, vérification de la sécurité par un auditeur, déploiement Devnet/Mainnet, connexion API au contrat, traitement réglementaire des crypto-actifs pour compte de tiers.

**Pas de levée du blocage des paiements directs ni de mise en production avant la validation de tous ces points.**


## V2 — Preuve d'immobilisation et rapprochement avec AI WORLD

Les nouveaux endpoints sont **désactivés par défaut** et ne fonctionnent que sur **Solana Devnet** :

- `GET /v1/escrow/info` : état de la connexion au programme. `enabled=false` tant que le déploiement réel n'est pas vérifié.
- `POST /v1/escrow/confirm-funded` : `{"job_height":123,"escrow_address":"..."}`. Le serveur lit le compte Solana avec un engagement **finalized** auprès du RPC Devnet officiel, puis valide le propriétaire du compte, le discriminateur Anchor, la correspondance avec les clés enregistrées du demandeur et du fournisseur, le `job_id`, le prix brut signé, la commission **3 %**, la trésorerie, l'arbitre distinct, le délai restant et l'état `FUNDED`. **Sans preuve complète, la tâche payante reste bloquée.**
- `POST /v1/escrow/reconcile-final` : après un dénouement sur Solana, relecture de l'état terminal `RELEASED` ou `REFUNDED`, puis rapprochement idempotent dans le registre SQLite. Aucune déclaration client ne suffit pour annoncer un paiement ou remboursement.
- `GET /v1/escrow/receipts/{job_height}` : journal des preuves Devnet vérifiées.

L'état `FUNDED` signifie **dépôt immobilisé**, pas **revenu déjà encaissé par AI WORLD**. Les 3 % ne sont versés à la trésorerie qu'une fois la tâche acceptée ou libérée avec les signatures nécessaires. Si le contrat rembourse, AI WORLD reçoit **0 SOL** sur cette tâche.

Le lien de financement suppose que les clés Ed25519 des agents enregistrées par AI WORLD correspondent bien aux **signataires des portefeuilles Solana** acheteur et fournisseur. Avant de permettre des portefeuilles externes, prévoir une délégation signée correctement vérifiée des deux côtés.

### Conditions pour tester sur un déploiement réel Devnet

1. Compiler au format SBF avec Anchor 0.32.x et l'outillage Solana compatible ; contrôler l'IDL générée.
2. Générer une clé de déploiement **localement**, jamais dans le dépôt. Exécuter `anchor keys sync` et publier le nouveau `declare_id!` vérifié dans la branche ; le programme ID de développement actuel est un **placeholder**.
3. Déployer sur **Devnet uniquement** et vérifier indépendamment le code, la clé d'upgrade et l'adresse du programme. Aucune clé privée ne doit passer par l'API.
4. Alors seulement, côté serveur de démonstration, renseigner `ARK_BILLING_ENABLED=1`, `ARK_SOLANA_NETWORK=devnet`, `ARK_ESCROW_GATEWAY_ENABLED=1`, `ARK_ESCROW_DEPLOYMENT_VERIFIED=1`, `ARK_ESCROW_PROGRAM_ID=<ID réel>`. Le flag «verified» est une **déclaration opérateur**, pas une attestation cryptographique d'audit externe.
5. Envoyer une transaction `fund` sur Devnet **cosignée par les deux portefeuilles**, puis appeler `confirm-funded` ; l'offre doit être encore ouverte et le délai laisser au moins deux minutes de travail.
6. Le fournisseur publie `submit_delivery` sur la chaîne et l'acheteur décide `accept_delivery` (ou demande arbitrage). Enfin appeler `reconcile-final` pour rapprocher la sortie. Les cas `refund_undelivered` et `settle_by_agreement` doivent aussi être testés.

Ces étapes **ne sont pas encore exécutées avec un programme SBF déployé**. La suite `--features runtime-tests --test escrow_runtime` est un test de banque Solana en mémoire, distinct d'un test de déploiement sur Devnet.

### Risques ouverts

- L'arbitre nommé peut devenir indisponible. L'accord bilatéral `settle_by_agreement` fournit une issue si **les deux parties coopèrent** ; en cas de blocage et d'absence d'arbitre, les fonds peuvent rester gelés. Définir une procédure de secours vérifiable, sans donner d'accès discrétionnaire au fondateur.
- Une empreinte de résultat fournie par un vendeur ne garantit **pas** la qualité du calcul. Accepter ou contester nécessite une validation du demandeur.
- Le site de test n'impose pas encore une politique exhaustive de résiliation, rétractation, TVA, dispute, KYC/LCB-FT. Ne pas collecter de vrais SOL avant une revue juridique indépendante.
- Les tests Python utilisent un faux RPC pour tester le refus de preuves falsifiées ; les tests Rust peuvent exécuter les instructions dans une banque simulée, mais **ne remplacent pas** un test SBF, un audit externe, ni une vérification du binaire déployé.

**Mainnet reste interdit pour cette version.**
