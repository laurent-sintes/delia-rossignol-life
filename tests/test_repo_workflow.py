from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.repo_workflow import (
    assert_publish_ready,
    git_snapshot,
    load_repository_config,
    review_content,
    review_operational,
    start_preview,
)


class RepositoryWorkflowTests(unittest.TestCase):
    def test_current_repository_snapshot_is_structured(self) -> None:
        config = load_repository_config(ROOT)
        self.assertEqual(config["ci_workflow"], "pages.yml")
        snapshot = git_snapshot(ROOT, config["expected_remote"], config["publish_branch"])
        self.assertTrue(snapshot["branch"])
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

    def test_preview_start_reuses_or_rejects_existing_runtime_state(self) -> None:
        running = {"running": True, "host": "127.0.0.1", "port": 8000, "url": "http://127.0.0.1:8000/"}
        with patch("delia_life.repo_workflow.preview_status", return_value=running):
            result = start_preview(ROOT, ROOT / "_site", "127.0.0.1", 8000)
        self.assertTrue(result["reused"])

        with (
            patch("delia_life.repo_workflow.preview_status", return_value={"running": False}),
            patch("delia_life.repo_workflow._port_is_free", return_value=False),
            self.assertRaisesRegex(ValueError, "already in use"),
        ):
            start_preview(ROOT, ROOT / "_site", "127.0.0.1", 8001)

    def test_review_content_orchestrates_quality_gates_before_preview(self) -> None:
        successful_process = SimpleNamespace(returncode=0)
        preview = {"running": True, "url": "http://127.0.0.1:8000/"}
        snapshot = {"branch": "main"}
        cv_document = {"id": "standard-cv", "output": "cv.pdf"}
        with (
            patch(
                "delia_life.repo_workflow.build_documents",
                return_value={"ok": True, "documents": [cv_document]},
            ) as documents,
            patch("delia_life.repo_workflow.subprocess.run", return_value=successful_process) as run,
            patch("delia_life.repo_workflow.check_documents", return_value={"ok": True, "errors": []}),
            patch("delia_life.repo_workflow.audit_site", return_value={"ok": True}),
            patch("delia_life.repo_workflow.build_site", return_value={"pages": ["index.html"]}) as site,
            patch("delia_life.repo_workflow.start_preview", return_value=preview),
            patch(
                "delia_life.repo_workflow.load_repository_config",
                return_value={"expected_remote": "https://example.com/repo.git", "publish_branch": "main"},
            ),
            patch("delia_life.repo_workflow.git_snapshot", return_value=snapshot),
        ):
            result = review_content(ROOT, ROOT / "_site", "127.0.0.1", 8000)
        documents.assert_called_once_with(ROOT)
        site.assert_called_once_with(ROOT, ROOT / "_site", cv_document=cv_document)
        self.assertEqual(run.call_count, 6)
        self.assertEqual(result["lint"], "passed")
        self.assertEqual(result["typing"], "passed")
        self.assertEqual(result["coverage"], "passed")
        self.assertEqual(result["preview"], preview)
        self.assertEqual(result["git"], snapshot)

    def test_review_content_stops_on_failed_tests(self) -> None:
        successful_process = SimpleNamespace(returncode=0)
        failed_process = SimpleNamespace(returncode=1)
        with (
            patch("delia_life.repo_workflow.build_documents", return_value={"ok": True}),
            patch(
                "delia_life.repo_workflow.subprocess.run",
                side_effect=[successful_process, successful_process, successful_process, failed_process],
            ),
            self.assertRaisesRegex(ValueError, "tests failed"),
        ):
            review_content(ROOT, ROOT / "_site", "127.0.0.1", 8000)

    def test_review_operational_skips_documents_and_site_build(self) -> None:
        successful_process = SimpleNamespace(returncode=0)
        snapshot = {"branch": "main"}
        with (
            patch("delia_life.repo_workflow.subprocess.run", return_value=successful_process) as run,
            patch(
                "delia_life.repo_workflow.load_repository_config",
                return_value={"expected_remote": "https://example.com/repo.git", "publish_branch": "main"},
            ),
            patch("delia_life.repo_workflow.git_snapshot", return_value=snapshot),
            patch("delia_life.repo_workflow.build_documents") as documents,
            patch("delia_life.repo_workflow.build_site") as site,
        ):
            result = review_operational(ROOT)
        self.assertEqual(run.call_count, 6)
        documents.assert_not_called()
        site.assert_not_called()
        self.assertEqual(result["validation"], "passed")
        self.assertEqual(result["git"], snapshot)


if __name__ == "__main__":
    unittest.main()
