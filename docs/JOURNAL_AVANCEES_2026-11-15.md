# Journal AI WORLD — 15 novembre 2026 : preuve GPU locale ET entre deux PC

**Source :** journaux PowerShell/Ubuntu WSL2 transmis par l'opérateur et changements réels committés à la branche de développement de PR #9. Les tests automatiques et le logiciel codé sont distincts des tests physiques.

## Première vraie génération IA avec GPU sur PC1 — SUCCÈS LOCAL

Après une première installation Ollama échouée faute de `zstd`, le PC1 a exécuté `ollama pull smollm2:135m` avec succès et lancé `python essai_gpu_pc1.py` sur Ubuntu WSL2.

Observations réelles :

- **NVIDIA GTX 1650 4 Gio de VRAM**, vue par Ubuntu WSL2.
- **Ollama 0.40.16**, modèle `smollm2:135m`.
- Avant génération : **0 Mio** de VRAM NVIDIA utilisée, **69 °C**, 0 % d'activité.
- Première réponse IA : texte non vide, **61,09 secondes**.
- Après génération : Ollama `/api/ps` déclare `size_vram_bytes=381828463` et `gpu_offload=true`. NVIDIA déclare **441 Mio de VRAM utilisée**, **77 °C**, 0 % d'activité après le calcul.
- Le vrai chemin d'inférence AI WORLD `volunteer_inference.infer_local` renvoie ensuite un texte non vide.
- Le texte renvoyé par le petit modèle peut être de faible qualité ; une réponse non vide ne garantit pas l'exactitude. La télémétrie GPU instantanée à 0 % était **après** la génération, non pendant.

**Conclusion :** première preuve locale d'inférence Ollama utilisant la VRAM GPU, et chemin AI WORLD opérationnel. La preuve GPU entre PC1 et PC2 est désormais également attestée par des journaux concordants (offre 19, tâche 21). Rapport exact : [preuves GPU du 15 novembre](RESULTATS_PREUVE_GPU_LOCAL_2026-11-15.md).

## Pilote GPU entre deux PC — OFFLOAD NVIDIA ET DEMANDE SIGNÉE VALIDÉS

Un nouveau script `essai_reseau_gpu.py` prépare le rôle **PC1 volontaire GPU, PC2 demandeur WSL1**, inverse du pilote CPU. Il conserve les identités privées sur chaque machine, exige une offre signée volontaire de type `inference` pour un modèle autorisé, **0 paiement**, 1 tâche, 120 s, et bloque les résultats d'un autre volontaire.

Le volontaire tente d'observer pendant la génération une montée de VRAM NVIDIA et/ou `size_vram > 0` d'Ollama. Le demandeur lit le résultat en privé, vérifie identité/modèle/paramètres/texte non vide et soumet une revue signée. **Ce n'est pas une preuve de vérité sémantique d'un texte LLM ni une attestation matérielle distante.** Les quotas Python n'isolent pas Ollama.

- [Guide complet GPU entre PC1 WSL2 et PC2 WSL1, réseau privé, nettoyage](TEST_GPU_DEUX_PC_LAN.md).
- [Programme pilote GPU inter-PC](../essai_reseau_gpu.py).
- [Tests automatisés du pilote GPU](../test_essai_reseau_gpu.py).

**État actualisé :** le PC1 a bien publié l'offre GPU n° 19, PC2 a envoyé une demande signée n° 21, obtenu un texte et confirmé une revue signée avec état `accepted_by_requester`. C'est une **réussite du transfert d'inférence entre deux agents**, et les métriques NVIDIA/Ollama ont été relevées sur PC1 **pendant cette même tâche**. **La preuve GPU inter-PC est donc validée pour le pilote sur LAN privé**. Après collecte de la sortie PC1, retirer les règles LAN temporaires. [Rapport inter-PC complet](RESULTATS_PILOTE_GPU_DEUX_PC_2026-11-15.md).

## Preuve terrain reçue côté PC2 — offre GPU n° 19 / tâche n° 21

Le PC2 a lancé `essai_reseau_gpu.py demandeur --server http://192.168.1.132:8000 --offer 19 --wait-seconds 480`. Le terminal a indiqué :

```text
PC2 - TACHE GPU N° 21 | OFFRE N° 19
Modele demande : smollm2:135m
SUCCES : inference inter-PC signee et acceptee par le demandeur PC2.
Reponse du modele : "Environnement de 8873cf. Reponds en une courte phrase en francais sans executer de commande."
Signature de revue et etat accepted_by_requester confirmes.
```

**Confirmed :** le routage signé a fonctionné de PC2 vers l'offre du PC1 et retour, avec une réponse effectivement acceptée par l'agent demandeur. **Confirmé sur PC1 pour cette tâche :** `completed_unverified`, pic VRAM NVIDIA **441 Mio** (départ 0 Mio), pic GPU **6 %**, pic `size_vram` Ollama **381 828 463 octets**, ligne `OFFLOAD GPU OBSERVE`. Les deux observations correspondent à l'offre 19 et la tâche 21. Le texte produit est de qualité limitée (reprend la consigne). [Détails et limites dans le rapport](RESULTATS_PILOTE_GPU_DEUX_PC_2026-11-15.md).

## Preuve complémentaire terrain côté PC1 — offre 19 / tâche 21

Le PC1 a transmis la suite de sa console volontaire :

```text
{"job": 21, "status": "completed_unverified", "result": {"model": "smollm2:135m", "text": "\"Environnement de 8873cf. Reponds en une courte phrase en francais sans executer de commande.\""}}
PC1 - OBSERVATIONS GPU DURANT LA TACHE : {"baseline_vram_mib": 0, "peak_vram_mib": 441, "peak_gpu_pct": 6, "peak_ollama_vram_bytes": 381828463}
PC1 - OFFLOAD GPU OBSERVE : Ollama a declare le modele resident en VRAM.
PC1 - Tache envoyee au coordinateur ; attente de la revue signee par PC2.
```

**Conclusion : pilote de prêt GPU entre deux ordinateurs physiques réussi au niveau des observations logicielles concordantes.** Le volontaire PC1 a fait exécuter une inférence par Ollama sur sa GTX 1650 pendant que le demandeur PC2 obtenait la réponse et signait son acceptation. Pas d'attestation matérielle cryptographique indépendante, ni de GPU partagé directement au niveau P2P, ni de preuve de qualité sémantique du modèle. Réseau LAN temporaire à refermer ; **retrait non encore confirmé**.

[Rapport terrain des deux PC](RESULTATS_PILOTE_GPU_DEUX_PC_2026-11-15.md).

## Autres avancées à conserver

- CPU local sur un PC validé le 14 novembre : offre 5, tâche 6, 669 nombres premiers.
- CPU entre deux ordinateurs physiques validé le 14 novembre : offre 12, tâche 14, 690 nombres premiers, résultat signé.
- Le routage est encore assuré par un serveur central FastAPI. Le P2P direct et le partage GPU mondial n'existent pas encore.
- Le site `site/index.html` présente désormais la mission : « les agents se prêtent leur puissance, AI WORLD leur donne la route » et l'annuaire du coordinateur.
- Aucun paiement, aucune location commerciale, aucun minage/jeton ni exposition publique.

**Précautions :** les sorties du terrain sont communiquées par l'opérateur. Ne jamais publier de clés privées ni de données personnelles ; les règles LAN temporaires doivent être supprimées après les essais.
