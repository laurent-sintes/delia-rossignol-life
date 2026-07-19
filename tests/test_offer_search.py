from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.core import load_json
from delia_life.offer_search import canonical_offer_url, offer_identity, rank_offers, score_offer
from delia_life.project_validation import missing_priority_sector_coverage


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


if __name__ == "__main__":
    unittest.main()
