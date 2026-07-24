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
9. Versionner dans Git le code, les configurations, schémas, templates, originaux et connaissances validées nécessaires à la reproductibilité. Garder hors de Git les secrets techniques, caches, fichiers temporaires et artefacts opérationnels régénérables de recherche d'offres : captures sous `private/offer-scan-archives/`, annonces collectées sous `data/offers/`, rapports sous `generated/offer-search/`, brouillons sous `generated/offer-feedback/` et cache sémantique sous `generated/offer-semantic-cache/`.
10. Favoriser le français pour les contenus destinés à Délia; conserver les identifiants et interfaces techniques en anglais.
11. Considérer que tout fichier committé est lisible dans le dépôt GitHub public. La visibilité sur GitHub Pages reste une décision distincte, contrôlée par `site/publication.json`.
12. Toute expérience validée doit comporter une `mission` explicite, courte et sourcée. Si elle manque, la signaler; ne jamais la déduire des responsabilités ou de l'intitulé.
13. Toute expérience validée doit comporter des `responsibilities` explicites, sourcées et non vides. Si elles manquent, les signaler; ne jamais les déduire de la mission, du titre ou des résultats.

## Répartition IA / Python

Utiliser l'IA pour les tâches qui demandent du jugement : extraction sémantique, rapprochement non littéral, reformulation, synthèse, analyse du ton et explication d'une recommandation. Pour une offre, l’IA caractérise chaque exigence par un rapprochement `exact`, `transferable`, `gap` ou `unknown`, mais ne produit jamais le score final.

Utiliser le paquet Python `delia_life` pour toute opération déterministe :

- calcul d'empreinte et d'identifiant stable;
- création de manifestes de sources;
- crawl statique borné d'un site;
- validation de structures JSON;
- transitions et journal d'audit des propositions;
- détection littérale de doublons;
- validation des preuves de rapprochement et calcul explicable du score d'une offre;
- classement des templates;
- enregistrement chronologique des événements de candidature.

Ne pas recalculer manuellement ce que la CLI sait calculer. Cela réduit le coût en tokens et garantit la reproductibilité.

Pour la recherche d’offres, la stratégie de sourcing vit dans `config/offer-search.json` : privilégier les portails directs des grandes enseignes et des maisons, puis les sites spécialisés, puis les agrégateurs. Rechercher la page exacte de l’employeur lorsqu’elle est disponible, mais ne pas écarter une annonce actuellement accessible sur LinkedIn, Indeed, Hellowork ou un autre agrégateur lorsqu’elle ne l’est pas : conserver l’annonce dans son classement avec un point de vigilance sur la source. La configuration doit déclarer au moins une source pour chaque secteur prioritaire du projet de carrière ; le contrôle Python bloque un scan si cette couverture est incomplète.
Chaque domaine de `source_domains` doit avoir exactement un mode de contrôle : collecte automatisée auditée ou contrôle manuel `core` / `complementary`. Un contrôle manuel doit produire un reçu rattaché au `scan_id`, avec URL, horodatage, statut et nombre d’offres observées. Seul un statut `success` couvre la source ; `no_access`, `skipped` ou l’absence de reçu interdit de finaliser le scan.

Toute offre extraite automatiquement et non déjà exclue par une règle certaine doit recevoir une revue LLM v3. Le LLM inventorie d'abord toutes les exigences significatives dans `semantic_requirements`, puis produit exactement un `semantic_match` par exigence. Chaque exigence cite un extrait réellement présent dans l'archive contrôlée; chaque correspondance positive cite au moins un champ précis d'une preuve validée du profil. Python rejette les couvertures incomplètes, les extraits absents et les références ou champs inconnus. Il dérive seul la confiance utilisée pour la pondération et calcule seul le score; `llm_confidence` reste explicative et ne modifie jamais la note. Un `gap` sur une exigence obligatoire place l'offre dans la section `informational` sans soustraire de points. Le rapprochement lexical reste uniquement un mode de compatibilité explicite pour les offres historiques ou manuelles sans revue sémantique. Une revue est réutilisable uniquement si les empreintes de la source et du profil, la version du prompt et la version du schéma sont identiques.

Associer chaque expérience validée à un ou plusieurs `industry_sector_ids` du référentiel normalisé. Tout prérequis d’expérience sectorielle d’une offre doit utiliser ces mêmes identifiants et une durée structurée lorsqu’elle est explicite. Le moteur résout la couverture à partir des périodes précises validées, en fusionnant les chevauchements ; les périodes connues seulement à l’année ne prouvent pas automatiquement une durée en mois. Une absence sectorielle ne peut être conclue qu’à partir d’un fait négatif validé. Lorsqu’une offre impose une durée minimale chiffrée dans un secteur dont l’absence d’expérience est validée, cette incompatibilité certaine exclut l’offre sans modifier son score.

Le périmètre de classement dépend du mode préparé par `python scripts/delia_life.py offer-scan` : un `full` ou `send` classe uniquement le répertoire isolé indiqué dans `rank_inputs`, tandis qu’un `delta` classe `data/offers` dans son ensemble. Un `full` ou `send` ne charge aucune annonce d’une recherche précédente et sa `revalidation_queue` doit être vide; seules les annonces rencontrées pendant la session courante alimentent son rapport. Un `delta` conserve l’historique et traite sa `revalidation_queue`. Chaque annonce repérée conserve un `verification_status` et sa dernière date de contrôle ; une annonce dont le lien détaillé actuel renvoie une erreur ou bloque l’accès reste traçable mais ne participe pas au classement actif. Transmettre `--scan-manifest`, chaque `--visited-source`, `--covered-query-family` et `--covered-priority-sector` au classement strict. Utiliser `--require-complete-pool` et ne jamais présenter comme finale une recherche dont `pool_complete`, `scan_coverage.complete` ou `finalization_allowed` est faux.
La complétude d’un scan ne dépend d’aucun volume minimal d’offres. Conserver, classer et restituer toutes les offres actives et éligibles, sans plafond de volume. Tous les secteurs prioritaires et tous les domaines fonctionnels prioritaires ont le même poids dans le score ; aucun bonus propre à un secteur ou domaine n’est autorisé.

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

Versionner les originaux, archives d'ingestion, candidatures, feedbacks, manifestes, propositions et décisions de revue afin qu'un clone du dépôt suffise à poursuivre le dossier de carrière. Les artefacts d'un scan d'offres restent locaux et régénérables dans les quatre répertoires exclus ci-dessus. Le nom `private/` signifie « exclu de GitHub Pages et des documents publics par défaut », pas automatiquement « exclu de Git » ; seule `private/offer-scan-archives/` est exclue en tant qu'artefact de scan. Ne jamais y stocker de mot de passe, jeton, clé privée, cookie d'authentification ou fichier `.env`.

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

Pour un email de revue d’offres à Délia, partir du rapport complet et afficher toutes les offres sans plafond de volume ni limite propre à l’email. Regrouper les offres classées dans trois sections ordonnées : « Il faut répondre, ça matche et tu as des chances d’un retour positif », « Tu peux répondre, on ne sait jamais », puis « Je te les mets pour info, mais il y a peu de chances ». Trier chaque section par pertinence décroissante et conserver une numérotation globale. Chaque offre doit présenter secteur, mission / poste, salaire proposé ou non communiqué, pertinence sur 100, puis un point de vigilance factuel visuellement signalé. Afficher les prérequis contraignants en rouge sans les soustraire du score ; ne jamais révéler les contraintes personnelles utilisées pour le classement. Ajouter ensuite une annexe non classée « Offres probablement actives à revérifier » pour les annonces `pending`, avec leur lien et leur motif de revérification, sans rang ni score. Introduire cette annexe en précisant que les annonces concernées ont été rencontrées dans la recherche actuelle, mais que leur lien détaillé a renvoyé une erreur ou bloqué l’accès; cela ne signifie ni qu’elles sont fermées ni qu’elles sont incompatibles. Les annonces accessibles sur un agrégateur ou sur une page listant plusieurs offres restent classées avec un point de vigilance et ne sont pas placées dans cette annexe. Terminer la liste par « Offres exclues et pourquoi », sans rang, avec le score calculé lorsqu’il existe et tous les motifs d’exclusion ; ne pas y répéter les annonces `pending`.

## Publication GitHub Pages

Le fichier `site/publication.json` est la liste blanche de publication. N'ajouter une source ou une clé qu'après validation explicite de son caractère public. Ne jamais publier depuis `private/`, `generated/`, `data/applications/`, `data/offers/`, `data/review/` ou `data/sources/`.

Générer et contrôler les documents avec `python scripts/delia_life.py build-documents` puis `python scripts/delia_life.py check-documents`. Construire le site avec `python scripts/delia_life.py build-site --output _site`. Inspecter `_site/` avant tout push sur `main`. Le workflow `.github/workflows/pages.yml` régénère les documents, teste, valide, construit puis déploie l'artefact par GitHub Actions.

## Git, commit et publication

Utiliser `$manage-delia-git` pour les commandes utilisateur `commit`, `push` et `publish`.

Pour `commit`, inspecter le diff, exécuter `python scripts/repo_flow.py prepare-commit`, puis, si tous les tests, validations et builds réussissent, mettre en index les fichiers concernés, inspecter le diff indexé et créer le commit local dans la même action. La demande explicite `commit` autorise ce commit local sans validation intermédiaire; elle n'autorise aucun push. Inclure les sources et données métier utiles à la reproductibilité, mais exclure tout secret technique, fichier temporaire et artefact opérationnel de recherche listé par `.gitignore`.

`push` et `publish` sont synonymes. Vérifier `config/repository.json`, exécuter `python scripts/repo_flow.py publish-check`, puis pousser uniquement le commit local courant vers le remote et la branche configurés. Suivre ensuite le workflow GitHub Actions configuré pour le SHA poussé jusqu'à son résultat final. Ne jamais forcer un push, fusionner, réécrire l'historique, corriger un échec de CI ou créer implicitement un commit local.

## Revue locale obligatoire des contenus

Après toute demande utilisateur qui modifie un contenu visible ou publiable — notamment `data/knowledge/`, `model/`, `templates/`, `site/content/`, `site/assets/` ou les descriptions de skills affichées sur le site — exécuter `python scripts/repo_flow.py review-content`.

Cette commande doit régénérer les documents déterministes, terminer les tests, contrôler leur reproductibilité et leur fraîcheur, valider le modèle et la base, construire le site puis assurer le déploiement local. Communiquer l'URL produite et laisser le serveur actif pour permettre la vérification utilisateur. Lors d'une correction suivante, reconstruire sur le même serveur. Ne l'arrêter qu'à la demande explicite de l'utilisateur. Un commit, une publication ou la fin d'un échange ne sont pas des motifs d'arrêt.

Pour une modification limitée au code de recherche, aux offres opérationnelles ou au message de revue par email, exécuter `python scripts/repo_flow.py review-operational` : les mêmes contrôles de code et de données s’appliquent, mais sans régénérer le CV ni reconstruire le site. Le serveur local existant reste actif.

Ne pas créer de commit et ne pas publier sur GitHub au titre de cette règle. `commit` et `push` / `publish` restent des autorisations explicites séparées.

## Routage vers les skills

- Import de CV, diplôme, document ou site : `$ingest-delia-knowledge`.
- Ajout ou choix d'un modèle : `$manage-delia-templates`.
- Création d'un CV ou d'une lettre : `$generate-delia-application`.
- Recherche multi-site et classement d'offres : `$search-delia-offers`.
- Nettoyage de l’état de recherche, scan full, scan delta ou scan full suivi d’un envoi : `$manage-delia-offer-scans`, qui orchestre ensuite `$search-delia-offers` et, pour l’envoi, `$share-delia-offer-selection`.
- Partage d'une sélection d'offres et collecte du feedback de Délia : `$share-delia-offer-selection`.
- Analyse et rapprochement d'une offre : `$match-delia-offers`.
- Événement de candidature ou feedback : `$track-delia-applications`.
- Construction, contrôle ou publication du site : `$publish-delia-site`.
- Préparation d'un commit ou push vers GitHub : `$manage-delia-git`.

## Qualité

Avant de terminer une modification :

1. exécuter `python -m ruff check src scripts tests`;
2. exécuter `python -m mypy`;
3. exécuter `python -m coverage run -m unittest discover -s tests -v` puis `python -m coverage report`;
4. exécuter `python scripts/delia_life.py model-check`;
5. exécuter `python scripts/delia_life.py check`;
6. exécuter `python scripts/delia_life.py build-documents` puis `python scripts/delia_life.py check-documents`;
7. pour une modification publiable, exécuter `python scripts/delia_life.py build-site --output _site`;
8. valider toute skill modifiée avec `quick_validate.py`;
9. inspecter `git diff`, vérifier que les sources et données métier attendues sont incluses, que les artefacts de recherche régénérables restent exclus et qu'aucun secret technique ne l'est.
