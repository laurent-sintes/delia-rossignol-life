from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.mental_model import load_mental_model, model_impact, model_summary, validate_mental_model


class MentalModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = load_mental_model(ROOT / "model" / "model.yaml")

    def test_model_is_valid_and_has_expected_scope(self) -> None:
        summary = model_summary(self.model)
        self.assertTrue(summary["ok"], summary["errors"])
        self.assertEqual(summary["model_version"], "1.1.9")
        self.assertGreaterEqual(summary["concept_count"], 31)
        self.assertIn("professional-posture", {concept["id"] for concept in self.model["concepts"]})
        self.assertGreaterEqual(summary["relation_count"], 55)
        self.assertEqual(summary["invariant_count"], 17)

    def test_unknown_relation_endpoint_is_rejected(self) -> None:
        broken = copy.deepcopy(self.model)
        broken["relations"][0]["to"] = "missing-concept"
        errors = validate_mental_model(broken)
        self.assertTrue(any("unknown to concept" in error for error in errors))

    def test_impact_lists_incoming_and_outgoing_relations(self) -> None:
        impact = model_impact(self.model, "experience")
        self.assertIn("person", impact["neighbor_concepts"])
        self.assertIn("organization", impact["neighbor_concepts"])
        self.assertIn("skill", impact["neighbor_concepts"])
        self.assertIn("achievement", impact["neighbor_concepts"])
        self.assertIn("job-role", impact["neighbor_concepts"])
        self.assertIn("location", impact["neighbor_concepts"])
        self.assertGreaterEqual(impact["relation_count"], 7)

    def test_career_project_connects_targets_and_constraints(self) -> None:
        impact = model_impact(self.model, "career-project")
        relation_ids = {relation["id"] for relation in impact["outgoing_relations"]}
        self.assertEqual(
            relation_ids,
            {
                "career-project-targets-sector",
                "career-project-targets-job-role",
                "career-project-targets-location",
                "career-project-has-search-criterion",
            },
        )
        self.assertIn("match-assessment", impact["neighbor_concepts"])

    def test_unknown_concept_has_no_impact_report(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown concept"):
            model_impact(self.model, "unknown")


if __name__ == "__main__":
    unittest.main()
