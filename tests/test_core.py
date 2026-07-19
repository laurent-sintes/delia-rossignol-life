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
from delia_life.application_plan import plan_personal_response
from delia_life.ingestion import (
    apply_proposal,
    create_file_manifest,
    find_unresolved_duplicate_keys,
    migrate_career_project_entity,
    transition_proposal,
)
from delia_life.review_batch import create_review_batch, review_batch
from delia_life.experience import missing_experience_missions, missing_experience_responsibilities
from delia_life.recommendation import match_offer, rank_templates
from delia_life.schema import validate
from delia_life.tracking import append_event
from delia_life.website import LinkParser, _fetch_url, normalize_url, same_origin


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

    def test_replacement_proposal_requires_the_provenance_it_supersedes(self) -> None:
        original = {
            "id": "proposal-original", "source": {"id": "src-1", "locator": "source#1", "evidence": "original"},
            "target": {"entity_type": "experience", "entity_id": "example", "field": "chronology"},
            "classification": "fact", "confidence": 1.0, "proposed_value": {"start": "2006-11"}, "status": "pending", "history": [],
        }
        accepted = transition_proposal(original, "accept", "reviewer")
        apply_proposal(accepted, self.work)
        replacement = {
            **original, "id": "proposal-replacement", "source": {"id": "src-2", "locator": "source#2", "evidence": "replacement"},
            "proposed_value": {"start": "2006-11", "end": "2008-09"}, "replaces_proposal_id": "proposal-original",
        }
        updated, entity = apply_proposal(transition_proposal(replacement, "accept", "reviewer"), self.work)
        self.assertEqual(entity["fields"]["chronology"]["value"]["end"], "2008-09")
        self.assertEqual(len(entity["fields"]["chronology"]["provenance"]), 2)
        self.assertIn("application", updated)

    def test_replacement_chain_is_not_reported_as_an_unresolved_duplicate(self) -> None:
        base = {
            "id": "proposal-base", "target": {"entity_type": "experience", "entity_id": "example", "field": "chronology"},
        }
        replacement = {**base, "id": "proposal-replacement", "replaces_proposal_id": "proposal-base"}
        self.assertEqual(find_unresolved_duplicate_keys([base, replacement]), [])
        unrelated = {**base, "id": "proposal-unrelated"}
        self.assertEqual(find_unresolved_duplicate_keys([base, unrelated]), [("experience", "example", "chronology")])

    def test_unreviewed_proposal_cannot_be_applied(self) -> None:
        with self.assertRaises(ValueError):
            apply_proposal({"status": "pending"}, self.work)

    def test_review_batch_keeps_evidence_in_queue_and_applies_only_after_acceptance(self) -> None:
        queue = self.work / "queue"
        proposal = {
            "id": "proposal-batch-1",
            "source": {"id": "source-1", "locator": "source#line=1", "evidence": "preuve"},
            "target": {"entity_type": "skill", "entity_id": "example", "field": "label"},
            "classification": "fact",
            "confidence": 1.0,
            "proposed_value": "Conseil",
            "status": "pending",
            "history": [],
        }
        from delia_life.core import write_json

        write_json(queue / "proposal-batch-1.json", proposal)
        batch_path = self.work / "batches" / "lot-1.json"
        batch = create_review_batch({"id": "lot-1", "proposal_ids": ["proposal-batch-1"]}, queue, batch_path)
        self.assertEqual(batch["status"], "pending")
        result = review_batch(batch_path, queue, self.work / "knowledge", "accept", "reviewer", apply=True)
        self.assertEqual(result["batch"]["status"], "accepted")
        self.assertEqual(result["applied_proposal_ids"], ["proposal-batch-1"])
        saved = json.loads((queue / "proposal-batch-1.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "accepted")
        self.assertIn("application", saved)

    def test_missing_experience_missions_are_reported_deterministically(self) -> None:
        experience_root = self.work / "experience"
        experience_root.mkdir()
        (experience_root / "with-mission.json").write_text(
            json.dumps({"id": "with-mission", "fields": {"mission": {"value": "Concevoir des projets."}}}),
            encoding="utf-8",
        )
        (experience_root / "without-mission.json").write_text(
            json.dumps({"id": "without-mission", "fields": {"title": {"value": "Rôle"}}}),
            encoding="utf-8",
        )
        self.assertEqual(
            [(path.name, experience_id) for path, experience_id in missing_experience_missions(self.work)],
            [("without-mission.json", "without-mission")],
        )

    def test_missing_experience_responsibilities_accepts_existing_embedded_shape(self) -> None:
        experience_root = self.work / "experience"
        experience_root.mkdir()
        (experience_root / "embedded.json").write_text(
            json.dumps({"id": "embedded", "fields": {"details": {"value": {"responsibilities": ["Gérer"]}}}}),
            encoding="utf-8",
        )
        (experience_root / "missing.json").write_text(
            json.dumps({"id": "missing", "fields": {"responsibilities": {"value": []}}}),
            encoding="utf-8",
        )
        self.assertEqual(
            [(path.name, experience_id) for path, experience_id in missing_experience_responsibilities(self.work)],
            [("missing.json", "missing")],
        )

    def test_generic_career_project_migration_is_schema_compatible_and_lossless(self) -> None:
        entity = {
            "id": "next-role",
            "type": "career-project",
            "fields": {
                "targets": {
                    "value": {
                        "industry_sectors": {
                            "priority": ["Luxe"],
                            "acceptable": ["Bien-être"],
                            "excluded": ["immobilier"],
                        }
                    },
                    "provenance": [{"proposal_id": "targets-1"}],
                },
                "availability": {
                    "value": "2026-09-01",
                    "provenance": [{"proposal_id": "availability-1"}],
                },
                "contract_preferences": {
                    "value": {"excluded": ["freelance"]},
                    "provenance": [{"proposal_id": "contracts-1"}],
                },
            },
        }
        criterion = {
            "id": "alternating-week",
            "fields": {
                "details": {
                    "value": {
                        "dimension": "schedule",
                        "operator": "custom",
                        "value": "compatible hours",
                        "priority": 5,
                        "hard_constraint": True,
                    },
                    "provenance": [{"proposal_id": "schedule-1"}],
                }
            },
        }
        migrated = migrate_career_project_entity(entity, "delia-rossignol", criterion)
        schema = json.loads((ROOT / "schemas" / "career-project.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(validate(migrated, schema), [])
        self.assertEqual(migrated["targets"]["industry_sector_ids"], ["luxe", "bien-etre"])
        self.assertEqual(migrated["availability"], "2026-09-01")
        self.assertEqual(migrated["fields"], entity["fields"])
        self.assertTrue(any(item["id"] == "alternating-week" for item in migrated["criteria"]))

    def test_match_offer_is_explainable(self) -> None:
        result = match_offer(
            {"required_skills": ["Python", "Gestion"], "preferred_skills": ["Anglais"]},
            {"skills": ["python", "anglais"]},
        )
        self.assertEqual(result["score"], 62.5)
        self.assertEqual(result["missing_required"], ["gestion"])

    def test_personal_response_plan_selects_validated_evidence_with_sources(self) -> None:
        knowledge = self.work / "knowledge"
        from delia_life.core import write_json

        write_json(knowledge / "experience" / "retail.json", {"id": "retail", "fields": {"mission": {"value": "Développer la relation client en boutique.", "provenance": [{"source_id": "src-retail"}]}, "responsibilities": {"value": ["Conseiller une clientèle internationale"], "provenance": [{"source_id": "src-retail"}]}}})
        write_json(knowledge / "professional-posture" / "delia-rossignol.json", {"id": "delia-rossignol", "fields": {"site_claims": {"value": ["Étudier le besoin avant de proposer une solution."], "provenance": [{"source_id": "src-posture"}]}}})
        plan = plan_personal_response({"id": "offer-1", "title": "Conseillère clientèle", "employer": "Maison", "required_skills": ["relation client"], "preferred_skills": []}, knowledge)
        self.assertEqual(plan["method"], "personal-response-plan-v1")
        self.assertEqual(plan["experience_evidence"][0]["experience_id"], "retail")
        self.assertEqual(plan["experience_evidence"][0]["source_ids"], ["src-retail"])
        self.assertEqual(plan["professional_posture"][0]["source_ids"], ["src-posture"])

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

    def test_career_project_schema_structures_hard_constraints(self) -> None:
        schema = json.loads((ROOT / "schemas" / "career-project.schema.json").read_text(encoding="utf-8"))
        project = {
            "id": "career-project-1",
            "person_id": "delia-rossignol",
            "status": "draft",
            "targets": {"industry_sector_ids": [], "job_role_ids": [], "location_ids": []},
            "criteria": [
                {
                    "id": "criterion-1",
                    "dimension": "work_mode",
                    "operator": "in",
                    "value": ["onsite", "hybrid"],
                    "priority": 5,
                    "hard_constraint": True,
                }
            ],
        }
        self.assertEqual(validate(project, schema), [])
        project["criteria"][0]["priority"] = 0
        self.assertIn("$.criteria[0].priority: value is below minimum", validate(project, schema))

    def test_standard_cv_template_has_validated_rendering_rules(self) -> None:
        schema = json.loads((ROOT / "schemas" / "template.schema.json").read_text(encoding="utf-8"))
        template = json.loads(
            (ROOT / "templates" / "cv" / "ats-classic" / "template.json").read_text(encoding="utf-8")
        )
        self.assertEqual(validate(template, schema), [])
        self.assertTrue(template["ats_compatible"])
        self.assertEqual(template["rendering"]["engine"], "standard-single-column-v1")
        self.assertTrue(template["content_rules"]["require_validated_facts"])
        self.assertIn("date_of_birth", template["content_rules"]["forbidden_fields"])

    def test_website_url_rules_and_asset_discovery(self) -> None:
        self.assertEqual(normalize_url("HTTPS://Example.com?a=1&utm_source=x#top"), "https://example.com/?a=1")
        self.assertEqual(
            normalize_url("https://example.com/mes-réalisations"),
            "https://example.com/mes-r%C3%A9alisations",
        )
        self.assertEqual(
            normalize_url("https://example.com/mes-r%C3%A9alisations"),
            "https://example.com/mes-r%C3%A9alisations",
        )
        self.assertTrue(same_origin("https://example.com/image.png", "https://example.com/"))
        self.assertFalse(same_origin("https://cdn.example.com/image.png", "https://example.com/"))
        parser = LinkParser()
        parser.feed('<a href="/about">A</a><img src="/logo.png"><script src="/track.js"></script>')
        self.assertEqual(parser.links, ["/about", "/logo.png"])

    def test_website_fetch_retries_once_then_returns_traceable_error(self) -> None:
        from unittest.mock import patch
        import urllib.error

        with patch("delia_life.website.urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            result = _fetch_url("https://example.com/", "test", 1, 1, 0)
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["error"], "<urlopen error offline>")


if __name__ == "__main__":
    unittest.main()
