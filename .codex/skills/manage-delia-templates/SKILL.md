---
name: manage-delia-templates
description: Créer, modifier, cataloguer, contrôler ou sélectionner des templates de CV et de lettres pour Délia Rossignol selon un employeur, un poste, un secteur, les contraintes ATS et le style validé de Délia. Utiliser cette skill pour tout travail sur le référentiel de modèles ou leur classement.
---

# Gestion des templates de candidature

## Procédure

1. Lire les règles Templates dans `AGENTS.md` et le style validé dans `data/style/delia.json`.
2. Garder les données personnelles hors du template.
3. Créer un dossier versionné sous `templates/cv/<id>/` ou `templates/cover-letter/<id>/`.
4. Décrire le modèle dans `template.json` : formats, ATS, secteurs, rôles, séniorité, pays et version.
5. Exécuter `python scripts/repo_flow.py review-content` après toute modification et conserver l’aperçu local actif.
6. Pour une offre, formaliser le contexte en JSON puis exécuter `python scripts/delia_life.py select-template <contexte> <templates...>`.
7. Présenter le classement et ses raisons. Laisser l'utilisateur imposer un autre modèle.
8. Produire et inspecter un aperçu avant de valider un nouveau rendu.

Ne pas utiliser le template pour contourner un manque dans la base de connaissances.
