from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.offer_scan import (
    clean_offer_scan_cache,
    prepare_offer_scan,
    record_manual_source_receipts,
)
from delia_life.storage import remove_tree


class OfferScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / "tests" / ".tmp" / "offer-scan"
        remove_tree(self.root, ignore_errors=True)
        self.runtime = self.root / ".runtime" / "offer-search"
        self.offers = self.root / "data" / "offers"
        self.reports = self.root / "generated" / "offer-search"
        self.now = datetime(2026, 7, 21, 18, 30, tzinfo=UTC)

    def tearDown(self) -> None:
        remove_tree(self.root, ignore_errors=True)

    def test_clean_cache_preserves_versioned_offer_and_report_roots(self) -> None:
        self.runtime.mkdir(parents=True)
        (self.runtime / "cached.json").write_text("{}", encoding="utf-8")
        self.offers.mkdir(parents=True)
        self.reports.mkdir(parents=True)
        (self.offers / "offer.json").write_text("{}", encoding="utf-8")
        (self.reports / "report.json").write_text("{}", encoding="utf-8")

        result = clean_offer_scan_cache(self.runtime)

        self.assertTrue(result["cache_cleaned"])
        self.assertFalse(self.runtime.exists())
        self.assertTrue((self.offers / "offer.json").exists())
        self.assertTrue((self.reports / "report.json").exists())

    def test_clean_cache_rejects_any_target_outside_the_disposable_runtime_root(self) -> None:
        unsafe = self.root / "data" / "offers"
        unsafe.mkdir(parents=True)
        marker = unsafe / "offer.json"
        marker.write_text("{}", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "must end with .runtime/offer-search"):
            clean_offer_scan_cache(unsafe)

        self.assertTrue(marker.exists())

    def test_full_scan_cleans_cache_and_isolates_ranking_to_fresh_session(self) -> None:
        self.runtime.mkdir(parents=True)
        (self.runtime / "stale.json").write_text("{}", encoding="utf-8")

        result = prepare_offer_scan(
            "full",
            runtime_root=self.runtime,
            offers_root=self.offers,
            reports_root=self.reports,
            now=self.now,
        )

        self.assertTrue(result["cache_cleaned"])
        self.assertEqual(result["history_policy"], "fresh-session-only")
        self.assertEqual(result["rank_inputs"], [result["offer_output_directory"]])
        self.assertFalse(result["delivery_requested"])
        self.assertTrue(Path(result["offer_output_directory"]).exists())
        self.assertTrue(Path(result["manifest_path"]).exists())

    def test_full_scan_manifest_does_not_import_history_into_revalidation(self) -> None:
        history = self.offers / "2026-07-20"
        history.mkdir(parents=True)
        (history / "active.json").write_text(
            '{"id":"active","title":"Poste actif","employer":"A",'
            '"source_url":"https://example.test/active","verification_status":"active",'
            '"last_verified_at":"2026-07-20T10:00:00+02:00"}',
            encoding="utf-8",
        )
        (history / "pending.json").write_text(
            '{"id":"pending","title":"Poste pending","employer":"B",'
            '"source_url":"https://example.test/pending","verification_status":"pending",'
            '"last_verified_at":"2026-07-20T10:00:00+02:00"}',
            encoding="utf-8",
        )
        (history / "closed.json").write_text(
            '{"id":"closed","title":"Poste fermé","employer":"C",'
            '"source_url":"https://example.test/closed","verification_status":"closed",'
            '"last_verified_at":"2026-07-20T10:00:00+02:00"}',
            encoding="utf-8",
        )

        result = prepare_offer_scan(
            "full",
            runtime_root=self.runtime,
            offers_root=self.offers,
            reports_root=self.reports,
            now=self.now,
        )

        self.assertEqual(result["revalidation_count"], 0)
        self.assertEqual(result["revalidation_queue"], [])
        self.assertTrue(result["requirements"]["required_source_domains"])
        self.assertIn("u-bordeaux.fr", result["requirements"]["manual_source_domains"])
        self.assertIn("hellowork.com", result["requirements"]["manual_source_domains"])
        self.assertEqual(len(result["requirements"]["manual_source_domains"]), 21)
        self.assertNotIn("u-bordeaux.fr", result["requirements"]["required_source_domains"])
        self.assertTrue(result["requirements"]["required_query_families"])
        self.assertTrue(result["requirements"]["required_priority_sectors"])
        self.assertEqual(
            result["requirements"]["required_sector_functional_pairs"],
            [
                "industrie::commerce-et-vente",
                "industrie::conseil-et-relation-client",
                "industrie::gestion-administrative",
                "industrie::gestion-et-coordination-de-projets",
            ],
        )
        self.assertIn(
            "industrie::commerce-et-vente",
            result["requirements"]["manual_source_sector_functional_coverage"][
                "careers.rexel.com"
            ],
        )
        self.assertEqual(result["manual_source_receipts"], [])

    def test_delta_scan_uses_cumulative_history_without_cleaning_cache(self) -> None:
        self.runtime.mkdir(parents=True)
        cached = self.runtime / "cached.json"
        cached.write_text("{}", encoding="utf-8")

        result = prepare_offer_scan(
            "delta",
            runtime_root=self.runtime,
            offers_root=self.offers,
            reports_root=self.reports,
            now=self.now,
        )

        self.assertFalse(result["cache_cleaned"])
        self.assertEqual(result["history_policy"], "cumulative-history")
        self.assertEqual(result["rank_inputs"], [str(self.offers)])
        self.assertTrue(cached.exists())
        self.assertEqual(len(result["requirements"]["manual_source_domains"]), 19)

    def test_manual_source_receipts_are_traceable_and_scan_specific(self) -> None:
        prepared = prepare_offer_scan(
            "full",
            runtime_root=self.runtime,
            offers_root=self.offers,
            reports_root=self.reports,
            now=self.now,
        )
        batch_path = self.root / "manual-receipts.json"
        batch_path.write_text(
            json.dumps(
                {
                    "scan_id": prepared["scan_id"],
                    "receipts": [
                        {
                            "domain": "hellowork.com",
                            "status": "success",
                            "source_url": "https://www.hellowork.com/fr-fr/emploi/recherche.html",
                            "checked_at": "2026-07-21T18:45:00+00:00",
                            "offers_found": 3,
                            "note": "Recherche Bordeaux contrôlée manuellement.",
                            "covered_query_families": [
                                "conseil-et-relation-client",
                                "commerce-et-vente",
                            ],
                        },
                        {
                            "domain": "linkedin.com",
                            "status": "no_access",
                            "source_url": "https://fr.linkedin.com/jobs/search",
                            "checked_at": "2026-07-21T18:46:00+00:00",
                            "offers_found": 0,
                            "note": "Accès bloqué avant confirmation des résultats.",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = record_manual_source_receipts(Path(prepared["manifest_path"]), batch_path)

        self.assertEqual(result["recorded_count"], 2)
        self.assertEqual(result["manual_source_control"]["successful_count"], 1)
        self.assertFalse(result["manual_source_control"]["complete"])
        manifest = json.loads(Path(prepared["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(
            {receipt["domain"]: receipt["status"] for receipt in manifest["manual_source_receipts"]},
            {"hellowork.com": "success", "linkedin.com": "no_access"},
        )
        self.assertIn(
            "conseil-et-relation-client",
            manifest["collection"]["covered_query_families"],
        )

    def test_manual_source_receipt_rejects_a_cross_domain_url(self) -> None:
        prepared = prepare_offer_scan(
            "full",
            runtime_root=self.runtime,
            offers_root=self.offers,
            reports_root=self.reports,
            now=self.now,
        )
        batch_path = self.root / "invalid-manual-receipt.json"
        batch_path.write_text(
            json.dumps(
                {
                    "scan_id": prepared["scan_id"],
                    "receipts": [
                        {
                            "domain": "hellowork.com",
                            "status": "success",
                            "source_url": "https://example.test/jobs",
                            "checked_at": "2026-07-21T18:45:00+00:00",
                            "offers_found": 0,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "URL does not match hellowork.com"):
            record_manual_source_receipts(Path(prepared["manifest_path"]), batch_path)

    def test_successful_manual_receipt_completes_coverage_and_promotes_partial_offers(self) -> None:
        prepared = prepare_offer_scan(
            "full",
            runtime_root=self.runtime,
            offers_root=self.offers,
            reports_root=self.reports,
            now=self.now,
        )
        manifest_path = Path(prepared["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        partial_directory = self.root / "archives" / prepared["scan_id"] / "partial-offers"
        partial_directory.mkdir(parents=True)
        (partial_directory / "offer-example.json").write_text(
            '{"id":"offer-example"}',
            encoding="utf-8",
        )
        manifest["requirements"] = {
            "required_source_domains": [],
            "manual_source_domains": ["hellowork.com"],
            "manual_source_sector_coverage": {
                "hellowork.com": ["services-aux-entreprises"],
            },
            "manual_source_sector_functional_coverage": {
                "hellowork.com": [
                    "services-aux-entreprises::conseil-et-relation-client"
                ],
            },
            "required_query_families": ["conseil-et-relation-client"],
            "required_priority_sectors": ["services-aux-entreprises"],
            "required_sector_functional_pairs": [
                "services-aux-entreprises::conseil-et-relation-client"
            ],
        }
        manifest["collection"] = {
            "failed_source_domains": [],
            "visited_sources": [],
            "covered_query_families": [],
            "covered_priority_sectors": [],
            "covered_sector_functional_pairs": [],
            "missing_query_families": ["conseil-et-relation-client"],
            "missing_priority_sectors": ["services-aux-entreprises"],
            "missing_sector_functional_pairs": [
                "services-aux-entreprises::conseil-et-relation-client"
            ],
            "collected_output_directory": str(partial_directory),
            "promoted_to_rank_inputs": False,
            "semantic_review_queue": [
                {
                    "offer_id": "offer-example",
                    "offer_path": str(partial_directory / "offer-example.json"),
                }
            ],
            "complete": False,
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        batch_path = self.root / "complete-manual-receipt.json"
        batch_path.write_text(
            json.dumps(
                {
                    "scan_id": prepared["scan_id"],
                    "receipts": [
                        {
                            "domain": "hellowork.com",
                            "status": "success",
                            "source_url": "https://www.hellowork.com/fr-fr/emploi/recherche.html",
                            "checked_at": "2026-07-21T18:45:00+00:00",
                            "offers_found": 1,
                            "covered_query_families": ["conseil-et-relation-client"],
                            "covered_priority_sectors": ["services-aux-entreprises"],
                            "covered_sector_functional_pairs": [
                                "services-aux-entreprises::conseil-et-relation-client"
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = record_manual_source_receipts(manifest_path, batch_path)

        self.assertTrue(result["collection_complete"])
        self.assertTrue(result["promoted_to_rank_inputs"])
        self.assertTrue((Path(prepared["offer_output_directory"]) / "offer-example.json").is_file())
        updated = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["status"], "collected")
        self.assertEqual(
            updated["collection"]["semantic_review_queue"][0]["offer_path"],
            str(Path(prepared["offer_output_directory"]) / "offer-example.json"),
        )

    def test_delta_scan_queues_pending_and_stale_active_history(self) -> None:
        history = self.offers / "2026-07-01"
        history.mkdir(parents=True)
        (history / "active.json").write_text(
            '{"id":"active","title":"Poste actif","employer":"A",'
            '"source_url":"https://example.test/active","verification_status":"active",'
            '"last_verified_at":"2026-07-01T10:00:00+02:00"}',
            encoding="utf-8",
        )
        (history / "pending.json").write_text(
            '{"id":"pending","title":"Poste pending","employer":"B",'
            '"source_url":"https://example.test/pending","verification_status":"pending",'
            '"last_verified_at":"2026-07-20T10:00:00+02:00"}',
            encoding="utf-8",
        )

        result = prepare_offer_scan(
            "delta",
            runtime_root=self.runtime,
            offers_root=self.offers,
            reports_root=self.reports,
            now=self.now,
        )

        self.assertEqual({item["id"] for item in result["revalidation_queue"]}, {"active", "pending"})

    def test_send_action_is_a_full_scan_with_delivery_requested(self) -> None:
        result = prepare_offer_scan(
            "send",
            runtime_root=self.runtime,
            offers_root=self.offers,
            reports_root=self.reports,
            now=self.now,
        )

        self.assertEqual(result["scan_mode"], "full")
        self.assertTrue(result["cache_cleaned"])
        self.assertTrue(result["delivery_requested"])
        self.assertEqual(result["rank_inputs"], [result["offer_output_directory"]])


if __name__ == "__main__":
    unittest.main()
