from __future__ import annotations

import argparse
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.cli import build_parser, main
from delia_life.storage import remove_tree


class CliTests(unittest.TestCase):
    def test_parser_exposes_all_operational_commands(self) -> None:
        parser = build_parser()
        command_registry = next(
            action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
        )
        self.assertEqual(
            set(command_registry.choices),
            {
                "apply-proposal",
                "build-documents",
                "build-site",
                "check",
                "check-documents",
                "crawl-site",
                "create-review-batch",
                "hash",
                "manifest",
                "match-offer",
                "migrate-career-project",
                "model-check",
                "model-impact",
                "offer-scan",
                "plan-personal-response",
                "prepare-offer-feedback-email",
                "rank-offers",
                "review",
                "review-batch",
                "select-template",
                "site-audit",
                "track-event",
            },
        )
        help_text = parser.format_help()
        for command in [
            "check",
            "review-batch",
            "crawl-site",
            "build-documents",
            "check-documents",
            "rank-offers",
            "offer-scan",
            "prepare-offer-feedback-email",
            "build-site",
            "model-impact",
        ]:
            self.assertIn(command, help_text)
        self.assertNotIn("slurp-site", help_text)
        parsed = parser.parse_args(["crawl-site", "https://example.com", "--output", "archive", "--max-bytes", "4096"])
        self.assertEqual(parsed.max_bytes, 4096)
        ranked = parser.parse_args(
            [
                "rank-offers",
                "data/offers/2026-07-19",
                "data/offers/2026-07-20",
                "--visited-source",
                "https://careers.example/jobs",
                "--require-complete-pool",
            ]
        )
        self.assertEqual(ranked.offers, [Path("data/offers/2026-07-19"), Path("data/offers/2026-07-20")])
        self.assertEqual(ranked.visited_sources, ["https://careers.example/jobs"])
        self.assertTrue(ranked.require_complete_pool)
        feedback = parser.parse_args(["prepare-offer-feedback-email", "report.json", "--recipient", "delia@example.test", "--site-url", "https://example.test", "--output", "draft"])
        self.assertEqual(feedback.limit, 100)
        self.assertEqual(feedback.bcc, "laurent.sintes74@gmail.com")
        full_scan = parser.parse_args(["offer-scan", "full"])
        self.assertEqual(full_scan.action, "full")
        self.assertEqual(full_scan.runtime_root, Path(".runtime/offer-search"))

    def test_main_returns_structured_exit_codes(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["hash", str(ROOT / "README.md")]), 0)
        self.assertRegex(stdout.getvalue().strip(), r"^[0-9a-f]{64}$")

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(main(["hash", str(ROOT / "missing-file")]), 2)
        self.assertIn("error:", stderr.getvalue())

    def test_check_command_validates_the_complete_repository(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["check", "--root", str(ROOT)]), 0)
        report = json.loads(stdout.getvalue())
        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["checked_files"], 146)

    def test_rank_offers_strict_mode_blocks_an_incomplete_pool(self) -> None:
        test_temp_root = ROOT / "tests" / ".tmp"
        test_temp_root.mkdir(exist_ok=True)
        directory = test_temp_root / "cli-strict-incomplete-pool"
        remove_tree(directory, ignore_errors=True)
        directory.mkdir()
        try:
            offer_path = directory / "offer.json"
            offer_path.write_text(
                json.dumps(
                    {
                        "id": "offer-test",
                        "title": "Gestionnaire relation client",
                        "employer": "Employeur Test",
                        "source_url": "https://jobs.example/offers/test",
                        "source_site": "jobs.example",
                        "source_kind": "direct_employer",
                        "verification_status": "active",
                        "last_verified_at": datetime.now().astimezone().isoformat(),
                        "published_at": None,
                        "contract_type": "CDI",
                        "full_time": True,
                        "location_label": "Bordeaux",
                        "summary": "Gestion administrative et relation client en équipe.",
                        "required_skills": ["relation client"],
                        "preferred_skills": [],
                        "conditions": {},
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["rank-offers", str(offer_path), "--require-complete-pool"])
        finally:
            remove_tree(directory, ignore_errors=True)

        self.assertEqual(exit_code, 3)
        report = json.loads(stdout.getvalue())
        self.assertFalse(report["pool_complete"])
        self.assertFalse(report["finalization_allowed"])


if __name__ == "__main__":
    unittest.main()
