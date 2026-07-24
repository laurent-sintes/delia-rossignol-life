from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.core import load_json
from delia_life.offer_search import score_offer


class OfferSemanticRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project = load_json(ROOT / "private" / "career-project" / "delia-next-role-2026.json")
        cls.policy = load_json(ROOT / "config" / "offer-search.json")
        cls.corpus = load_json(ROOT / "tests" / "fixtures" / "offer-semantic-regressions.json")
        cls.base_offer = {
            "id": "golden-offer",
            "title": "Responsable relation client luxe",
            "employer": "Maison Exemple",
            "source_url": "https://jobs.example/offers/golden",
            "source_site": "jobs.example",
            "source_kind": "direct_employer",
            "verification_status": "active",
            "last_verified_at": "2026-07-19T09:00:00+02:00",
            "published_at": "2026-07-18",
            "contract_type": "CDI",
            "location_label": "Bordeaux",
            "summary": "Relation client, coordination et administration dans le luxe.",
            "required_skills": ["relation client", "administration"],
            "preferred_skills": ["coordination"],
            "full_time": True,
            "conditions": {},
        }

    def test_golden_semantic_and_prerequisite_cases(self) -> None:
        for case in self.corpus["cases"]:
            with self.subTest(case=case["id"]):
                context = self._context(case.get("context", {}))
                assessment = score_offer(
                    {**self.base_offer, **case["offer"]},
                    self.project,
                    self.policy,
                    set(),
                    date(2026, 7, 19),
                    **context,
                )
                expected = case["expected"]
                self.assertEqual(assessment["eligible"], expected["eligible"])
                if "recommendation_band" in expected:
                    self.assertEqual(
                        assessment["recommendation_band"],
                        expected["recommendation_band"],
                    )
                if marker := expected.get("failure_contains"):
                    self.assertIn(marker, " ".join(assessment["hard_constraint_failures"]))
                if marker := expected.get("application_barrier_contains"):
                    self.assertIn(marker, " ".join(assessment["application_barriers"]))
                if method := expected.get("matching_method"):
                    self.assertEqual(assessment["matching_method"], method)
                if match_type := expected.get("semantic_effective_match"):
                    self.assertEqual(
                        assessment["semantic_matches"][0]["effective_match_type"],
                        match_type,
                    )

    @staticmethod
    def _context(raw: dict[str, Any]) -> dict[str, Any]:
        context = dict(raw)
        for key in ("complete_profile_dimensions", "absent_sector_experience_ids"):
            if key in context:
                context[key] = set(context[key])
        if "absent_certifications" in context:
            context["absent_certifications"] = {
                identifier: set(evidence_ids)
                for identifier, evidence_ids in context["absent_certifications"].items()
            }
        if "knowledge_evidence_catalog" in context:
            context["knowledge_evidence_catalog"] = {
                identifier: frozenset(fields)
                for identifier, fields in context["knowledge_evidence_catalog"].items()
            }
        return context


if __name__ == "__main__":
    unittest.main()
