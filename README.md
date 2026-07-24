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

Le cœur déterministe utilise Python 3.11 ou plus récent. Il gère le référentiel conceptuel, la génération PDF et le site public.

```powershell
python -m pip install -e ".[dev]" -c requirements/constraints.txt
python -m ruff check src scripts tests
python -m mypy
python -m coverage run -m unittest discover -s tests -v
python -m coverage report
python scripts/delia_life.py model-check
python scripts/delia_life.py check
python scripts/delia_life.py build-documents
python scripts/delia_life.py check-documents
python scripts/delia_life.py --help
```

Le classement déterministe d'un pool d'offres normalisées s'exécute avec :

```powershell
python scripts/delia_life.py rank-offers data/offers --require-complete-pool --output generated/offer-search/2026-07-19.json
```

Les scans d’offres commencent par une session explicite :

```powershell
python scripts/delia_life.py offer-scan clean-cache
python scripts/delia_life.py offer-scan full
python scripts/delia_life.py offer-scan delta
python scripts/delia_life.py offer-scan send
python scripts/delia_life.py record-offer-source-receipts generated/manual-source-receipts.json
```

`full` et `send` nettoient l’état technique puis isolent la collecte dans un nouveau répertoire ; le classement ne lit que les observations fraîches de cette session. Chaque domaine déclaré est classé comme automatisé ou manuel. Les portails manuels doivent recevoir, pour la session courante, un reçu `success`, `no_access` ou `skipped` contenant l’URL contrôlée, la date et le nombre d’offres observées ; seul `success` satisfait la couverture stricte. `delta` conserve le pool historique et le dédoublonne. Pour la restitution, les republications quasi identiques d’un même portail spécialisé ou agrégateur sont regroupées dans une fiche unique qui conserve tous leurs liens ; les offres directes employeur restent distinctes. `send` prépare un full destiné au workflow d’envoi à Délia, sans déléguer l’envoi à la CLI.

Les originaux sont déposés dans `private/originals/` et versionnés avec les manifestes, propositions, décisions et connaissances produites. Le nom `private/` indique une exclusion de GitHub Pages et des candidatures par défaut; il ne constitue pas une protection contre la lecture du dépôt public.

## Site GitHub Pages

Le site statique est construit sans dépendance externe depuis `site/publication.json`. Cette liste blanche choisit les fichiers et les clés JSON publiés.

```powershell
python scripts/delia_life.py build-documents
python scripts/delia_life.py check-documents
python scripts/delia_life.py build-site --output _site
```

`build-documents` régénère le CV standard dans `output/pdf/` et dans les téléchargements publics. `check-documents` vérifie sa reproductibilité, son format A4, son contenu obligatoire, l'absence de champs interdits et la fraîcheur du PDF publié. Le build du site régénère également le PDF dans l'artefact Pages.

Le dépôt versionne les sources du dossier de carrière, les configurations, preuves, manifestes, files de revue, connaissances et documents publiables. Les artefacts opérationnels d'une recherche d'offres sont régénérables et restent locaux : captures, annonces collectées, rapports et brouillons d'email. GitHub Pages ne publie qu'une projection choisie par `site/publication.json`; `_site/` est lui aussi régénéré et n'est pas versionné. Un push sur `main` déclenche `.github/workflows/pages.yml`, puisque la source Pages du dépôt est configurée sur GitHub Actions.

## Workflow Git assisté

La skill `$manage-delia-git` orchestre deux parcours : `commit` exécute les tests et builds puis crée le commit local; `push` ou `publish` vérifie le dépôt, pousse ce commit vers la branche configurée et suit le run GitHub Actions correspondant jusqu'à son résultat final.

Un `push` / `publish` exige un arbre de travail propre et n'invente jamais un commit local. Après le push, la publication n'est déclarée réussie que lorsque le workflow configuré dans `config/repository.json` termine avec succès.

```powershell
python scripts/repo_flow.py review-content
python scripts/repo_flow.py prepare-commit
python scripts/repo_flow.py preview-status
python scripts/repo_flow.py preview-stop
python scripts/repo_flow.py publish-check
```

## Principes

Les règles opérationnelles destinées aux agents sont dans `AGENTS.md`. Les workflows Codex sont versionnés sous `.codex/skills/`. Les calculs répétables sont implémentés dans `src/delia_life/` afin d'éviter les décisions implicites et les dépenses de tokens inutiles.

L'architecture Python, ses frontières et ses invariants sont décrits dans `docs/python-architecture.md`.

## Modèle mental

`model/model.yaml` référence les concepts et relations du domaine. Utiliser l'analyse d'impact avant tout refactor structurel :

```powershell
python scripts/delia_life.py model-check
python scripts/delia_life.py model-impact experience
```

Les identifiants conceptuels sont stables. Une suppression, fusion ou modification de cardinalité doit être accompagnée d'une migration Python.
