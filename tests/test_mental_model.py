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
        self.assertEqual(summary["concept_count"], 21)
        self.assertGreaterEqual(summary["relation_count"], 30)
        self.assertEqual(summary["invariant_count"], 7)

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
        self.assertGreaterEqual(impact["relation_count"], 3)

    def test_unknown_concept_has_no_impact_report(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown concept"):
            model_impact(self.model, "unknown")


if __name__ == "__main__":
    unittest.main()
