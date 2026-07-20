---
name: manage-delia-git
description: Tester, prévisualiser, committer et publier les changements du dépôt Delia Rossignol Life. Utiliser cette skill lorsque l'utilisateur demande explicitement une revue locale, un contrôle Git, un commit, une publication, un push ou le déclenchement de GitHub Pages.
---

# Gestion Git du projet Délia

## Action `review`

1. Après toute modification de contenu définie dans `AGENTS.md`, exécuter `python scripts/repo_flow.py review-content`.
2. Communiquer l'URL locale produite et l'ouvrir dans le navigateur intégré s'il est disponible.
3. Laisser le serveur actif pendant les retours utilisateur. Une nouvelle exécution reconstruit le site et réutilise le même serveur.
4. Ne pas committer et ne pas pousser dans ce workflow.

## Action `commit`

1. Lire `AGENTS.md` puis inspecter `git status --short` et les diffs. Inclure les originaux, archives, données de travail et productions métier concernés; exclure uniquement les secrets techniques, caches, temporaires et `_site/`.
2. Si la revue locale n'est pas déjà à jour, exécuter `python scripts/repo_flow.py prepare-commit`. Ne pas reproduire manuellement les tests, le build ou le démarrage du serveur.
3. Communiquer l'URL locale produite et, si le navigateur intégré est disponible, l'ouvrir pour inspection.
4. Attendre la validation visuelle de l'utilisateur avant le commit. Ne pas confondre la demande initiale de préparation avec l'approbation du rendu.
5. Après validation, sélectionner explicitement les fichiers concernés avec `git add`; vérifier que les données métier nécessaires à un clone autonome sont présentes et qu'aucun secret technique n'est inclus.
6. Inspecter `git diff --cached`, proposer un message concis si aucun n'est fourni, puis exécuter `git commit`.
7. Conserver l'aperçu local actif après le commit. Ne jamais exécuter `python scripts/repo_flow.py preview-stop` sans une demande explicite de l'utilisateur.

Si un test ou le build échoue, ne pas committer. Corriger uniquement si la demande inclut la correction; sinon expliquer le blocage.

## Action `publish`

1. Lire `config/repository.json`, puis inspecter la branche, le remote et le statut Git.
2. Si `origin` manque, le configurer avec `expected_remote`. Si un autre remote existe, arrêter et demander une décision; ne jamais le remplacer silencieusement.
3. Exécuter `python scripts/repo_flow.py publish-check`. Ne pas pousser si le dépôt est sale, sans commit, sur une autre branche ou en retard sur son upstream.
4. Exécuter `git push -u origin <publish_branch>` avec la valeur lue dans `config/repository.json`. Ne jamais utiliser `--force` ou `--force-with-lease` dans ce workflow.
5. Vérifier le statut après push. Si `gh` est disponible, afficher le dernier run du workflow `pages.yml`; ne pas prétendre que Pages est déployé avant confirmation du run.

La commande explicite `publish` autorise le push du commit courant vers le remote et la branche configurés, mais n'autorise ni merge, ni rebase, ni réécriture d'historique.
