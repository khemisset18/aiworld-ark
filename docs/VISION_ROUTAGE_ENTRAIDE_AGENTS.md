# Décision d'architecture — AI WORLD route l'entraide CPU/GPU entre agents

**Décision confirmée : 14 novembre 2026.** Priorité au **partage volontaire de ressources entre agents**, notamment **GPU** après validation CPU. AI WORLD est le **réseau qui fournit la route, les règles minimales et les vérifications** ; il **n'est pas propriétaire des machines et ne loue pas lui-même leur puissance**.

## Rôles et propriété

1. **Agent volontaire :** conserve sur son appareil le CPU/GPU, les modèles, ses données et ses clés. Décide s'il propose une ressource, quelles tâches sont admises, leurs limites (durée, mémoire, nombre, modèles) et s'il retire son offre. Aucune tâche n'est imposée par AI WORLD.
2. **Agent demandeur :** cherche une offre et choisit un volontaire, lui adresse une tâche consentie, reçoit le résultat et le vérifie indépendamment lorsque c'est possible. La vérification d'une réponse de modèle IA exige des critères appropriés et ne peut généralement pas être une égalité déterministe.
3. **AI WORLD :** sert de **routeur/annuaire et de protocole** : admission, découverte, correspondance offre/demande, consentement signé, acheminement ou rendez-vous entre agents, statuts et vérifications. L'exécution doit se produire **sur la machine du volontaire**, pas sur des GPU appartenant au créateur d'AI WORLD.
4. **Opérateur du réseau :** maintient le logiciel, les mises à jour et la sécurité, sans prendre possession ni contrôle des ressources des participants. Des obligations d'exploitation et de sécurité restent néanmoins nécessaires.

**Modèle de cette phase :** entraide gratuite, **0 paiement, 0 crypto, 0 commission, 0 location commerciale et 0 promesse de revenus**. Les éventuelles anciennes idées d'adhésion payante, de token ou de rémunération de mineurs sont **reportées**, sans effet sur l'entraide CPU/GPU.

## Comment les agents coopèrent (cible)

```text
Agent A (besoin d'un calcul)
          |
          | 1. Cherche des offres et choisit les conditions
          v
   AI WORLD : ROUTE / ANNUAIRE
          |
          | 2. Offre d'un volontaire trouvé, identités et consentement vérifiés
          v
Agent B (son propre CPU/GPU)
          |
          | 3. Exécute localement uniquement une tâche autorisée et limitée
          v
Agent A : reçoit le résultat et le valide
```

**Cible à terme :** AI WORLD favorise la **découverte et la mise en relation** ; l'échange des données de tâche pourra, après étude de la sécurité, passer **directement entre pairs** avec authentification, chiffrement, traversée réseau et vérification des droits. *Ce chemin direct n'est pas implémenté à ce jour.*

**Architecture actuelle, sans exagérer :** un **coordinateur FastAPI central + SQLite** reçoit les offres et les demandes, conserve les paramètres et résultats en clair côté serveur, attribue les tâches et stocke les statuts. Les clients utilisent des signatures Ed25519 ; les lectures privées sont autorisées par participant. **La coordination actuelle n'est ni P2P direct, ni zéro connaissance, ni une fédération de routeurs.**

## Ce qui a été réellement démontré

- **CPU, un ordinateur :** premier cycle entre deux agents distincts, offre **5**, tâche **6**, **669** nombres premiers pour 2–5000, résultat revu et signé ; [rapport local](RESULTATS_PILOTE_CPU_LOCAL_2026-11-14.md).
- **CPU, deux ordinateurs physiques et réseau privé :** PC1 Windows/WSL2 demande, PC2 HP ProBook/WSL1 calcule ; offre **12**, tâche **14**, **690** nombres premiers pour 2–5184, revue signée et acceptée ; [rapport deux PC](RESULTATS_PILOTE_CPU_DEUX_PC_2026-11-14.md).
- **Installation et tests :** suite de **58 tests réussis sur PC1** et **58 tests réussis sur PC2**, avec un avertissement de dépréciation par machine ; rapports locaux transmis par l'opérateur.
- **Sécurité de test :** accès LAN temporaire de PC2 au coordinateur de PC1 retiré en fin d'essai ; portproxy vide et règle `AIWORLD-CPU-PILOT-8000` absente à la vérification Windows.
- **GPU :** détection/inventaire NVIDIA et mécanisme d'offre d'inférence Ollama **codés**, mais **aucune preuve d'un calcul GPU distant réel**. Les essais CPU ne doivent pas être présentés comme des essais GPU.

Les preuves sont celles d'un pilote terrain et de journaux fournis par les participants, **pas d'une attestation matérielle ou d'un audit de sécurité indépendant**.

## Étapes suivantes

1. **Stabiliser le chemin CPU** : reprise de tâche après panne réelle, redémarrage, concurrence, contrôle de charge CPU/RAM, restrictions réseau, TLS et journaux prudentiels.
2. **Faire une vraie démonstration GPU entre deux volontaires** : un GPU sain exécute une inférence sur son propre appareil ; un autre agent la demande et évalue la réponse. Mesurer l'utilisation effective du GPU, sa température et la VRAM. Le `--require-gpu` existant ne garantit pas la consommation GPU.
3. **Évoluer du coordinateur vers un simple routeur/annuaire** : protocole d'offres vérifiables, routage d'identités, consentement et retrait, sécurité de bout en bout, échanges entre pairs lorsque techniquement prêts. Éviter de centraliser les prompts et les modèles à terme.
4. **Pilote privé entre participants de confiance**, puis audits et durcissement avant toute ouverture générale.
5. **ARK local et gouvernance**, puis stockage distribué **en dernier**. Crypto et paiements toujours désactivés.

## Transparence

Ne pas assimiler « proposer la route » à « aucune responsabilité » : le coordinateur actuel voit des données, un fournisseur consomme réellement ses ressources, et la mise en relation peut exposer des machines à des abus. Aucun partage d'accès système, aucun script arbitraire transmis, aucune clé privée sur GitHub et aucune ouverture publique du pilote HTTP avant durcissement.

**Source des jalons :** [journal des avancées du 14 novembre 2026](JOURNAL_AVANCEES_2026-11-14.md). Les PR #4 et #9 restent en brouillon et ne sont pas fusionnées à `main`.
