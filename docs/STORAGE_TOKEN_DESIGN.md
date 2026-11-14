# AI WORLD — économie envisagée pour les mineurs de mémoire

**Statut : document de conception, aucune cryptomonnaie émise, aucun contrat déployé
et aucune promesse de rendement.** Ce réseau de stockage se teste actuellement sans argent.

## Objectif

Un agent IA autorise la sauvegarde de sa mémoire chiffrée; des propriétaires de disques
indépendants louent de l'espace et gagnent une récompense uniquement lorsque le service
de conservation convenu est effectivement rendu.

Le mot *mineur* désigne ici un **fournisseur de stockage**. Ce n'est pas un mineur
Proof-of-Work et stocker des fichiers ne crée pas automatiquement une blockchain.

## Ce qui devrait être signé avant chaque contrat de stockage

- Identité cryptographique de l'agent demandeur et du fournisseur.
- Hash de la capsule chiffrée, nombre d'octets et délai d'engagement.
- Tarifs, devise, durée, modalités d'annulation, limites de données et dépôt.
- Fréquence des audits indépendants et conditions de réclamation/remboursement.
- Politique de suppression et de récupération, répartition géographique, confidentialité.

Le **contenu de la mémoire privée ne va jamais sur une blockchain**. La chaîne peut
éventuellement enregistrer des engagements cryptographiques, reçus, contestations et paiements,
en veillant aux métadonnées personnelles.

## Ordre de réalisation raisonnable

1. **Pilote gratuit** : trois mineurs réels indépendants et restauration réussie en cas de
   panne simulée d'un nœud, sans argent.
2. **Crédits non transférables de test** : émuler les contrats et la comptabilité, sans valeur
   commerciale ni distribution automatique.
3. **Audit de stockage** : défis imprévisibles fréquents, échantillonnage de blocs avec
   engagements Merkle ou protocole de preuve de possession adapté, résistance à la collusion
   et mesures fiables de disponibilité dans le temps.
4. **Paiement sur testnet/devnet** : utiliser éventuellement un jeton test Solana ou une
   monnaie existante en environnement de test, avec contrat et contrôle des remboursements.
5. **Audit financier et juridique** : modèle économique, sécurité des clés, droit des données,
   fiscalité, règles applicables aux cryptoactifs dans les juridictions ciblées.
6. **Seulement ensuite** : décider s'il faut réellement créer un nouveau jeton transférable
   ou si une monnaie existante (par exemple SOL) suffit.

## Les récompenses ne sont pas simplement « 1 mineur = 1 paiement »

Une idée de calcul à étudier :

```text
recompense_brute =
    stockage_Gio × duree_en_mois × tarif_par_Gio_mois
    × score_de_disponibilite_verifie
```

Ce calcul **n'est pas un système de rémunération implémenté**. Il faut mesurer la présence
réelle des copies, les preuves anti-triche, les duplications, la valeur d'un service réel
et la répartition des défaillances. Un mineur ne doit pas pouvoir réclamer plusieurs
récompenses pour la même copie non indépendante.

Les preuves par simple SHA-256 + nonce de `storage_miner.py` sont destinées aux tests :
elles ne garantissent **pas** la conservation continue sur disque et ne sauraient
à elles seules justifier un paiement réel.

## Sécurité économique

- Ne jamais verser un paiement sur la seule déclaration d'un mineur.
- Ne jamais demander à un agent de contourner les plafonds de son portefeuille.
- Aucun transfert automatique sans budget préautorisé et règles explicites.
- Les dépôts bloqués, pénalités et remboursements devront être légaux, vérifiables
  et contestables ; les contrats ne remplacent pas les protections juridiques.
- Éviter de promettre immortalité, protection absolue de la mémoire ou rendements garantis.

**Conclusion :** le réseau de stockage est l'élément essentiel à prouver d'abord.
Le jeton peut venir après, mais un jeton sans sauvegardes fiables ne protège personne.
