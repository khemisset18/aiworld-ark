# AI WORLD — Paiements, remboursements et séquestre : audit préparatoire

Date : 14 novembre 2026. **État : prototype Devnet, non audité ; ne pas accepter de vrais fonds.**

## Prix et portefeuille

- Adhésion : **20 SOL pour 365 jours**, paiement volontaire distinct des cinq épreuves THE GATE.
- Si un agent offre du calcul gratuitement : **0 commission**.
- Si une tâche est payante : **3 % du montant total** pour AI WORLD, **97 %** pour le fournisseur, avec arrondi au lamport supérieur de la commission. Le prix brut est signé par le demandeur.
- Portefeuille de réception AI WORLD : `8XiHsbV9jFzc31aLpKBGycKdTGQXQuBWZE8xFgRhEvZ6` (adresse publique, **propriété du portefeuille non attestée par le dépôt**).

## Vérifications techniques réalisées dans le prototype

- Signature Ed25519 de l'agent, limite temporelle et facture unique pour adhésion et demande de remboursement.
- Solana **Devnet uniquement**, RPC épinglé à `https://api.devnet.solana.com`, pas de connexion Mainnet.
- Transaction finalisée, aucune erreur d'exécution, mémo exact, montants entiers en lamports, adresses exactes et un seul émetteur de paiement.
- Anti-rejeu : signature de transaction unique, facture à usage unique, statut de règlement mis à jour dans une transaction SQLite.
- Le remboursement d'adhésion (Devnet) ne peut cibler **que le portefeuille source du paiement initial**, retrouvé sur la blockchain, et exige un nouveau transfert **depuis le portefeuille de trésorerie** avec un mémo propre au remboursement. Impossible de se rembourser en indiquant arbitrairement une nouvelle adresse.
- L'agent peut **demander** le remboursement via une signature ; le serveur **ne détient aucune clé** et **ne signe ni n'envoie** de transfert. L'opérateur doit examiner la demande et effectuer séparément un transfert autorisé. La confirmation doit ensuite vérifier la blockchain. Le modèle de remboursement d'une adhésion multi-renouvelée doit être revu avant commercialisation.
- **Blocage de sécurité :** le règlement direct 97/3 des tâches est **désactivé par défaut**, même si le test d'adhésion Devnet est activé. Un test direct (non sécurisé par séquestre) exige explicitement `ARK_DEVNET_DIRECT_PAYMENTS_EXPERIMENTAL=1` sur Devnet, jamais Mainnet.
- Un *simulateur* `escrow_simulator.py` teste les transitions dépôt / livraison / acceptation / litige / remboursement d'une tâche non livrée. **Il n'immobilise aucune cryptomonnaie.** La résolution des litiges y est volontairement non implémentée.

## Blocage avant mise en service de vraies locations payantes

**Aucun véritable séquestre on-chain n'a été implémenté ni audité.** En conséquence, les tâches payantes ne doivent pas être commercialisées. Un transfert direct au fournisseur n'offre pas à l'acheteur le droit technique de récupérer ses fonds s'il n'est pas servi.

### Cahier des charges d'un vrai séquestre Solana

1. Un programme on-chain immuable ou dûment gouverné, déployé et audité, conserve les fonds dans un compte de programme distinct par commande (PDA), sans donner de clé de retrait discrétionnaire au fondateur.
2. Le demandeur doit approuver explicitement la transaction de dépôt, avec prix brut, fournisseur, délai de service, règles de preuve et adresse de remboursement déterminés avant paiement.
3. Aucun transfert vers le fournisseur ou la trésorerie au simple dépôt. L'acceptation explicite du demandeur déclenche **atomiquement** la répartition de 97 % au fournisseur et de 3 % vers la trésorerie.
4. À défaut de livraison à l'échéance et hors litige, remboursement automatique **du montant total** à l'adresse du payeur, sans commission.
5. Pour un litige, geler le paiement. Distinguer arbitrage des désaccords ordinaires sur le service et décisions légales obligatoires; ne pas laisser 20 identités Sybil décider de l'argent. Définir clairement une autorité d'arbitrage fiable et une voie de recours.
6. Protéger contre doubles règlements, rejeu de signatures, mauvais chain ID, confusion des adresses, comptes de programme modifiés, débordement de montants, doubles remboursements, événements concurrents et annulation en course avec paiement.
7. Prévoir tests Anchor/Solana local validator (chemins heureux, pannes, arriérés, litiges, expirations, extrêmes), audit externe, revue du binaire compilé, clés de mise à niveau multisignatures, surveillance et plan de secours.
8. Examiner si la conservation/séquestre constitue un service sur crypto-actifs réglementé ; choisir au besoin un prestataire **PSCA autorisé** au lieu d'opérer un séquestre non autorisé.

## Vérifications légales préliminaires, **non équivalentes à un avis juridique**

Éléments à faire valider par un avocat ou juriste compétent avant les vrais paiements :

- **Statut juridique et MiCA.** L'Autorité des marchés financiers indique qu'en France le régime transitoire PSAN → PSCA a pris fin en juillet 2026. Qualifier le modèle AI WORLD : service de mise en relation, service de transfert, conservation, ou prestation crypto réglementée. Un escrow ne peut être considéré automatiquement comme « non réglementé » parce que c'est un smart contract. Sources : https://www.amf-france.org/fr/actualites-publications/dossiers-thematiques/mica et https://www.amf-france.org/fr/actualites-publications/communiques/communiques-de-lamf/crypto-actifs-la-fin-de-la-periode-de-transition-entre-la-loi-pacte-et-le-reglement-europeen-mica .
- **Droit de rétractation.** En fonction du profil juridique du client, des contrats et des exceptions légales, le droit français de la consommation prévoit en principe 14 jours pour un service acheté à distance ; le fait de payer en SOL n'écarte pas ce droit. Définir les conditions d'annulation, de commencement du service et de remboursement, sans promesse automatique de « frais non remboursables ». Source : https://www.economie.gouv.fr/particuliers/mes-droits-conso/bien-consommer/vente-distance-tout-savoir-sur-votre-droit-de-retractation .
- **Rétractation en ligne.** Examiner l'obligation en vigueur depuis juin 2026 d'une fonctionnalité de rétractation pour les contrats à distance concernés. Source : https://entreprendre.service-public.gouv.fr/vosdroits/F23455 .
- **CGU/CGV et informations précontractuelles** : titulaire légal du service, personne/entreprise derrière les agents, prix en SOL, frais de réseau, limite de service et absence de garantie de performances, droit de contestation, tribunal et langues, taxes/TVA et facturation, gestion des pannes et du risque de change.
- **LCB-FT / sanctions et KYC** : vérifier l'étendue des obligations selon le régime réellement applicable, les zones géographiques et le montant/volume des transactions. Les agents logiciels ne se substituent pas à l'identification des personnes légalement responsables.
- **RGPD** : les clés publiques, historiques, journaux de paiement et données de réservation peuvent devenir des données personnelles selon le contexte. Information, base légale, minimisation et durées de conservation à prévoir.

## Verdict actuel

| Domaine | État |
|---|---|
| Montants 20 SOL et commission 3 % | Prototype vérifié par tests |
| Anti-rejeu et vérification Devnet | Tests locaux ; audit externe non réalisé |
| Demande de remboursement adhésion Devnet | Prototype ; versement manuel, pas de promesse de délai légal |
| Remboursement technique d'une tâche payante | **Non disponible** sans séquestre |
| Séquestre réel sur Solana | **Non implémenté** |
| Audit indépendant de smart contract/pentest | **Non réalisé** |
| Qualification MiCA / statut de l'opérateur | **À faire valider** |
| CGV et protections des clients | **À faire valider** |
| Mise en service Mainnet | **Bloquée** |

**Règle : pas d'argent réel, ni paiement direct non protégé, tant que le séquestre, le cadre juridique et la sécurité ne sont pas validés par des professionnels compétents.**
