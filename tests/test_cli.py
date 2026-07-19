from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.cli import build_parser, main


class CliTests(unittest.TestCase):
    def test_parser_exposes_all_operational_commands(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        for command in [
            "check",
            "review-batch",
            "slurp-site",
            "build-documents",
            "check-documents",
            "rank-offers",
            "prepare-offer-feedback-email",
            "build-site",
            "model-impact",
        ]:
            self.assertIn(command, help_text)
        parsed = parser.parse_args(["slurp-site", "https://example.com", "--output", "archive", "--max-bytes", "4096"])
        self.assertEqual(parsed.max_bytes, 4096)
        ranked = parser.parse_args(["rank-offers", "data/offers/2026-07-19", "data/offers/2026-07-20"])
        self.assertEqual(ranked.offers, [Path("data/offers/2026-07-19"), Path("data/offers/2026-07-20")])
        feedback = parser.parse_args(["prepare-offer-feedback-email", "report.json", "--recipient", "delia@example.test", "--site-url", "https://example.test", "--output", "draft"])
        self.assertEqual(feedback.limit, 50)

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


if __name__ == "__main__":
    unittest.main()
