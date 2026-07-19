# Delia Rossignol Life

Base de connaissances et outils de candidature de Délia Rossignol.

Le projet sépare quatre couches : les sources originales, les propositions à valider, les connaissances validées et les documents générés. Aucune extraction assistée par IA ne devient un fait sans décision humaine explicite.

## Domaines

- ingestion de CV, diplômes, documents et sites web;
- référentiel de compétences, expériences, formation et style;
- catalogue de templates de CV et lettres;
- génération de candidatures traçables;
- recherche et rapprochement explicable d'offres;
- suivi des réponses et exploitation contrôlée du feedback.

## Démarrage

Le cœur déterministe utilise Python 3.11 ou plus récent et PyYAML pour le référentiel conceptuel.

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
python scripts/delia_life.py model-check
python scripts/delia_life.py check
python scripts/delia_life.py --help
```

Les originaux sont déposés dans `private/originals/` et versionnés avec les manifestes, propositions, décisions et connaissances produites. Le nom `private/` indique une exclusion de GitHub Pages et des candidatures par défaut; il ne constitue pas une protection contre la lecture du dépôt public.

## Site GitHub Pages

Le site statique est construit sans dépendance externe depuis `site/publication.json`. Cette liste blanche choisit les fichiers et les clés JSON publiés.

```powershell
python scripts/delia_life.py build-site --output _site
```

Le dépôt versionne l'ensemble du dossier métier : sources, archives, offres, candidatures, preuves, manifestes, files de revue, connaissances et documents générés. Ces fichiers sont donc lisibles dans le dépôt public. GitHub Pages n'en publie qu'une projection choisie par `site/publication.json`; `_site/` est régénéré et n'est pas versionné. Un push sur `main` déclenche `.github/workflows/pages.yml`, puisque la source Pages du dépôt est configurée sur GitHub Actions.

## Workflow Git assisté

La skill `$manage-delia-git` orchestre deux actions : `commit` prépare les contrôles et ouvre un aperçu local avant validation; `publish` vérifie le remote et pousse le commit validé vers `main`.

```powershell
python scripts/repo_flow.py review-content
python scripts/repo_flow.py prepare-commit
python scripts/repo_flow.py preview-status
python scripts/repo_flow.py preview-stop
python scripts/repo_flow.py publish-check
```

## Principes

Les règles opérationnelles destinées aux agents sont dans `AGENTS.md`. Les workflows Codex sont versionnés sous `.codex/skills/`. Les calculs répétables sont implémentés dans `src/delia_life/` afin d'éviter les décisions implicites et les dépenses de tokens inutiles.

## Modèle mental

`model/model.yaml` référence les concepts et relations du domaine. Utiliser l'analyse d'impact avant tout refactor structurel :

```powershell
python scripts/delia_life.py model-check
python scripts/delia_life.py model-impact experience
```

Les identifiants conceptuels sont stables. Une suppression, fusion ou modification de cardinalité doit être accompagnée d'une migration Python.
