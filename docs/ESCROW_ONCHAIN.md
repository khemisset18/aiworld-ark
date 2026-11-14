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
