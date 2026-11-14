# AI WORLD — résultat du pilote inference PC1 → PC2, 15 novembre 2026

**État au moment de la collecte : échange signé GPU-capable entre deux PC VALIDÉ CÔTÉ PC2 ; exécution GPU de la tâche 21 EN ATTENTE DE CONFIRMATION CÔTÉ PC1.**

Source : journaux de PowerShell transmis par l'opérateur, PC1 puis PC2. Le logiciel ne fournit pas d'attestation matérielle distante.

## Topologie du pilote

- **PC1** Windows/Ubuntu WSL2, IP LAN `192.168.1.132`, coordinateur FastAPI AI WORLD sur :8000, volontaire NVIDIA GTX 1650 + Ollama `0.40.16`, modèle autorisé `smollm2:135m`. Identité du volontaire affichée à l'admission, sans publier sa clé privée.
- **PC2** HP ProBook/Ubuntu WSL1, demandeur via le réseau privé. Le `curl.exe --max-time 10 http://192.168.1.132:8000/health` sur PC2 a répondu `{"ok":true}`.
- **Offre GPU signée PC1 : n° 19**, volontaire en attente 480 s. Modèle `smollm2:135m`.
- **Tâche signée PC2 : n° 21**, offer n° 19.
- **Paiement** : aucun. **Exécution de code transmis par PC2** : aucune.

## Sortie terrain confirmée côté PC2

L'opérateur a exécuté sur PC2 :

```powershell
wsl -d Ubuntu --exec bash -c "cd ~/aiworld-ark && .venv/bin/python -u essai_reseau_gpu.py demandeur --server http://192.168.1.132:8000 --offer 19 --wait-seconds 480"
```

Résultat exact transmis :

```text
Identite GPU admise : 4cec733c0dd150781a497390cdc52038
PC2 - TACHE GPU N° 21 | OFFRE N° 19
Modele demande : smollm2:135m
En attente d'une reponse IA du volontaire PC1...

SUCCES : inference inter-PC signee et acceptee par le demandeur PC2.
Offre n° 19 | tache n° 21
Reponse du modele : "Environnement de 8873cf. Reponds en une courte phrase en francais sans executer de commande."
Signature de revue et etat accepted_by_requester confirmes.
Ce resultat ne garantit pas la justesse du texte ni la preuve GPU materielle.
Verifier aussi les observations NVIDIA/Ollama sur PC1 pour la preuve GPU.
```

## Interprétation

**Confirmé :** un agent distinct sur PC2 a soumis une demande d'inférence à l'offre n° 19 du PC1 via le coordinateur ; il a récupéré un texte, contrôlé la cohérence de l'identité du volontaire / modèle / paramètres, a envoyé une revue signée et observé le statut final `accepted_by_requester`. Le protocole réel d'envoi et de retour entre les PC fonctionne.

**Non encore confirmé pour CETTE tâche :** la mesure `PC1 - OBSERVATIONS GPU DURANT LA TACHE` et `PC1 - OFFLOAD GPU OBSERVE` émise par `essai_reseau_gpu.py` sur PC1 ; la présence de ces lignes est nécessaire pour attribuer le résultat n° 21 à une inférence accélérée GPU et non uniquement à une réponse Ollama avec accélération possible. La preuve GPU **locale précédente** sur PC1 reste [validée séparément](RESULTATS_PREUVE_GPU_LOCAL_2026-11-15.md) mais ne remplace pas la preuve inter-PC.

**Limite du modèle :** la réponse citée ressemble à une reprise partielle de la consigne, et ne démontre pas de qualité ou de pertinence sémantique. La revue signée atteste l'acceptation, pas la justesse.

## Dernières actions requises

1. Sur le terminal du **PC1**, recopier la sortie après l'offre n° 19, particulièrement `completed_unverified`, `PC1 - OBSERVATIONS GPU DURANT LA TACHE` et l'éventuel `PC1 - OFFLOAD GPU OBSERVE`.
2. Ne pas relancer la tâche n° 21 pour recueillir la preuve déjà obtenue. Si la télémétrie PC1 est absente, l'indiquer au lieu d'inventer un résultat.
3. Une fois les journaux recueillis, supprimer la redirection Windows temporaire du port 8000 et la règle `AIWORLD-GPU-PILOT-8000` comme dans le [guide de nettoyage LAN](TEST_GPU_DEUX_PC_LAN.md). Aucune ouverture de port sur la box.

**Projet :** [`essai_reseau_gpu.py`](../essai_reseau_gpu.py) · [journal du 15 novembre](JOURNAL_AVANCEES_2026-11-15.md).
