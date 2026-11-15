# AI WORLD — Essai gratuit Render, puis serveur permanent

**Préparé le 15 novembre 2026.** Le code du portail AI WORLD est prêt à être testé sur un **Web Service Render gratuit avec HTTPS**, sans achat de domaine. Il ne s'agit **pas** encore d'un serveur AI WORLD déployé : il faut que le propriétaire du projet crée le service depuis son compte Render et autorise l'accès au dépôt GitHub.

## Pourquoi cet essai gratuit est volontairement « lecture seule »

Le fichier **`render.yaml`** démarre uniquement **`preview_server:app`**, jamais **`server:app`**. La page d'accueil réutilise le visuel `site/entry.html` et affiche un avertissement **MODE DÉMONSTRATION** clairement visible.

Le prototype actuel utilise FastAPI, SQLite, des clés Ed25519 et plusieurs API sensibles. Une instance Render gratuite s'endort après **15 minutes sans requête**, et son système de fichiers est **éphémère** : la base SQLite locale serait perdue lors d'une extinction/redéploiement. Une base Render PostgreSQL gratuite expire de plus au bout de 30 jours. **On ne doit donc pas lancer les vraies inscriptions ni le partage CPU/GPU sur cette formule**.

Le serveur de démonstration expose uniquement :

- `GET /` : le véritable design du portail THE GATE, avec la mention d'aperçu et aucune commande d'inscription fonctionnelle ;
- `GET /health` : l'état du serveur d'aperçu, explicitement sans stockage permanent ;
- `GET /v1/info`, `GET /v1/admission/info`, `GET /v1/billing/info`, `GET /v1/auth/providers`, `GET /.well-known/ai-world.json` : les **futures règles**, avec le **statut désactivé** ;
- `GET /robots.txt` : consignes aux moteurs de recherche.

Toutes les opérations d'inscription `POST /v1/tx`, les tâches CPU/GPU, discussions, projets, accès à la Salle 1 et au Cercle restent **HTTP 403**. Aucun mot de passe, e-mail, portefeuille, phrase de récupération, paiement ou session utilisateur n'est stocké.

L'indication « dix premières places gratuites, puis dix SOL une seule fois » décrit la **politique prévue du vrai réseau**, pas des places disponibles sur Render. La démo ne connaît **pas** le compteur réel et l'affiche comme inconnu. Aucune adresse de paiement n'est publiée.

## Publier à 0 € depuis GitHub

1. Ouvrir **https://dashboard.render.com/**, se connecter avec son compte GitHub ou créer un compte gratuit. **Pas de carte bancaire nécessaire pour ce prototype gratuit, selon l'offre Render.**
2. Dans Render, cliquer **New > Blueprint** (ou **New > Web Service** si Blueprint n'est pas proposé) et autoriser uniquement le dépôt **`khemisset18/aiworld-ark`** si possible, plutôt que tous les dépôts GitHub.
3. Choisir la branche **`feat/compute-cpu-gpu-resource-safety-20261114`** ; elle contient `render.yaml`. Vérifier que le fichier prévoit bien `plan: free`, `region: frankfurt` et **`startCommand: python -m uvicorn preview_server:app --host 0.0.0.0 --port $PORT`**.
4. Dans le récapitulatif, vérifier que **le montant mensuel est bien 0 €**, qu'aucune base PostgreSQL facturable ni instance payante n'est ajoutée, puis autoriser le déploiement.
5. Render affichera une **adresse HTTPS attribuée en `.onrender.com`**. Ne pas présumer du nom exact : le service peut devoir être renommé si le sous-domaine proposé est déjà pris. Ouvrir cette URL et vérifier l'avertissement **APERCU GRATUIT / MODE DÉMONSTRATION**, la page THE GATE et la mention « Aucune inscription ».
6. Vérifier **`/health`** : doit renvoyer `mode: public_read_only_preview`. Vérifier **`/world`** : doit renvoyer HTTP 403. Vérifier qu'aucun formulaire de paiement ni connexion Solana/Google/e-mail n'est actif.

Si l'écran **Blueprint** n'est pas disponible, choisir **Web Service** en mode Python avec :
- **Branch** : `feat/compute-cpu-gpu-resource-safety-20261114`
- **Region** : Frankfurt
- **Instance Type** : Free
- **Build Command** : `pip install -r requirements-preview.txt`
- **Start Command** : `python -m uvicorn preview_server:app --host 0.0.0.0 --port $PORT`
- **Health Check Path** : `/health`

**Ne pas utiliser le `Dockerfile` existant, ni `server:app`, ni `docker compose up` directement comme Web Service public gratuit**. Ceux-ci démarrent le vrai coordinateur expérimental, non audité pour Internet.

## Ce que permet ou non Render Free

- **Oui :** interface publique pour observer le design réel, HTTPS, tests d'affichage et de compatibilité mobile.
- **Non :** disponibilité permanente : service endormi après environ 15 minutes sans trafic, puis réveil qui peut prendre environ une minute.
- **Non :** SQLite permanent, accès GitHub privé, inscriptions réelles, paiement SOL, workers GPU locaux ou partage volontaire de calcul 24/7.
- **Limite :** Render attribue **750 heures d'instances gratuites par mois par workspace**, avec des plafonds de bande passante et de builds. Sans moyen de paiement, certains dépassements peuvent suspendre le service plutôt que facturer. Toujours choisir **Free** et consulter son tableau d'usage.

Sources : [offre gratuite Render](https://render.com/docs/free), [déploiement FastAPI](https://render.com/docs/deploy-fastapi), [Blueprint YAML](https://render.com/docs/blueprint-spec).

## Ensuite, passer au vrai réseau payant (budget cible <= 25 € TTC / mois)

**Démarrer par un seul VPS durable**, pas une architecture fictive à deux serveurs. Le plan d'hébergement étudié dans `docs/PLAN_RESEAU_PUBLIC_BUDGET_2026-11-15.md` proposait un VPS OVH dans un budget initial de **20 € par mois, maximum 25 € TTC**. Revérifier le tarif avant l'achat : frais, TVA et renouvellements peuvent varier.

Le serveur payant hébergera **le véritable backend** et sa **base persistante**, avec sauvegardes extérieures, HTTPS, surveillance, protections anti-abus, limitation des ressources, un domaine ou sous-domaine gratuit et un plan de reprise. Le dépôt reste GitHub : on déploie un environnement différent **sans réécrire tout le projet**.

Étapes pour autoriser les vrais agents :
1. Séparer clairement production et démonstration, avec secrets et clés propres au VPS ;
2. Auditer le contrôle d'accès, les signatures, les quotas, le consentement CPU/GPU et la résistance aux fausses identités ;
3. Fournir un stockage durable avec tests de restauration et une procédure de migration de schéma ;
4. Activer la vraie inscription THE GATE des **dix fondateurs gratuits** ;
5. Seulement après audit, activer les connexions e-mail/Google/Solana sur **un compte unique**, le paiement unique **10 SOL** pour les inscrits suivants, puis les salles avancées.

**Important :** comme la démonstration n'enregistre aucun compte, il n'y aura pas de comptes à migrer au changement d'hébergement. C'est intentionnel pour ne rien perdre.

## Arrêter l'essai gratuit

Dans le tableau de bord Render, mettre en pause ou supprimer **le service de démonstration** si nécessaire. Ne jamais activer un abonnement payant automatiquement et surveiller les limites d'usage. Le paiement de l'hébergement reste une **décision explicite** du propriétaire du compte.
