## Règle essentielle

Le dépôt et le site sont publics. Ne jamais committer un CV original, un diplôme, des coordonnées privées, une candidature détaillée, un feedback confidentiel ou une archive brute. Conserver ces éléments dans `private/`, qui est ignoré par Git.

Le site ne publie que les fichiers et les clés autorisés dans `site/publication.json`. Ajouter une clé à cette liste est une décision de publication et doit être relu comme telle.

## Quel workflow utiliser ?

### Comprendre ou modifier le modèle mental

Consulter la page `Modèle mental` et les fichiers YAML sous `model/`. Avant un refactor, exécuter `python scripts/delia_life.py model-impact <concept>` pour lister les relations entrantes, sortantes et les concepts voisins. Valider ensuite avec `model-check`.

### Importer un CV, un diplôme ou un document

Invoquer `$ingest-delia-knowledge`. La skill crée un manifeste, extrait des propositions sourcées, recherche les doublons et prépare la revue humaine. Ne jamais demander une insertion directe dans le profil.

### Sauvegarder le site de l'entreprise

Invoquer `$ingest-delia-knowledge` avec l'URL. Le crawl doit rester borné au même domaine. Les archives brutes restent dans `private/website-archives/`; seuls les faits ou analyses validés rejoignent la connaissance.

### Administrer les modèles de CV

Invoquer `$manage-delia-templates`. Décrire les usages du modèle dans son `template.json`, contrôler sa compatibilité ATS et générer un aperçu avant validation.

### Évaluer une offre

Invoquer `$match-delia-offers`. Le score Python couvre les correspondances littérales. Les équivalences proposées par l'IA doivent rester identifiables et ne créent jamais une compétence.

### Produire une candidature

Invoquer `$generate-delia-application`. Utiliser uniquement les connaissances validées, signaler les exigences non couvertes et conserver une fiche de traçabilité du CV et de la lettre.

### Enregistrer un retour

Invoquer `$track-delia-applications`. Un retour employeur est une observation liée à une candidature. Toute amélioration du profil, d'un template ou d'une règle doit redevenir une proposition à valider.

### Mettre à jour ce site

Invoquer `$publish-delia-site`. Contrôler la liste blanche, construire le site localement et inspecter les pages avant tout push sur `main`.

### Préparer un commit

Dire `commit` ou invoquer `$manage-delia-git`. La skill exécute les tests, contrôle la base, construit le site et lance un serveur local. Examiner l'URL fournie, puis confirmer le rendu avant la création effective du commit.

### Vérifier chaque modification de contenu

Après toute modification visible, le workflow exécute automatiquement `python scripts/repo_flow.py review-content`. Il teste, valide, construit et sert le site localement. Le serveur reste ouvert pendant la revue et les corrections suivantes utilisent la même URL. Cette étape ne crée ni commit ni push.

### Publier sur GitHub

Dire `publish` ou invoquer `$manage-delia-git`. La skill vérifie que le dépôt est propre, que `origin` correspond au dépôt attendu et que la branche courante est `main`, puis pousse le commit. Le push déclenche GitHub Pages par Actions.

## Contrôles avant publication

```powershell
python -m unittest discover -s tests -v
python scripts/delia_life.py model-check
python scripts/delia_life.py check
python scripts/delia_life.py build-site --output _site
```

Inspecter ensuite `_site/`. Un push sur `main` déclenche le workflow GitHub Actions et publie l'artefact construit.

## Modifier ce qui est visible

1. Faire valider l'information dans la base de connaissances.
2. Vérifier qu'elle est appropriée pour un dépôt public.
3. Ajouter uniquement la clé nécessaire dans `site/publication.json`.
4. Construire le site et rechercher toute donnée inattendue dans `_site/`.
5. Faire relire le résultat avant publication.
