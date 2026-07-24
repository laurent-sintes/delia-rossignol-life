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
                    "assessment": {"score": 91, "reasons": ["secteur prioritaire : luxe"], "unknowns": ["rémunération non précisée", "temps plein à confirmer"]},
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

    def test_preference_alert_is_visible_in_email_vigilance(self) -> None:
        report = {
            "offers": [
                {
                    "id": "offer-1",
                    "title": "Conseillère de vente",
                    "employer": "Maison Exemple",
                    "source_url": "https://jobs.example/offers/1",
                    "assessment": {
                        "score": 82,
                        "preference_alerts": [
                            "poste de vente sans responsabilité élargie, dépriorisé dans la recherche actuelle"
                        ],
                    },
                }
            ]
        }
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")

        prepare_offer_feedback_email(
            report,
            "delia@example.test",
            "https://example.test",
            cv,
            self.work / "draft",
        )

        draft_text = (self.work / "draft" / "offer-selection.txt").read_text(encoding="utf-8")
        self.assertIn(
            "Point de vigilance : poste de vente sans responsabilité élargie",
            draft_text,
        )

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

    def test_grouped_quasi_duplicates_keep_every_publication_link(self) -> None:
        report = {
            "offers": [
                {
                    "id": "mango-latest",
                    "title": "Multifunctional Sales Associate",
                    "employer": "Mango",
                    "source_url": "https://fr.fashionjobs.com/emploi/mango/latest.html",
                    "assessment": {"score": 91, "reasons": ["forte correspondance"]},
                    "represented_offer_count": 3,
                    "similar_publications": [
                        {
                            "id": "mango-older-1",
                            "source_url": "https://fr.fashionjobs.com/emploi/mango/older-1.html",
                            "published_at": "2026-07-09",
                        },
                        {
                            "id": "mango-older-2",
                            "source_url": "https://fr.fashionjobs.com/emploi/mango/older-2.html",
                            "published_at": "2026-07-04",
                        },
                    ],
                }
            ]
        }
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")

        prepare_offer_feedback_email(
            report,
            "delia@example.test",
            "https://example.test",
            cv,
            self.work / "draft",
        )

        text_body = (self.work / "draft" / "offer-selection.txt").read_text(encoding="utf-8")
        html_body = (self.work / "draft" / "offer-selection.html").read_text(encoding="utf-8")
        for link in (
            "https://fr.fashionjobs.com/emploi/mango/latest.html",
            "https://fr.fashionjobs.com/emploi/mango/older-1.html",
            "https://fr.fashionjobs.com/emploi/mango/older-2.html",
        ):
            self.assertIn(link, text_body)
            self.assertIn(link, html_body)
        self.assertIn("2 autre(s) publication(s) très similaire(s) regroupée(s)", text_body)
        self.assertIn("Voir la publication similaire du 2026-07-09", html_body)

    def test_pending_offers_are_rendered_in_a_separate_unranked_section(self) -> None:
        report = {
            "visited_sources": ["https://fr.linkedin.com"],
            "offers": [
                {
                    "id": "ranked-offer",
                    "title": "Poste classé",
                    "employer": "Employeur",
                    "source_url": "https://jobs.example/ranked",
                    "assessment": {"score": 80},
                }
            ],
            "pending_offers": [
                {
                    "id": "hermes-charge-sav",
                    "title": "Chargé SAV H/F — Magasin de Bordeaux",
                    "employer": "Hermès",
                    "contract_type": "CDI",
                    "location_label": "Bordeaux",
                    "source_url": "https://fr.linkedin.com/jobs/view/hermes-charge-sav",
                    "verification_status": "pending",
                    "verification_reason": "page employeur exacte non vérifiée",
                }
            ],
        }
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")

        result = prepare_offer_feedback_email(
            report,
            "delia@example.test",
            "https://example.test",
            cv,
            self.work / "draft",
        )

        text_body = (self.work / "draft" / "offer-selection.txt").read_text(encoding="utf-8")
        html_body = (self.work / "draft" / "offer-selection.html").read_text(encoding="utf-8")
        self.assertIn("Offres probablement actives à revérifier", text_body)
        self.assertIn("Cela ne signifie ni qu’elles sont fermées ni qu’elles sont incompatibles", text_body)
        self.assertIn("Le motif propre à chaque offre est indiqué ci-dessous", text_body)
        self.assertIn("restent, elles, dans le classement avec un point de vigilance", text_body)
        self.assertIn("Hermès — Chargé SAV H/F — Magasin de Bordeaux", text_body)
        self.assertIn("page employeur exacte non vérifiée", text_body)
        self.assertIn('data-verification-status="pending"', html_body)
        self.assertIn("Cela ne signifie ni qu’elles sont fermées ni qu’elles sont incompatibles", html_body)
        self.assertNotIn("Pertinence : non calculée", text_body)
        self.assertEqual(result["offer_count"], 1)
        self.assertEqual(result["pending_offer_count"], 1)
        self.assertEqual(result["pending_offer_displayed_count"], 1)
        self.assertEqual(result["displayed_item_count"], 2)

    def test_excluded_offers_are_rendered_last_with_their_reasons(self) -> None:
        report = {
            "visited_sources": ["https://jobs.example"],
            "offers": [
                {
                    "id": "ranked-offer",
                    "title": "Poste classé",
                    "employer": "Employeur",
                    "source_url": "https://jobs.example/ranked",
                    "assessment": {"score": 80},
                }
            ],
            "pending_offers": [
                {
                    "id": "pending-offer",
                    "title": "Poste à revérifier",
                    "employer": "Employeur",
                    "source_url": "https://jobs.example/pending",
                    "verification_status": "pending",
                    "verification_reason": "page employeur exacte non vérifiée",
                }
            ],
            "excluded": [
                {
                    "id": "pending-offer",
                    "title": "Poste à revérifier",
                    "employer": "Employeur",
                    "verification_status": "pending",
                    "verification_reason": "page employeur exacte non vérifiée",
                },
                {
                    "id": "excluded-offer",
                    "title": "Gestionnaire assurance",
                    "employer": "Filhet-Allard",
                    "contract_type": "CDI",
                    "location_label": "Mérignac",
                    "source_url": "https://jobs.example/excluded",
                    "phase": "policy",
                    "score": 80,
                    "failures": [
                        "diplôme obligatoire non satisfait",
                        "expérience sectorielle obligatoire non satisfaite",
                    ],
                },
            ],
        }
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")

        result = prepare_offer_feedback_email(
            report,
            "delia@example.test",
            "https://example.test",
            cv,
            self.work / "draft",
        )

        text_body = (self.work / "draft" / "offer-selection.txt").read_text(encoding="utf-8")
        html_body = (self.work / "draft" / "offer-selection.html").read_text(encoding="utf-8")
        self.assertIn("Offres exclues et pourquoi", text_body)
        self.assertIn("Filhet-Allard — Gestionnaire assurance", text_body)
        self.assertIn("Pourquoi exclue : diplôme obligatoire non satisfait", text_body)
        self.assertIn("expérience sectorielle obligatoire non satisfaite", text_body)
        self.assertLess(
            text_body.index("Offres probablement actives à revérifier"),
            text_body.index("Offres exclues et pourquoi"),
        )
        self.assertLess(
            text_body.index("Offres exclues et pourquoi"),
            text_body.index("sites consultés pour cette recherche"),
        )
        self.assertIn('data-result-status="excluded"', html_body)
        self.assertEqual(result["excluded_offer_count"], 1)
        self.assertEqual(result["excluded_offer_displayed_count"], 1)
        self.assertEqual(result["excluded_offer_ids"], ["excluded-offer"])
        self.assertEqual(result["displayed_item_count"], 3)

    def test_prerequisite_constraint_is_rendered_in_red(self) -> None:
        report = {
            "offers": [
                {
                    "id": "offer-prerequisite",
                    "title": "Directrice d’agence",
                    "employer": "Employeur",
                    "source_url": "https://jobs.example/offers/prerequisite",
                    "assessment": {
                        "score": 62,
                        "prerequisite_alerts": [
                            {
                                "description": "Expérience assurantielle préalable",
                                "message": "non démontré dans les connaissances validées",
                            }
                        ],
                    },
                }
            ]
        }
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")
        prepare_offer_feedback_email(report, "delia@example.test", "https://example.test", cv, self.work / "draft")
        text_body = (self.work / "draft" / "offer-selection.txt").read_text(encoding="utf-8")
        html_body = (self.work / "draft" / "offer-selection.html").read_text(encoding="utf-8")
        self.assertIn("⚠ PRÉREQUIS : Expérience assurantielle préalable", text_body)
        self.assertIn("aucun autre point de vigilance identifié", text_body)
        self.assertIn('style="color: #b42318;"', html_body)
        self.assertIn("Expérience assurantielle préalable", html_body)

    def test_legacy_insurance_condition_is_still_rendered_in_red(self) -> None:
        report = {
            "offers": [
                {
                    "id": "legacy-offer",
                    "title": "Directrice d’agence",
                    "employer": "Employeur",
                    "source_url": "https://jobs.example/offers/legacy",
                    "conditions": {"insurance_experience_required": True},
                    "assessment": {"score": 62},
                }
            ]
        }
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")
        prepare_offer_feedback_email(report, "delia@example.test", "https://example.test", cv, self.work / "draft")
        html_body = (self.work / "draft" / "offer-selection.html").read_text(encoding="utf-8")
        self.assertIn('style="color: #b42318;"', html_body)
        self.assertIn("Expérience préalable dans le domaine assurantiel", html_body)

    def test_all_ranked_results_are_displayed_without_a_cap(self) -> None:
        report = {"offers": [{"id": f"offer-{index}", "title": "Poste", "employer": "Employeur", "source_url": "https://jobs.example/offers", "assessment": {}} for index in range(105)]}
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")
        result = prepare_offer_feedback_email(report, "delia@example.test", "https://example.test", cv, self.work / "draft")
        self.assertEqual(result["offer_count"], 105)

    def test_all_ranked_pending_and_excluded_offers_are_displayed(self) -> None:
        report = {
            "offers": [
                {
                    "id": f"ranked-{index}",
                    "title": "Poste classé",
                    "employer": "Employeur",
                    "source_url": f"https://jobs.example/ranked/{index}",
                    "assessment": {"score": 80 - index},
                }
                for index in range(12)
            ],
            "pending_offers": [
                {
                    "id": f"pending-{index}",
                    "title": "Poste à revérifier",
                    "employer": "Employeur",
                    "source_url": f"https://jobs.example/pending/{index}",
                }
                for index in range(3)
            ],
            "excluded": [
                {
                    "id": f"excluded-{index}",
                    "title": "Poste exclu",
                    "employer": "Employeur",
                    "source_url": f"https://jobs.example/excluded/{index}",
                    "failures": ["prérequis obligatoire non satisfait"],
                }
                for index in range(3)
            ],
        }
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")

        result = prepare_offer_feedback_email(
            report,
            "delia@example.test",
            "https://example.test",
            cv,
            self.work / "draft",
        )

        self.assertEqual(result["displayed_item_count"], 18)
        self.assertEqual(result["offer_count"], 12)
        self.assertEqual(result["excluded_offer_displayed_count"], 3)
        self.assertEqual(result["pending_offer_displayed_count"], 3)

    def test_large_excluded_pool_does_not_erase_ranked_sections(self) -> None:
        report = {
            "offers": [
                {
                    "id": f"ranked-{index}",
                    "title": "Poste classÃ©",
                    "employer": "Employeur",
                    "source_url": f"https://jobs.example/ranked/{index}",
                    "recommendation_band": band,
                    "assessment": {"score": 90 - index},
                }
                for index, band in enumerate(
                    ["priority", "possible", "possible", "possible", "informational"]
                )
            ],
            "excluded": [
                {
                    "id": f"excluded-{index}",
                    "title": "Poste exclu",
                    "employer": "Employeur",
                    "source_url": f"https://jobs.example/excluded/{index}",
                    "failures": ["prÃ©requis obligatoire non satisfait"],
                }
                for index in range(260)
            ],
        }
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")

        result = prepare_offer_feedback_email(
            report,
            "delia@example.test",
            "https://example.test",
            cv,
            self.work / "draft",
        )

        self.assertEqual(result["offer_count"], 5)
        self.assertEqual(result["section_counts"], {"priority": 1, "possible": 3, "informational": 1})
        self.assertEqual(result["excluded_offer_displayed_count"], 260)
        self.assertEqual(result["displayed_item_count"], 265)

    def test_incomplete_report_cannot_be_prepared_for_delivery(self) -> None:
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")

        with self.assertRaisesRegex(ValueError, "incomplete offer report"):
            prepare_offer_feedback_email(
                {"offers": [], "finalization_allowed": False},
                "delia@example.test",
                "https://example.test",
                cv,
                self.work / "draft",
            )

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

    def test_email_groups_three_sections_before_score_and_keeps_global_numbering(self) -> None:
        report = {
            "offers": [
                {
                    "id": "info-high",
                    "title": "Poste informationnel",
                    "employer": "Employeur",
                    "source_url": "https://jobs.example/info",
                    "recommendation_band": "informational",
                    "assessment": {"score": 95},
                },
                {
                    "id": "priority",
                    "title": "Poste prioritaire",
                    "employer": "Employeur",
                    "source_url": "https://jobs.example/priority",
                    "recommendation_band": "priority",
                    "assessment": {"score": 80},
                },
                {
                    "id": "possible",
                    "title": "Poste possible",
                    "employer": "Employeur",
                    "source_url": "https://jobs.example/possible",
                    "recommendation_band": "possible",
                    "assessment": {"score": 55},
                },
            ]
        }
        cv = self.work / "cv.pdf"
        cv.write_bytes(b"%PDF-1.4\nexample")
        result = prepare_offer_feedback_email(
            report,
            "delia@example.test",
            "https://example.test",
            cv,
            self.work / "draft",
            offer_ids=["info-high", "possible", "priority"],
        )
        self.assertEqual(result["offer_ids"], ["priority", "possible", "info-high"])
        self.assertEqual(result["section_counts"], {"priority": 1, "possible": 1, "informational": 1})
        text_body = (self.work / "draft" / "offer-selection.txt").read_text(encoding="utf-8")
        html_body = (self.work / "draft" / "offer-selection.html").read_text(encoding="utf-8")
        headings = [
            "Il faut répondre, ça matche et tu as des chances d’un retour positif",
            "Tu peux répondre, on ne sait jamais",
            "Je te les mets pour info, mais il y a peu de chances",
        ]
        self.assertEqual([text_body.index(heading) for heading in headings], sorted(text_body.index(heading) for heading in headings))
        self.assertIn("1. Secteur d’activité", text_body)
        self.assertIn("2. Secteur d’activité", text_body)
        self.assertIn("3. Secteur d’activité", text_body)
        self.assertIn('<ol start="1">', html_body)
        self.assertIn('<ol start="2">', html_body)
        self.assertIn('<ol start="3">', html_body)

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
