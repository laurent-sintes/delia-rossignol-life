from __future__ import annotations

import json
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
TEST_TMP = ROOT / ".test-tmp"
TEST_TMP.mkdir(exist_ok=True)

from delia_life.site_audit import audit_site
from delia_life.site_builder import (
    build_site,
    markdown_to_html,
    render_cv_template_preview,
    render_json_document,
    render_knowledge_card,
    safe_source,
)
from delia_life.storage import remove_tree


class SiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = TEST_TMP / f"{self._testMethodName}-{uuid.uuid4().hex}"
        self.work.mkdir(parents=True)

    def tearDown(self) -> None:
        if self.work.exists():
            remove_tree(self.work, ignore_errors=True)

    def test_publication_rejects_private_and_operational_sources(self) -> None:
        for source in ("private/cv.pdf", "data/applications/a.json", "data/review/queue/a.json"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                safe_source(ROOT, source)

    def test_json_projection_never_renders_unlisted_keys(self) -> None:
        rendered = render_json_document(
            {"headline": "Visible", "private_phone": "forbidden-secret"},
            {"fields": ["headline"], "labels": {"headline": "Titre"}},
        )
        self.assertIn("Visible", rendered)
        self.assertNotIn("forbidden-secret", rendered)
        self.assertNotIn("private_phone", rendered)

    def test_dates_are_rendered_in_french(self) -> None:
        rendered = render_knowledge_card(
            {"fields": {"period": {"value": "2026-07-31"}, "month": {"value": "2020-08"}}},
            {"title": "Carte", "fields": [{"path": "fields.period.value", "label": "Fin"}, {"path": "fields.month.value", "label": "Début"}]},
        )
        self.assertIn("31 juillet 2026", rendered)
        self.assertIn("août 2020", rendered)

    def test_knowledge_text_highlights_are_safe_and_discreet(self) -> None:
        rendered = render_knowledge_card(
            {"fields": {"statement": {"value": "Étudier le besoin avant une solution sur mesure."}}},
            {"title": "Carte", "fields": [{"path": "fields.statement.value", "label": "Principe", "highlights": ["Étudier le besoin", "solution sur mesure"]}]},
        )
        self.assertIn('<strong class="text-highlight">Étudier le besoin</strong>', rendered)
        self.assertIn('<strong class="text-highlight">solution sur mesure</strong>', rendered)

    def test_knowledge_projection_uses_explicit_nested_paths_without_provenance(self) -> None:
        rendered = render_knowledge_card(
            {
                "fields": {
                    "details": {
                        "value": {"title": "Visible", "secret": "forbidden-secret"},
                        "provenance": [{"source_id": "private-source"}],
                    }
                }
            },
            {
                "title": "Carte",
                "fields": [{"path": "fields.details.value.title", "label": "Fonction"}],
            },
        )
        self.assertIn("Visible", rendered)
        self.assertIn('class="knowledge-fields knowledge-fields--single"', rendered)
        self.assertNotIn("forbidden-secret", rendered)
        self.assertNotIn("private-source", rendered)

    def test_badge_presentation_is_limited_to_scalar_values(self) -> None:
        rendered = render_knowledge_card(
            {"fields": {"strengths": {"value": ["Autonomie", "Créativité"]}}},
            {
                "title": "Carte",
                "fields": [{"path": "fields.strengths.value", "label": "Forces", "presentation": "badge"}],
            },
        )
        self.assertIn('class="knowledge-badge">Autonomie</span>', rendered)
        with self.assertRaisesRegex(ValueError, "Badge presentation"):
            render_knowledge_card(
                {"fields": {"metrics": {"value": {"count": 8}}}},
                {"title": "Carte", "fields": [{"path": "fields.metrics.value", "label": "Métrique", "presentation": "badge"}]},
            )

    def test_editorial_knowledge_card_separates_summary_and_detail(self) -> None:
        rendered = render_knowledge_card(
            {"fields": {"details": {"value": {"role": "Direction", "responsibilities": ["Piloter", "Coordonner"]}}}},
            {
                "title": "Expérience",
                "layout": "editorial",
                "fields": [
                    {"path": "fields.details.value.role", "label": "Fonction"},
                    {
                        "path": "fields.details.value.responsibilities",
                        "label": "Responsabilités",
                        "presentation": "detail",
                    },
                ],
            },
        )
        self.assertIn('class="knowledge-card knowledge-card--editorial"', rendered)
        self.assertIn('class="knowledge-summary"', rendered)
        self.assertIn('class="knowledge-detail"', rendered)
        self.assertLess(rendered.index("Fonction"), rendered.index("Responsabilités"))

    def test_site_audit_detects_invalid_badge_and_internal_label(self) -> None:
        source_path = self.work / "site" / "content" / "knowledge.json"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(json.dumps({"fields": {"value": {"value": {"not": "scalar"}}}}), encoding="utf-8")
        config_path = self.work / "publication.json"
        config_path.write_text(json.dumps({"pages": [{"kind": "knowledge", "slug": "profil", "sections": [{"cards": [{"source": "site/content/knowledge.json", "title": "Carte", "fields": [{"path": "fields.value.value", "label": "Posture validée", "presentation": "badge"}]}]}]}]}), encoding="utf-8")
        report = audit_site(self.work, config_path)
        self.assertFalse(report["ok"])
        self.assertTrue(any("badge" in item["message"] for item in report["errors"]))
        self.assertTrue(any("internal validation" in item["message"] for item in report["warnings"]))

    def test_markdown_escapes_html_and_filters_unsafe_links(self) -> None:
        rendered = markdown_to_html("# Titre\n\n<script>alert(1)</script> [piège](javascript:alert(1)) [page](profil.html)")
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("href=\"javascript:", rendered)
        self.assertIn('href="profil.html"', rendered)

    def test_cv_template_preview_is_fictitious_and_rejects_unknown_engines(self) -> None:
        template = {
            "rendering": {
                "engine": "standard-single-column-v1",
                "preferred_pages": 2,
                "photo_policy": "optional-disabled-by-default",
                "sections": ["profile", "professional-experience"],
            }
        }
        rendered = render_cv_template_preview(template)
        self.assertIn("Contenu fictif", rendered)
        self.assertIn("PRÉNOM NOM", rendered)
        self.assertIn("Photo optionnelle", rendered)
        self.assertNotIn("Délia", rendered)
        template["rendering"]["engine"] = "unsafe-engine"
        with self.assertRaises(ValueError):
            render_cv_template_preview(template)

    def test_build_site_is_repeatable_and_includes_advice(self) -> None:
        output = ROOT / "_site"
        stale_staging = ROOT / ".runtime" / "site-builds" / f"_site.staging-stale{uuid.uuid4().hex}"
        stale_staging.mkdir(parents=True)
        first = build_site(ROOT, output)
        second = build_site(ROOT, output)
        self.assertFalse(stale_staging.exists())
        self.assertEqual(list(ROOT.glob("._site.staging-*")), [])
        self.assertEqual(first["pages"], second["pages"])
        self.assertEqual(
            set(first["pages"]),
            {"index.html", "profil.html", "parcours.html", "administration.html"},
        )
        administration = (output / "administration.html").read_text(encoding="utf-8")
        self.assertIn("$ingest-delia-knowledge", administration)
        self.assertIn("$manage-delia-templates", administration)
        self.assertNotIn("Catalogue des skills", administration)
        self.assertTrue((output / ".nojekyll").exists())
        self.assertTrue((output / "assets" / "style.css").exists())
        self.assertTrue((output / "assets" / "delia-rossignol.avif").exists())
        self.assertTrue((output / "assets" / "delia-rossignol-logo.svg").exists())
        homepage = (output / "index.html").read_text(encoding="utf-8")
        parcours = (output / "parcours.html").read_text(encoding="utf-8")
        self.assertIn('class="hero"', homepage)
        self.assertIn('class="text-highlight">préparer des candidatures</strong>', homepage)
        self.assertRegex(homepage, r'assets/style\.css\?v=[0-9a-f]{12}')
        self.assertIn('alt="Portrait de Délia Rossignol"', homepage)
        self.assertIn("delia-rossignol-logo.svg", homepage)
        self.assertIn("assets/downloads/cv-delia-rossignol-signature.pdf", homepage)
        self.assertTrue((output / "assets" / "downloads" / "cv-delia-rossignol-signature.pdf").exists())
        self.assertIn("knowledge-section--editorial", parcours)
        self.assertIn("knowledge-card--editorial", parcours)
        self.assertNotIn("tel:", homepage)
        logo = (output / "assets" / "delia-rossignol-logo.svg").read_text(encoding="utf-8")
        self.assertIn("Délia Rossignol", logo)
        self.assertNotIn("Agenceur", logo)

    def test_failed_site_build_preserves_the_previous_output(self) -> None:
        output = self.work / "site"
        build_site(ROOT, output)
        previous = (output / "index.html").read_bytes()
        config = json.loads((ROOT / "site" / "publication.json").read_text(encoding="utf-8"))
        config["pages"][1]["kind"] = "unsupported"
        config_path = self.work / "invalid-publication.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unsupported page kind"):
            build_site(ROOT, output, config_path)
        self.assertEqual((output / "index.html").read_bytes(), previous)
        self.assertTrue((output / ".delia-site-output").exists())


if __name__ == "__main__":
    unittest.main()
