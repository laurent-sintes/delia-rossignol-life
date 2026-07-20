---
name: match-delia-offers
description: Importer, structurer, comparer et expliquer la pertinence d'une offre d'emploi déjà identifiée pour Délia Rossignol face à ses compétences et expériences validées. Utiliser cette skill pour analyser une annonce précise ou approfondir des finalistes, calculer leur couverture et relever les écarts. Pour scanner le marché, utiliser search-delia-offers.
---

# Rapprochement des offres

## Procédure

1. Enregistrer l'offre et sa provenance sous `data/offers/`.
2. Séparer exigences obligatoires, préférées et informations contextuelles.
3. Exécuter `python scripts/delia_life.py match-offer <offre> <connaissances>` pour le score littéral reproductible.
4. Utiliser l'IA seulement pour proposer des équivalences sémantiques ou expliquer le contexte. Identifier clairement ces propositions.
5. Présenter les correspondances, les exigences manquantes, la méthode et les limites du score.
6. Ne jamais transformer un mot-clé d'offre en compétence détenue par Délia.
7. Soumettre toute nouvelle compétence présumée au workflow d'ingestion et de validation.

Ne pas classer définitivement une offre sur le seul score; tenir compte des préférences validées de Délia et laisser la décision finale à l'humain.
