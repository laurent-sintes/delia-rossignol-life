from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.core import load_json
from delia_life.offer_search import (
    canonical_offer_url,
    collect_validated_absent_sector_experience_ids,
    collect_validated_profile_completeness,
    collect_validated_sector_experience_months,
    offer_identity,
    rank_offers,
    score_offer,
    source_origin,
)
from delia_life.project_validation import (
    invalid_offer_pool_limits,
    invalid_offer_source_audit,
    invalid_recommendation_band_thresholds,
    missing_priority_functional_coverage,
    missing_priority_sector_coverage,
)


class OfferSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = load_json(ROOT / "private" / "career-project" / "delia-next-role-2026.json")
        self.policy = load_json(ROOT / "config" / "offer-search.json")
        self.source_audit = load_json(ROOT / "config" / "offer-source-audit.json")
        self.today = date(2026, 7, 19)
        self.base = {
            "id": "offer-1",
            "title": "Responsable administration des ventes luxe",
            "employer": "Maison Exemple",
            "source_url": "https://jobs.example/offers/1?utm_source=test",
            "source_site": "jobs.example",
            "source_kind": "direct_employer",
            "verification_status": "active",
            "last_verified_at": "2026-07-19T09:00:00+02:00",
            "published_at": "2026-07-18",
            "contract_type": "CDI",
            "location_label": "Bordeaux",
            "summary": "Administration, relation client et coordination avec une équipe dans le luxe.",
            "required_skills": ["relation client", "administration"],
            "preferred_skills": ["coordination"],
            "full_time": True,
            "conditions": {},
        }

    def test_cdi_ranks_above_interim_with_equal_content(self) -> None:
        interim = {**self.base, "id": "offer-2", "source_url": "https://jobs.example/offers/2", "contract_type": "intérim"}
        result = rank_offers([interim, self.base], self.project, self.policy, {"relation", "client", "administration"}, today=self.today)
        self.assertEqual(result["offers"][0]["id"], "offer-1")
        self.assertGreater(result["offers"][0]["assessment"]["score"], result["offers"][1]["assessment"]["score"])

    def test_score_offer_characterization_preserves_the_complete_assessment(self) -> None:
        self.assertEqual(
            score_offer(
                self.base,
                self.project,
                self.policy,
                {"relation", "client", "administration"},
                self.today,
            ),
            {
                "eligible": True,
                "score": 94.5,
                "reasons": [
                    "CDI, contrat prioritaire",
                    "secteur très recherché : luxe",
                    "activité prioritaire : conseil et relation client",
                    "expérience transférable : administration, client, relation",
                    "offre publiée depuis moins de 8 jours",
                    "dimension collective explicite",
                ],
                "gaps": [],
                "unknowns": ["rémunération non précisée"],
                "hard_constraint_failures": [],
                "knowledge_keyword_matches": ["administration", "client", "relation"],
                "prerequisite_alerts": [],
                "application_barriers": [],
                "profile_family_matches": [],
                "recommendation_band": "priority",
                "recommendation_reasons": ["forte correspondance sans prérequis obligatoire incertain"],
                "forced_to_end": False,
            },
        )

    def test_not_demonstrated_prerequisite_changes_band_without_changing_score(self) -> None:
        offer = {
            **self.base,
            "prerequisites": [
                {
                    "id": "experience-assurantielle",
                    "kind": "sector_experience",
                    "description": "Expérience préalable dans le domaine assurantiel",
                    "mandatory": True,
                    "profile_status": "not_demonstrated",
                }
            ],
        }
        assessment = score_offer(
            offer,
            self.project,
            self.policy,
            {"relation", "client", "administration"},
            self.today,
        )
        self.assertTrue(assessment["eligible"])
        self.assertEqual(assessment["score"], 94.5)
        self.assertEqual(assessment["recommendation_band"], "possible")
        self.assertFalse(assessment["forced_to_end"])
        self.assertEqual(
            assessment["prerequisite_alerts"],
            [
                {
                    "id": "experience-assurantielle",
                    "kind": "sector_experience",
                    "description": "Expérience préalable dans le domaine assurantiel",
                    "mandatory": True,
                    "status": "not_demonstrated",
                    "message": "non démontré dans les connaissances validées",
                }
            ],
        )

    def test_explicitly_met_prerequisite_stays_resolved_without_an_alert(self) -> None:
        offer = {
            **self.base,
            "prerequisites": [
                {
                    "id": "anglais-operationnel",
                    "kind": "language",
                    "description": "Anglais opérationnel à l'oral",
                    "mandatory": True,
                    "profile_status": "met",
                }
            ],
        }

        assessment = score_offer(offer, self.project, self.policy, set(), self.today)

        self.assertEqual(assessment["prerequisite_alerts"], [])
        self.assertEqual(assessment["recommendation_band"], "priority")

    def test_certain_mandatory_unmet_prerequisite_forces_offer_to_end_without_changing_score(self) -> None:
        offer = {
            **self.base,
            "prerequisites": [
                {
                    "id": "experience-obligatoire",
                    "kind": "prior_role",
                    "description": "Expérience préalable obligatoire",
                    "mandatory": True,
                    "profile_status": "unmet",
                }
            ],
        }
        assessment = score_offer(offer, self.project, self.policy, set(), self.today)
        self.assertTrue(assessment["eligible"])
        self.assertEqual(assessment["score"], 87.0)
        self.assertEqual(assessment["recommendation_band"], "informational")
        self.assertTrue(assessment["forced_to_end"])
        self.assertEqual(assessment["hard_constraint_failures"], [])
        self.assertIn(
            "prérequis obligatoire non satisfait : Expérience préalable obligatoire",
            assessment["application_barriers"],
        )

    def test_certain_missing_mandatory_certification_excludes_offer_without_changing_score(self) -> None:
        offer = {
            **self.base,
            "prerequisites": [
                {
                    "id": "certification-amf",
                    "kind": "certification",
                    "credential_id": "certification-amf",
                    "description": "Certification AMF",
                    "mandatory": True,
                    "profile_status": "unmet",
                    "profile_evidence_ids": ["knowledge-fact:delia-amf-certification-absent"],
                }
            ],
        }

        assessment = score_offer(
            offer,
            self.project,
            self.policy,
            set(),
            self.today,
            absent_certifications={
                "certification-amf": {"knowledge-fact:delia-amf-certification-absent"}
            },
        )

        self.assertFalse(assessment["eligible"])
        self.assertEqual(assessment["score"], 87.0)
        self.assertEqual(assessment["recommendation_band"], "excluded")
        self.assertFalse(assessment["forced_to_end"])
        self.assertIn(
            "certification obligatoire non satisfaite : Certification AMF",
            assessment["hard_constraint_failures"],
        )

    def test_unvalidated_missing_certification_is_not_treated_as_certain(self) -> None:
        offer = {
            **self.base,
            "prerequisites": [
                {
                    "id": "certification-inconnue",
                    "kind": "certification",
                    "credential_id": "certification-inconnue",
                    "description": "Certification métier",
                    "mandatory": True,
                    "profile_status": "unmet",
                }
            ],
        }

        assessment = score_offer(offer, self.project, self.policy, set(), self.today)

        self.assertTrue(assessment["eligible"])
        self.assertEqual(assessment["recommendation_band"], "possible")
        self.assertEqual(assessment["prerequisite_alerts"][0]["status"], "not_demonstrated")

    def test_complete_diploma_inventory_excludes_missing_mandatory_qualification(self) -> None:
        offer = {
            **self.base,
            "prerequisites": [
                {
                    "id": "diplome-esthetique",
                    "kind": "qualification",
                    "description": "CAP, BP ou BTS Esthétique",
                    "mandatory": True,
                    "profile_status": "not_demonstrated",
                }
            ],
        }
        baseline = score_offer(offer, self.project, self.policy, set(), self.today)

        assessment = score_offer(
            offer,
            self.project,
            self.policy,
            set(),
            self.today,
            complete_profile_dimensions={"credentials"},
        )

        self.assertTrue(baseline["eligible"])
        self.assertFalse(assessment["eligible"])
        self.assertEqual(assessment["score"], baseline["score"])
        self.assertEqual(assessment["recommendation_band"], "excluded")
        self.assertEqual(assessment["prerequisite_alerts"][0]["status"], "unmet")
        self.assertIn(
            "diplôme obligatoire non satisfait : CAP, BP ou BTS Esthétique",
            assessment["hard_constraint_failures"],
        )

    def test_complete_diploma_inventory_does_not_exclude_missing_experience(self) -> None:
        offer = {
            **self.base,
            "prerequisites": [
                {
                    "id": "experience-mode",
                    "kind": "minimum_experience",
                    "description": "Deux ans d'expérience dans la mode",
                    "mandatory": True,
                    "profile_status": "not_demonstrated",
                }
            ],
        }

        assessment = score_offer(
            offer,
            self.project,
            self.policy,
            set(),
            self.today,
            complete_profile_dimensions={"credentials"},
        )

        self.assertTrue(assessment["eligible"])
        self.assertEqual(assessment["recommendation_band"], "possible")
        self.assertEqual(assessment["prerequisite_alerts"][0]["status"], "not_demonstrated")

    def test_validated_profile_completeness_is_loaded_from_knowledge(self) -> None:
        self.assertIn(
            "credentials",
            collect_validated_profile_completeness(ROOT / "data" / "knowledge"),
        )

    def test_validated_sector_experience_months_are_merged_from_precise_periods(self) -> None:
        months = collect_validated_sector_experience_months(ROOT / "data" / "knowledge")

        self.assertEqual(months["mode-et-pret-a-porter"], 32)
        self.assertEqual(months["luxe"], 23)
        self.assertEqual(months["agencement-et-amenagement-interieur"], 89)
        self.assertNotIn("cosmetique", months)

    def test_validated_absent_sector_experience_uses_normalized_ids(self) -> None:
        self.assertEqual(
            collect_validated_absent_sector_experience_ids(ROOT / "data" / "knowledge"),
            {"banque-et-assurance"},
        )

    def test_normalized_sector_duration_automatically_resolves_a_prerequisite(self) -> None:
        offer = {
            **self.base,
            "prerequisites": [
                {
                    "id": "experience-mode-un-an",
                    "kind": "sector_experience",
                    "description": "Au moins un an dans la mode",
                    "mandatory": True,
                    "minimum_years": 1,
                    "industry_sector_ids": ["mode-et-pret-a-porter"],
                    "profile_status": "not_demonstrated",
                }
            ],
        }
        baseline = score_offer(offer, self.project, self.policy, set(), self.today)

        assessment = score_offer(
            offer,
            self.project,
            self.policy,
            set(),
            self.today,
            sector_experience_months={"mode-et-pret-a-porter": 32},
        )

        self.assertEqual(assessment["score"], baseline["score"])
        self.assertEqual(baseline["recommendation_band"], "possible")
        self.assertEqual(assessment["recommendation_band"], "priority")
        self.assertEqual(assessment["prerequisite_alerts"], [])
        self.assertIn(
            "prérequis sectoriel couvert : 32 mois validés pour 12 requis",
            assessment["reasons"],
        )

    def test_validated_absent_sector_automatically_marks_prerequisite_unmet(self) -> None:
        offer = {
            **self.base,
            "prerequisites": [
                {
                    "id": "experience-assurance",
                    "kind": "sector_experience",
                    "description": "Expérience préalable dans l'assurance",
                    "mandatory": True,
                    "industry_sector_ids": ["banque-et-assurance"],
                    "profile_status": "not_demonstrated",
                }
            ],
        }
        baseline = score_offer(offer, self.project, self.policy, set(), self.today)

        assessment = score_offer(
            offer,
            self.project,
            self.policy,
            set(),
            self.today,
            absent_sector_experience_ids={"banque-et-assurance"},
        )

        self.assertEqual(assessment["score"], baseline["score"])
        self.assertEqual(assessment["recommendation_band"], "informational")
        self.assertTrue(assessment["forced_to_end"])
        self.assertEqual(assessment["prerequisite_alerts"][0]["status"], "unmet")

    def test_quantified_sector_experience_is_excluded_when_sector_absence_is_validated(self) -> None:
        offer = {
            **self.base,
            "prerequisites": [
                {
                    "id": "experience-assurance-deux-ans",
                    "kind": "sector_experience",
                    "description": "Deux ans chez un assureur ou un courtier",
                    "mandatory": True,
                    "industry_sector_ids": ["banque-et-assurance"],
                    "minimum_years": 2,
                    "profile_status": "not_demonstrated",
                }
            ],
        }
        baseline = score_offer(offer, self.project, self.policy, set(), self.today)

        assessment = score_offer(
            offer,
            self.project,
            self.policy,
            set(),
            self.today,
            absent_sector_experience_ids={"banque-et-assurance"},
        )

        self.assertEqual(assessment["score"], baseline["score"])
        self.assertFalse(assessment["eligible"])
        self.assertEqual(assessment["recommendation_band"], "excluded")
        self.assertIn(
            "expérience sectorielle obligatoire non satisfaite : Deux ans chez un assureur ou un courtier",
            assessment["hard_constraint_failures"],
        )

    def test_legacy_insurance_condition_uses_the_generic_possible_band(self) -> None:
        offer = {**self.base, "conditions": {"insurance_experience_required": True}}
        assessment = score_offer(
            offer,
            self.project,
            self.policy,
            {"relation", "client", "administration"},
            self.today,
        )
        self.assertTrue(assessment["eligible"])
        self.assertEqual(assessment["score"], 94.5)
        self.assertEqual(assessment["recommendation_band"], "possible")

    def test_rank_offers_compiles_the_scoring_context_once(self) -> None:
        import delia_life.offer_search as offer_search

        original = offer_search._build_scoring_context
        with patch.object(offer_search, "_build_scoring_context", wraps=original) as build_context:
            rank_offers([self.base, {**self.base, "id": "offer-2", "source_url": "https://jobs.example/offers/2"}], self.project, self.policy, set(), today=self.today)
            build_context.assert_called_once_with(
                self.project,
                self.policy,
                set(),
                self.today,
                None,
                None,
                None,
                None,
            )

    def test_rank_offers_characterization_preserves_order_diversity_and_exclusions(self) -> None:
        offers = [
            self.base,
            {**self.base, "id": "offer-copy", "source_url": "https://jobs.example/offers/1?utm_campaign=copy"},
            {
                **self.base,
                "id": "offer-interim",
                "source_url": "https://specialist.example/offers/2",
                "source_site": "specialist.example",
                "employer": "Employeur Deux",
                "contract_type": "intérim",
            },
            {
                **self.base,
                "id": "offer-excluded",
                "source_url": "https://direct.example/offers/3",
                "source_site": "direct.example",
                "employer": "Employeur Trois",
                "summary": "Prospection physique et démarchage téléphonique.",
            },
        ]
        result = rank_offers(
            offers,
            self.project,
            self.policy,
            {"relation", "client", "administration"},
            today=self.today,
            visited_sources=["https://visited.example/search"],
        )
        self.assertEqual(
            {
                "candidate_count": result["candidate_count"],
                "unique_count": result["unique_count"],
                "eligible_count": result["eligible_count"],
                "excluded_count": result["excluded_count"],
                "ranked_ids": [offer["id"] for offer in result["offers"]],
                "ranked_scores": [offer["assessment"]["score"] for offer in result["offers"]],
                "excluded": result["excluded"],
                "visited_sources": result["visited_sources"],
            },
            {
                "candidate_count": 4,
                "unique_count": 3,
                "eligible_count": 2,
                "excluded_count": 1,
                "ranked_ids": ["offer-1", "offer-interim"],
                "ranked_scores": [94.5, 76.5],
                "excluded": [
                    {
                        "id": "offer-excluded",
                        "title": "Responsable administration des ventes luxe",
                        "employer": "Employeur Trois",
                        "source_url": "https://direct.example/offers/3",
                        "employer_source_url": None,
                        "contract_type": "CDI",
                        "location_label": "Bordeaux",
                        "sector_labels": [],
                        "phase": "policy",
                        "score": 87.5,
                        "failures": [
                            "activité exclue : démarchage téléphonique",
                            "activité exclue : prospection physique",
                        ],
                    }
                ],
                "visited_sources": [
                    "https://visited.example",
                    "https://jobs.example",
                    "https://specialist.example",
                    "https://direct.example",
                ],
            },
        )

    def test_hard_constraints_exclude_prospecting_and_part_time(self) -> None:
        excluded = {
            **self.base,
            "summary": "Prospection physique et démarchage téléphonique.",
            "full_time": False,
        }
        assessment = score_offer(excluded, self.project, self.policy, set(), self.today)
        self.assertFalse(assessment["eligible"])
        self.assertIn("offre à temps partiel", assessment["hard_constraint_failures"])
        self.assertTrue(any("activité exclue" in failure for failure in assessment["hard_constraint_failures"]))

    def test_tracking_parameters_do_not_create_duplicates(self) -> None:
        duplicate = {**self.base, "id": "offer-copy", "source_url": "https://jobs.example/offers/1?utm_campaign=x"}
        result = rank_offers([self.base, duplicate], self.project, self.policy, set(), today=self.today)
        self.assertEqual(result["unique_count"], 1)
        self.assertEqual(canonical_offer_url(self.base["source_url"]), "https://jobs.example/offers/1")
        self.assertEqual(offer_identity(self.base), offer_identity(duplicate))

    def test_canonical_offer_id_deduplicates_aggregator_and_employer_pages(self) -> None:
        aggregator = {
            **self.base,
            "canonical_offer_id": "REF-123",
            "source_url": "https://aggregator.example/jobs/123",
            "source_kind": "aggregator",
        }
        employer = {
            **self.base,
            "canonical_offer_id": "REF-123",
            "source_url": "https://employer.example/jobs/123",
            "last_verified_at": "2026-07-19T10:00:00+02:00",
        }

        result = rank_offers([aggregator, employer], self.project, self.policy, set(), today=self.today)

        self.assertEqual(result["unique_count"], 1)
        self.assertEqual(result["offers"][0]["source_url"], "https://employer.example/jobs/123")

    def test_incomplete_pool_and_unknown_conditions_are_explicit(self) -> None:
        offer = {**self.base, "published_at": None, "conditions": {}, "summary": "Administration dans le luxe."}
        offer.pop("contract_type")
        result = rank_offers([offer], self.project, self.policy, set(), today=self.today)
        self.assertEqual(result["eligible_count"], 1)
        self.assertTrue(any("pool actif incomplet" in warning for warning in result["warnings"]))
        self.assertIn("type de contrat non précisé", result["offers"][0]["assessment"]["unknowns"])

    def test_unverified_legacy_offers_are_queued_instead_of_ranked(self) -> None:
        legacy = {key: value for key, value in self.base.items() if key != "verification_status"}

        result = rank_offers([legacy], self.project, self.policy, set(), today=self.today)

        self.assertEqual(result["active_count"], 0)
        self.assertEqual(result["eligible_count"], 0)
        self.assertEqual(result["verification_counts"]["pending"], 1)
        self.assertEqual(result["pending_offer_count"], 1)
        self.assertEqual(result["pending_offers"][0]["id"], "offer-1")
        self.assertEqual(result["pending_offers"][0]["source_url"], self.base["source_url"])
        self.assertEqual(
            result["pending_offers"][0]["verification_reason"],
            "annonce en attente de revérification",
        )
        self.assertEqual(result["excluded"][0]["phase"], "verification")
        self.assertIn("attente de revérification", result["excluded"][0]["failures"][0])

    def test_latest_verification_supersedes_an_older_active_copy(self) -> None:
        closed = {
            **self.base,
            "id": "offer-closed",
            "verification_status": "closed",
            "last_verified_at": "2026-07-20T09:00:00+02:00",
        }

        result = rank_offers([self.base, closed], self.project, self.policy, set(), today=self.today)

        self.assertEqual(result["unique_count"], 1)
        self.assertEqual(result["active_count"], 0)
        self.assertEqual(result["verification_counts"]["closed"], 1)
        self.assertEqual(result["pending_offer_count"], 0)
        self.assertEqual(result["pending_offers"], [])

    def test_active_offer_requires_recent_verification(self) -> None:
        stale = {**self.base, "last_verified_at": "2026-07-01T09:00:00+02:00"}

        result = rank_offers([stale], self.project, self.policy, set(), today=self.today)

        self.assertEqual(result["active_count"], 0)
        self.assertIn("revérification nécessaire", result["excluded"][0]["failures"][0])

    def test_aggregator_offer_requires_an_exact_employer_page(self) -> None:
        aggregator = {**self.base, "source_kind": "aggregator"}
        verified = {
            **aggregator,
            "employer_source_url": "https://employer.example/jobs/offer-1",
        }

        pending_result = rank_offers([aggregator], self.project, self.policy, set(), today=self.today)
        verified_result = rank_offers([verified], self.project, self.policy, set(), today=self.today)

        self.assertEqual(pending_result["active_count"], 0)
        self.assertIn("page employeur exacte", pending_result["excluded"][0]["failures"][0])
        self.assertEqual(verified_result["active_count"], 1)

    def test_report_separates_pool_eligibility_and_selection_metrics(self) -> None:
        result = rank_offers([self.base], self.project, self.policy, set(), today=self.today)

        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["unique_count"], 1)
        self.assertEqual(result["active_count"], 1)
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["selected_count"], 1)
        self.assertFalse(result["pool_complete"])
        self.assertEqual(result["report_status"], "incomplete")
        self.assertFalse(result["finalization_allowed"])

    def test_strict_pool_completeness_requires_declared_scan_coverage(self) -> None:
        offers = [
            {
                **self.base,
                "id": f"offer-{index}",
                "source_url": f"https://jobs.example/offers/{index}",
            }
            for index in range(30)
        ]
        requirements = {
            "required_source_domains": ["jobs.example"],
            "required_query_families": ["relation-client"],
            "required_priority_sectors": ["luxe"],
        }

        incomplete = rank_offers(
            offers,
            self.project,
            self.policy,
            set(),
            today=self.today,
            scan_requirements=requirements,
            require_scan_coverage=True,
        )
        complete = rank_offers(
            offers,
            self.project,
            self.policy,
            set(),
            today=self.today,
            visited_sources=["https://jobs.example/search"],
            scan_requirements=requirements,
            covered_query_families={"relation-client"},
            covered_priority_sectors={"luxe"},
            require_scan_coverage=True,
        )

        self.assertTrue(incomplete["active_pool_complete"])
        self.assertFalse(incomplete["pool_complete"])
        self.assertEqual(incomplete["scan_coverage"]["missing_source_domains"], ["jobs.example"])
        self.assertTrue(complete["pool_complete"])
        self.assertTrue(complete["finalization_allowed"])

    def test_monthly_compensation_is_compared_as_an_annual_amount(self) -> None:
        eligible = {
            **self.base,
            "compensation": {"minimum": 2400, "maximum": 2500, "currency": "EUR", "period": "month"},
        }
        excluded = {
            **self.base,
            "id": "offer-low-pay",
            "source_url": "https://jobs.example/offers/low-pay",
            "compensation": {"minimum": 2000, "maximum": 2200, "currency": "EUR", "period": "month"},
        }
        self.assertTrue(score_offer(eligible, self.project, self.policy, set(), self.today)["eligible"])
        assessment = score_offer(excluded, self.project, self.policy, set(), self.today)
        self.assertFalse(assessment["eligible"])
        self.assertIn("rémunération maximale sous le minimum validé", assessment["hard_constraint_failures"])

    def test_luxury_emphasis_breaks_a_tie_between_priority_sectors(self) -> None:
        common = {**self.base, "title": "Responsable relation client", "summary": "Relation client et coordination avec une équipe."}
        luxury = {**common, "sector_labels": ["luxe"]}
        cosmetics = {
            **common,
            "id": "offer-cosmetics",
            "title": "Responsable relation client",
            "source_url": "https://jobs.example/offers/cosmetics",
            "sector_labels": ["cosmétique"],
        }
        luxury_score = score_offer(luxury, self.project, self.policy, set(), self.today)["score"]
        cosmetics_score = score_offer(cosmetics, self.project, self.policy, set(), self.today)["score"]
        self.assertGreater(luxury_score, cosmetics_score)

    def test_ranked_report_keeps_email_header_fields(self) -> None:
        offer = {
            **self.base,
            "sector_labels": ["luxe"],
            "compensation": {"minimum": 30000, "currency": "EUR", "period": "year"},
            "conditions": {"insurance_experience_required": False},
        }
        result = rank_offers([offer], self.project, self.policy, set(), today=self.today)
        ranked = result["offers"][0]
        self.assertEqual(ranked["sector_labels"], ["luxe"])
        self.assertEqual(ranked["compensation"]["minimum"], 30000)
        self.assertTrue(ranked["full_time"])
        self.assertIn("insurance_experience_required", ranked["conditions"])

    def test_ranked_report_preserves_structured_prerequisites(self) -> None:
        prerequisite = {
            "id": "experience-metier",
            "kind": "prior_role",
            "description": "Avoir déjà exercé le métier",
            "mandatory": True,
            "profile_status": "unknown",
        }
        result = rank_offers(
            [{**self.base, "prerequisites": [prerequisite]}],
            self.project,
            self.policy,
            set(),
            today=self.today,
        )
        self.assertEqual(result["offers"][0]["prerequisites"], [prerequisite])
        self.assertEqual(result["offers"][0]["assessment"]["score"], 87.0)
        self.assertEqual(result["offers"][0]["recommendation_band"], "possible")

    def test_ranking_groups_sections_before_sorting_by_score(self) -> None:
        priority = self.base
        possible = {
            **self.base,
            "id": "offer-possible",
            "source_url": "https://jobs.example/offers/possible",
            "title": "Responsable relation client",
            "summary": "Relation client et coordination avec une équipe.",
            "sector_labels": ["services"],
            "required_skills": [],
            "preferred_skills": [],
        }
        forced_to_end = {
            **self.base,
            "id": "offer-forced",
            "source_url": "https://jobs.example/offers/forced",
            "prerequisites": [
                {
                    "id": "experience-obligatoire",
                    "kind": "prior_role",
                    "description": "Expérience préalable obligatoire",
                    "mandatory": True,
                    "profile_status": "unmet",
                }
            ],
        }
        result = rank_offers(
            [forced_to_end, possible, priority],
            self.project,
            self.policy,
            {"relation", "client", "administration"},
            today=self.today,
        )
        self.assertEqual([offer["id"] for offer in result["offers"]], ["offer-1", "offer-possible", "offer-forced"])
        self.assertGreater(
            result["offers"][2]["assessment"]["score"],
            result["offers"][1]["assessment"]["score"],
        )
        self.assertEqual(result["section_counts"], {"priority": 1, "possible": 1, "informational": 1})

    def test_recommendation_thresholds_must_be_ordered(self) -> None:
        invalid_policy = {**self.policy, "recommendation_bands": {"priority_minimum_score": 60, "possible_minimum_score": 70}}
        self.assertEqual(
            invalid_recommendation_band_thresholds(invalid_policy),
            ["offer search policy: possible score threshold cannot exceed priority score threshold"],
        )
        with self.assertRaisesRegex(ValueError, "possible recommendation score"):
            score_offer(self.base, self.project, invalid_policy, set(), self.today)

    def test_offer_pool_limits_distinguish_minimum_and_maximum(self) -> None:
        self.assertEqual(invalid_offer_pool_limits(self.policy), [])
        invalid_policy = {
            **self.policy,
            "candidate_pool_minimum": 101,
            "candidate_pool_maximum": 100,
            "result_limit": 101,
        }
        self.assertEqual(
            invalid_offer_pool_limits(invalid_policy),
            [
                "offer search policy: candidate pool minimum cannot exceed maximum",
                "offer search policy: result limit cannot exceed candidate pool maximum",
            ],
        )
        with self.assertRaisesRegex(ValueError, "offer result limit must be between 1 and 100"):
            rank_offers([self.base], self.project, self.policy, set(), limit=101, today=self.today)
        with self.assertRaisesRegex(ValueError, "offer result limit must be between 1 and 100"):
            rank_offers([self.base], self.project, self.policy, set(), limit=0, today=self.today)

    def test_ranking_keeps_more_than_thirty_active_offers_and_returns_up_to_one_hundred(self) -> None:
        offers = [
            {
                **self.base,
                "id": f"offer-{index}",
                "source_url": f"https://jobs.example/offers/{index}",
                "employer": f"Employeur {index}",
            }
            for index in range(101)
        ]

        result = rank_offers(offers, self.project, self.policy, set(), today=self.today)

        self.assertEqual(result["active_count"], 101)
        self.assertEqual(result["eligible_count"], 101)
        self.assertEqual(result["selected_count"], 100)
        self.assertEqual(result["active_overflow_count"], 1)
        self.assertEqual(len(result["offers"]), 100)
        self.assertTrue(result["pool_complete"])
        self.assertIn("100 restituées au maximum", " ".join(result["warnings"]))

    def test_priority_sectors_must_have_declared_source_coverage(self) -> None:
        self.assertEqual(missing_priority_sector_coverage(self.project, self.policy), [])
        incomplete_policy = {**self.policy, "priority_sector_coverage": {"luxe": ["careers.lvmh.com"]}}
        errors = missing_priority_sector_coverage(self.project, incomplete_policy)
        self.assertTrue(any("banque-et-assurance" in error for error in errors))

    def test_priority_functional_domains_must_have_query_families(self) -> None:
        self.assertEqual(missing_priority_functional_coverage(self.project, self.policy), [])
        incomplete_policy = {**self.policy, "functional_query_families": {}}
        errors = missing_priority_functional_coverage(self.project, incomplete_policy)
        self.assertEqual(
            errors,
            [
                "offer search policy: missing query family for priority functional domain conseil-et-relation-client",
                "offer search policy: missing query family for priority functional domain commerce-et-vente",
                "offer search policy: missing query family for priority functional domain gestion-administrative",
                "offer search policy: missing query family for priority functional domain gestion-et-coordination-de-projets",
            ],
        )

    def test_regional_source_audit_is_declared_and_categorized(self) -> None:
        self.assertEqual(invalid_offer_source_audit(self.policy, self.source_audit), [])

        undeclared_policy = {
            **self.policy,
            "source_domains": [
                domain for domain in self.policy["source_domains"] if domain != "emploi.cdiscount.com"
            ],
        }
        self.assertEqual(
            invalid_offer_source_audit(undeclared_policy, self.source_audit),
            ["offer source audit: domains missing from offer search policy: emploi.cdiscount.com"],
        )

        miscategorizated_policy = {
            **self.policy,
            "source_strategy": {
                **self.policy["source_strategy"],
                "specialized_domains": [
                    domain
                    for domain in self.policy["source_strategy"]["specialized_domains"]
                    if domain != "emploi-territorial.fr"
                ],
            },
        }
        self.assertIn(
            "offer source audit: specialized portal not categorized as specialized: emploi-territorial.fr",
            invalid_offer_source_audit(miscategorizated_policy, self.source_audit),
        )

    def test_functional_domain_aliases_respect_the_validated_priority_order(self) -> None:
        result = score_offer(self.base, self.project, self.policy, set(), self.today)
        functional_reasons = [reason for reason in result["reasons"] if reason.startswith("activité prioritaire")]
        self.assertEqual(functional_reasons, ["activité prioritaire : conseil et relation client"])

    def test_sector_labels_do_not_inflate_functional_domain_score(self) -> None:
        data_offer = {
            **self.base,
            "title": "Directeur Data",
            "summary": "Pilotage de la gouvernance des données et des plateformes analytiques.",
            "industry_sector_ids": ["commerce-et-distribution"],
            "sector_labels": ["commerce et distribution"],
            "functional_domains": ["data"],
            "required_skills": ["SQL", "Power BI", "Snowflake"],
            "preferred_skills": [],
        }

        result = score_offer(data_offer, self.project, self.policy, set(), self.today)

        self.assertIn("secteur acceptable : commerce et distribution", result["reasons"])
        self.assertFalse(any(reason.startswith("activité prioritaire") for reason in result["reasons"]))
        self.assertIn("domaine fonctionnel peu explicite", result["gaps"])

    def test_specialist_data_profile_is_excluded_with_explainable_classification(self) -> None:
        offer = {
            **self.base,
            "title": "Directeur Data F/H",
            "summary": "Diriger la fonction Data, sa gouvernance et ses équipes techniques.",
            "required_skills": ["SQL", "Power BI", "Snowflake"],
            "preferred_skills": ["transformation d'une fonction Data"],
        }

        result = score_offer(offer, self.project, self.policy, set(), self.today)

        self.assertFalse(result["eligible"])
        self.assertIn("famille de profil exclue : profil spécialiste Data", result["hard_constraint_failures"])
        self.assertEqual(result["recommendation_band"], "excluded")
        self.assertEqual(result["profile_family_matches"][0]["id"], "specialist-data")
        self.assertEqual(result["profile_family_matches"][0]["confidence"], "high")
        self.assertIn("directeur data", result["profile_family_matches"][0]["title_markers"])

    def test_single_data_tool_does_not_exclude_a_generalist_project_role(self) -> None:
        offer = {
            **self.base,
            "title": "Chef de projet expérience client",
            "summary": "Piloter des projets et produire des tableaux de bord pour le service client.",
            "required_skills": ["Power BI"],
            "preferred_skills": [],
        }

        result = score_offer(offer, self.project, self.policy, set(), self.today)

        self.assertTrue(result["eligible"])
        self.assertEqual(result["profile_family_matches"], [])

    def test_profile_markers_are_matched_as_complete_terms(self) -> None:
        offer = {
            **self.base,
            "title": "Responsable gouvernance des données clients",
            "summary": "Organiser la gouvernance des données et les tableaux de bord clients.",
            "required_skills": ["MySQL", "Power BI"],
            "preferred_skills": [],
        }

        result = score_offer(offer, self.project, self.policy, set(), self.today)

        self.assertTrue(result["eligible"])
        self.assertEqual(result["profile_family_matches"], [])

    def test_ranked_report_records_all_consulted_source_origins(self) -> None:
        result = rank_offers(
            [self.base],
            self.project,
            self.policy,
            set(),
            today=self.today,
            visited_sources=["https://careers.example/jobs?q=bordeaux", "specialist.example"],
        )
        self.assertEqual(
            result["visited_sources"],
            ["https://careers.example", "https://specialist.example", "https://jobs.example"],
        )
        self.assertIsNone(source_origin("javascript:alert(1)"))


if __name__ == "__main__":
    unittest.main()
