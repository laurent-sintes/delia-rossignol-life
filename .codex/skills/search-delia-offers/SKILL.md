---
name: search-delia-offers
description: Rechercher sur internet des offres d’emploi actuelles pour Délia Rossignol, constituer un pool multi-site, normaliser et dédoublonner les annonces, puis classer les 10 opportunités les plus intéressantes selon son projet professionnel validé. Utiliser cette skill lorsque l’utilisateur demande de scanner le marché, trouver des CDI ou missions d’intérim, produire une sélection d’offres ou actualiser un top 10 avec liens, résumés et explications de correspondance.
---

# Recherche d’offres pour Délia

## Workflow

1. Charger `private/career-project/delia-next-role-2026.json` et `config/offer-search.json`, puis exécuter `python scripts/delia_life.py check`. La couverture de chaque secteur prioritaire doit être déclarée dans `priority_sector_coverage`; la compléter avant tout scan. Ne jamais exposer dans le rapport les critères marqués sensibles.
2. Rechercher sur le web des annonces actuelles correspondant aux secteurs et fonctions du projet professionnel, autour de Bordeaux. Couvrir chaque domaine fonctionnel prioritaire avec toutes les requêtes déclarées dans `functional_query_families`; le contrôle Python bloque la recherche si une famille manque. Suivre `source_strategy.priority_order` : d’abord les portails directs des grandes enseignes et des maisons, ensuite les sites spécialisés, puis les agrégateurs. Couvrir plusieurs domaines de `source_domains`; viser au moins `candidate_pool_minimum` annonces distinctes.
3. Ouvrir la page exacte de chaque offre. Vérifier qu’elle est encore active et relever titre, employeur, lien canonique, source, lieu, contrat, date, résumé factuel, compétences et conditions explicites. Pour une annonce repérée par un agrégateur, remonter vers la page employeur lorsqu’elle est disponible, conformément à `require_direct_offer_verification`. Exclure les pages de résultats génériques du classement final.
4. Respecter les conditions d’utilisation, `robots.txt` et les limites d’accès. Ne contourner ni connexion, ni CAPTCHA, ni dispositif anti-robot. Ne pas recopier l’annonce intégralement; conserver seulement les faits utiles et un court résumé original.
5. Enregistrer chaque annonce normalisée sous `data/offers/YYYY-MM-DD/`. Utiliser le schéma `schemas/job-offer.schema.json` et renseigner au minimum ses champs obligatoires. Marquer toute donnée absente comme inconnue; ne jamais l’inférer silencieusement.
6. Exécuter `python scripts/delia_life.py rank-offers data/offers/YYYY-MM-DD --visited-source <site-1> --visited-source <site-2> --output generated/offer-search/YYYY-MM-DD.json`. Répéter `--visited-source` pour chaque site effectivement consulté, y compris s'il n'a fourni aucune offre retenue.
7. Examiner les exclusions, inconnues et avertissements produits. Une incompatibilité certaine écarte l’offre; une information inconnue reste un point de vigilance.
8. Utiliser `$match-delia-offers` pour approfondir les finalistes. Employer l’IA uniquement pour résumer l’annonce et expliquer des transferts de compétences non littéraux, en les distinguant du score déterministe.

## Règles de sélection

- Prioriser les CDI. Accepter un nombre limité de missions d’intérim lorsque le contenu est particulièrement pertinent.
- Utiliser le luxe comme critère de départage fort : c’est un environnement particulièrement recherché par Délia. Rechercher aussi systématiquement les métiers de relation client, gestion de portefeuille, back-office et coordination des portails directs banque-assurance ; ne pas assimiler vente-conseil et démarchage.
- Exclure le freelance, le temps partiel, l’immobilier, la restauration, la prospection physique et le démarchage téléphonique.
- Ne pas supposer compatibles le salaire, les horaires, la garde alternée, le travail en soirée ou le dimanche lorsqu’ils ne sont pas précisés.
- Favoriser la stabilité, l’autonomie, la responsabilité, le travail en équipe, la relation client et la gestion administrative.
- Préserver la diversité des employeurs et des sites; ne pas laisser un diffuseur dominer artificiellement le top 10.
- Ne jamais transformer une exigence d’annonce en compétence détenue par Délia.

## Restitution

Présenter jusqu’à 10 offres classées. Pour chacune, fournir :

- le poste, l’employeur, le contrat, le lieu et la date;
- le lien direct vers l’annonce;
- un résumé original de 40 à 70 mots;
- le score déterministe et ses principaux composants;
- deux à quatre raisons étayées par les connaissances validées;
- les écarts et informations à vérifier avant candidature.

Terminer par la date de recherche, les sources consultées, le nombre d’offres collectées, dédoublonnées, exclues et retenues. Préciser que le classement aide à décider et ne remplace pas la validation de Délia.
