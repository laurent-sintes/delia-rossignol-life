## Conseils et outils

Cette page aide à enrichir le dossier, préparer des candidatures et entretenir le site.

### Importer un document ou un site

Invoquer `$ingest-delia-knowledge` pour importer un CV, un diplôme, une note ou un site professionnel. Pour un site : `python scripts/delia_life.py slurp-site <url> --output private/website-archives/<capture> --retries 2`.

### Préparer une candidature

Utiliser `$match-delia-offers` pour analyser une offre, puis `$generate-delia-application` pour préparer le CV et la lettre. Les templates sont gérés avec `$manage-delia-templates`.

### Suivre les candidatures

Utiliser `$track-delia-applications` pour noter les envois, les entretiens et les retours.

### Prévisualiser et publier le site

Après une modification visible, exécuter `python scripts/repo_flow.py review-content` pour ouvrir l’aperçu local. Dire `commit` pour préparer un commit, puis `publish` pour envoyer les changements sur GitHub.

Ne jamais ajouter de mot de passe, jeton, clé privée, cookie d’authentification ou fichier `.env` au dépôt.
