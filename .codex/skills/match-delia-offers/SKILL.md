---
name: match-delia-offers
description: Importer, structurer, comparer et expliquer la pertinence d'une offre d'emploi déjà identifiée pour Délia Rossignol face à ses compétences et expériences validées. Utiliser cette skill pour analyser une annonce précise ou approfondir des finalistes, calculer leur couverture et relever les écarts. Pour scanner le marché, utiliser search-delia-offers.
---

# Rapprochement des offres

## Procédure

1. Enregistrer l'offre et sa provenance sous `data/offers/`.
2. Séparer exigences obligatoires, préférées et informations contextuelles. Pour tout prérequis d’expérience sectorielle, renseigner les `industry_sector_ids` du référentiel validé et `minimum_years` lorsque la durée est explicite.
3. Faire résoudre les prérequis sectoriels par le moteur à partir des secteurs normalisés des expériences validées. Le moteur additionne les périodes précises après fusion des chevauchements ; une période connue seulement à l’année reste associée au secteur mais ne prouve pas une durée en mois. Un fait négatif sectoriel validé permet de conclure `unmet`. Si l’annonce impose en plus une durée minimale chiffrée dans ce secteur absent, l’incompatibilité est certaine et exclut l’offre.
4. Utiliser l’IA pour inventorier toutes les exigences significatives dans `semantic_requirements`, puis produire dans `semantic_matches` exactement un rapprochement par exigence : `exact`, `transferable`, `gap` ou `unknown`. Chaque exigence conserve son importance, sa nature et un extrait localisable réellement présent dans l’archive. Chaque correspondance conserve `llm_confidence` et une justification; un rapprochement positif doit citer au moins un `profile_evidence_ref` vers un identifiant et un champ précis du profil validé.
5. Faire valider la couverture, les extraits, les empreintes et les références par Python, puis laisser Python dériver `scoring_confidence` et calculer seul le score à partir de ces rapprochements et des coefficients de la politique. `llm_confidence` n’influence pas la note. Un `gap` obligatoire force la section `informational` sans pénalité de score; le LLM ne fournit ni score final ni décision d’exclusion.
6. Pour une offre historique ou manuelle sans revue sémantique, le moteur peut conserver temporairement un `lexical_fallback`, explicitement signalé; il ne constitue pas la méthode cible.
7. Présenter les correspondances, les exigences manquantes, la méthode et les limites du score.
8. Ne jamais transformer un mot-clé d'offre en compétence détenue par Délia.
9. Soumettre toute nouvelle compétence présumée au workflow d'ingestion et de validation.
10. Après enregistrement ou modification d’une offre, exécuter `python scripts/repo_flow.py review-operational`.

Ne pas classer définitivement une offre sur le seul score; tenir compte des préférences validées de Délia et laisser la décision finale à l'humain.
