from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
TEST_TMP = ROOT / ".test-tmp"
TEST_TMP.mkdir(exist_ok=True)

from delia_life.storage import atomic_write_bytes_group, remove_tree


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = TEST_TMP / f"{self._testMethodName}-{uuid.uuid4().hex}"
        self.work.mkdir(parents=True)

    def tearDown(self) -> None:
        remove_tree(self.work, ignore_errors=True)

    def test_binary_transaction_rolls_back_an_intermediate_failure(self) -> None:
        first = self.work / "first.txt"
        second = self.work / "second.txt"
        first.write_bytes(b"old-first")
        second.write_bytes(b"old-second")
        real_replace = os.replace
        calls = 0

        def flaky_replace(source: Path, destination: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise PermissionError("injected failure")
            real_replace(source, destination)

        with (
            patch("delia_life.storage.os.replace", side_effect=flaky_replace),
            self.assertRaisesRegex(RuntimeError, "File transaction failed"),
        ):
            atomic_write_bytes_group({first: b"new-first", second: b"new-second"})
        self.assertEqual(first.read_bytes(), b"old-first")
        self.assertEqual(second.read_bytes(), b"old-second")


if __name__ == "__main__":
    unittest.main()
