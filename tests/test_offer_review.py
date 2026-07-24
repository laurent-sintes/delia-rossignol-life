from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.core import load_json, sha256_file
from delia_life.offer_review import (
    apply_offer_semantic_reviews,
    reuse_cached_semantic_reviews,
    semantic_profile_sha256,
)
from delia_life.storage import remove_tree


class OfferReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / "tests" / ".tmp" / "offer-review"
        remove_tree(self.root, ignore_errors=True)
        self.offers = self.root / "offers"
        self.offers.mkdir(parents=True)
        self.cache = self.root / "cache"
        self.knowledge = self.root / "knowledge"
        self.knowledge.mkdir(parents=True)
        (self.knowledge / "experience.json").write_text(
            json.dumps(
                {
                    "id": "experience-client",
                    "type": "experience",
                    "fields": {"mission": {"value": "Accompagner et conseiller les clients."}},
                }
            ),
            encoding="utf-8",
        )
        self.archive = self.root / "archive.html"
        self.archive.write_text(
            "<section id='requirements'>Vous accompagnez chaque client dans son choix.</section>",
            encoding="utf-8",
        )
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
                        "source_archive_path": str(self.archive),
                        "source_sha256": sha256_file(self.archive),
                    },
                }
            ),
            encoding="utf-8",
        )
        self.review_path = self.root / "review.json"
        self.review_path.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "prompt_version": "offer-match-v5",
                    "profile_sha256": semantic_profile_sha256(self.knowledge),
                    "reviewed_at": "2026-07-22T20:20:00+02:00",
                    "review_method": "LLM semantic review of archived employer evidence",
                    "review_model": "test-semantic-model",
                    "reviews": [
                        {
                            "offer_id": "offer-1",
                            "updates": {
                                "summary": "Résumé validé",
                                "prerequisites": [],
                                "semantic_requirements": [
                                    {
                                        "id": "relation-client",
                                        "description": "Accompagner personnellement les clients",
                                        "importance": "required",
                                        "kind": "mission",
                                        "offer_evidence": {
                                            "locator": "archive.html#requirements",
                                            "excerpt": "Vous accompagnez chaque client dans son choix.",
                                        },
                                    }
                                ],
                                "semantic_matches": [
                                    {
                                        "requirement_id": "relation-client",
                                        "match_type": "transferable",
                                        "llm_confidence": "high",
                                        "profile_evidence_refs": [
                                            {
                                                "id": "experience:experience-client",
                                                "field": "mission",
                                            }
                                        ],
                                        "rationale": (
                                            "L’expérience démontre un accompagnement client transférable."
                                        ),
                                    }
                                ],
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        remove_tree(self.root, ignore_errors=True)

    def _apply(self) -> dict[str, object]:
        return apply_offer_semantic_reviews(
            self.offers,
            self.review_path,
            self.knowledge,
            ROOT / "config" / "offer-search.json",
            self.cache,
            self.root,
        )

    def test_apply_offer_semantic_reviews_marks_traceable_completion(self) -> None:
        result = self._apply()

        reviewed = load_json(self.offer_path)
        self.assertEqual(result["reviewed_count"], 1)
        self.assertEqual(reviewed["summary"], "Résumé validé")
        self.assertEqual(reviewed["extraction"]["review_status"], "completed")
        self.assertEqual(reviewed["extraction"]["review_schema_version"], 3)
        self.assertEqual(reviewed["extraction"]["review_model"], "test-semantic-model")
        self.assertEqual(reviewed["semantic_matches"][0]["match_type"], "transferable")
        self.assertTrue((self.cache / f"{reviewed['extraction']['semantic_cache_key']}.json").is_file())

    def test_semantic_review_rejects_unknown_profile_evidence_field(self) -> None:
        batch = load_json(self.review_path)
        batch["reviews"][0]["updates"]["semantic_matches"][0]["profile_evidence_refs"][0][
            "field"
        ] = "invented"
        self.review_path.write_text(json.dumps(batch), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "unknown profile evidence field"):
            self._apply()

    def test_semantic_review_requires_complete_requirement_coverage(self) -> None:
        batch = load_json(self.review_path)
        batch["reviews"][0]["updates"]["semantic_matches"] = []
        self.review_path.write_text(json.dumps(batch), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "semantic matches are missing"):
            self._apply()

    def test_semantic_review_rejects_offer_excerpt_absent_from_archive(self) -> None:
        batch = load_json(self.review_path)
        batch["reviews"][0]["updates"]["semantic_requirements"][0]["offer_evidence"][
            "excerpt"
        ] = "Texte inventé absent de l’annonce."
        self.review_path.write_text(json.dumps(batch), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "offer excerpt not found in archive"):
            self._apply()

    def test_identical_source_profile_and_prompt_reuse_cached_review(self) -> None:
        self._apply()
        reviewed = load_json(self.offer_path)
        reviewed.pop("semantic_requirements")
        reviewed.pop("semantic_matches")
        reviewed["extraction"]["review_status"] = "required"
        for key in (
            "reviewed_at",
            "review_method",
            "review_model",
            "review_prompt_version",
            "review_profile_sha256",
            "review_schema_version",
            "semantic_cache_key",
        ):
            reviewed["extraction"].pop(key, None)
        self.offer_path.write_text(json.dumps(reviewed), encoding="utf-8")

        result = reuse_cached_semantic_reviews(
            self.offers,
            self.knowledge,
            ROOT / "config" / "offer-search.json",
            self.cache,
            self.root,
        )

        reused = load_json(self.offer_path)
        self.assertEqual(result["reused_offer_ids"], ["offer-1"])
        self.assertEqual(reused["extraction"]["review_status"], "completed")
        self.assertIn("semantic_cache_reused_at", reused["extraction"])

    def test_shared_source_archive_does_not_cross_reuse_between_offers(self) -> None:
        self._apply()
        second_offer_path = self.offers / "offer-2.json"
        second_offer_path.write_text(
            json.dumps(
                {
                    "id": "offer-2",
                    "summary": "Autre annonce issue du même flux",
                    "extraction": {
                        "method": "deterministic-html",
                        "extractor_version": 1,
                        "review_status": "required",
                        "ambiguous_fields": ["summary", "prerequisites"],
                        "source_archive_path": str(self.archive),
                        "source_sha256": sha256_file(self.archive),
                    },
                }
            ),
            encoding="utf-8",
        )

        reuse_cached_semantic_reviews(
            self.offers,
            self.knowledge,
            ROOT / "config" / "offer-search.json",
            self.cache,
            self.root,
        )

        second_offer = load_json(second_offer_path)
        self.assertEqual(second_offer["extraction"]["review_status"], "required")
        self.assertNotIn("semantic_matches", second_offer)


if __name__ == "__main__":
    unittest.main()
