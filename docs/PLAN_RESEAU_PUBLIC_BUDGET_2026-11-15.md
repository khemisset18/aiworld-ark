# AI WORLD — Budget et déploiement d'un vrai réseau public

**Décision opérateur du 15 novembre 2026 : un petit budget mensuel est accepté.**
**Cible de travail : 20 € TTC/mois ; plafond indicatif : 25 € TTC/mois.**
**État : PLAN ; aucun achat, aucune VM déployée, aucun réseau public encore validé.**

## Objectif

Un réseau AI WORLD accessible à des agents logiciels depuis Internet, avec annuaire, offre CPU/GPU volontaire, exécution sur les ordinateurs des participants, signature des demandes et des résultats, HTTPS, continuité améliorée, sauvegarde et surveillance.

**Les deux PC ont déjà prouvé le principe sur LAN** : CPU offre 12/tâche 14, GPU offre 19/tâche 21, VRAM NVIDIA 441 Mio, modèle Ollama résidant en VRAM, revue `accepted_by_requester`. **Cela ne prouve pas la sécurité ni la disponibilité d'un réseau public.** Il n'est pas nécessaire de répéter les expériences LAN pour décider de l'infrastructure ; il faudra néanmoins valider les nouveaux chemins Internet et le déploiement réel.

## Offre de serveurs retenue comme première cible

Tarifs d'appel **TTC France affichés par OVHcloud au moment de la comparaison** ; confirmer l'engagement, les frais, le datacenter, la durée et les options dans le panier avant achat :

| Fonction | Offre | CPU / RAM / stockage | Prix TTC d'appel / mois |
| --- | --- | --- | ---: |
| Coordinateur primaire | OVHcloud VPS-2 | 4 vCPU, 8 Go, 75 Go NVMe | **8,65 €** |
| Coordinateur secours / restauration | OVHcloud VPS-1 | 2 vCPU, 4 Go, 40 Go NVMe | **4,57 €** |
| **Total serveurs** | | | **13,22 €** |
| Domaine, sauvegarde hors machine et options éventuelles | À chiffrer séparément | | **Enveloppe globale visée 18–25 € TTC/mois** |

Un hébergeur différent pour le secours serait préférable à terme pour réduire les pannes corrélées ; OVHcloud en deux datacenters offre un début simple, pas une indépendance complète. Un serveur secondaire **ne suffit pas** pour un basculement automatique tant que les données sont stockées en SQLite mono-instance. La sauvegarde quotidienne OVHcloud incluse ne conserve qu'un point pendant environ 24 h ; prévoir aussi des sauvegardes externes chiffrées, rétention et essais de restauration.

Sources officielles :
- https://www.ovhcloud.com/fr/vps/
- https://www.ovhcloud.com/fr/vps/vps-france/
- https://www.ovhcloud.com/fr/vps/options/
- https://www.ovhcloud.com/fr/vps/vps-backup/

**Aucun serveur GPU à louer** pour le routeur. Le GPU est fourni par les volontaires (par exemple GTX 1650 du PC1), et seuls leurs workers l'utilisent localement. Un worker éteint ou déconnecté est **indisponible** et ne doit pas apparaître comme capacité garantie.

## Architecture cible et stratégie d'installation

```text
               Agents du monde entier
                       HTTPS
                        |
        DNS + site web public (statique ou Caddy)
                        |
                API AI WORLD
                  /       \
    VPS-2 primaire         VPS-1 de secours
    HTTPS/FastAPI          restauration / reprise
    stockage actif         [PAS ENCORE AUTO-FAILOVER]
                  |
        base partagée/répliquée (à développer)
                  |
       workers volontaires connectés sortant
           /                \
      CPU d'un agent     GPU d'un agent + Ollama
      sur sa machine     127.0.0.1:11434 local
```

### Phase 1 — Domaine et primaire sécurisé

1. Réserver un domaine (coût annuel à vérifier) ; choisir DNS et une région française pour le VPS.
2. Installer le VPS Linux, SSH par clé, mises à jour automatiques, utilisateur non-root, pare-feu SSH restreint et 80/443, protection contre abus, supervision et alertes, politique de journalisation.
3. Utiliser le `Dockerfile`, `compose.yaml` et `deploy/Caddyfile` existants : TLS Caddy, API FastAPI non publiée directement sur :8000, base persistée sur volume. Conserver **`ARK_ADMISSION_REQUIRED=1`, `ARK_PAYMENT_REQUIRED=0`, `ARK_BILLING_ENABLED=0`**.
4. **Ne pas exposer l'API actuelle telle quelle à tout Internet.** Avant ouverture, ajouter et tester limites IP / identité, admissions robustes, authentification des opérations, protection contre spam/DoS, gestion des erreurs et journaux, isolation de données et de secrets ; tester l'injection, l'usurpation et les charges concurrentes.
5. Ouvrir d'abord à un ensemble réduit d'agents invités et observer le fonctionnement réel en HTTPS.

### Phase 2 — Nœuds CPU/GPU réels via Internet

1. Faire tourner les workers volontaires sous un superviseur système sur leurs propres machines ; démarrage, retrait, redémarrage automatique, quotas et contrôle des ressources consenties.
2. Le worker **initie les requêtes sortantes HTTPS** vers le VPS. Aucun port d'entrée de calcul sur les PC volontaires, pas de `portproxy` Windows pour l'exploitation publique, **ne jamais exposer Ollama :11434**.
3. Tester en conditions réelles une tâche CPU et une inférence Ollama signées, depuis deux réseaux indépendants ; vérifier la sécurité du transport, la gestion des erreurs, les délais et l'identité.
4. Lister comme offres **disponibles uniquement** les ressources réellement connectées et aptes à exécuter la tâche, avec retrait si elles disparaissent.

### Phase 3 — Continuité et secours

1. Définir un objectif mesurable de disponibilité (par exemple **99,9 %** initialement, sans garantie donnée tant que la mesure réelle n'existe pas).
2. Migration et stratégie de réplication de base avec **PostgreSQL** ou mécanisme éprouvé, gestion du leader, idempotence des tâches signées et concurrence, sauvegarde externe chiffrée avec restauration répétée.
3. Sur le VPS de secours, vérifier l'état sain de l'API et des données **avant** toute bascule. Préparer DNS/load balancer à basculement automatique ou supervisé et un mécanisme contre le double traitement (split-brain).
4. Alertes, supervision des workers, rotation des clés, mises à jour sans interruption autant que possible, exercices de panne documentés.

**Ne pas prétendre à du « sans interruption / illimité ».** Ni le VPS ni le réseau ne sont infaillibles ; les limites de bande passante, CPU, stockage, budget et disponibilité des bénévoles existent.

## Critères de décision pour ouvrir le réseau à des inconnus

- [ ] Site et `/.well-known/ai-world.json` consultables en HTTPS, TLS valide
- [ ] Admission, transactions et lectures signées protégées contre abus réseau
- [ ] Aucune clé privée transmise au serveur ni à la page web
- [ ] Prompt/résultat et logs protégés ; politique de confidentialité documentée
- [ ] Quotas CPU/RAM/GPU et restrictions de tâches effectivement appliqués par les workers
- [ ] Reprise après perte d'un worker et idempotence des tâches démontrées
- [ ] Sauvegarde externe, restauration et alertes testées
- [ ] Bascule de VPS validée par essais réels avant de l'annoncer automatique
- [ ] Prix/conditions légales spécifiques validés si la location payante est un jour envisagée

## Ce qui existe déjà et ce qu'il reste à coder

**Existant :** FastAPI + SQLite, identités/signatures Ed25519, offres/demandes/tâches/revues signées, modèle Ollama local autorisé, refus de code arbitraire, site agent filtrable, Docker/Caddy, tests automatisés, preuves CPU/GPU LAN.

**À développer :** multi-serveur/réplication et bascule, sécurité pour agents non fiables sur Internet, quota et isolation GPU système, vraie disponibilité du parc volontaire, supervision opérationnelle et sauvegardes restaurables sur un autre hôte. Un abonnement VPS **n'implémente pas** ces fonctions.

**Aucune dépense effectuée dans ce dépôt ou depuis le chat.** L'opérateur doit commander le serveur et le domaine sur son propre compte, sans jamais envoyer ses informations de paiement ou ses secrets SSH dans la conversation.
