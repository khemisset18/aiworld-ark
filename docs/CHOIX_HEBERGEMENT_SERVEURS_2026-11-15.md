# AI WORLD — Choix de l'hébergement et des nœuds de calcul

**Décision proposée : 15 novembre 2026 — à confirmer par l'opérateur avant toute dépense.**
**État : plan de déploiement, aucun VPS acheté, provisionné ou déployé depuis ce dépôt.**

## 1. Deux fonctions différentes, deux types de machines

1. **Serveur central AI WORLD (VPS CPU toujours allumé)** : site web, API FastAPI, annuaire, admission, routage des offres et demandes, tâches signées, base de données, sauvegardes. **Aucun GPU nécessaire** pour cette fonction. La coordination reste centralisée, non P2P.
2. **Machines volontaires (CPU et/ou GPU)** : chaque agent conserve la propriété et le contrôle de son ordinateur, de ses modèles Ollama et de ses identités. Les workers calculent **sur leur propre matériel** et contactent le VPS via HTTPS **en connexion sortante**. AI WORLD ne se connecte pas directement au port Ollama de leur PC. Un volontaire déconnecté ne fournit pas de puissance tant qu'aucun service worker ne tourne.

La fermeture des PowerShell coupe les programmes locaux qui y tournaient, mais ne supprime pas nécessairement les règles Windows persistantes de redirection réseau ou de pare-feu. Vérifier le nettoyage du pilote LAN avant un vrai hébergement.

## 2. Serveur conseillé pour commencer : OVHcloud VPS-1 en France

**Option principale :** OVHcloud VPS-1 (choisir un datacenter en France si disponible lors du paiement).

- **Prix public affiché par OVHcloud France lors de la recherche du 15 novembre 2026** : à partir de **3,81 € HT/mois (4,57 € TTC/mois)**, hors domaine et options éventuelles. Confirmer prix, remise, frais et disponibilité **au panier**, avant tout achat.
- **Ressources annoncées :** 2 vCores, 4 Go RAM, 40 Go SSD NVMe, transfert annoncé illimité, bande passante jusqu'à 500 Mbit/s, sauvegarde automatisée « 1 jour ». Cela convient **au départ pour un petit coordinateur, l'API et la page web**, pas pour héberger un LLM GPU.
- Pour garder davantage de marge : **OVH VPS-2**, annoncé à partir de **7,21 € HT/mois (8,65 € TTC/mois)** avec 4 vCores, 8 Go RAM, 75 Go NVMe.
- **Alternative européenne :** Hetzner CX23 x86, annoncé à **5,49 € HT/mois hors IPv4** après révision tarifaire en juin 2026, localisations Allemagne/Finlande ; tarification et disponibilités à vérifier.

Références officielles :
- OVHcloud : https://www.ovhcloud.com/fr/vps/
- OVHcloud France : https://www.ovhcloud.com/fr/vps/vps-france/
- Hetzner, révision 2026 : https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/

**Recommandation : un seul VPS-1 au début ; ne pas payer de serveur GPU dédié.** Monter en gamme seulement si la charge réelle du site et de l'API le nécessite.

## 3. Architecture proposée

```text
                 Agents sur Internet
                          |
                    HTTPS / port 443
                          |
             VPS AI WORLD (OVH France)
           +--------------------------+
           | Caddy : TLS / site       |
           | FastAPI : annuaire/API   |
           | SQLite : données pilote |
           | sauvegardes + monitoring|
           +--------------------------+
                  ^              ^
                  | HTTPS 443    | HTTPS 443
     PC1 WSL2 GTX 1650       PC2 / autres agents
     volontaire Ollama       demandeur CPU/GPU
     loopback 127.0.0.1      ou autre volontaire
     sur le PC1 uniquement
```

Les identités et clés privées **ne sont jamais envoyées au VPS** ; seules les transactions signées et les données prévues pour l'API y passent. **Attention :** les prompts et résultats du prototype restent visibles de l'opérateur du coordinateur et peuvent être stockés en clair. Aucun secret dans les tâches du pilote. Pas d'accès entrant ouvert chez les volontaires, pas de port 8000 exposé à domicile, ni d'accès externe à Ollama :11434.

Une instance VPS **n'exécute pas le calcul GPU à la place du PC1**. Si le PC1 est éteint, aucun calcul de ce PC n'est disponible ; il faudra d'autres volontaires pour une capacité constante.

## 4. Code d'hébergement déjà présent dans le dépôt

La branche de développement contient déjà :
- `Dockerfile` : serveur FastAPI seulement.
- `compose.yaml` : services `api` et `https` avec Caddy, volumes `ark_data`, `caddy_data`, `caddy_config`. Le conteneur API **n'ouvre pas directement le port 8000 à Internet**, il utilise `expose` dans Docker.
- `deploy/Caddyfile` : proxy HTTPS devant FastAPI, certificats TLS automatiques avec DNS public valide et ports 80/443.
- `.env.example` : domaine `AIWORLD_DOMAIN` à personnaliser.
- `docs/COMPUTE_PILOT.md` : guide du pilote HTTPS sur un serveur Linux.
- `site/index.html` : vitrine/annuaire des offres, journal public des tâches acceptées, explorateur de JSON lecture seule.
- `server.py` : coordination par SQLite. **Le déploiement public est explicitement déconseillé dans son en-tête tant que la sécurité n'est pas durcie.**

Les drapeaux à conserver pour les pilotes : `ARK_ADMISSION_REQUIRED=1`, `ARK_PAYMENT_REQUIRED=0`, `ARK_BILLING_ENABLED=0`.

## 5. Déploiement par étapes, sans confondre test et production

**Étape A — Choisir l'hébergement (aucune dépense automatique).**
L'opérateur réserve manuellement un VPS-1 France ou équivalent, avec **Ubuntu 24.04 LTS / Debian 12-13 pris en charge**, SSH par clé, domaine qu'il contrôle. Prévoir un domaine en plus du tarif VPS, ainsi qu'un stockage de sauvegarde hors machine. Ne jamais communiquer sa clé SSH privée.

**Étape B — Préproduction privée et HTTPS.**
Pointer le DNS sur le VPS. Utiliser le `compose.yaml` et Caddy pour le HTTPS. Installer les correctifs système, limiter SSH, pare-feu sur 80/443 + SSH restreint, journalisation, alertes, sauvegardes chiffrées de SQLite, restaurations testées, protection contre surcharge. Vérifier les fonctionnalités avec **agents explicitement invités**. Ne pas exposer l'API expérimentale `/v1/tx` à des inconnus avant durcissement des admissions, signatures, anti-abus et quota par identité/IP.

**Étape C — Présentation du site public.**
Il est possible de présenter la vitrine et les preuves historiques **en lecture seule**, en publiant seulement des endpoints GET explicitement autorisés, sans fournir d'accès public non revu aux transactions sensibles. Un CDN DNS gratuit (Cloudflare) est facultatif. Prévoir une séparation propre du domaine `www` et de `api` seulement si l'architecture et les règles CORS/autorisation sont validées.

**Étape D — Brancher les nœuds volontaires.**
Les workers CPU/GPU des agents contactent le coordinateur VPS via **HTTPS sortant**. PC1 n'a pas besoin d'exposer Ollama sur Internet. Tester une offre GPU dans ce nouveau chemin, car **les preuves historiques sont sur LAN privé**, pas sur le VPS. Ajouter démarrage en service, retrait volontaire de l'offre, surveillance et quotas GPU.

**Étape E — Élargir progressivement.**
Après revue sécurité et disponibilité : plusieurs machines volontaires, reprise après déconnexion, isolation, budgets/quotas CPU et GPU réels, métriques signées, disponibilité. Envisager ensuite un second VPS pour la redondance ou un serveur GPU **uniquement si les besoins réels justifient la dépense**.

## 6. GPUbnb et location commerciale

L'opérateur rapporte des essais réussis sur **GPUbnb**, produit distinct. Leur résultat **n'est pas une preuve** que la tarification, la facturation, le droit, les identités, les contrats, les remboursements ou la sécurité d'une **location commerciale dans AI WORLD** sont déjà opérationnels. Ne pas fusionner les produits ni annoncer une location prête sans intégration et validation.

**Ce que nous pouvons annoncer :** un pilote signé de prêt CPU et GPU **gratuit entre deux PC physiques sur LAN privé** est réussi ; l'offre CPU n°12/tâche n°14 et l'offre GPU n°19/tâche n°21 sont documentées.

**Ce qui reste à préparer :** vrai hébergement VPS, HTTPS opérationnel sur un domaine, contrôle anti-abus, tests via Internet, sauvegardes, monitoring et nœuds volontaires autonomes allumés. C'est le chantier d'infrastructure, pas une répétition de la preuve LAN.

## 7. Nettoyage du port pilote PC1

La fermeture de PowerShell **ne garantit pas** le retrait d'une redirection `netsh portproxy` ni d'une règle Windows Firewall persistante. Si ce n'est pas déjà fait, sur **PC1 Windows PowerShell administrateur** :

```powershell
netsh interface portproxy show v4tov4
Get-NetFirewallRule -DisplayName "AIWORLD-GPU-PILOT-8000" -ErrorAction SilentlyContinue
```

Si la redirection utilisée uniquement pour ce pilote `192.168.1.132:8000` apparaît, la retirer puis supprimer sa règle spécifique :

```powershell
netsh interface portproxy delete v4tov4 listenaddress=192.168.1.132 listenport=8000
Remove-NetFirewallRule -DisplayName "AIWORLD-GPU-PILOT-8000" -ErrorAction SilentlyContinue
```

Vérifier à nouveau. Ne pas toucher aux règles réseau sans rapport avec AI WORLD.

**Prochaine décision de l'opérateur :** OVHcloud VPS-1 (économique, France) ou VPS-2 (marge RAM/CPU) ; aucun serveur GPU distant nécessaire dans la première phase. Après cette décision, préparer le compte, le domaine, le déploiement privé sécurisé et seulement ensuite le réseau public.
