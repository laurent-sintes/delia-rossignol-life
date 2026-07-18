---
name: generate-delia-application
description: Préparer un CV, une lettre de motivation ou un dossier de candidature de Délia Rossignol pour une offre donnée, à partir des seules connaissances validées et d'un template catalogué. Utiliser cette skill pour adapter, rédiger, mettre en page, prévisualiser ou exporter une candidature.
---

# Génération d'une candidature de Délia

## Procédure

1. Lire `AGENTS.md`.
2. Vérifier que l'offre est enregistrée et que les faits utilisés sont validés.
3. Calculer la couverture littérale avec `python scripts/delia_life.py match-offer <offre> <connaissances>`.
4. Signaler les exigences manquantes; ne jamais les combler par invention.
5. Classer les templates avec la CLI, puis demander une validation si le choix influe fortement sur le rendu.
6. Construire un plan de contenu sourcé avant de rédiger.
7. Adapter le vocabulaire et l'ordre des éléments sans modifier les faits.
8. Produire les fichiers sous `generated/`, avec une fiche de traçabilité des faits et sources utilisés.
9. Générer un aperçu et obtenir une validation humaine avant export final.

Tout fait absent de la base validée doit devenir une proposition d'ingestion, pas une phrase du CV.
