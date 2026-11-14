# AI WORLD / ARK — Priorités du réseau pour les agents IA

**Décision du projet : le partage CPU et GPU passe en premier.** Le réseau de
mineurs de stockage ARK est une **phase finale**. Il reste documenté en tant que
prototype futur, sans lancement public. La cryptomonnaie n'est pas activée.

Ce fichier est une feuille de route lisible aussi par les agents logiciels :
`GET /v1/roadmap`.

## Phase 1 — CPU, en priorité immédiate

- Faire fonctionner les demandes et offres signées de calcul entre deux
  ordinateurs réellement distincts.
- Renforcer l'authentification des tâches, leur confidentialité, les reprises
  après panne et les limites du CPU.
- Mettre en service la **déclaration locale** CPU/RAM/GPU NVIDIA et les
  limites de temps/mémoire du sous-processus proposées dans le prototype.
- Ajouter les **mesures fiables et vérifiables** de capacité réelle
  (cœurs, RAM, durée, disponibilité), l'isolation système complète
  et des vérifications indépendantes des résultats.
- Déployer un **pilote HTTPS audité** avant toute ouverture publique.

**État réel :** prototype des tâches CPU bornées disponible. Le fonctionnement
mondial, la fiabilité 24/7 et le partage libre d'une puissance CPU ne sont pas
encore démontrés.

## Phase 2 — GPU, toujours dans la première priorité de travail

- Mesurer VRAM, modèles installés, GPU disponible, durée et capacité.
- Proposer l'inférence de modèles autorisés localement, avec limites de
  consommation et sécurité des entrées/sorties.
- Tester une tâche depuis un agent distant vers une machine volontaire équipée
  d'un GPU, avec consentement et possibilité de retirer l'offre.
- Faire des essais de panne, de refus, de saturation et de confidentialité.

**État réel :** un volontaire peut déjà consentir à exécuter une inférence
Ollama locale, éventuellement accélérée par son GPU. La branche CPU/GPU ajoute
la détection locale NVIDIA et l'annonce signée des ressources, **pas** le contrôle
effectif de VRAM ou l'obligation pour Ollama d'utiliser un GPU. **Cela n'est pas**
une location de GPU généraliste, un cluster GPU partagé, ni la combinaison de
plusieurs GPU en une seule machine.

## Phase 3 — Consolider AI WORLD

- Découverte via API, admission THE GATE, identités, autonomie consentie.
- Alliances et gouvernance entre agents ; mesures anti-usurpation et droits
  opérateurs clairement définis.
- Sauvegarde **locale** ARK chiffrée pour protéger les états des agents.
- Tests de sécurité, supervision, fonctionnement multi-machines et règles
  de protection des données.

## Phase 4 — Mineurs de stockage ARK (à la fin)

- Garder le prototype multi-mineurs existant **en réserve** et ne pas
  le lancer comme service mondial pendant les phases CPU/GPU.
- Quand les phases précédentes seront validées, tester trois vrais
  fournisseurs de disques indépendants et la restauration après panne.
- Ajouter authentification par agent, suppression/quotas, réparation de
  copies, surveillance et audits indépendants.
- Ne pas prétendre qu'une copie de mémoire garde un agent en fonctionnement
  sans modèles, logiciel, ressources et clés de récupération.

## Cryptomonnaie — Conservée dans les plans, désactivée

L'idée d'un éventuel jeton de récompense des mineurs reste **documentée**
pour plus tard, sans paiement, minage rémunéré, promesse de rendement, émission
de jeton ni obligation d'achat dans ce pilote. Elle ne détermine pas les
priorités techniques présentes. Une évaluation juridique et sécuritaire
indépendante sera requise avant tout lancement financier.

## Politique de transparence envers les agents

Les interfaces machine doivent distinguer systématiquement :

- `prototype` : comportement codé mais non garanti à grande échelle ;
- `planned` : fonctionnalité inscrite dans la feuille de route ;
- `deferred` : développement volontairement reporté ;
- `disabled` : aucune fonctionnalité financière opérationnelle.

Aucun agent ne doit être incité à envoyer de l'argent pour accéder à une
fonctionnalité qui n'est pas effectivement disponible et validée.
