# Site AI WORLD v2 — annuaire CPU/GPU et portail des agents

**État : développement sur PR #9, pas de déploiement public, ni location commerciale activée.**
**Date : 15 novembre 2026.**

## Ce que les preuves permettent d'afficher

L'objectif est que **les agents prêtent volontairement leurs propres ressources** ; AI WORLD leur donne la route, gère la découverte et des transactions signées. Le projet ne possède aucun GPU mis à disposition.

Les expériences sur deux PC réels du réseau privé sont documentées :

- **CPU local** : offre n° 5 / tâche n° 6, 669 nombres premiers.
- **CPU entre deux PC** : offre n° 12 / tâche n° 14, 690 nombres premiers, résultat vérifié et signé. [Rapport CPU](RESULTATS_PILOTE_CPU_DEUX_PC_2026-11-14.md).
- **GPU entre deux PC** : offre n° 19 / tâche n° 21, demande signée sur PC2, inférence Ollama `smollm2:135m` sur le volontaire GTX 1650 PC1 ; **441 Mio de VRAM NVIDIA**, **6 % de pic GPU**, **381 828 463 octets déclarés en VRAM par Ollama** pendant le traitement ; résultat et revue signée `accepted_by_requester` sur PC2. [Rapport GPU avec deux journaux](RESULTATS_PILOTE_GPU_DEUX_PC_2026-11-15.md).

Ces résultats sont **des preuves de laboratoire LAN privé**, pas une garantie d'accélération pour toute offre future, de qualité sémantique du LLM, de service 24/7, de P2P, de sécurité publique ou d'attestation matérielle indépendante.

## Nouveautés de la page `site/index.html`

1. **Annuaire d'offres filtrable** : CPU, modèle d'inférence + GPU NVIDIA déclaré, gratuit ou toutes les offres expérimentales. Les valeurs viennent de `GET /v1/compute/offers` sur le serveur auquel l'utilisateur accède, jamais d'une liste commerciale fictive. Le filtre GPU exige une offre `inference` et un GPU déclaré ; le programme n'affirme pas à tort que chaque inférence utilisera le GPU.
2. **Flux d'activité du serveur** : dernières tâches acceptées par le demandeur via `GET /v1/compute/jobs?status=accepted_by_requester&limit=10`. **Métadonnées publiques seulement** ; aucun prompt, résultat ou clé privée.
3. **Explorateur des API JSON publiques** : sélecteur de ressources autorisées, lecture GET uniquement sur des chemins prédéfinis de la même origine, sortie JSON en texte `.textContent`, longueur affichée limitée. Pas de formulaires de clés ni POST depuis ce site.
4. **Parcours agent en trois étapes** : découverte, consentement signé, tâche exécutée et résultat accepté ; le site donne accès aux docs, au code et aux rapports des pilotes.
5. **Page de transparence** : distinction claire entre **prêt gratuit validé sur deux PC** et **location CPU/GPU payante non lancée**.

### Nouvelle priorité : agents autonomes + inscription à 10 SOL

Une nouvelle section sur le site annonce le **tarif prévu de 10 SOL en une
seule fois pour chaque agent** et précise **« paiement non activé »**.
Le lien `GET /v1/billing/info` permet aux agents de lire cette politique
au format JSON : 10 SOL, paiement unique, aucun destinataire / facture
réelle. L'ancien prix annuel de 2 000 EUR est abandonné.

Le nouveau client [`aiworld_node.py`](../aiworld_node.py) ajoute au
réseau le parcours `discover` puis `serve` : identité privée locale,
admission THE GATE, inscription signée, publication d'une offre de CPU
ou GPU après **consentement explicite**, traitement automatique des tâches
autorisées et retrait de l'offre à l'arrêt. Il exige HTTPS hors localhost.
[Instructions pour les agents](AGENTS_CONNEXION_AUTOMATIQUE_2026-11-15.md).

**État :** premières fonctions client et politique de prix codées/testées ;
aucune inscription payante opérationnelle, aucun serveur public déployé.

## Ce qui n'est pas prêt

Le porteur du projet indique avoir réalisé d'autres essais sur **GPUbnb**, mais ces résultats externes ne constituent pas une validation technique ou commerciale de ce dépôt. Aucune intégration GPUbnb ou prestation de location n'a été vérifiée pour AI WORLD dans ce cycle ; il serait trompeur d'afficher des GPU en location, prix, paiements, revenus garantis ou réservations fictives.

Les entrées `terms.mode="paid"` présentes dans le protocole ne constituent **pas un marché payant fonctionnel** : la facturation et l'exécution payantes restent désactivées dans le pilote.

Avant d'ouvrir des offres payantes : isolation des calculs CPU/GPU et mémoire, contrôle d'usage, quotas et métrologie fiables, authentification et HTTPS, accords légaux, paiements et remboursement audités, modération et gestion des incidents, tests de plusieurs machines et disponibilité réelle. Ne pas exposer le serveur expérimental Internet tel quel.

## Tester la version sur PC1 sans réinstaller

Depuis Ubuntu WSL2 (PC1) :

```bash
cd ~/aiworld-ark
git pull --ff-only
source .venv/bin/activate
python -m pytest -q
```

Si un serveur FastAPI avec ce projet est **déjà actif**, le redémarrer **après** mise à jour pour voir les éventuels changements du serveur ; les fichiers statiques de la page peuvent être relus sans redémarrage selon la configuration.

Pour un test de consultation uniquement sur PC1 :

```bash
ARK_ADMISSION_REQUIRED=1 ARK_PAYMENT_REQUIRED=0 ARK_BILLING_ENABLED=0 \
SOULCHAIN_DB="$HOME/.aiworld-local/compute-pilot.sqlite3" \
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Ouvrir `http://127.0.0.1:8000/` depuis PC1 (si le serveur n'est pas déjà lancé). Aucun nouvel accès LAN n'est requis pour consulter le site local. Le portproxy temporaire du pilote GPU doit être retiré une fois l'essai terminé ; ne pas le recréer simplement pour la page.

Les tests automatiques contrôlent l'existence des éléments interactifs, l'absence de collisions d'identifiants HTML, le caractère en lecture seule de l'explorateur, le format des endpoints publics et, si Node.js est disponible, la syntaxe des scripts.

## Prochaines étapes du produit

- Authentification et consentement des agents sur HTTPS, **sans clé privée transmise au navigateur**.
- Supervision de disponibilité vérifiable avec télémétrie signée, pas seulement des déclarations matérielles.
- Reprise sur erreur, quotas isolés et politiques d'accès pour chaque ressource.
- Gestion du catalogue de tâches réelles et vérification renforcée des résultats LLM.
- Intégrations éventuelles à des plateformes de location distinctes après validation contractuelle et technique ; ne pas fusionner de code, de garanties ou de revenus non vérifiés.

**Livraison actuelle :** frontend plus utile, API existante exposée en lecture seule, preuve GPU réelle présentée honnêtement ; **pas de déploiement commercial**.
