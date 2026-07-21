from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.skill_validation import validate_skill_catalog


class SkillTests(unittest.TestCase):
    def test_catalog_and_documented_commands_are_valid(self) -> None:
        result = validate_skill_catalog(ROOT)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["skills"], 9)

    def test_skill_triggers_and_workflows_are_unambiguous(self) -> None:
        skill_root = ROOT / ".codex" / "skills"
        manage_git = (skill_root / "manage-delia-git" / "SKILL.md").read_text(encoding="utf-8")
        match_offers = (skill_root / "match-delia-offers" / "SKILL.md").read_text(encoding="utf-8")
        publish_site = (skill_root / "publish-delia-site" / "SKILL.md").read_text(encoding="utf-8")
        generate = (skill_root / "generate-delia-application" / "SKILL.md").read_text(encoding="utf-8")
        share = (skill_root / "share-delia-offer-selection" / "SKILL.md").read_text(encoding="utf-8")

        self.assertNotIn("après une modification de contenu", manage_git)
        self.assertNotIn("git push -u origin main", manage_git)
        self.assertIn("## Action `push` / `publish`", manage_git)
        self.assertIn("gh run watch <run-id> --exit-status", manage_git)
        self.assertNotIn("Attendre la validation visuelle", manage_git)
        self.assertNotIn("pour rechercher ou analyser", match_offers.casefold())
        self.assertEqual(publish_site.count("python scripts/repo_flow.py review-content"), 1)
        self.assertNotIn("python -m unittest", publish_site)
        self.assertIn("CV standard", generate)
        self.assertIn("Sites consultés", share)


if __name__ == "__main__":
    unittest.main()
