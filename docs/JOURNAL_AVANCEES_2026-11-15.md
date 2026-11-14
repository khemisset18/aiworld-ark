# Journal AI WORLD — 15 novembre 2026 : première preuve GPU locale

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

**Conclusion :** première preuve locale d'inférence Ollama utilisant la VRAM GPU, et chemin AI WORLD opérationnel. Aucun résultat GPU entre PC1 et PC2 n'est encore attesté. Rapport exact : [preuves GPU du 15 novembre](RESULTATS_PREUVE_GPU_LOCAL_2026-11-15.md).

## Pilote GPU entre deux PC — préparé, pas exécuté physiquement

Un nouveau script `essai_reseau_gpu.py` prépare le rôle **PC1 volontaire GPU, PC2 demandeur WSL1**, inverse du pilote CPU. Il conserve les identités privées sur chaque machine, exige une offre signée volontaire de type `inference` pour un modèle autorisé, **0 paiement**, 1 tâche, 120 s, et bloque les résultats d'un autre volontaire.

Le volontaire tente d'observer pendant la génération une montée de VRAM NVIDIA et/ou `size_vram > 0` d'Ollama. Le demandeur lit le résultat en privé, vérifie identité/modèle/paramètres/texte non vide et soumet une revue signée. **Ce n'est pas une preuve de vérité sémantique d'un texte LLM ni une attestation matérielle distante.** Les quotas Python n'isolent pas Ollama.

- [Guide complet GPU entre PC1 WSL2 et PC2 WSL1, réseau privé, nettoyage](TEST_GPU_DEUX_PC_LAN.md).
- [Programme pilote GPU inter-PC](../essai_reseau_gpu.py).
- [Tests automatisés du pilote GPU](../test_essai_reseau_gpu.py).

**À faire par l'opérateur pour valider réellement :** redémarrer le coordinateur sur PC1, créer un accès LAN temporaire autorisé uniquement depuis PC2, démarrer le volontaire PC1, envoyer la demande signée PC2 et recueillir les sorties réelles des deux PC. Retirer les règles LAN après. **Aucun test GPU inter-PC réussi n'est annoncé aujourd'hui.**

## Autres avancées à conserver

- CPU local sur un PC validé le 14 novembre : offre 5, tâche 6, 669 nombres premiers.
- CPU entre deux ordinateurs physiques validé le 14 novembre : offre 12, tâche 14, 690 nombres premiers, résultat signé.
- Le routage est encore assuré par un serveur central FastAPI. Le P2P direct et le partage GPU mondial n'existent pas encore.
- Le site `site/index.html` présente désormais la mission : « les agents se prêtent leur puissance, AI WORLD leur donne la route » et l'annuaire du coordinateur.
- Aucun paiement, aucune location commerciale, aucun minage/jeton ni exposition publique.

**Précautions :** les sorties du terrain sont communiquées par l'opérateur. Ne jamais publier de clés privées ni de données personnelles ; les règles LAN temporaires doivent être supprimées après les essais.
