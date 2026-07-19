from __future__ import annotations

import io
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
            "build-site",
            "model-impact",
        ]:
            self.assertIn(command, help_text)
        parsed = parser.parse_args(["slurp-site", "https://example.com", "--output", "archive", "--max-bytes", "4096"])
        self.assertEqual(parsed.max_bytes, 4096)

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
        self.assertIn('"checked_files": 145', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
