---
name: match-delia-offers
description: Importer, structurer, comparer et expliquer la pertinence d'une offre d'emploi déjà identifiée pour Délia Rossignol face à ses compétences et expériences validées. Utiliser cette skill pour analyser une annonce précise ou approfondir des finalistes, calculer leur couverture et relever les écarts. Pour scanner le marché, utiliser search-delia-offers.
---

# Rapprochement des offres

## Procédure

1. Enregistrer l'offre et sa provenance sous `data/offers/`.
2. Séparer exigences obligatoires, préférées et informations contextuelles. Pour tout prérequis d’expérience sectorielle, renseigner les `industry_sector_ids` du référentiel validé et `minimum_years` lorsque la durée est explicite.
3. Faire résoudre les prérequis sectoriels par le moteur à partir des secteurs normalisés des expériences validées. Le moteur additionne les périodes précises après fusion des chevauchements ; une période connue seulement à l’année reste associée au secteur mais ne prouve pas une durée en mois. Un fait négatif sectoriel validé permet de conclure `unmet`. Si l’annonce impose en plus une durée minimale chiffrée dans ce secteur absent, l’incompatibilité est certaine et exclut l’offre.
4. Exécuter `python scripts/delia_life.py match-offer <offre> <connaissances>` pour le score littéral reproductible.
5. Utiliser l'IA seulement pour proposer des équivalences sémantiques ou expliquer le contexte. Identifier clairement ces propositions.
6. Présenter les correspondances, les exigences manquantes, la méthode et les limites du score.
7. Ne jamais transformer un mot-clé d'offre en compétence détenue par Délia.
8. Soumettre toute nouvelle compétence présumée au workflow d'ingestion et de validation.
9. Après enregistrement ou modification d’une offre, exécuter `python scripts/repo_flow.py review-operational`.

Ne pas classer définitivement une offre sur le seul score; tenir compte des préférences validées de Délia et laisser la décision finale à l'humain.
