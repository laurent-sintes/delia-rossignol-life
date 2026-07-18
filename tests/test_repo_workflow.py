from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.repo_workflow import assert_publish_ready, git_snapshot, load_repository_config


class RepositoryWorkflowTests(unittest.TestCase):
    def test_current_repository_snapshot_is_structured(self) -> None:
        config = load_repository_config(ROOT)
        snapshot = git_snapshot(ROOT, config["expected_remote"], config["publish_branch"])
        self.assertEqual(snapshot["branch"], "main")
        self.assertIn("is_clean", snapshot)
        self.assertIn("changes", snapshot)

    def test_publish_preflight_accepts_safe_snapshot(self) -> None:
        snapshot = {
            "has_commits": True,
            "is_clean": True,
            "origin": "https://github.com/laurent-sintes/delia-rossignol-life.git",
            "origin_matches": True,
            "on_publish_branch": True,
            "publish_branch": "main",
            "behind": 0,
        }
        assert_publish_ready(snapshot)

    def test_publish_preflight_rejects_dirty_or_wrong_remote(self) -> None:
        snapshot = {
            "has_commits": True,
            "is_clean": False,
            "origin": "https://github.com/example/wrong.git",
            "origin_matches": False,
            "on_publish_branch": True,
            "publish_branch": "main",
            "behind": 0,
        }
        with self.assertRaisesRegex(ValueError, "working tree is not clean"):
            assert_publish_ready(snapshot)


if __name__ == "__main__":
    unittest.main()
