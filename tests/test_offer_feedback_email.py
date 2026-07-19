from __future__ import annotations

import json
import sys
import unittest
import uuid
from email import policy
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
TEST_TMP = ROOT / ".test-tmp"
TEST_TMP.mkdir(exist_ok=True)

from delia_life.offer_feedback_email import prepare_offer_feedback_email
from delia_life.storage import remove_tree


class OfferFeedbackEmailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = TEST_TMP / f"{self._testMethodName}-{uuid.uuid4().hex}"
        self.work.mkdir(parents=True)

    def tearDown(self) -> None:
        remove_tree(self.work, ignore_errors=True)

    def test_prepares_an_email_with_site_link_and_cv_attachment(self) -> None:
        report = {
            "offers": [
                {
                    "id": "offer-1",
                    "title": "Responsable boutique",
                    "employer": "Maison Exemple",
                    "contract_type": "CDI",
                    "location_label": "Bordeaux",
                    "source_url": "https://jobs.example/offers/1",
                    "assessment": {"score": 91, "reasons": ["secteur très recherché : luxe"]},
                }
            ]
        }
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")
        result = prepare_offer_feedback_email(
            report,
            "delia@example.test",
            "https://laurent-sintes.github.io/delia-rossignol-life/",
                cv,
                self.work / "draft",
                offer_ids=["offer-1"],
        )
        self.assertEqual(result["status"], "draft_prepared")
        message = BytesParser(policy=policy.default).parsebytes((self.work / "draft" / "offer-selection.eml").read_bytes())
        self.assertEqual(message["To"], "delia@example.test")
        self.assertEqual(message["Subject"], "Sélection de 1 offres — ton avis")
        draft_text = (self.work / "draft" / "offer-selection.txt").read_text(encoding="utf-8")
        self.assertIn("laurent-sintes.github.io", draft_text)
        self.assertNotIn("score", draft_text)
        self.assertEqual([attachment.get_filename() for attachment in message.iter_attachments()], ["cv.pdf"])
        manifest = json.loads((self.work / "draft" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["send_authorization"], "required")

    def test_rejects_invalid_recipient(self) -> None:
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")
        with self.assertRaises(ValueError):
            prepare_offer_feedback_email({"offers": [{"id": "x"}]}, "invalid", "https://example.test", cv, self.work / "draft")


if __name__ == "__main__":
    unittest.main()
