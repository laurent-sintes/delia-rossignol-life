from __future__ import annotations

import hashlib
import json
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
TEST_TMP = ROOT / ".test-tmp"
TEST_TMP.mkdir(exist_ok=True)

from delia_life.core import sha256_file, stable_id
from delia_life.ingestion import apply_proposal, create_file_manifest, transition_proposal
from delia_life.recommendation import match_offer, rank_templates
from delia_life.schema import validate
from delia_life.tracking import append_event
from delia_life.website import LinkParser, normalize_url, same_origin


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = TEST_TMP / self._testMethodName
        if self.work.exists():
            shutil.rmtree(self.work)
        self.work.mkdir(parents=True)

    def tearDown(self) -> None:
        if self.work.exists():
            shutil.rmtree(self.work)

    def test_hash_and_manifest_are_stable(self) -> None:
        path = ROOT / "README.md"
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(sha256_file(path), expected)
        first = create_file_manifest(path, "document")
        second = create_file_manifest(path, "document")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["sha256"], second["sha256"])

    def test_stable_id_normalizes_case_and_spaces(self) -> None:
        self.assertEqual(stable_id("SRC", " Délia "), stable_id("src", "délia"))

    def test_review_then_apply_preserves_provenance(self) -> None:
        proposal = {
            "id": "proposal-1",
            "source": {"id": "source-1", "locator": "cv.txt#line=1", "evidence": "Titre"},
            "target": {"entity_type": "experience", "entity_id": "example", "field": "title"},
            "classification": "fact",
            "confidence": 1.0,
            "proposed_value": "Fondatrice",
            "status": "pending",
            "history": [],
        }
        accepted = transition_proposal(proposal, "accept", "reviewer")
        updated, entity = apply_proposal(accepted, self.work)
        self.assertIn("application", updated)
        self.assertEqual(entity["fields"]["title"]["value"], "Fondatrice")
        self.assertEqual(entity["fields"]["title"]["provenance"][0]["source_id"], "source-1")
        saved = json.loads((self.work / "experience" / "example.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["id"], "example")

    def test_unreviewed_proposal_cannot_be_applied(self) -> None:
        with self.assertRaises(ValueError):
            apply_proposal({"status": "pending"}, self.work)

    def test_match_offer_is_explainable(self) -> None:
        result = match_offer(
            {"required_skills": ["Python", "Gestion"], "preferred_skills": ["Anglais"]},
            {"skills": ["python", "anglais"]},
        )
        self.assertEqual(result["score"], 62.5)
        self.assertEqual(result["missing_required"], ["gestion"])

    def test_template_ranking_is_deterministic(self) -> None:
        templates = [
            {"id": "creative", "ats_compatible": False, "sectors": ["design"]},
            {"id": "ats", "ats_compatible": True, "sectors": ["retail"]},
        ]
        ranked = rank_templates(templates, {"ats_required": True, "sectors": ["retail"]})
        self.assertEqual(ranked[0]["template_id"], "ats")
        self.assertEqual(ranked[0]["score"], 60)

    def test_tracking_does_not_mutate_details(self) -> None:
        details = {"occurred_at": "2026-07-18T12:00:00+00:00", "channel": "email"}
        result = append_event({"id": "application-1"}, "submitted", details)
        self.assertIn("occurred_at", details)
        self.assertEqual(result["events"][0]["details"], {"channel": "email"})

    def test_schema_reports_missing_property(self) -> None:
        errors = validate({}, {"type": "object", "required": ["id"]})
        self.assertEqual(errors, ["$.id: required property is missing"])

    def test_website_url_rules_and_asset_discovery(self) -> None:
        self.assertEqual(normalize_url("HTTPS://Example.com?a=1&utm_source=x#top"), "https://example.com/?a=1")
        self.assertTrue(same_origin("https://example.com/image.png", "https://example.com/"))
        self.assertFalse(same_origin("https://cdn.example.com/image.png", "https://example.com/"))
        parser = LinkParser()
        parser.feed('<a href="/about">A</a><img src="/logo.png"><script src="/track.js"></script>')
        self.assertEqual(parser.links, ["/about", "/logo.png"])


if __name__ == "__main__":
    unittest.main()
