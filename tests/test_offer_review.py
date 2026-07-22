from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.core import load_json
from delia_life.offer_review import apply_offer_semantic_reviews
from delia_life.storage import remove_tree


class OfferReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / "tests" / ".tmp" / "offer-review"
        remove_tree(self.root, ignore_errors=True)
        self.offers = self.root / "offers"
        self.offers.mkdir(parents=True)
        self.offer_path = self.offers / "offer-1.json"
        self.offer_path.write_text(
            json.dumps(
                {
                    "id": "offer-1",
                    "summary": "Résumé automatique",
                    "extraction": {
                        "method": "deterministic-html",
                        "extractor_version": 1,
                        "review_status": "required",
                        "ambiguous_fields": ["summary", "prerequisites"],
                        "source_archive_path": "archive.html",
                        "source_sha256": "a" * 64,
                    },
                }
            ),
            encoding="utf-8",
        )
        self.review_path = self.root / "review.json"
        self.review_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "reviewed_at": "2026-07-22T20:20:00+02:00",
                    "review_method": "LLM semantic review of archived employer evidence",
                    "reviews": [
                        {
                            "offer_id": "offer-1",
                            "updates": {"summary": "Résumé validé", "prerequisites": []},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        remove_tree(self.root, ignore_errors=True)

    def test_apply_offer_semantic_reviews_marks_traceable_completion(self) -> None:
        result = apply_offer_semantic_reviews(self.offers, self.review_path)

        reviewed = load_json(self.offer_path)
        self.assertEqual(result["reviewed_count"], 1)
        self.assertEqual(reviewed["summary"], "Résumé validé")
        self.assertEqual(reviewed["extraction"]["review_status"], "completed")
        self.assertEqual(reviewed["extraction"]["ambiguous_fields"], [])
        self.assertEqual(
            reviewed["extraction"]["review_method"],
            "LLM semantic review of archived employer evidence",
        )


if __name__ == "__main__":
    unittest.main()
