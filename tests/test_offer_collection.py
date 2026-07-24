from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.core import load_json
from delia_life.offer_collection import (
    CollectorSettings,
    collect_offers,
    parse_html_offer_page,
    parse_offer_page,
)
from delia_life.storage import remove_tree

JOB_POSTING_HTML = b"""
<!doctype html>
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "Conseillere clientele",
  "identifier": {"value": "BOR-42"},
  "hiringOrganization": {"name": "Maison Exemple"},
  "url": "https://jobs.example/offre/bor-42",
  "datePosted": "2026-07-21",
  "validThrough": "2026-08-31",
  "employmentType": ["FULL_TIME", "CDI"],
  "description": "Relation client et gestion administrative en CDI.",
  "jobLocation": {"address": {"addressLocality": "Bordeaux", "addressCountry": "FR"}},
  "baseSalary": {
    "currency": "EUR",
    "value": {"minValue": 28000, "maxValue": 32000, "unitText": "YEAR"}
  }
}
</script>
</head><body>
<a href="/offre/bor-43">Autre offre</a>
<a href="mailto:partage@example.test">Partager</a>
<a href="https://external.example/offre/externe">Offre externe</a>
</body></html>
"""


class OfferCollectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / "tests" / ".tmp" / "offer-collection"
        remove_tree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.policy_path = self.root / "policy.json"
        self.audit_path = self.root / "audit.json"
        self.manifest_path = self.root / "current.json"
        self.output_directory = self.root / "offers"
        self.archive_root = self.root / "archives"
        self.policy = {
            "regional_source_audit": str(self.audit_path),
            "functional_query_families": {
                "gestion-administrative": ["gestion administrative"],
                "conseil-et-relation-client": ["relation client"],
            },
            "collector": {
                "user_agent": "OfferCollectionTests/1.0",
                "timeout_seconds": 1,
                "retries": 0,
                "delay_seconds": 0,
                "max_response_bytes": 100000,
                "max_concurrent_sources": 2,
                "location_markers": ["Bordeaux"],
                "adapter_domains": {"specialized": ["jobs.example"]},
            },
        }
        self.audit = {
            "sources": [
                {
                    "organization": "Maison Exemple",
                    "organization_type": "private_employer",
                    "career_url": "https://jobs.example/carrieres",
                    "scan_domain": "jobs.example",
                    "sectors": ["commerce-et-distribution"],
                    "functional_domains": ["gestion-administrative"],
                }
            ]
        }
        self.manifest = {
            "schema_version": 2,
            "scan_id": "2026-07-22-test-full",
            "scan_mode": "full",
            "offer_output_directory": str(self.output_directory),
            "rank_inputs": [str(self.output_directory)],
            "requirements": {
                "required_source_domains": ["jobs.example"],
                "required_query_families": ["gestion-administrative"],
                "required_priority_sectors": ["commerce-et-distribution"],
            },
        }
        self.policy_path.write_text(json.dumps(self.policy), encoding="utf-8")
        self.audit_path.write_text(json.dumps(self.audit), encoding="utf-8")
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def tearDown(self) -> None:
        remove_tree(self.root, ignore_errors=True)

    def test_parse_offer_page_extracts_structured_job_posting_and_links(self) -> None:
        offers, references = parse_offer_page(
            JOB_POSTING_HTML,
            "https://jobs.example/carrieres",
            self.audit["sources"][0],
            self.policy,
            datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
        )

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["canonical_offer_id"], "jobs.example:BOR-42")
        self.assertEqual(offers[0]["contract_type"], "CDI")
        self.assertTrue(offers[0]["full_time"])
        self.assertEqual(offers[0]["compensation"]["minimum"], 28000)
        self.assertEqual(offers[0]["required_skills"], ["gestion administrative", "relation client"])
        self.assertEqual([reference.url for reference in references], ["https://jobs.example/offre/bor-43"])

    def test_html_detail_fallback_is_traceable_and_requires_semantic_review(self) -> None:
        offer = parse_html_offer_page(
            b"<html><head><title>Gestionnaire de stocks F/H</title></head>"
            b"<body><h1>Gestionnaire de stocks F/H</h1><p>CDI a Bordeaux, relation client.</p></body></html>",
            "https://jobs.example/offre/stock-42",
            "Gestionnaire de stocks F/H",
            self.audit["sources"][0],
            self.policy,
            datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
        )

        self.assertIsNotNone(offer)
        assert offer is not None
        self.assertEqual(offer["title"], "Gestionnaire de stocks F/H")
        self.assertEqual(offer["contract_type"], "CDI")
        self.assertEqual(offer["extraction"]["method"], "deterministic-html")
        self.assertEqual(offer["extraction"]["review_status"], "required")

    def test_html_detail_prefers_contract_prefix_in_listing_title(self) -> None:
        offer = parse_html_offer_page(
            b"<html><body><h1>Responsable qualite F/H</h1>"
            b"<p>Collaboration avec l'equipe alternance et les stagiaires.</p></body></html>",
            "https://jobs.example/offre/qualite-42",
            "CDI - Responsable qualite F/H",
            self.audit["sources"][0],
            self.policy,
            datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
        )

        self.assertIsNotNone(offer)
        assert offer is not None
        self.assertEqual(offer["contract_type"], "CDI")

    def test_navigation_pages_are_not_extracted_as_offers(self) -> None:
        captured_at = datetime(2026, 7, 22, 9, 0, tzinfo=UTC)
        for title in (
            "Bourse de l'emploi",
            "Nos ressources",
            "Accompagnements",
            "Accéder par concours",
            "Formations",
            "Les offres d'emploi : Administratif / technique",
            "Observatoire régional de l'emploi",
        ):
            with self.subTest(title=title):
                offer = parse_html_offer_page(
                    f"<html><body><h1>{title}</h1></body></html>".encode(),
                    "https://jobs.example/offre/navigation",
                    title,
                    self.audit["sources"][0],
                    self.policy,
                    captured_at,
                )
                self.assertIsNone(offer)

    def test_collect_offers_writes_offer_archive_and_machine_proof_of_coverage(self) -> None:
        fetched_urls: list[str] = []

        def fetch_page(url: str, _settings: CollectorSettings) -> dict[str, object]:
            fetched_urls.append(url)
            return {
                "capture_status": "captured",
                "url": url,
                "final_url": url,
                "status": 200,
                "media_type": "text/html",
                "body": JOB_POSTING_HTML if url.endswith("carrieres") else JOB_POSTING_HTML.replace(b"BOR-42", b"BOR-43"),
            }

        result = collect_offers(
            self.manifest_path,
            policy_path=self.policy_path,
            source_audit_path=self.audit_path,
            archive_root=self.archive_root,
            fetch_page=fetch_page,
            now=datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
        )

        self.assertTrue(result["complete"], result)
        self.assertEqual(result["offer_count"], 2)
        self.assertEqual(fetched_urls, ["https://jobs.example/carrieres", "https://jobs.example/offre/bor-43"])
        self.assertEqual(result["covered_query_families"], ["gestion-administrative"])
        self.assertEqual(result["covered_priority_sectors"], ["commerce-et-distribution"])
        self.assertEqual(result["semantic_review_required_count"], 2)
        self.assertEqual(len(result["semantic_review_queue"]), 2)
        self.assertEqual(len(list(self.output_directory.glob("*.json"))), 2)
        self.assertTrue((self.archive_root / self.manifest["scan_id"] / "manifest.json").is_file())
        updated_manifest = load_json(self.manifest_path)
        self.assertEqual(updated_manifest["status"], "collected")
        self.assertEqual(updated_manifest["collection"]["source_receipts"][0]["records"][0]["http_status"], 200)

    def test_collect_offers_proves_required_sector_functional_intersection(self) -> None:
        manifest = load_json(self.manifest_path)
        manifest["requirements"]["required_sector_functional_pairs"] = [
            "commerce-et-distribution::gestion-administrative"
        ]
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        result = collect_offers(
            self.manifest_path,
            policy_path=self.policy_path,
            source_audit_path=self.audit_path,
            archive_root=self.archive_root,
            fetch_page=lambda url, _settings: {
                "capture_status": "captured",
                "url": url,
                "final_url": url,
                "status": 200,
                "media_type": "text/html",
                "body": JOB_POSTING_HTML,
            },
            now=datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
        )

        self.assertTrue(result["complete"], result)
        self.assertEqual(
            result["covered_sector_functional_pairs"],
            ["commerce-et-distribution::gestion-administrative"],
        )
        self.assertEqual(result["missing_sector_functional_pairs"], [])

    def test_collect_offers_marks_scan_incomplete_when_a_required_source_fails(self) -> None:
        def fetch_page(url: str, _settings: CollectorSettings) -> dict[str, object]:
            return {"capture_status": "error", "url": url, "error": "timeout"}

        result = collect_offers(
            self.manifest_path,
            policy_path=self.policy_path,
            source_audit_path=self.audit_path,
            archive_root=self.archive_root,
            fetch_page=fetch_page,
            now=datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
        )

        self.assertFalse(result["complete"])
        self.assertEqual(result["failed_source_domains"], ["jobs.example"])
        self.assertFalse(result["promoted_to_rank_inputs"])
        self.assertEqual(list(self.output_directory.glob("*.json")), [])
        self.assertEqual(load_json(self.manifest_path)["status"], "collection-incomplete")

        with self.assertRaisesRegex(ValueError, "already been collected"):
            collect_offers(
                self.manifest_path,
                policy_path=self.policy_path,
                source_audit_path=self.audit_path,
                archive_root=self.archive_root,
                fetch_page=fetch_page,
                now=datetime(2026, 7, 22, 9, 5, tzinfo=UTC),
            )

    def test_reachable_but_unreadable_portal_does_not_count_as_covered(self) -> None:
        def fetch_page(url: str, _settings: CollectorSettings) -> dict[str, object]:
            return {
                "capture_status": "captured",
                "url": url,
                "final_url": url,
                "status": 200,
                "media_type": "text/html",
                "body": b"<html><body><div id='javascript-app'></div></body></html>",
            }

        result = collect_offers(
            self.manifest_path,
            policy_path=self.policy_path,
            source_audit_path=self.audit_path,
            archive_root=self.archive_root,
            fetch_page=fetch_page,
            now=datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
        )

        self.assertFalse(result["complete"])
        self.assertEqual(result["source_receipts"][0]["status"], "unverified-empty")
        self.assertEqual(result["visited_sources"], [])

    def test_workday_adapter_paginates_and_keeps_only_configured_locations(self) -> None:
        self.policy["collector"]["adapter_domains"] = {"workday": ["tenant.wd3.myworkdayjobs.com"]}
        self.audit["sources"][0].update(
            {
                "career_url": "https://tenant.wd3.myworkdayjobs.com/fr-FR/Site",
                "scan_domain": "tenant.wd3.myworkdayjobs.com",
            }
        )
        self.manifest["requirements"]["required_source_domains"] = ["tenant.wd3.myworkdayjobs.com"]
        self.policy_path.write_text(json.dumps(self.policy), encoding="utf-8")
        self.audit_path.write_text(json.dumps(self.audit), encoding="utf-8")
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

        def fetch_page(url: str, _settings: CollectorSettings) -> dict[str, object]:
            body = (
                b"<html><body><div id='app'></div></body></html>"
                if url.endswith("/Site")
                else b"<html><body><h1>Conseiller de vente</h1><p>CDI Bordeaux</p></body></html>"
            )
            return {
                "capture_status": "captured",
                "url": url,
                "final_url": url,
                "status": 200,
                "media_type": "text/html",
                "body": body,
            }

        def fetch_json(
            url: str,
            payload: dict[str, object],
            _settings: CollectorSettings,
        ) -> dict[str, object]:
            self.assertEqual(payload["offset"], 0)
            document = {
                "total": 2,
                "jobPostings": [
                    {
                        "title": "Conseiller de vente",
                        "externalPath": "/job/BORDEAUX/conseiller_JR1",
                        "locationsText": "Bordeaux",
                    },
                    {
                        "title": "Conseiller de vente",
                        "externalPath": "/job/LYON/conseiller_JR2",
                        "locationsText": "Lyon",
                    },
                ],
            }
            return {
                "capture_status": "captured",
                "url": url,
                "final_url": url,
                "status": 200,
                "media_type": "application/json",
                "body": json.dumps(document).encode("utf-8"),
            }

        result = collect_offers(
            self.manifest_path,
            policy_path=self.policy_path,
            source_audit_path=self.audit_path,
            archive_root=self.archive_root,
            fetch_page=fetch_page,
            fetch_json=fetch_json,
            now=datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
        )

        self.assertTrue(result["complete"])
        self.assertEqual(result["offer_count"], 1)
        self.assertEqual(result["source_receipts"][0]["offers_discovered"], 1)

    def test_bpce_adapter_paginates_and_keeps_only_configured_locations(self) -> None:
        self.policy["collector"]["adapter_domains"] = {"bpce": ["recrutement.bpce.fr"]}
        self.audit["sources"][0].update(
            {
                "organization": "Groupe BPCE",
                "career_url": "https://recrutement.bpce.fr/app/",
                "scan_domain": "recrutement.bpce.fr",
            }
        )
        self.manifest["requirements"]["required_source_domains"] = ["recrutement.bpce.fr"]
        self.policy_path.write_text(json.dumps(self.policy), encoding="utf-8")
        self.audit_path.write_text(json.dumps(self.audit), encoding="utf-8")
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

        def fetch_page(url: str, _settings: CollectorSettings) -> dict[str, object]:
            return {
                "capture_status": "captured",
                "url": url,
                "final_url": url,
                "status": 200,
                "media_type": "text/html",
                "body": b"<html><body><div id='root'></div></body></html>",
            }

        offsets: list[str] = []

        def fetch_json(
            url: str,
            payload: dict[str, object],
            _settings: CollectorSettings,
        ) -> dict[str, object]:
            self.assertTrue(url.endswith("/app/wp-json/bpce/v1/search/jobs"))
            offset = str(payload["from"])
            offsets.append(offset)
            location = "Bordeaux" if offset == "0" else "Lyon"
            reference = "BPCE-1" if offset == "0" else "BPCE-2"
            document = {
                "data": {
                    "total": 2,
                    "items": [
                        {
                            "job_number": reference,
                            "title": "Conseiller clientele",
                            "localisation": location,
                            "description": "<p>Relation client</p>",
                            "brand": ["Banque Populaire"],
                            "contract": ["CDI"],
                            "date": "2026-07-22",
                            "link": {"url": f"/app/offre/{reference}"},
                        }
                    ],
                }
            }
            return {
                "capture_status": "captured",
                "url": url,
                "final_url": url,
                "status": 200,
                "media_type": "application/json",
                "body": json.dumps(document).encode("utf-8"),
            }

        result = collect_offers(
            self.manifest_path,
            policy_path=self.policy_path,
            source_audit_path=self.audit_path,
            archive_root=self.archive_root,
            fetch_page=fetch_page,
            fetch_json=fetch_json,
            now=datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
        )

        self.assertTrue(result["complete"])
        self.assertEqual(result["offer_count"], 1)
        self.assertEqual(offsets, ["0", "1"])
        offer = load_json(next(self.output_directory.glob("*.json")))
        self.assertEqual(offer["employer"], "Banque Populaire")
        self.assertEqual(offer["extraction"]["method"], "deterministic-api")

    def test_jobaffinity_adapter_reads_embedded_list_and_detail(self) -> None:
        self.policy["collector"]["adapter_domains"] = {"jobaffinity": ["sources-hotels.com"]}
        self.policy["collector"]["location_markers"].append("Martillac")
        self.audit["sources"][0].update(
            {
                "organization": "Les Sources de Caudalie",
                "career_url": "https://www.sources-hotels.com/bordeaux/recrutement/",
                "scan_domain": "sources-hotels.com",
            }
        )
        self.manifest["requirements"]["required_source_domains"] = ["sources-hotels.com"]
        self.policy_path.write_text(json.dumps(self.policy), encoding="utf-8")
        self.audit_path.write_text(json.dumps(self.audit), encoding="utf-8")
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

        def fetch_page(url: str, _settings: CollectorSettings) -> dict[str, object]:
            if "list_job" in url:
                content = (
                    "document.write('<table><tr><td><a href=\"https://www.sources-hotels.com/"
                    "bordeaux/recrutement/?intuition_id=42&amp;intuition_source_id=10382\">"
                    "Guest Relation Agent</a></td></tr><tr><td><a href=\"https://www.sources-hotels.com/"
                    "bordeaux/recrutement/?intuition_id=43&amp;intuition_source_id=10382\">"
                    "Candidature spontanée</a></td></tr></table>')"
                ).encode()
            elif "info_job" in url:
                content = (
                    "document.write('<h2>Guest Relation Agent (H/F)</h2>\\n<p>CDI à Bordeaux-Martillac. "
                    "Accueil et relation client. Expérience en hôtel demandée.</p>')"
                ).encode()
            else:
                content = (
                    b'<html><body><script src="https://jobaffinity.fr/syndication/publication/'
                    b'462/10382"></script></body></html>'
                )
            return {
                "capture_status": "captured",
                "url": url,
                "final_url": url,
                "status": 200,
                "media_type": "text/javascript" if "jobaffinity.fr" in url else "text/html",
                "body": content,
            }

        result = collect_offers(
            self.manifest_path,
            policy_path=self.policy_path,
            source_audit_path=self.audit_path,
            archive_root=self.archive_root,
            fetch_page=fetch_page,
            now=datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
        )

        self.assertTrue(result["complete"], result)
        self.assertEqual(result["offer_count"], 1)
        self.assertEqual(result["source_receipts"][0]["pages_fetched"], 3)
        offer = load_json(next(self.output_directory.glob("*.json")))
        self.assertEqual(offer["title"], "Guest Relation Agent")
        self.assertEqual(offer["contract_type"], "CDI")
        self.assertEqual(offer["location_label"], "Bordeaux")

    def test_fashionjobs_adapter_paginates_listing_and_extracts_only_offer_details(self) -> None:
        self.policy["collector"]["adapter_domains"] = {"fashionjobs": ["fr.fashionjobs.com"]}
        self.audit["sources"][0].update(
            {
                "organization": "FashionJobs Bordeaux",
                "career_url": "https://fr.fashionjobs.com/s/emploi/vendeur-vendeuse-bordeaux.html",
                "scan_domain": "fr.fashionjobs.com",
                "sectors": ["luxe", "mode-et-pret-a-porter"],
            }
        )
        self.manifest["requirements"].update(
            {
                "required_source_domains": ["fr.fashionjobs.com"],
                "required_priority_sectors": ["mode-et-pret-a-porter"],
            }
        )
        self.policy_path.write_text(json.dumps(self.policy), encoding="utf-8")
        self.audit_path.write_text(json.dumps(self.audit), encoding="utf-8")
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

        listing_url = "https://fr.fashionjobs.com/s/emploi/vendeur-vendeuse-bordeaux.html"
        second_page_url = "https://fr.fashionjobs.com/s/emploi/vendeur-vendeuse-bordeaux,2.html"
        first_offer_url = "https://fr.fashionjobs.com/emploi/maison-a/conseiller-de-vente,11880001.html"
        second_offer_url = "https://fr.fashionjobs.com/emploi/maison-b/vendeur,11880002.html"

        def detail(reference: str, title: str, url: str) -> bytes:
            posting = {
                "@context": "https://schema.org",
                "@type": "JobPosting",
                "title": title,
                "identifier": {"value": reference},
                "hiringOrganization": {"name": "Maison de mode"},
                "url": url,
                "datePosted": "2026-07-22",
                "employmentType": "FULL_TIME",
                "description": "Conseil et relation client en boutique.",
                "jobLocation": {"address": {"addressLocality": "Bordeaux", "addressCountry": "FR"}},
            }
            return (
                "<html><head><script type='application/ld+json'>"
                + json.dumps(posting)
                + "</script></head><body><p><span>Type de contrat :</span><b>CDI</b></p>"
                + "<p><span>Type d'emploi :</span><b>Plein temps</b></p></body></html>"
            ).encode()

        fetched_urls: list[str] = []

        def fetch_page(url: str, _settings: CollectorSettings) -> dict[str, object]:
            fetched_urls.append(url)
            bodies = {
                listing_url: (
                    f'<a class="tw-relative extended-link" href="{first_offer_url}">Conseiller</a>'
                    f'<a href="{second_page_url}">2</a>'
                    '<a href="/s/emploi/vendeur-vendeuse-paris.html">Paris</a>'
                ).encode(),
                second_page_url: (
                    f'<a class="tw-relative extended-link" href="{second_offer_url}">Vendeur</a>'
                    f'<a href="{listing_url}">1</a>'
                ).encode(),
                first_offer_url: detail("FJ-1", "Conseiller de vente", first_offer_url),
                second_offer_url: detail("FJ-2", "Vendeur", second_offer_url),
            }
            return {
                "capture_status": "captured",
                "url": url,
                "final_url": url,
                "status": 200,
                "media_type": "text/html",
                "body": bodies[url],
            }

        result = collect_offers(
            self.manifest_path,
            policy_path=self.policy_path,
            source_audit_path=self.audit_path,
            archive_root=self.archive_root,
            fetch_page=fetch_page,
            now=datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
        )

        self.assertTrue(result["complete"], result)
        self.assertEqual(result["offer_count"], 2)
        self.assertEqual(result["covered_priority_sectors"], ["mode-et-pret-a-porter"])
        self.assertEqual(result["source_receipts"][0]["pages_fetched"], 4)
        self.assertEqual(result["source_receipts"][0]["offers_discovered"], 2)
        self.assertEqual(set(fetched_urls), {listing_url, second_page_url, first_offer_url, second_offer_url})
        contracts = {load_json(path)["contract_type"] for path in self.output_directory.glob("*.json")}
        self.assertEqual(contracts, {"CDI"})

    def test_ikea_zero_postes_page_does_not_turn_location_links_into_offers(self) -> None:
        self.policy["collector"]["adapter_domains"] = {"ikea": ["jobs.ikea.com"]}
        self.audit["sources"][0].update(
            {
                "organization": "IKEA Bordeaux",
                "career_url": "https://jobs.ikea.com/fr/lieu/jobs/22908/3017382-11071620-3031582/4",
                "scan_domain": "jobs.ikea.com",
            }
        )
        self.manifest["requirements"]["required_source_domains"] = ["jobs.ikea.com"]
        self.policy_path.write_text(json.dumps(self.policy), encoding="utf-8")
        self.audit_path.write_text(json.dumps(self.audit), encoding="utf-8")
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

        def fetch_page(url: str, _settings: CollectorSettings) -> dict[str, object]:
            return {
                "capture_status": "captured",
                "url": url,
                "final_url": url,
                "status": 200,
                "media_type": "text/html",
                "body": (
                    b"<html><body><h1>0 Postes a Bordeaux</h1>"
                    b'<a href="/de/standort/bordeaux-jobs/22908/3017382-11071620-3031582/4">Deutsch</a>'
                    b"</body></html>"
                ),
            }

        result = collect_offers(
            self.manifest_path,
            policy_path=self.policy_path,
            source_audit_path=self.audit_path,
            archive_root=self.archive_root,
            fetch_page=fetch_page,
            now=datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
        )

        self.assertTrue(result["complete"], result)
        self.assertEqual(result["offer_count"], 0)
        self.assertEqual(result["source_receipts"][0]["status"], "success")
        self.assertEqual(result["source_receipts"][0]["pages_fetched"], 1)
        self.assertEqual(result["source_receipts"][0]["offers_discovered"], 0)


if __name__ == "__main__":
    unittest.main()
