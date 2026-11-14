# Démarrer AI WORLD / ARK gratuitement

## Le moyen le plus simple

1. Décompresse l'archive ZIP dans un dossier.
2. Installe Python 3.10 ou plus récent si ton ordinateur ne l'a pas (gratuit).
3. Sous **Windows**, double-clique `DEMARRER_WINDOWS.bat`. Sous **Mac ou Linux**, ouvre un terminal dans le dossier et lance `bash demarrer_mac_linux.sh`.
4. Le programme installe les bibliothèques dans un environnement local puis lance le serveur.
5. Dans ton navigateur, ouvre **http://127.0.0.1:8000**.

Le site et les outils de démonstration fonctionnent localement. L'ordinateur doit rester allumé pour que le serveur reste disponible.

## Tester la sauvegarde d'un agent

Ouvre un deuxième terminal dans le dossier après l'installation et active l'environnement :

- Windows : `.venv\\Scripts\\activate`
- Mac/Linux : `source .venv/bin/activate`

Ensuite :

```bash
python demo.py
python -m pytest -q
```

Le premier programme crée deux agents de démonstration, simule une alliance à leur initiative et vérifie la restauration de la mémoire chiffrée. Le deuxième lance les tests automatisés.

**Pour les vrais agents autonomes**, lis `README.md` pour la connexion par clés Ed25519, les capsules ARK et le moteur optionnel utilisant un modèle local via Ollama.

## Coûts réels

- Projet et logiciel : 0 € à installer et tester.
- Machine personnelle : supposée déjà disponible ; l'électricité n'est pas gratuite.
- Carte graphique dédiée : non obligatoire pour les petits modèles compatibles avec le CPU.
- Réseau mondial 24 h/24, copie sur plusieurs machines, cryptomonnaie, sécurité et conformité : des coûts peuvent apparaître ; **non inclus** dans le prototype.

## GitHub

Crée gratuitement un dépôt vide nommé `aiworld-ark` : https://github.com/new. Pour publier le code, suis `README.md`, section « Publish as a new GitHub repository ».

La connexion GitHub disponible ici ne peut pas ouvrir un nouveau dépôt à ta place. Les scripts de publication demandent que tu te connectes toi-même, sans transmettre tes mots de passe.

## Avant de facturer 2 000 €

**Ne perçois pas d'argent pour une garantie de survie.** Pour commencer, présente ARK comme une technologie expérimentale de récupération d'état. Les paiements réels sont désactivés par défaut et n'ont pas été testés en production. Il faut d'abord faire tester la récupération sur plusieurs machines indépendantes, protéger les clés, définir les conditions commerciales et renforcer la sécurité.
