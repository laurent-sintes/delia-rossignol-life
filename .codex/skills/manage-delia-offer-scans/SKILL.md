---
name: manage-delia-offer-scans
description: "Orchestrer les recherches d’offres de Délia avec quatre commandes explicites : « clean cache », « scan full », « scan delta » et « envoi à Délia ». Utiliser cette skill lorsque l’utilisateur demande de nettoyer l’état de recherche, de repartir de zéro, d’actualiser seulement les changements, ou d’effectuer une recherche complète suivie de l’envoi du résultat à Délia."
---

# Gestion des scans d’offres

## Commandes

Interpréter exactement les quatre intentions suivantes :

- `clean cache` : supprimer uniquement l’état technique jetable du scanner. Conserver tous les fichiers versionnés sous `data/offers/` et `generated/`.
- `scan full` : exécuter `clean cache`, repartir d’une session de collecte isolée, consulter toutes les sources prévues et classer uniquement les annonces observées ou revérifiées pendant cette session.
- `scan delta` : conserver l’historique, rechercher les nouvelles annonces et revérifier les offres devenues anciennes, incertaines ou modifiées depuis le dernier rapport complet.
- `envoi à Délia` : exécuter un `scan full`, préparer le paquet de revue, le contrôler puis envoyer effectivement le message à l’adresse validée de Délia. Cette formulation explicite autorise l’envoi pour cette exécution seulement.

## Démarrage déterministe

1. Lire `AGENTS.md`, `config/offer-search.json` et l’audit régional référencé par la configuration.
2. Pour `clean cache`, exécuter `python scripts/delia_life.py offer-scan clean-cache`. Pour `scan full` ou `scan delta`, exécuter respectivement `python scripts/delia_life.py run-offer-scan full` ou `python scripts/delia_life.py run-offer-scan delta`. Pour `envoi à Délia`, exécuter d’abord `python scripts/delia_life.py run-offer-scan full`, puis seulement le workflow d’envoi autorisé.
3. Pour `clean-cache`, vérifier `cache_cleaned: true`, présenter les racines préservées et s’arrêter.
4. Pour les scans, conserver le manifeste `.runtime/offer-search/current.json` et utiliser strictement :
   - `offer_output_directory` pour enregistrer chaque observation de la session ;
   - `rank_inputs` comme seules entrées du classement ;
   - `report_output_path` pour le rapport final ;
   - `requirements` comme checklist des sources, familles de requêtes et secteurs à couvrir ;
   - `revalidation_queue` comme liste prioritaire des annonces historiques à rouvrir en mode `delta`; elle doit être vide en mode `full` ou `send`.

Ne jamais remplacer `rank_inputs` par `data/offers` lors d’un scan `full` ou `send`. L’isolation de cette entrée garantit que les anciennes annonces ne réapparaissent pas comme si elles avaient été contrôlées aujourd’hui.
Ne jamais modifier `--runtime-root` pour viser un autre répertoire : Python refuse toute cible qui n’est pas un sous-répertoire `.runtime/offer-search` du dépôt.

## Collecte et classement

Utiliser `$search-delia-offers` pour la collecte, la vérification, la normalisation, le dédoublonnage et le classement.

- En mode `full`, consulter toutes les sources `core` et `complementary`, toutes les familles de requêtes et tous les secteurs prioritaires. Ne charger aucune annonce historique et ne recopier aucun résultat précédent : seules les annonces observées pendant la session courante peuvent entrer dans le rapport.
- En mode `delta`, partir du dernier rapport complet, interroger les sources modifiées ou tournantes, rechercher les nouveautés et revérifier les annonces `pending` ainsi que les annonces actives au-delà de l’âge maximal autorisé.
- Enregistrer aussi les annonces fermées, expirées, inaccessibles ou exclues observées pendant la session.
- Laisser `run-offer-scan` produire les reçus de collecte, archiver les pages, extraire les annonces structurées et transmettre automatiquement au classement les sources, familles de requêtes et secteurs effectivement couverts. Ne jamais déclarer cette couverture manuellement.
- Si le manifeste contient une `semantic_review_queue`, utiliser `$search-delia-offers` pour relire chaque archive indiquée, compléter uniquement les faits démontrés de l’offre et passer `extraction.review_status` à `completed` avec la date et la méthode de revue. Relancer ensuite `rank-offers <rank_inputs...> --require-complete-pool --scan-manifest .runtime/offer-search/current.json --output <report_output_path>`. Tant qu’une revue reste requise, `finalization_allowed` doit rester faux.
- Pour diagnostiquer une étape séparément, utiliser `offer-scan full|delta`, puis `collect-offers --scan-manifest .runtime/offer-search/current.json`, puis `rank-offers <rank_inputs...> --require-complete-pool --scan-manifest .runtime/offer-search/current.json --output <report_output_path>`.
- Ne jamais qualifier de complet un rapport dont `pool_complete` ou `finalization_allowed` est faux.

Un `scan full` peut retrouver moins d’annonces qu’un delta : ce résultat est acceptable s’il reflète uniquement des pages revérifiées et si toutes les sources prévues ont été consultées. Ne jamais compléter artificiellement avec une ancienne annonce non contrôlée pendant la session.

## Restitution et envoi

- Pour `scan full` et `scan delta`, restituer le rapport en conversation ou dans le format demandé. Ne produire ni brouillon ni envoi sans demande de partage.
- Pour `envoi à Délia`, utiliser `$share-delia-offer-selection` avec le rapport complet produit par la session. Appliquer le plafond général de 100 résultats, sans limite propre à l’email, puis contrôler le destinataire validé, le Bcc, les liens et le CV avant d’utiliser le connecteur de messagerie pour envoyer le message.
- Si le rapport full est incomplet, ne pas envoyer : expliquer les sources ou vérifications manquantes.
- Après toute modification de données, de rapport ou de paquet d’email, exécuter `python scripts/repo_flow.py review-operational`.
