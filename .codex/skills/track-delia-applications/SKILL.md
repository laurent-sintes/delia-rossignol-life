---
name: track-delia-applications
description: Enregistrer et analyser le cycle de vie des candidatures de Délia Rossignol, notamment envoi, accusé, entretien, refus, offre et feedback employeur. Utiliser cette skill pour mettre à jour un suivi, produire un bilan ou proposer des améliorations à partir des retours.
---

# Suivi des candidatures de Délia

## Procédure

1. Lire `AGENTS.md` et ouvrir la candidature concernée sous `data/applications/`.
2. Ajouter tout événement avec `python scripts/delia_life.py track-event <candidature> <type> --details '<json>'`.
3. Préserver la chronologie; ne pas supprimer un événement pour corriger l'histoire. Ajouter un nouvel événement correctif.
4. Relier un feedback à sa candidature, son offre, son template et les versions des documents envoyés.
5. Distinguer le contenu explicite du retour et l'interprétation qui en est faite.
6. Transformer une amélioration envisagée en proposition à valider. Ne pas modifier automatiquement le profil, un template ou les règles de génération.
7. Lors d'un bilan, comparer des groupes pertinents et signaler les faibles volumes; ne pas généraliser à partir d'un seul refus.
