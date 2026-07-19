# Instructions du projet Delia Rossignol Life

## Mission

Construire un dossier de carrière fiable et traçable pour Délia Rossignol, puis l'utiliser pour préparer des candidatures adaptées, rechercher des offres et apprendre des retours reçus.

## Règles non négociables

1. Ne jamais inventer un fait, une compétence, une date, un diplôme, un résultat ou une responsabilité.
2. Ne jamais intégrer automatiquement une extraction ou une inférence dans la base validée.
3. Conserver la provenance de chaque proposition : source, empreinte, emplacement, extrait et date d'ingestion.
4. Distinguer `fact`, `claim` et `inference`. Une déclaration commerciale reste un `claim`; une interprétation stylistique reste une `inference`.
5. Seules les propositions `accepted` ou `edited` peuvent alimenter la base de connaissances.
6. Préserver l'historique des décisions de validation. Ne pas réécrire silencieusement un événement passé.
7. Signaler les doublons et contradictions au lieu de choisir arbitrairement.
8. Séparer le contenu validé, la stratégie éditoriale et le rendu graphique.
9. Versionner dans Git les originaux, données de travail, productions documentaires et historiques métier. Garder uniquement les secrets techniques, caches et fichiers temporaires hors de Git.
10. Favoriser le français pour les contenus destinés à Délia; conserver les identifiants et interfaces techniques en anglais.
11. Considérer que tout fichier committé est lisible dans le dépôt GitHub public. La visibilité sur GitHub Pages reste une décision distincte, contrôlée par `site/publication.json`.
12. Toute expérience validée doit comporter une `mission` explicite, courte et sourcée. Si elle manque, la signaler; ne jamais la déduire des responsabilités ou de l'intitulé.
13. Toute expérience validée doit comporter des `responsibilities` explicites, sourcées et non vides. Si elles manquent, les signaler; ne jamais les déduire de la mission, du titre ou des résultats.

## Répartition IA / Python

Utiliser l'IA pour les tâches qui demandent du jugement : extraction sémantique, rapprochement non littéral, reformulation, synthèse, analyse du ton et explication d'une recommandation.

Utiliser le paquet Python `delia_life` pour toute opération déterministe :

- calcul d'empreinte et d'identifiant stable;
- création de manifestes de sources;
- crawl statique borné d'un site;
- validation de structures JSON;
- transitions et journal d'audit des propositions;
- détection littérale de doublons;
- score explicable d'une offre;
- classement des templates;
- enregistrement chronologique des événements de candidature.

Ne pas recalculer manuellement ce que la CLI sait calculer. Cela réduit le coût en tokens et garantit la reproductibilité.

## Modèle mental

Le répertoire `model/` est la source de vérité conceptuelle. `model/model.yaml` référence les concepts, relations, cardinalités, invariants et règles de refactor. Les fichiers sous `data/` sont des instances de ce modèle.

Avant d'ajouter une nouvelle structure de données, rechercher si le concept existe déjà. Avant de renommer, fusionner ou supprimer un concept, exécuter `python scripts/delia_life.py model-impact <concept>`. Mettre à jour le YAML, le code, les schémas, les migrations et la documentation dans le même changement.

Ne jamais modifier une cardinalité ou un identifiant silencieusement. Conserver la compatibilité ou fournir une migration Python déterministe.

## Workflow d'ingestion

1. Placer l'original dans `private/originals/` ou fournir une URL.
2. Créer un manifeste avec la CLI; ne pas modifier l'original.
3. Extraire des propositions dans `data/review/queue/`, avec une preuve localisable.
4. Exécuter les contrôles déterministes de structure, doublon et conflit.
5. Présenter les propositions à un humain.
6. Enregistrer chaque décision comme `accepted`, `edited` ou `rejected`.
7. Appliquer uniquement les valeurs validées à `data/knowledge/`.

Pour un site, rester sur le même domaine, respecter `robots.txt`, limiter le débit et le nombre de pages, dater la capture et exclure les scripts de suivi. Archiver le brut dans `private/website-archives/`.

Versionner les originaux, archives, offres, candidatures, feedbacks, manifestes, propositions et décisions de revue afin qu'un clone du dépôt suffise à poursuivre le travail. Le nom `private/` signifie « exclu de GitHub Pages et des documents publics par défaut », pas « exclu de Git ». Ne jamais y stocker de mot de passe, jeton, clé privée, cookie d'authentification ou fichier `.env`.

## Workflow de candidature

1. Importer l'offre dans `data/offers/`.
2. Calculer un rapprochement explicable avec la base validée.
3. Choisir un template selon ses métadonnées et permettre une dérogation humaine.
4. Composer le CV et la lettre uniquement avec des faits validés.
5. Montrer les sources utilisées et les écarts non couverts.
6. Faire valider l'aperçu avant export DOCX/PDF.
7. Enregistrer l'envoi et les retours dans `data/applications/`.

## Templates

Un template ne contient aucune donnée personnelle. Son fichier `template.json` décrit ses usages, contraintes ATS, secteurs, séniorité, longueur et formats. Le style de Délia vit séparément dans `data/style/delia.json`. Toute sélection automatique doit fournir le détail de son score et rester remplaçable manuellement.

## Feedback

Un retour employeur est une observation rattachée à une candidature, pas une vérité universelle. Ne pas modifier automatiquement le profil ou les règles de génération. Produire une proposition d'amélioration, puis la soumettre à validation.

## Publication GitHub Pages

Le fichier `site/publication.json` est la liste blanche de publication. N'ajouter une source ou une clé qu'après validation explicite de son caractère public. Ne jamais publier depuis `private/`, `generated/`, `data/applications/`, `data/offers/`, `data/review/` ou `data/sources/`.

Construire le site avec `python scripts/delia_life.py build-site --output _site`. Inspecter `_site/` avant tout push sur `main`. Le workflow `.github/workflows/pages.yml` teste, valide, construit puis déploie l'artefact par GitHub Actions.

## Git, commit et publication

Utiliser `$manage-delia-git` pour les commandes utilisateur `commit` et `publish`.

Pour `commit`, exécuter `python scripts/repo_flow.py prepare-commit`, communiquer l'URL de prévisualisation et attendre la validation visuelle avant de mettre en index et committer. Inspecter le diff indexé, inclure les données métier utiles à la reproductibilité et exclure tout secret technique ou fichier temporaire.

Pour `publish`, vérifier `config/repository.json`, exécuter `python scripts/repo_flow.py publish-check`, puis pousser uniquement vers le remote et la branche configurés. Ne jamais forcer un push, fusionner ou réécrire l'historique implicitement.

## Revue locale obligatoire des contenus

Après toute demande utilisateur qui modifie un contenu visible ou publiable — notamment `data/knowledge/`, `model/`, `templates/`, `site/content/`, `site/assets/` ou les descriptions de skills affichées sur le site — exécuter `python scripts/repo_flow.py review-content`.

Cette commande doit terminer les tests, la validation du modèle et de la base, le build du site et le déploiement local. Communiquer l'URL produite et laisser le serveur actif pour permettre la vérification utilisateur. Lors d'une correction suivante, reconstruire sur le même serveur. Ne l'arrêter qu'à la demande explicite de l'utilisateur. Un commit, une publication ou la fin d'un échange ne sont pas des motifs d'arrêt.

Ne pas créer de commit et ne pas publier sur GitHub au titre de cette règle. `commit` et `publish` restent des autorisations explicites séparées.

## Routage vers les skills

- Import de CV, diplôme, document ou site : `$ingest-delia-knowledge`.
- Ajout ou choix d'un modèle : `$manage-delia-templates`.
- Création d'un CV ou d'une lettre : `$generate-delia-application`.
- Analyse et rapprochement d'une offre : `$match-delia-offers`.
- Événement de candidature ou feedback : `$track-delia-applications`.
- Construction, contrôle ou publication du site : `$publish-delia-site`.
- Préparation d'un commit ou push vers GitHub : `$manage-delia-git`.

## Qualité

Avant de terminer une modification :

1. exécuter `python -m unittest discover -s tests -v`;
2. exécuter `python scripts/delia_life.py model-check`;
3. exécuter `python scripts/delia_life.py check`;
4. pour une modification publiable, exécuter `python scripts/delia_life.py build-site --output _site`;
5. valider toute skill modifiée avec `quick_validate.py`;
6. inspecter `git diff`, vérifier que les sources et données métier attendues sont incluses et qu'aucun secret technique ne l'est.
