# Architecture Python

Le paquet `delia_life` transforme des données validées en connaissances, documents et pages statiques. L'architecture privilégie des traitements déterministes, transactionnels et testables.

## Couches

1. **Domaine et contrats** — `domain.py`, `schemas/` et `project_validation.py` portent les types, les schémas JSON et les invariants transverses.
2. **Services métier** — ingestion, revue, rapprochement, candidatures et classement des templates manipulent le domaine sans dépendre du rendu.
3. **Composition documentaire** — `cv_composer.py` sélectionne les faits validés et produit un `CVViewModel` traçable.
4. **Rendu** — `pdf_renderer.py` dessine exclusivement le modèle de vue; aucune donnée métier de Délia n'y est codée en dur.
5. **Publication** — `document_builder.py` et `site_builder.py` construisent en zone temporaire puis publient de manière atomique.
6. **Orchestration** — `cli.py` et `repo_workflow.py` enchaînent les services et exposent des codes d'erreur stables.

## Invariants de fiabilité

- Une proposition appliquée est immuable et sa chaîne de remplacement est linéaire, connexe et sans cycle.
- Une validation par lot est préparée entièrement avant toute écriture, puis committée sous verrou avec restauration en cas d'échec.
- Les fichiers JSON sont écrits par remplacement atomique après synchronisation sur disque.
- Les remplacements atomiques réessaient brièvement les verrous transitoires de Windows et des clients de synchronisation ; les fichiers de test, de vérification documentaire et de staging du site vivent dans le répertoire temporaire système, hors OneDrive.
- Le build du site préserve la version servie tant que le nouvel artefact n'est pas complet.
- Le crawl web refuse les réseaux privés, les redirections inter-domaines et les réponses hors limite; une indisponibilité de `robots.txt` bloque l'ingestion.
- Un PDF publié est reproductible à partir des connaissances, de la stratégie éditoriale et du template versionnés.

## Qualité automatisée

Ruff contrôle le style et les erreurs statiques, mypy vérifie les interfaces du paquet et Coverage impose un seuil minimal de 75 % de couverture de branches. `pyproject.toml` décrit les plages compatibles ; `requirements/constraints.txt` fige l’ensemble des versions directes et transitives testées. `pip check` est exécuté localement et dans GitHub Actions pour vérifier que l’environnement résolu est cohérent. GitHub Actions exécute ces contrôles sous Python 3.11 et 3.13 avant le build Pages.

La commande `python scripts/repo_flow.py review-content` applique les mêmes contrôles, reconstruit les documents et le site, puis réutilise le serveur local de prévisualisation.
