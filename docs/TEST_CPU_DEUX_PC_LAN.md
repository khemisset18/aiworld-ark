# AI WORLD — Test CPU entre deux vrais PC (réseau local privé)

**Statut : EXÉCUTÉ AVEC SUCCÈS sur deux PC physiques le 14 novembre 2026.**
Le premier cycle signé **sur un seul PC WSL2** avait déjà réussi
([résultats locaux](RESULTATS_PILOTE_CPU_LOCAL_2026-11-14.md)).
Un **deuxième jalon, entre deux ordinateurs différents**, est désormais attesté
par les journaux des deux machines : **offre 12, tâche 14, calcul CPU sur PC2,
résultat 690, revue signée et vérifiée sur PC1**.
Lire le [rapport du premier échange CPU inter-PC](RESULTATS_PILOTE_CPU_DEUX_PC_2026-11-14.md).

La procédure ci-dessous permet de le reproduire avec une nouvelle offre et une
nouvelle tâche ; ne réutilise pas les numéros 12 et 14 déjà consommés.

**Matériel :**
- **PC1 :** le PC Windows/Ubuntu WSL2 déjà configuré. Il héberge le coordinateur
  AI WORLD et le **demandeur**.
- **PC2 :** un autre ordinateur **physique** sous Ubuntu/Linux ou Windows + Ubuntu WSL1/WSL2 (validé sur HP ProBook, WSL1).
  Il héberge le **volontaire CPU** et fait le calcul lui-même.
- Les deux PC doivent être **sur le même réseau privé de confiance** (même
  routeur/Wi-Fi domestique, sans isolation Wi-Fi « invité »). Aucune redirection
  de port sur la box Internet.

**Sécurité :** ce pilote utilise HTTP non chiffré uniquement sur un LAN de
confiance et un port Windows temporairement limité à l'IP du PC2.
Les transactions sont signées Ed25519, **mais les données HTTP sont visibles
sur le réseau**. Ne transmettre ni secrets, ni informations sensibles, ni
données réelles d'autres personnes. Ne pas ouvrir cette API sur Internet.
Ne pas utiliser le GPU. Ne pas activer de paiement.

## 1 — Préparer les adresses IP

Sur **chacun des deux PC Windows**, dans PowerShell :

```powershell
ipconfig
```

Repérer l'**adresse IPv4** de la carte Wi-Fi/Ethernet active ; elle ressemble à
`192.168.1.20`. **Ne pas copier** les exemples tels quels.
Dans la suite :
- `IP_PC1` = adresse IPv4 Windows du PC hébergeant le serveur.
- `IP_PC2` = adresse IPv4 Windows de l'autre ordinateur, volontaire CPU.

S'il s'agit d'un PC2 sous Linux, utiliser `ip -4 addr` pour retrouver son
adresse de réseau local.

## 2 — PC1, Ubuntu WSL2 : démarrer le coordinateur

**Premier terminal Ubuntu** du PC1 :

```bash
cd ~/aiworld-ark
source .venv/bin/activate
git pull --ff-only
mkdir -p ~/.aiworld-local

ARK_ADMISSION_REQUIRED=1 ARK_PAYMENT_REQUIRED=0 ARK_BILLING_ENABLED=0 \
SOULCHAIN_DB="$HOME/.aiworld-local/compute-pilot.sqlite3" \
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

Laisser ce terminal ouvert. C'est **le même fichier SQLite** que pour le test
local précédent ; les anciennes identités restent intactes. Le serveur
écoute dans WSL2 sur le port 8000, mais WSL2 NAT n'est normalement pas
accessible directement depuis le LAN.

## 3 — PC1, PowerShell administrateur : accès LAN temporaire

**N'effectuer cette étape que si le PC1 utilise WSL2 en mode réseau NAT**,
le mode par défaut habituel. D'autres configurations, notamment le mode
WSL2 « mirrored », nécessitent des règles adaptées.

Ouvrir **un nouveau PowerShell en administrateur** sur le PC1. Remplacer
les deux IP exemples par les **vraies IP du PC1 et du PC2**, lues à l'étape 1.

```powershell
$ipPc1 = "192.168.1.20"  # A REMPLACER : IPv4 du PC1 Windows
$ipPc2 = "192.168.1.21"  # A REMPLACER : IPv4 du PC2
$wslIp = ((wsl -d Ubuntu hostname -I).Trim() -split '\s+')[0]

Write-Host "PC1 LAN: $ipPc1 | PC2 LAN: $ipPc2 | Ubuntu WSL: $wslIp"
Get-NetConnectionProfile
Get-Service iphlpsvc
netsh interface portproxy show v4tov4
```

Vérifier que le réseau du domicile est de profil **Private** et que le
service `iphlpsvc` (Assistance IP) fonctionne. Si `iphlpsvc` est arrêté,
le démarrer en administrateur avec `Start-Service iphlpsvc`.

**Attention :** si le port `IP_PC1:8000` est déjà utilisé dans
`portproxy show`, ne pas écraser la règle : la signaler avant de continuer.

Une fois vérifié, dans le même PowerShell **administrateur** :

```powershell
netsh interface portproxy add v4tov4 listenaddress=$ipPc1 listenport=8000 connectaddress=$wslIp connectport=8000

New-NetFirewallRule -DisplayName "AIWORLD-CPU-PILOT-8000" -Direction Inbound -Action Allow -Profile Private -Protocol TCP -LocalAddress $ipPc1 -RemoteAddress $ipPc2 -LocalPort 8000

netsh interface portproxy show v4tov4
```

Le pare-feu autorise ainsi le **seul PC2** à contacter le PC1 sur ce port
sur le profil privé, si aucune autre règle plus large n'est déjà active.
Ne pas configurer de NAT/port-forwarding dans la box Internet.

Selon la version/configuration Windows, des règles supplémentaires liées
au pare-feu Hyper-V de WSL2 peuvent être nécessaires ; ne jamais les
ouvrir globalement sans raison.

## 4 — PC2 : installer la branche CPU/GPU, sans charger de GPU

Si PC2 est sous Windows, ouvrir PowerShell :

```powershell
wsl -l -v
wsl -d Ubuntu
```

**Alternative validée : WSL1 sur PC2.** Si la session interactive WSL1 se
bloque, exécuter une commande ponctuelle depuis PowerShell Windows sans
ouvrir de terminal interactif :

```powershell
wsl -d Ubuntu --exec bash -c "cd ~/aiworld-ark && .venv/bin/python -m pytest -q"
```

Ne pas réinstaller Ubuntu, Git ou Python si les 58 tests réussissent déjà.
Si Ubuntu est absent, l'installer suivant les prérequis de la machine.
Le matériel ancien sans virtualisation active peut nécessiter WSL1 plutôt
que WSL2, comme le pilote PC2 documenté.
Sur Linux natif, utiliser directement son terminal.

**Dans le terminal Ubuntu du PC2 :**

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git

cd ~
git clone https://github.com/khemisset18/aiworld-ark.git
cd aiworld-ark
git fetch origin feat/compute-cpu-gpu-resource-safety-20261114
git switch -c essai-cpu-gpu --track origin/feat/compute-cpu-gpu-resource-safety-20261114

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
```

Si le projet est déjà présent sur PC2, ne pas re-cloner : entrer dans
`~/aiworld-ark`, choisir la branche de pilote puis `git pull --ff-only`.

## 5 — PC2 : vérifier la connexion puis prêter son CPU

Dans Ubuntu du **PC2**, remplacer `IP_PC1` par la vraie IPv4 du PC1 :

```bash
python -c "import httpx; print(httpx.get('http://IP_PC1:8000/health',timeout=8).json())"
```

**Résultat attendu :** `{'ok': True}`. Sinon, corriger la connexion
(portproxy / pare-feu / IP / réseau invité / serveur arrêté) avant
de poursuivre. Ne pas tenter de rendre le serveur public.

Toujours sur **PC2**, lancer :

```bash
python essai_reseau_cpu.py volontaire --server http://IP_PC1:8000
```

**Sous Windows avec WSL1 et PowerShell**, version équivalente déjà utilisée
sur le HP ProBook (en remplaçant `IP_PC1`) :

```powershell
wsl -d Ubuntu --exec bash -c "cd ~/aiworld-ark && .venv/bin/python -u essai_reseau_cpu.py volontaire --server http://IP_PC1:8000 --wait-seconds 480"
```

Le script crée **localement sur PC2** `~/.aiworld-2pc/volontaire.json`,
passe THE GATE si nécessaire, annonce l'inventaire volontaire et ouvre
**une seule offre CPU**, avec durée maximum **15 s**, mémoire maximum
**512 MiB**, durée de validité **600 s**. Il affiche :

```text
PC2 - OFFRE CPU N° 9
Communique uniquement ce numero au PC1.
```

Le numéro **9 n'est qu'un exemple**. Ne pas fermer ce terminal :
le volontaire attend ensuite la tâche au maximum 240 secondes.

## 6 — PC1 : envoyer une demande et vérifier automatiquement

Sur le **PC1**, ouvrir un **deuxième terminal Ubuntu** (différent du serveur) :

```bash
cd ~/aiworld-ark
source .venv/bin/activate
git pull --ff-only

python essai_reseau_cpu.py demandeur --server http://127.0.0.1:8000 --offer 9
```

Remplacer **9** par le numéro d'offre **réel** indiqué sur le PC2.

Le script crée sa propre identité sur le PC1
(`~/.aiworld-2pc/demandeur.json`), passe THE GATE, vérifie que l'offre
provient d'un autre agent, puis soumet une tâche `prime_count` avec
une borne supérieure tirée aléatoirement entre **5000 et 5199**.
Le PC2 calcule. Le PC1 recalcule lui-même le résultat, puis signe une
revue positive uniquement si la sortie est correcte.

**Résultat à rechercher sur PC1 :**

```text
SUCCES : echange CPU signe entre PC1 et PC2 (a confirmer physiquement).
Demandeur distinct, execution CPU par le volontaire, verification signee.
```

Le logiciel ne peut pas attester seul que les deux terminaux tournent
sur deux appareils physiques : c'est au testeur de vérifier la configuration.

## 7 — Après le test : tout fermer

- Enregistrer **uniquement les sorties publiques** des deux terminaux
  (offre, tâche, état, résultat). **Jamais** les fichiers
  `~/.aiworld-2pc/*.json` ni les clés de `~/.aiworld-local`.
- Arrêter le coordinateur Ubuntu sur PC1 avec `Ctrl+C`.
- Sur PC1, dans **PowerShell administrateur**, avec la même variable
  `$ipPc1` que plus haut :

```powershell
netsh interface portproxy delete v4tov4 listenaddress=$ipPc1 listenport=8000
Remove-NetFirewallRule -DisplayName "AIWORLD-CPU-PILOT-8000"
netsh interface portproxy show v4tov4
```

Ces commandes suppriment **uniquement** la règle temporaire du pilote
(si elle porte bien le nom/adresse indiqué). Ne pas effacer les autres
règles du système. L'IP interne WSL2 peut changer après redémarrage ;
si besoin, refaire le pont avec la nouvelle IP.

## 8 — Ce que ce test validera (et ce qu'il ne validera pas)

**À valider par les sorties des deux vrais PC :** identité signée,
offre gratuite d'une machine, tâche CPU exécutée sur l'autre,
lecture privée et validation signée positive ; calcul non codé en dur.

**Pas encore validé :** HTTPS public, isolement hostile, attribution et
quotas GPU/VRAM, autonomie réelle des agents, résilience du coordinateur,
P2P mondial, capacités de milliers de machines, tout paiement ou stockage
distribué. Ce dépôt reste un prototype de recherche.

Références : [documentation Microsoft sur WSL2 NAT et portproxy](https://learn.microsoft.com/fr-fr/windows/wsl/networking)
et [règles de pare-feu Windows PowerShell](https://learn.microsoft.com/fr-fr/powershell/module/netsecurity/new-netfirewallrule).
