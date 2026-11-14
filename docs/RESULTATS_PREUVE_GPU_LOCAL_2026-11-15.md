# Validation terrain — première inférence locale AI WORLD avec GPU NVIDIA

**Date : 15 novembre 2026**  
**Statut : GPU LOCAL CONFIRMÉ PAR OLLAMA + TÉLÉMÉTRIE VRAM**  
**Source :** sortie de `python essai_gpu_pc1.py` communiquée depuis PC1 (Ubuntu WSL2). Il ne s'agit pas d'une attestation indépendante ni d'une preuve de transfert de tâche entre PC1 et PC2.

## Environnement réellement utilisé

- **Machine :** PC1 Windows + Ubuntu WSL2.
- **GPU :** NVIDIA GeForce GTX 1650, 4 096 Mio de VRAM.
- **Ollama :** version `0.40.16`, service accessible localement.
- **Modèle téléchargé :** `smollm2:135m` (environ 270 Mo transférés).
- **Programme :** `essai_gpu_pc1.py` sur la branche `feat/compute-cpu-gpu-resource-safety-20261114`, utilisant également `volunteer_inference.infer_local` du véritable logiciel AI WORLD.

Une première tentative d'installation avait échoué faute de `zstd` ; une installation fonctionnelle d'Ollama est ensuite attestée par les journaux du test, sans préjuger des commandes correctives exactes exécutées.

## Preuve brute transmise par l'opérateur

```text
ETAPE 1/4: serveur Ollama local...
Version : 0.40.16
GPU avant calcul : {"name": "NVIDIA GeForce GTX 1650", "temperature_c": 69, "utilization_pct": 0, "used_vram_mib": 0, "total_vram_mib": 4096}
ETAPE 2/4: petite generation IA et mesure du chargement GPU...
Reponse du modele : "En une phrase en français, explique pourquoi deux agents peuvent se preter du calcul CPU."  Explanation:  The phrase "en français" is translated to "in French".
Duree generation : 61.09 secondes
ETAPE 3/4: verifier la VRAM reellement chargee par Ollama...
Ollama /api/ps : {"size_bytes": 381828463, "size_vram_bytes": 381828463, "gpu_offload": true}
GPU apres calcul : {"name": "NVIDIA GeForce GTX 1650", "temperature_c": 77, "utilization_pct": 0, "used_vram_mib": 441, "total_vram_mib": 4096}
PREUVE GPU LOCALE : Ollama declare le modele charge en VRAM NVIDIA.
ETAPE 4/4: verifier le vrai chemin inference d'AI WORLD...
AI WORLD inference locale : Bonjour, merci for all the help I've provided. I'm here to assist you in any way I can
Chemin inference AI WORLD : OK
SUCCES : generation Ollama sur PC1 avec offload GPU observe, chemin AI WORLD local OK.
IMPORTANT : le PC2 n'a pas encore demande cette tache. Le test GPU inter-PC reste a faire.
```

## Interprétation technique honnête

- L'API Ollama `/api/ps` rapporte un modèle chargé de **381 828 463 octets**, dont **381 828 463 octets en VRAM** : `gpu_offload: true`. Cela étaye fortement l'utilisation de l'accélération GPU pour la génération.
- L'inventaire `nvidia-smi` a montré **0 → 441 Mio** de mémoire GPU occupée avant/après la première génération, cohérent avec le modèle chargé sur NVIDIA.
- Le compteur `utilization_pct: 0` a été relevé **après** la génération ; il ne constitue **pas** un échec et **ne permet pas** d'estimer l'utilisation GPU pendant la génération.
- La première génération a pris **61,09 s** et renvoyé un texte non vide, mais la qualité sémantique était faible : ce n'est ni une évaluation de la qualité d'un LLM ni une mesure de débit GPU.
- La fonction `volunteer_inference.infer_local` réellement utilisée dans AI WORLD a ensuite renvoyé un texte non vide avec le modèle autorisé, prouvant le bon fonctionnement du **chemin d'inférence local**. Sa consommation GPU **n'a pas été instrumentée séparément** dans cette exécution.

## Ce qui est validé et ce qui reste à démontrer

**Validé :** compatibilité GPU NVIDIA dans le WSL2 du PC1, installation Ollama et modèle local, génération avec offload VRAM constaté, chemin de code local d'AI WORLD.

**Non validé :** une **tâche d'inférence envoyée depuis PC2**, une attribution et exécution à distance sous le worker `run_once`, la signature et relecture du résultat par le demandeur PC2, l'utilisation GPU en production sous simultanéité, les quotas VRAM et la fiabilité de production.

**Suite :** préparer le **pilote GPU à deux PC** : PC1 volontaire GPU, PC2 demandeur WSL1, coordinateur AI WORLD sur PC1 (LAN privé uniquement), preuve GPU pendant l'exécution et statut signé `accepted_by_requester` après examen du texte. Aucune facturation, aucun script arbitraire, aucune exposition publique.

**Référence technique :** [`essai_gpu_pc1.py`](../essai_gpu_pc1.py), [protocole GPU](TEST_PREUVE_GPU_AGENTS.md), [pilote CPU entre deux PC](RESULTATS_PILOTE_CPU_DEUX_PC_2026-11-14.md).
