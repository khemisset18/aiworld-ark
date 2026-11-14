# AI WORLD — Pilote GPU entre deux vrais PC (LAN privé)

**STATUT : PRÊT À EXÉCUTER, NON ENCORE VALIDÉ ENTRE LES DEUX PC.**

La preuve **locale** GPU de PC1 est réussie : Ollama 0.40.16, modèle `smollm2:135m`, `size_vram_bytes=381828463`, 441 Mio de VRAM utilisés et inférence AI WORLD fonctionnelle. Voir le [rapport local GPU](RESULTATS_PREUVE_GPU_LOCAL_2026-11-15.md).

**Rôles inversés par rapport au pilote CPU :** PC1 Windows/WSL2 (GTX 1650) = **volontaire GPU** et coordinateur. PC2 HP ProBook/WSL1 = **agent demandeur**. AI WORLD route les tâches signées, sans posséder ni louer le GPU des agents. Aucun paiement.

Les IP Windows déjà connues du pilote précédent sont **PC1 `192.168.1.132`** et **PC2 `192.168.1.74`**. Vérifier qu'elles n'ont pas changé ; l'IP d'Ubuntu WSL2 doit être relue à chaque redémarrage. Les règles réseau du pilote CPU précédent ont été supprimées.

## 1. PC1 — lancer le coordinateur

Dans le **premier terminal Ubuntu** du PC1 :

```bash
cd ~/aiworld-ark
source .venv/bin/activate
git pull --ff-only
mkdir -p ~/.aiworld-local
ARK_ADMISSION_REQUIRED=1 ARK_PAYMENT_REQUIRED=0 ARK_BILLING_ENABLED=0 \
SOULCHAIN_DB="$HOME/.aiworld-local/compute-pilot.sqlite3" \
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

Garder la fenêtre ouverte. Si cette instance est **déjà active**, ne pas la relancer. Vérifier sur PC1 PowerShell :

```powershell
curl.exe http://localhost:8000/health
```

Résultat : `{"ok":true}`.

Vérifier dans **Ubuntu PC1** que le service Ollama déjà installé répond :

```bash
curl http://127.0.0.1:11434/api/version
```

Si Ollama n'est pas démarré, lancer `ollama serve` dans un terminal Ubuntu distinct. **Ne jamais exposer Ollama :11434 sur le LAN ou Internet.**

## 2. PC1 — accès LAN temporaire au seul PC2

Dans **PowerShell administrateur PC1**, vérifier d'abord :

```powershell
$ipPc1 = "192.168.1.132"
$ipPc2 = "192.168.1.74"
$wslIp = ((wsl -d Ubuntu hostname -I).Trim() -split '\s+')[0]

Write-Host "PC1=$ipPc1 PC2=$ipPc2 WSL2=$wslIp"
Get-NetConnectionProfile
Get-Service iphlpsvc
netsh interface portproxy show v4tov4
Get-NetFirewallRule -DisplayName "AIWORLD-GPU-PILOT-8000" -ErrorAction SilentlyContinue
```

Profil réseau requis : **Private**. Service `iphlpsvc` : **Running**. Si la redirection `192.168.1.132:8000` ou la règle `AIWORLD-GPU-PILOT-8000` existent déjà, **ne pas créer de doublon**.

Sinon :

```powershell
netsh interface portproxy add v4tov4 listenaddress=$ipPc1 listenport=8000 connectaddress=$wslIp connectport=8000

New-NetFirewallRule -DisplayName "AIWORLD-GPU-PILOT-8000" -Direction Inbound -Action Allow -Profile Private -Protocol TCP -LocalAddress $ipPc1 -RemoteAddress $ipPc2 -LocalPort 8000

netsh interface portproxy show v4tov4
```

**Ne pas ouvrir de port sur la Freebox**. HTTP non chiffré est acceptable uniquement pour une démonstration sans secrets sur un réseau local privé et de confiance. Les règles ci-dessus concernent WSL2 en mode NAT, pas le mode « mirrored ».

## 3. PC2 — vérifier la connexion et mettre à jour sans réinstaller

Sur **PC2 PowerShell** :

```powershell
curl.exe --max-time 10 http://192.168.1.132:8000/health
```

Attendu : `{"ok":true}`.

Mettre à jour les scripts dans le projet **déjà installé** sur PC2 :

```powershell
wsl -d Ubuntu --exec bash -c "cd ~/aiworld-ark && git pull --ff-only && .venv/bin/python essai_reseau_gpu.py --help"
```

Cela fonctionne avec **Ubuntu WSL1 sur PC2**, sans réinstaller WSL2.

## 4. PC1 — publier l'offre GPU gratuite et attendre

Dans le **deuxième terminal Ubuntu du PC1** :

```bash
cd ~/aiworld-ark
source .venv/bin/activate
git pull --ff-only
python -u essai_reseau_gpu.py volontaire --server http://127.0.0.1:8000 --wait-seconds 480
```

Le programme vérifie NVIDIA et `smollm2:135m`, crée ou relit une identité privée dans `~/.aiworld-gpu-2pc/volontaire_gpu_pc1.json`, passe THE GATE si nécessaire puis signe une offre `inference` **gratuite**, avec **1 tâche**, **120 s de durée maximum** et **512 Mio de mémoire du sous-processus Python**. Ollama reste distinct et sa VRAM n'est pas bornée par ce plafond. Offre valable 1200 s.

Le terminal PC1 affiche le véritable **numéro d'offre GPU** :

```text
PC1 - OFFRE GPU N° NN
Modele autorise : smollm2:135m
Attente de la demande pendant 480 secondes.
```

**NN n'est qu'un exemple** : utiliser le numéro réellement reçu. Ne pas fermer ce terminal.

## 5. PC2 — demander un vrai calcul IA au GPU du PC1

Sur **PC2 PowerShell**, remplacer `NN` par le numéro d'offre PC1 :

```powershell
wsl -d Ubuntu --exec bash -c "cd ~/aiworld-ark && .venv/bin/python -u essai_reseau_gpu.py demandeur --server http://192.168.1.132:8000 --offer NN --wait-seconds 480"
```

Le demandeur crée/reprend une identité privée **distincte** sous `~/.aiworld-gpu-2pc/demandeur_gpu_pc2.json`, passe THE GATE, signe un `compute_request` pour le modèle autorisé et attend la réponse. Après réception, il vérifie le modèle, les paramètres, l'identité du volontaire et un texte non vide, puis signe `compute_review(accepted=True)` et confirme le statut `accepted_by_requester`.

**Attention :** une sortie LLM ne se vérifie pas mathématiquement comme le calcul de nombres premiers. La revue est une acceptation du demandeur, **pas une garantie de vérité du texte**.

## 6. Les deux preuves à conserver

**PC1 :** offre GPU, numéro de tâche, résultat `completed_unverified`, `PC1 - OBSERVATIONS GPU DURANT LA TACHE`. Le script consulte NVIDIA et `/api/ps` **pendant** l'inférence, car le worker décharge Ollama après la tâche. Si Ollama indique `size_vram > 0` pendant le calcul, il affiche `PC1 - OFFLOAD GPU OBSERVE`. Si seule la VRAM NVIDIA augmente, il parle d'**indice** ; si les relevés sont insuffisants, **GPU NON PROUVE**.

**PC2 :** `PC2 - TACHE GPU N° ...` puis `SUCCES : inference inter-PC signee et acceptee` et statut final `accepted_by_requester`.

**Ne déclarer le test GPU inter-PC réussi qu'après les deux journaux réels**, pas après la seule simulation des tests GitHub.

## 7. Après le pilote, fermer l'accès réseau

Arrêter le coordinateur de test sur PC1 avec `Ctrl+C` si nécessaire. Dans **PowerShell administrateur PC1** :

```powershell
netsh interface portproxy delete v4tov4 listenaddress=192.168.1.132 listenport=8000
Remove-NetFirewallRule -DisplayName "AIWORLD-GPU-PILOT-8000" -ErrorAction SilentlyContinue
netsh interface portproxy show v4tov4
Get-NetFirewallRule -DisplayName "AIWORLD-GPU-PILOT-8000" -ErrorAction SilentlyContinue
```

Ces commandes ne doivent retirer **que** les règles du pilote. Ne jamais mettre sur GitHub les identités privées `*.json`, prompts secrets ou états confidentiels.

## Limites

Le serveur actuel reste un coordinateur central avec données de tâche accessibles à son opérateur ; l'accès entre PC1 et PC2 est en HTTP LAN non chiffré ; **pas de P2P direct, pas de cluster GPU, pas de location commerciale, pas de quotas VRAM fiables**. Une démonstration entre deux machines n'est pas un audit de sécurité.

[Script GPU inter-PC](../essai_reseau_gpu.py) · [Test GPU local validé](RESULTATS_PREUVE_GPU_LOCAL_2026-11-15.md) · [Test CPU inter-PC validé](RESULTATS_PILOTE_CPU_DEUX_PC_2026-11-14.md).
