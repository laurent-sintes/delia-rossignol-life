---
name: generate-delia-application
description: Préparer le CV standard ou un CV, une lettre et un dossier de candidature adaptés à une offre pour Délia Rossignol, à partir des seules connaissances validées et d'un template catalogué. Utiliser cette skill pour composer, adapter, rédiger, mettre en page, prévisualiser ou exporter ces documents.
---

# Génération d'une candidature de Délia

## Procédure

1. Lire `AGENTS.md`.
2. Déterminer le mode de génération : CV standard sans offre, ou candidature adaptée à une offre enregistrée.
3. Dans le mode adapté, calculer la couverture littérale avec `python scripts/delia_life.py match-offer <offre> <connaissances>` et signaler les exigences manquantes sans les combler par invention.
4. Classer les templates avec la CLI, puis demander une validation si le choix influe fortement sur le rendu.
5. Construire un plan de contenu sourcé avant de rédiger et adapter le vocabulaire ou l'ordre sans modifier les faits.
6. Pour le CV standard, utiliser `python scripts/delia_life.py build-documents`; ses sorties de référence sont `output/pdf/` et `site/assets/downloads/`.
7. Pour une candidature liée à une offre, produire les fichiers et la fiche de traçabilité sous `generated/`.
8. Générer un aperçu et obtenir une validation humaine avant export final.

Tout fait absent de la base validée doit devenir une proposition d'ingestion, pas une phrase du CV.
