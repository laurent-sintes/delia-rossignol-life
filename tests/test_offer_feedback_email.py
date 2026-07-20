from __future__ import annotations

import json
import sys
import unittest
import uuid
from email import policy
from email.parser import BytesParser
from pathlib import Path
from tempfile import gettempdir

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
TEST_TMP = Path(gettempdir()) / "delia-rossignol-life-tests"
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
            "visited_sources": ["https://jobs.example/search", "https://careers.example/jobs"],
            "offers": [
                {
                    "id": "offer-1",
                    "title": "Responsable boutique",
                    "employer": "Maison Exemple",
                    "contract_type": "CDI",
                    "location_label": "Bordeaux",
                    "sector_labels": ["luxe"],
                    "compensation": {"minimum": 32000, "maximum": 36000, "currency": "EUR", "period": "year"},
                    "full_time": True,
                    "source_url": "https://jobs.example/offers/1",
                    "assessment": {"score": 91, "reasons": ["secteur très recherché : luxe"], "unknowns": ["rémunération non précisée", "temps plein à confirmer"]},
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
        self.assertEqual(message["Bcc"], "laurent.sintes74@gmail.com")
        self.assertEqual(message["Subject"], "Sélection de 1 offre — ton avis")
        draft_text = (self.work / "draft" / "offer-selection.txt").read_text(encoding="utf-8")
        self.assertIn("sites consultés pour cette recherche", draft_text)
        self.assertIn("- https://jobs.example", draft_text)
        self.assertIn("- https://careers.example", draft_text)
        self.assertIn("laurent-sintes.github.io", draft_text)
        self.assertIn("Secteur d’activité : luxe", draft_text)
        self.assertIn("Mission / poste : Responsable boutique", draft_text)
        self.assertIn("Salaire proposé : 32\u202f000 – 36\u202f000 € brut/an", draft_text)
        self.assertIn("Pertinence : 91/100", draft_text)
        self.assertIn("Point de vigilance : aucun point bloquant identifié", draft_text)
        self.assertNotIn("laurent.sintes74@gmail.com", draft_text)
        self.assertEqual([attachment.get_filename() for attachment in message.iter_attachments()], ["cv.pdf"])
        manifest = json.loads((self.work / "draft" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["visited_sources"], ["https://jobs.example", "https://careers.example"])
        self.assertEqual(manifest["bcc"], "laurent.sintes74@gmail.com")
        self.assertEqual(manifest["send_authorization"], "required")
        html_body = (self.work / "draft" / "offer-selection.html").read_text(encoding="utf-8")
        self.assertNotIn("laurent.sintes74@gmail.com", html_body)
        self.assertIn("careers.example", html_body)
        self.assertIn('style="color: #b85c20;"', html_body)
        self.assertIn('<li style="margin: 0 0 18px 0; padding: 0;">', html_body)

    def test_legacy_report_derives_consulted_sites_from_offer_links(self) -> None:
        report = {
            "offers": [
                {
                    "id": "offer-1",
                    "title": "Poste",
                    "employer": "Employeur",
                    "source_url": "https://jobs.example/offers/1",
                    "assessment": {},
                }
            ]
        }
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")
        prepare_offer_feedback_email(report, "delia@example.test", "https://example.test", cv, self.work / "draft")
        draft_text = (self.work / "draft" / "offer-selection.txt").read_text(encoding="utf-8")
        self.assertIn("- https://jobs.example", draft_text)

    def test_limits_a_default_email_to_fifty_ranked_offers(self) -> None:
        report = {"offers": [{"id": f"offer-{index}", "title": "Poste", "employer": "Employeur", "source_url": "https://jobs.example/offers", "assessment": {}} for index in range(55)]}
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")
        result = prepare_offer_feedback_email(report, "delia@example.test", "https://example.test", cv, self.work / "draft")
        self.assertEqual(result["offer_count"], 50)
        with self.assertRaises(ValueError):
            prepare_offer_feedback_email(report, "delia@example.test", "https://example.test", cv, self.work / "too-many", limit=51)

    def test_default_email_orders_offers_by_descending_relevance(self) -> None:
        report = {
            "offers": [
                {"id": "lower", "title": "Poste", "employer": "Employeur", "source_url": "https://jobs.example/lower", "assessment": {"score": 20}},
                {"id": "higher", "title": "Poste", "employer": "Employeur", "source_url": "https://jobs.example/higher", "assessment": {"score": 90}},
            ]
        }
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")
        result = prepare_offer_feedback_email(report, "delia@example.test", "https://example.test", cv, self.work / "draft")
        self.assertEqual(result["offer_ids"], ["higher", "lower"])

    def test_email_caps_relevance_display_to_one_hundred(self) -> None:
        report = {
            "offers": [
                {
                    "id": "over-100",
                    "title": "Poste",
                    "employer": "Employeur",
                    "source_url": "https://jobs.example/over-100",
                    "assessment": {"score": 103},
                }
            ]
        }
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")
        prepare_offer_feedback_email(report, "delia@example.test", "https://example.test", cv, self.work / "draft")
        draft_text = (self.work / "draft" / "offer-selection.txt").read_text(encoding="utf-8")
        self.assertIn("Pertinence : 100/100", draft_text)
        self.assertNotIn("Pertinence : 103/100", draft_text)

    def test_rejects_invalid_recipient(self) -> None:
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")
        with self.assertRaises(ValueError):
            prepare_offer_feedback_email({"offers": [{"id": "x"}]}, "invalid", "https://example.test", cv, self.work / "draft")

    def test_rejects_invalid_bcc(self) -> None:
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")
        with self.assertRaisesRegex(ValueError, "valid BCC"):
            prepare_offer_feedback_email(
                {"offers": [{"id": "x"}]},
                "delia@example.test",
                "https://example.test",
                cv,
                self.work / "draft",
                bcc="invalid",
            )

    def test_unsafe_offer_links_are_not_rendered_as_links(self) -> None:
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")
        report = {
            "offers": [
                {
                    "id": "offer-1",
                    "title": "Poste",
                    "employer": "Employeur",
                    "source_url": "javascript:alert(1)",
                    "assessment": {},
                }
            ]
        }
        prepare_offer_feedback_email(report, "delia@example.test", "https://example.test", cv, self.work / "draft")
        html_body = (self.work / "draft" / "offer-selection.html").read_text(encoding="utf-8")
        self.assertNotIn("href=\"javascript:", html_body)
        self.assertIn("Lien de l’annonce non disponible", html_body)


if __name__ == "__main__":
    unittest.main()
