from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.core import load_json
from delia_life.offer_search import canonical_offer_url, offer_identity, rank_offers, score_offer, source_origin
from delia_life.project_validation import missing_priority_functional_coverage, missing_priority_sector_coverage


class OfferSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = load_json(ROOT / "private" / "career-project" / "delia-next-role-2026.json")
        self.policy = load_json(ROOT / "config" / "offer-search.json")
        self.today = date(2026, 7, 19)
        self.base = {
            "id": "offer-1",
            "title": "Responsable administration des ventes luxe",
            "employer": "Maison Exemple",
            "source_url": "https://jobs.example/offers/1?utm_source=test",
            "source_site": "jobs.example",
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
            },
        )

    def test_rank_offers_compiles_the_scoring_context_once(self) -> None:
        import delia_life.offer_search as offer_search

        original = offer_search._build_scoring_context
        with patch.object(offer_search, "_build_scoring_context", wraps=original) as build_context:
            rank_offers([self.base, {**self.base, "id": "offer-2", "source_url": "https://jobs.example/offers/2"}], self.project, self.policy, set(), today=self.today)
        build_context.assert_called_once_with(self.project, self.policy, set(), self.today)

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

    def test_incomplete_pool_and_unknown_conditions_are_explicit(self) -> None:
        offer = {**self.base, "published_at": None, "conditions": {}, "summary": "Administration dans le luxe."}
        offer.pop("contract_type")
        result = rank_offers([offer], self.project, self.policy, set(), today=self.today)
        self.assertEqual(result["eligible_count"], 1)
        self.assertTrue(any("pool incomplet" in warning for warning in result["warnings"]))
        self.assertIn("type de contrat non précisé", result["offers"][0]["assessment"]["unknowns"])

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

    def test_functional_domain_aliases_respect_the_validated_priority_order(self) -> None:
        result = score_offer(self.base, self.project, self.policy, set(), self.today)
        functional_reasons = [reason for reason in result["reasons"] if reason.startswith("activité prioritaire")]
        self.assertEqual(functional_reasons, ["activité prioritaire : conseil et relation client"])

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
