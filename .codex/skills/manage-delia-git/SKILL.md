---
name: manage-delia-git
description: Tester, construire et committer localement les changements du dépôt Delia Rossignol Life, puis pousser ou publier les commits et suivre leur CI GitHub. Utiliser cette skill lorsque l'utilisateur demande explicitement une revue locale, un contrôle Git, un commit, une publication, un push ou le déclenchement de GitHub Pages.
---

# Gestion Git du projet Délia

## Action `review`

1. Après toute modification de contenu définie dans `AGENTS.md`, exécuter `python scripts/repo_flow.py review-content`.
2. Communiquer l'URL locale produite et l'ouvrir dans le navigateur intégré s'il est disponible.
3. Laisser le serveur actif pendant les retours utilisateur. Une nouvelle exécution reconstruit le site et réutilise le même serveur.
4. Ne pas committer et ne pas pousser dans ce workflow.

## Action `commit`

1. Lire `AGENTS.md` puis inspecter `git status --short` et les diffs. Inclure les sources, configurations, originaux, données validées et productions publiables concernés. Exclure les secrets techniques, caches, temporaires, `_site/` et tous les artefacts opérationnels de recherche d'offres listés dans `.gitignore`.
2. Exécuter `python scripts/repo_flow.py prepare-commit`. Cette commande réalise les tests, validations et builds déterministes et maintient l'aperçu local; ne pas reproduire manuellement ces opérations.
3. Si les contrôles réussissent, sélectionner explicitement les fichiers concernés avec `git add`; vérifier que les sources nécessaires à un clone autonome sont présentes, qu'aucun artefact régénérable de recherche n'est inclus et qu'aucun secret technique n'est inclus.
4. Inspecter `git diff --cached`, choisir un message concis si aucun n'est fourni, puis exécuter `git commit` dans la même action utilisateur. La commande `commit` vaut autorisation du commit local après réussite des contrôles; elle n'autorise aucun push.
5. Communiquer le SHA créé, le résumé des contrôles et l'URL locale. Conserver l'aperçu actif; ne jamais exécuter `python scripts/repo_flow.py preview-stop` sans demande explicite.

Si un test ou le build échoue, ne pas committer. Corriger uniquement si la demande inclut la correction; sinon expliquer le blocage.

## Action `push` / `publish`

`push` et `publish` sont strictement synonymes dans ce dépôt.

1. Lire `config/repository.json`, notamment `expected_remote`, `publish_branch` et `ci_workflow`, puis inspecter la branche, le remote, le statut Git et le SHA courant.
2. Si `origin` manque, le configurer avec `expected_remote`. Si un autre remote existe, arrêter et demander une décision; ne jamais le remplacer silencieusement.
3. Exécuter `python scripts/repo_flow.py publish-check`. Ne pas pousser si le dépôt est sale, sans commit local, sur une autre branche ou en retard sur son upstream. Si des changements ne sont pas committés, demander d'abord une action `commit`; ne pas la déduire silencieusement de `push`.
4. Exécuter `git push -u origin <publish_branch>` avec la valeur lue dans `config/repository.json`. Ne jamais utiliser `--force` ou `--force-with-lease` dans ce workflow.
5. Vérifier que le SHA local est présent sur le remote. Avec `gh`, rechercher le run de `<ci_workflow>` rattaché exactement à ce SHA; attendre brièvement sa création si nécessaire, puis exécuter `gh run watch <run-id> --exit-status` jusqu'à son état terminal.
6. En cas de succès, communiquer le SHA distant, le lien du run et la confirmation du déploiement. En cas d'échec, communiquer le job ou l'étape en défaut et le lien du run; le push reste effectué, mais ne jamais prétendre que la publication est réussie. Si `gh` est indisponible ou non authentifié, signaler distinctement « push réussi, suivi CI non vérifié » et fournir le lien GitHub vérifiable.

Les commandes explicites `push` et `publish` autorisent le push du commit courant vers le remote et la branche configurés ainsi que le suivi de sa CI. Elles n'autorisent ni merge, ni rebase, ni réécriture d'historique, ni correction automatique après un échec de CI.
