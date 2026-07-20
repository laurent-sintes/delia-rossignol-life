---
name: publish-delia-site
description: Construire, contrôler et publier le site GitHub Pages de Délia Rossignol depuis la projection publique de sa base de connaissances et le guide d'administration des skills. Utiliser cette skill pour modifier le contenu visible, la liste blanche, la navigation, le style, le workflow Pages ou pour préparer une publication sur main.
---

# Publication du site de Délia

## Procédure

1. Lire `AGENTS.md`, particulièrement la distinction entre dépôt public complet et projection GitHub Pages.
2. Vérifier que toute information demandée est appropriée pour la projection GitHub Pages.
3. Si la demande change un fait ou un contenu éditorial, modifier d'abord les données validées. Pour une correction purement graphique ou technique, ne pas toucher à la base de connaissances.
4. Administrer la liste blanche dans `site/publication.json`. Autoriser seulement les clés nécessaires; ne jamais autoriser un objet complet implicitement.
5. Modifier les contenus éditoriaux dans `site/content/` et le style dans `site/assets/`.
6. Exécuter uniquement `python scripts/repo_flow.py review-content` : cette commande porte les contrôles de code, données, documents et site, puis déploie l'aperçu local. Ne pas relancer séparément les mêmes contrôles.
7. Communiquer l'URL et laisser le serveur actif pendant la vérification utilisateur.
8. Inspecter toutes les pages générées et rechercher les coordonnées, feedbacks, offres, preuves ou données inattendues.
9. Ne pousser sur la branche configurée qu'après validation humaine du contenu public. GitHub Actions effectuera le déploiement Pages.

Les dossiers `private/`, `generated/`, `data/applications/`, `data/offers/`, `data/review/` et `data/sources/` peuvent être versionnés dans Git, mais restent interdits comme sources de Pages. Ne jamais contourner la liste blanche en copiant leur contenu dans `site/` ou dans `_site/`.
