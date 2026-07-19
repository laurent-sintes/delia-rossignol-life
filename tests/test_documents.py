from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from tempfile import gettempdir

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
TEST_TMP = Path(gettempdir()) / "delia-rossignol-life-tests"
TEST_TMP.mkdir(exist_ok=True)

from delia_life.core import load_json
from delia_life.cv_composer import compose_standard_cv
from delia_life.document_builder import build_documents, build_standard_cv, check_documents
from delia_life.storage import remove_tree


class DocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = TEST_TMP / f"{self._testMethodName}-{uuid.uuid4().hex}"
        self.work.mkdir(parents=True)

    def tearDown(self) -> None:
        if self.work.exists():
            remove_tree(self.work, ignore_errors=True)

    def test_standard_cv_is_reproducible_a4_and_complete(self) -> None:
        first = self.work / "first.pdf"
        second = self.work / "second.pdf"
        first_result = build_standard_cv(ROOT, first)
        second_result = build_standard_cv(ROOT, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(first_result["sha256"], second_result["sha256"])

        reader = PdfReader(str(first))
        self.assertEqual(len(reader.pages), 2)
        for page in reader.pages:
            self.assertAlmostEqual(float(page.mediabox.width), 595.2756, places=2)
            self.assertAlmostEqual(float(page.mediabox.height), 841.8898, places=2)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("deliarossignol@gmail.com", text)
        self.assertIn("06 20 67 40 52", text)
        self.assertIn("construire ensemble une solution concrète", text)
        self.assertNotIn("41 ans", text)
        self.assertNotIn("2 enfants", text)

    def test_published_standard_cv_is_current(self) -> None:
        result = check_documents(ROOT)
        self.assertTrue(result["ok"], result["errors"])

    def test_document_build_publishes_the_same_atomic_artifact(self) -> None:
        result = build_documents(ROOT, self.work / "output", self.work / "public")
        document = result["documents"][0]
        output = Path(document["output"])
        public = Path(document["public_output"])
        self.assertEqual(output.read_bytes(), public.read_bytes())
        self.assertEqual(document["sha256"], __import__("hashlib").sha256(output.read_bytes()).hexdigest())

    def test_cv_composition_is_traceable_and_derives_periods(self) -> None:
        template = load_json(ROOT / "templates" / "cv" / "signature-editorial" / "template.json")
        strategy = load_json(ROOT / "data" / "style" / "cv-standard.json")
        view = compose_standard_cv(ROOT, template, strategy)
        self.assertGreater(len(view.source_ids), 5)
        self.assertEqual(view.recent_experiences[0].period, "01/2024 - 07/2026")
        self.assertEqual(view.complementary_experiences[2].period, "11/2006 - 09/2008")
        self.assertTrue(all(experience.evidence for experience in (*view.recent_experiences, *view.complementary_experiences)))

    def test_cv_template_rules_are_enforced_by_the_composer(self) -> None:
        template = load_json(ROOT / "templates" / "cv" / "signature-editorial" / "template.json")
        strategy = load_json(ROOT / "data" / "style" / "cv-standard.json")
        strategy["profile_summary"] = "mot " * (template["content_rules"]["profile_max_words"] + 1)
        with self.assertRaisesRegex(ValueError, "profile exceeds"):
            compose_standard_cv(ROOT, template, strategy)

    def test_pdf_renderer_contains_no_delia_business_content(self) -> None:
        source = (ROOT / "src" / "delia_life" / "pdf_renderer.py").read_text(encoding="utf-8")
        for personal_value in ["BLEU ROSSIGNOL", "Raison Home", "Cuisinella", "Winner", "deliarossignol@gmail.com"]:
            self.assertNotIn(personal_value, source)


if __name__ == "__main__":
    unittest.main()
