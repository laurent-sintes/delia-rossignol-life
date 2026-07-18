from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
TEST_TMP = ROOT / ".test-tmp"
TEST_TMP.mkdir(exist_ok=True)

from delia_life.site_builder import (
    build_site,
    markdown_to_html,
    render_cv_template_preview,
    render_json_document,
    safe_source,
)


class SiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = TEST_TMP / self._testMethodName
        if self.work.exists():
            shutil.rmtree(self.work)
        self.work.mkdir(parents=True)

    def tearDown(self) -> None:
        if self.work.exists():
            shutil.rmtree(self.work)

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

    def test_build_site_is_repeatable_and_includes_skill_advice(self) -> None:
        output = ROOT / "_site"
        first = build_site(ROOT, output)
        second = build_site(ROOT, output)
        self.assertEqual(first["pages"], second["pages"])
        self.assertEqual(
            set(first["pages"]),
            {"index.html", "profil.html", "templates.html", "modele.html", "administration.html"},
        )
        administration = (output / "administration.html").read_text(encoding="utf-8")
        mental_model = (output / "modele.html").read_text(encoding="utf-8")
        self.assertIn("$ingest-delia-knowledge", administration)
        self.assertIn("$publish-delia-site", administration)
        self.assertIn("30 concepts", mental_model)
        self.assertIn("person-has-experience", mental_model)
        self.assertIn("career-project-targets-sector", mental_model)
        self.assertIn("Critère de recherche", mental_model)
        self.assertTrue((output / ".nojekyll").exists())
        self.assertTrue((output / "assets" / "style.css").exists())
        self.assertTrue((output / "assets" / "delia-rossignol.avif").exists())
        self.assertTrue((output / "assets" / "delia-rossignol-logo.svg").exists())
        templates = (output / "templates.html").read_text(encoding="utf-8")
        self.assertIn("Standard sobre — ATS", templates)
        self.assertIn('class="cv-preview"', templates)
        self.assertIn("Contenu fictif", templates)
        self.assertNotIn("tel:", templates)
        self.assertNotIn("@gmail.com", templates)
        homepage = (output / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="hero"', homepage)
        self.assertIn('alt="Portrait de Délia Rossignol"', homepage)
        self.assertIn("delia-rossignol-logo.svg", homepage)
        self.assertNotIn("tel:", homepage)
        logo = (output / "assets" / "delia-rossignol-logo.svg").read_text(encoding="utf-8")
        self.assertIn("Délia Rossignol", logo)
        self.assertNotIn("Agenceur", logo)


if __name__ == "__main__":
    unittest.main()
