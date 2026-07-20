from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import sys
import tempfile
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date
from pathlib import Path
from typing import Any, TypedDict

from .ats_cv import ATS_VARIANTS
from .core import load_json, sha256_file
from .document_builder import STANDARD_CV_FILENAME, build_standard_cv
from .mental_model import load_mental_model, model_summary
from .storage import atomic_write_bytes_group, exclusive_directory_lock, remove_tree

ALLOWED_SOURCE_PREFIXES = {
    ("site", "content"),
    ("site", "assets"),
    ("data", "knowledge"),
    ("data", "style"),
    ("templates",),
    ("model",),
    (".codex", "skills"),
}
FORBIDDEN_SOURCE_PREFIXES = {
    ("private",),
    ("generated",),
    ("data", "applications"),
    ("data", "offers"),
    ("data", "review"),
    ("data", "sources"),
}
SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")
INLINE_PATTERN = re.compile(r"`([^`]+)`|==([^=]+)==|\[([^\]]+)\]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^(#{1,3})\s+(.+)$")
BULLET_PATTERN = re.compile(r"^[-*]\s+(.+)$")
NUMBERED_PATTERN = re.compile(r"^\d+\.\s+(.+)$")
KNOWLEDGE_CARD_VARIANTS = {"continuity-foundation", "continuity-context", "continuity-highlight"}


class SiteBuildResult(TypedDict):
    output: str
    pages: list[str]
    documents: list[dict[str, Any]]
    published_sources_are_allowlisted: bool
    staging_cleanup: dict[str, int]


def _is_prefix(parts: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    return parts[: len(prefix)] == prefix


def safe_source(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        parts = candidate.relative_to(root.resolve()).parts
    except ValueError as error:
        raise ValueError(f"Publication source escapes project root: {relative}") from error
    if any(_is_prefix(parts, prefix) for prefix in FORBIDDEN_SOURCE_PREFIXES):
        raise ValueError(f"Forbidden publication source: {relative}")
    if not any(_is_prefix(parts, prefix) for prefix in ALLOWED_SOURCE_PREFIXES):
        raise ValueError(f"Source is not in an allowed publication area: {relative}")
    return candidate


def render_inline(text: str) -> str:
    chunks: list[str] = []
    position = 0
    for match in INLINE_PATTERN.finditer(text):
        chunks.append(html.escape(text[position : match.start()]))
        if match.group(1) is not None:
            chunks.append(f"<code>{html.escape(match.group(1))}</code>")
        elif match.group(2) is not None:
            chunks.append(f'<strong class="text-highlight">{html.escape(match.group(2))}</strong>')
        else:
            label = html.escape(match.group(3) or "")
            target = match.group(4) or ""
            parsed = urllib.parse.urlsplit(target)
            safe_relative = not parsed.scheme and not parsed.netloc and not target.startswith("//")
            if parsed.scheme in {"https", "http", "mailto"} or safe_relative:
                chunks.append(f'<a href="{html.escape(target, quote=True)}">{label}</a>')
            else:
                chunks.append(label)
        position = match.end()
    chunks.append(html.escape(text[position:]))
    return "".join(chunks)


@dataclass
class MarkdownRenderState:
    output: list[str] = dataclass_field(default_factory=list)
    paragraph: list[str] = dataclass_field(default_factory=list)
    list_kind: str | None = None
    in_code: bool = False
    code_lines: list[str] = dataclass_field(default_factory=list)

    def flush_paragraph(self) -> None:
        if self.paragraph:
            self.output.append(f"<p>{render_inline(' '.join(self.paragraph))}</p>")
            self.paragraph.clear()

    def close_list(self) -> None:
        if self.list_kind:
            self.output.append(f"</{self.list_kind}>")
            self.list_kind = None

    def toggle_code(self) -> None:
        self.flush_paragraph()
        self.close_list()
        if self.in_code:
            self.flush_code()
        else:
            self.in_code = True

    def flush_code(self) -> None:
        self.output.append(f"<pre><code>{html.escape(chr(10).join(self.code_lines))}</code></pre>")
        self.code_lines.clear()
        self.in_code = False

    def add_list_item(self, kind: str, value: str) -> None:
        self.flush_paragraph()
        if self.list_kind != kind:
            self.close_list()
            self.output.append(f"<{kind}>")
            self.list_kind = kind
        self.output.append(f"<li>{render_inline(value)}</li>")

    def finish(self) -> str:
        if self.in_code:
            self.flush_code()
        self.flush_paragraph()
        self.close_list()
        return "\n".join(self.output)


def _render_markdown_line(state: MarkdownRenderState, raw_line: str) -> None:
    line = raw_line.rstrip()
    if line.startswith("```"):
        state.toggle_code()
        return
    if state.in_code:
        state.code_lines.append(raw_line)
        return
    if not line.strip():
        state.flush_paragraph()
        state.close_list()
        return
    heading = HEADING_PATTERN.match(line)
    if heading:
        state.flush_paragraph()
        state.close_list()
        level = len(heading.group(1))
        state.output.append(f"<h{level}>{render_inline(heading.group(2))}</h{level}>")
        return
    bullet = BULLET_PATTERN.match(line)
    numbered = NUMBERED_PATTERN.match(line)
    match = bullet or numbered
    if match:
        state.add_list_item("ul" if bullet else "ol", match.group(1))
        return
    state.paragraph.append(line.strip())


def markdown_to_html(markdown: str) -> str:
    state = MarkdownRenderState()
    for raw_line in markdown.splitlines():
        _render_markdown_line(state, raw_line)
    return state.finish()


def _label(name: str, labels: dict[str, str]) -> str:
    return labels.get(name, name.replace("_", " ").replace("-", " ").capitalize())


def _render_scalar(value: Any) -> str:
    if value is None or value == "":
        return '<span class="empty">À renseigner</span>'
    if isinstance(value, bool):
        return "Oui" if value else "Non"
    if isinstance(value, str) and re.fullmatch(r"\d{4}(?:-\d{2}){0,2}", value):
        parts = value.split("-")
        if len(parts) == 1:
            return value
        months = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
        year, month = int(parts[0]), int(parts[1])
        if not 1 <= month <= 12:
            return html.escape(value)
        if len(parts) == 2:
            return f"{months[month - 1]} {year}"
        try:
            return f"{date(year, month, int(parts[2])).day} {months[month - 1]} {year}"
        except ValueError:
            return html.escape(value)
    return html.escape(str(value))


def _render_text_with_highlights(value: str, highlights: list[str] | None) -> str:
    terms = sorted({term for term in (highlights or []) if term}, key=len, reverse=True)
    if not terms:
        return html.escape(value)
    pattern = re.compile("(" + "|".join(re.escape(term) for term in terms) + ")", re.IGNORECASE)
    return "".join(
        f'<strong class="text-highlight">{html.escape(part)}</strong>' if pattern.fullmatch(part) else html.escape(part)
        for part in pattern.split(value)
        if part
    )


def _render_value(
    value: Any,
    item_fields: list[str] | None,
    labels: dict[str, str],
    highlights: list[str] | None = None,
) -> str:
    if isinstance(value, list):
        if not value:
            return '<span class="empty">Aucune information publiée</span>'
        if all(not isinstance(item, (dict, list)) for item in value):
            return "<ul>" + "".join(
                f"<li>{_render_text_with_highlights(item, highlights) if isinstance(item, str) else _render_scalar(item)}</li>"
                for item in value
            ) + "</ul>"
        if not item_fields:
            raise ValueError("item_fields is required to publish structured list items")
        cards: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("Mixed structured and scalar list cannot be published")
            rows = "".join(
                f"<dt>{html.escape(_label(field, labels))}</dt>"
                f"<dd>{_render_value(item.get(field), None, labels)}</dd>"
                for field in item_fields
            )
            cards.append(f'<article class="data-card"><dl>{rows}</dl></article>')
        return '<div class="card-grid">' + "".join(cards) + "</div>"
    if isinstance(value, dict):
        if not item_fields:
            raise ValueError("item_fields is required to publish object values")
        rows = "".join(
            f"<dt>{html.escape(_label(field, labels))}</dt>"
            f"<dd>{_render_value(value.get(field), None, labels)}</dd>"
            for field in item_fields
        )
        return f"<dl>{rows}</dl>"
    if isinstance(value, str):
        if re.fullmatch(r"\d{4}(?:-\d{2}){0,2}", value):
            return _render_scalar(value)
        return _render_text_with_highlights(value, highlights)
    return _render_scalar(value)


def render_json_document(document: dict[str, Any], spec: dict[str, Any]) -> str:
    fields = spec.get("fields")
    if not fields:
        raise ValueError("Every published JSON source requires an explicit non-empty fields allowlist")
    labels = spec.get("labels", {})
    item_fields_by_field = spec.get("item_fields", {})
    blocks: list[str] = []
    for field in fields:
        value = document.get(field)
        content = _render_value(value, item_fields_by_field.get(field), labels)
        blocks.append(
            f'<section class="data-section"><h3>{html.escape(_label(field, labels))}</h3>{content}</section>'
        )
    return "".join(blocks)


def _nested_value(document: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    if not parts or any(not re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in parts):
        raise ValueError(f"Unsafe or empty knowledge path: {path}")
    value: Any = document
    for part in parts:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _render_badges(value: Any) -> str:
    values = value if isinstance(value, list) else [value]
    if not values or any(isinstance(item, (dict, list)) for item in values):
        raise ValueError("Badge presentation requires a scalar value or a list of scalar values")
    badges = "".join(f'<span class="knowledge-badge">{_render_scalar(item)}</span>' for item in values)
    return f'<div class="knowledge-badges">{badges}</div>'


@dataclass
class KnowledgeCardContent:
    rows: list[str] = dataclass_field(default_factory=list)
    summary_items: list[str] = dataclass_field(default_factory=list)
    detail_sections: list[str] = dataclass_field(default_factory=list)

    @property
    def has_values(self) -> bool:
        return bool(self.rows or self.summary_items or self.detail_sections)


def _knowledge_card_class(layout: str, variant: Any) -> str:
    if variant is not None and variant not in KNOWLEDGE_CARD_VARIANTS:
        raise ValueError(f"Unsupported knowledge card variant: {variant}")
    card_classes = ["knowledge-card"]
    if layout == "editorial":
        card_classes.append("knowledge-card--editorial")
    if variant is not None:
        card_classes.append(f"knowledge-card--{variant}")
    return " ".join(card_classes)


def _collect_knowledge_card_content(
    document: dict[str, Any],
    fields: list[dict[str, Any]],
    layout: str,
) -> KnowledgeCardContent:
    result = KnowledgeCardContent()
    for field in fields:
        path = field.get("path")
        label = field.get("label")
        if not path or not label:
            raise ValueError("Knowledge fields require path and label")
        value = _nested_value(document, path)
        if value is None or value == "" or value == []:
            continue
        presentation = field.get("presentation")
        content = (
            _render_badges(value)
            if presentation == "badge"
            else _render_value(value, field.get("item_fields"), field.get("labels", {}), field.get("highlights"))
        )
        if layout == "editorial" and presentation == "detail":
            result.detail_sections.append(
                '<section class="knowledge-detail">'
                f"<h4>{html.escape(str(label))}</h4>{content}</section>"
            )
        elif layout == "editorial":
            result.summary_items.append(
                '<div class="knowledge-summary-item">'
                f"<p>{html.escape(str(label))}</p><div>{content}</div></div>"
            )
        else:
            result.rows.append(f"<dt>{html.escape(str(label))}</dt><dd>{content}</dd>")
    return result


def _render_editorial_knowledge_card(
    spec: dict[str, Any], card_class: str, eyebrow_html: str, content: KnowledgeCardContent
) -> str:
    summary = (
        '<div class="knowledge-summary">' + "".join(content.summary_items) + "</div>"
        if content.summary_items
        else ""
    )
    return (
        f'<article class="{card_class}">'
        + eyebrow_html
        + f'<h3>{html.escape(str(spec["title"]))}</h3>'
        + summary
        + '<div class="knowledge-details">'
        + "".join(content.detail_sections)
        + "</div></article>"
    )


def render_knowledge_card(document: dict[str, Any], spec: dict[str, Any]) -> str:
    fields = spec.get("fields")
    if not fields:
        raise ValueError("Every knowledge card requires an explicit non-empty fields allowlist")
    layout = spec.get("layout", "standard")
    if layout not in {"standard", "editorial"}:
        raise ValueError(f"Unsupported knowledge card layout: {layout}")
    card_class = _knowledge_card_class(layout, spec.get("variant"))
    content = _collect_knowledge_card_content(document, fields, layout)
    if not content.has_values:
        raise ValueError(f"Knowledge card publishes no values: {spec.get('title', 'untitled')}")
    eyebrow = spec.get("eyebrow")
    eyebrow_html = f'<p class="knowledge-card-eyebrow">{html.escape(str(eyebrow))}</p>' if eyebrow else ""
    if layout == "editorial":
        return _render_editorial_knowledge_card(spec, card_class, eyebrow_html, content)
    field_list_class = "knowledge-fields knowledge-fields--single" if len(content.rows) == 1 else "knowledge-fields"
    return (
        f'<article class="{card_class}">'
        + eyebrow_html
        + f'<h3>{html.escape(str(spec["title"]))}</h3>'
        + f'<dl class="{field_list_class}">'
        + "".join(content.rows)
        + "</dl></article>"
    )


def render_knowledge_page(root: Path, page: dict[str, Any]) -> str:
    sections: list[str] = []
    for section in page.get("sections", []):
        section_layout = section.get("layout", "standard")
        if section_layout not in {"standard", "editorial", "continuity"}:
            raise ValueError(f"Unsupported knowledge section layout: {section_layout}")
        cards: list[str] = []
        for card in section.get("cards", []):
            source = safe_source(root, card["source"])
            default_card_layout = "editorial" if section_layout == "continuity" else section_layout
            card_spec = {**card, "layout": card.get("layout", default_card_layout)}
            cards.append(render_knowledge_card(load_json(source), card_spec))
        if not cards:
            raise ValueError(f"Knowledge section has no cards: {section.get('title', 'untitled')}")
        description = section.get("description")
        description_html = f'<p class="knowledge-section-intro">{html.escape(str(description))}</p>' if description else ""
        sections.append(
            f'<section class="knowledge-section knowledge-section--{html.escape(section_layout, quote=True)}">'
            f'<h2>{html.escape(str(section["title"]))}</h2>'
            + description_html
            + '<div class="knowledge-grid">'
            + "".join(cards)
            + "</div></section>"
        )
    return "".join(sections)


def render_cv_template_preview(document: dict[str, Any]) -> str:
    rendering = document.get("rendering")
    if not isinstance(rendering, dict):
        return ""
    engine = rendering.get("engine")
    if engine not in {"standard-single-column-v1", "signature-editorial-pdf-v1"}:
        raise ValueError(f"Unsupported CV preview engine: {engine}")

    section_order = rendering.get("sections", [])
    if len(section_order) != len(set(section_order)):
        raise ValueError("CV preview sections must be unique")

    sections = {
        "profile": (
            "Profil",
            '<p class="cv-preview-summary">Accroche ciblée en quelques lignes : proposition de valeur, '
            "expérience pertinente et objectif professionnel.</p>",
        ),
        "key-skills": (
            "Compétences clés",
            '<ul class="cv-preview-skills"><li>Compétence métier</li><li>Relation client</li>'
            "<li>Gestion de projet</li><li>Management</li><li>Outil maîtrisé</li><li>Langue</li></ul>",
        ),
        "professional-experience": (
            "Expérience professionnelle",
            '<div class="cv-preview-experience"><p class="cv-preview-date">MM/AAAA — MM/AAAA</p>'
            '<div><h4>Intitulé du poste · Organisation</h4><p>Ville · Type de contrat</p>'
            "<ul><li>Responsabilité directement liée au poste ciblé.</li>"
            "<li>Action concrète directement liée au poste ciblé.</li>"
            "<li>Résultat mesurable lorsque cela apporte une information utile.</li></ul></div></div>"
            '<div class="cv-preview-experience"><p class="cv-preview-date">MM/AAAA — MM/AAAA</p>'
            '<div><h4>Expérience précédente · Organisation</h4>'
            "<ul><li>Deux à quatre points courts, concrets et vérifiables.</li>"
            "<li>Les expériences anciennes sont condensées selon leur pertinence.</li></ul></div></div>",
        ),
        "education": (
            "Formation",
            '<div class="cv-preview-line"><strong>AAAA · Diplôme ou formation</strong>'
            "<span>Établissement · Ville</span></div>",
        ),
        "languages": (
            "Langues",
            '<p class="cv-preview-inline"><strong>Langue</strong> · niveau oral · niveau écrit · cadre éventuel</p>',
        ),
        "engagements-and-interests": (
            "Engagements et centres d’intérêt",
            '<p class="cv-preview-inline">Éléments personnels pertinents pour la candidature.</p>',
        ),
    }

    rendered_sections: list[str] = []
    for section_id in section_order:
        if section_id not in sections:
            raise ValueError(f"Unsupported CV preview section: {section_id}")
        label, content = sections[section_id]
        rendered_sections.append(
            f'<section class="cv-preview-section" data-section="{html.escape(section_id, quote=True)}">'
            f"<h3>{html.escape(label)}</h3>{content}</section>"
        )

    maximum_pages = html.escape(str(rendering.get("maximum_pages", "?")))
    photo_policy = rendering.get("photo_policy")
    photo_note = (
        "Photo optionnelle, désactivée par défaut"
        if photo_policy == "optional-disabled-by-default"
        else "Sans photo" if photo_policy == "disabled" else "Photo prévue"
    )
    return (
        '<div class="cv-preview-shell">'
        '<div class="cv-preview-caption"><strong>Aperçu structurel</strong>'
        f"<span>Contenu fictif · {maximum_pages} pages maximum · {html.escape(photo_note)}</span></div>"
        '<article class="cv-preview" aria-label="Aperçu fictif du template de CV">'
        '<header class="cv-preview-header"><p class="cv-preview-name">PRÉNOM NOM</p>'
        '<p class="cv-preview-headline">INTITULÉ DU POSTE CIBLÉ</p>'
        '<p class="cv-preview-contact">Ville · téléphone · prenom.nom@example.fr · profil professionnel</p>'
        "</header>"
        + "".join(rendered_sections)
        + "</article></div>"
    )


def parse_skill_metadata(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"Missing frontmatter in {path}")
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip().strip('"')
    if not metadata.get("name") or not metadata.get("description"):
        raise ValueError(f"Incomplete skill metadata in {path}")
    return metadata


def render_skill_catalog(root: Path) -> str:
    skills_root = safe_source(root, ".codex/skills")
    cards: list[str] = []
    for path in sorted(skills_root.glob("*/SKILL.md")):
        metadata = parse_skill_metadata(path)
        cards.append(
            '<article class="skill-card">'
            f'<p class="skill-name"><code>${html.escape(metadata["name"])}</code></p>'
            f'<p>{html.escape(metadata["description"])}</p>'
            "</article>"
        )
    return '<section><h2>Catalogue des skills</h2><div class="card-grid">' + "".join(cards) + "</div></section>"


def render_mental_model(model: dict[str, Any]) -> str:
    summary = model_summary(model)
    if not summary["ok"]:
        raise ValueError("Invalid mental model: " + "; ".join(summary["errors"]))
    labels = {concept["id"]: concept["label"] for concept in model["concepts"]}
    concept_cards: list[str] = []
    for concept in model["concepts"]:
        attributes = "".join(f"<li>{html.escape(str(item))}</li>" for item in concept["key_attributes"])
        concept_cards.append(
            '<article class="concept-card">'
            f'<div class="tag-row"><span>{html.escape(concept["kind"])}</span><span>{html.escape(concept["privacy"])}</span></div>'
            f'<h3>{html.escape(concept["label"])}</h3>'
            f'<p><code>{html.escape(concept["id"])}</code></p>'
            f'<p>{html.escape(concept["description"])}</p>'
            f'<p class="storage">Stockage : <code>{html.escape(concept["storage"])}</code></p>'
            f'<details><summary>Attributs structurants</summary><ul>{attributes}</ul></details>'
            "</article>"
        )
    relation_rows = "".join(
        "<tr>"
        f'<td><code>{html.escape(relation["id"])}</code></td>'
        f'<td>{html.escape(labels[relation["from"]])}</td>'
        f'<td>{html.escape(relation["label"])}</td>'
        f'<td>{html.escape(labels[relation["to"]])}</td>'
        f'<td><code>{html.escape(relation["cardinality"])}</code></td>'
        "</tr>"
        for relation in model["relations"]
    )
    invariants = "".join(
        f'<li><code>{html.escape(item["id"])}</code> — {html.escape(item["rule"])}</li>'
        for item in model.get("invariants", [])
    )
    return (
        f'<p class="model-summary">Version {html.escape(str(summary["model_version"]))} · '
        f'{summary["concept_count"]} concepts · {summary["relation_count"]} relations · '
        f'{summary["invariant_count"]} invariants</p>'
        '<section><h2>Invariants</h2><ul>' + invariants + "</ul></section>"
        '<section><h2>Concepts</h2><div class="card-grid">' + "".join(concept_cards) + "</div></section>"
        '<section><h2>Relations</h2><div class="table-scroll"><table><thead><tr>'
        "<th>Identifiant</th><th>Depuis</th><th>Lien</th><th>Vers</th><th>Cardinalité</th>"
        "</tr></thead><tbody>" + relation_rows + "</tbody></table></div></section>"
    )


def _page_template(
    site: dict[str, Any],
    page: dict[str, Any],
    navigation: list[dict[str, Any]],
    body: str,
    asset_version: str,
) -> str:
    nav_items: list[str] = []
    for item in navigation:
        href = "index.html" if item["slug"] == "index" else item["slug"] + ".html"
        current = ' aria-current="page"' if item["slug"] == page["slug"] else ""
        nav_items.append(f'<a href="{href}"{current}>{html.escape(item["title"])}</a>')
    nav = "".join(nav_items)
    title = html.escape(page["title"])
    site_title = html.escape(site["title"])
    description = html.escape(site.get("description", ""), quote=True)
    if page["slug"] == "index":
        ats_cards = "".join(
            '<article class="cv-download-card">'
            f'<p class="cv-download-kicker">{"CV socle" if variant.id == "transverse" else "CV ciblé"}</p>'
            f'<h3>{html.escape(variant.label)}</h3>'
            f'<p>{html.escape(variant.description)}</p>'
            '<div class="cv-download-actions">'
            f'<a href="assets/downloads/{html.escape(variant.pdf_filename, quote=True)}" download>PDF</a>'
            f'<a href="assets/downloads/{html.escape(variant.docx_filename, quote=True)}" download>Word</a>'
            '</div></article>'
            for variant in ATS_VARIANTS
        )
        page_content = f"""
  <main class="page page-home">
    <section class="hero" aria-labelledby="hero-title">
      <div class="hero-copy">
        <p class="eyebrow">Parcours professionnel</p>
        <h1 id="hero-title">Le parcours de Délia,<br><em>pensé sur mesure.</em></h1>
        <p class="hero-lead">Un parcours façonné par le conseil, le commerce, la gestion de projets et l’entrepreneuriat.</p>
        <div class="hero-actions">
          <a class="button button-primary" href="assets/downloads/cv-delia-rossignol-signature.pdf" download>CV Signature (PDF)</a>
          <a class="button button-secondary" href="#cv-downloads">Choisir un CV ATS</a>
          <a class="button button-secondary" href="profil.html">Découvrir le profil</a>
        </div>
      </div>
      <div class="hero-visual">
        <img class="portrait-logo" src="assets/delia-rossignol-logo.svg" alt="" width="365" height="254">
        <div class="portrait-frame">
          <img src="assets/delia-rossignol.avif" alt="Portrait de Délia Rossignol" width="656" height="998">
        </div>
      </div>
    </section>
    <section class="cv-downloads" id="cv-downloads" aria-labelledby="cv-downloads-title">
      <div class="cv-downloads-shell">
        <p class="eyebrow">Candidatures</p>
        <h2 id="cv-downloads-title">Choisir le CV adapté</h2>
        <p class="cv-downloads-intro">Le CV transverse présente les quatre domaines prioritaires. Les trois variantes renforcent les mots-clés et les preuves du métier visé, sans modifier les faits.</p>
        <p class="cv-ats-note"><strong>ATS, c’est quoi&nbsp;?</strong> ATS signifie <em>Applicant Tracking System</em>, ou «&nbsp;système de suivi des candidatures&nbsp;»&nbsp;: un logiciel qui aide les recruteurs à lire, organiser et rechercher les CV. Ces versions utilisent une structure simple et des mots-clés explicites.</p>
        <div class="cv-download-grid">{ats_cards}</div>
      </div>
    </section>
    <section class="home-content" aria-label="Présentation du dossier">
      {body}
    </section>
  </main>"""
    else:
        page_content = f"""
  <main class="page page-{html.escape(page['slug'], quote=True)}">
    <div class="page-shell">
      <p class="eyebrow">Parcours professionnel</p>
      <h1>{title}</h1>
      {body}
    </div>
  </main>"""
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{description}">
  <title>{title} · {site_title}</title>
  <link rel="stylesheet" href="assets/style.css?v={html.escape(asset_version, quote=True)}">
</head>
<body>
  <header class="site-header">
    <a class="brand" href="index.html" aria-label="{site_title} — accueil">
      <img src="assets/delia-rossignol-logo.svg" alt="" width="365" height="254">
    </a>
    <nav aria-label="Navigation principale">{nav}</nav>
  </header>
{page_content}
  <footer>
    <span>Délia Rossignol</span>
    <span>Parcours, expériences et réalisations.</span>
  </footer>
</body>
</html>
"""


def _prepare_output(root: Path, output: Path) -> Path:
    output = output.resolve()
    if output == root.resolve():
        raise ValueError("Site output cannot be the project root")
    if output.exists():
        marker = output / ".delia-site-output"
        if any(output.iterdir()) and not marker.exists():
            raise ValueError(f"Refusing to replace unmarked output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    (output / ".delia-site-output").write_text("generated\n", encoding="utf-8")
    return output


def _validate_page_slugs(pages: list[dict[str, Any]]) -> None:
    slugs: set[str] = set()
    for page in pages:
        slug = page["slug"]
        if not SLUG_PATTERN.fullmatch(slug) or slug in slugs:
            raise ValueError(f"Invalid or duplicate page slug: {slug}")
        slugs.add(slug)
    if "index" not in slugs:
        raise ValueError("Publication requires an index page")


def _render_collection_page(root: Path, page: dict[str, Any]) -> str:
    pattern = page["source_glob"]
    prefix = pattern.split("*", 1)[0].rstrip("/\\")
    safe_source(root, prefix)
    cards: list[str] = []
    for source in sorted(root.glob(pattern)):
        safe_source(root, source.relative_to(root).as_posix())
        template_document = load_json(source)
        name = html.escape(str(template_document.get("name", source.parent.name)))
        preview = render_cv_template_preview(template_document)
        cards.append(
            f'<article class="template-card"><h2>{name}</h2>'
            f"{render_json_document(template_document, page)}{preview}</article>"
        )
    return '<div class="card-grid">' + "".join(cards) + "</div>"


def _render_page_body(root: Path, page: dict[str, Any]) -> str:
    kind = page["kind"]
    if kind in {"markdown", "administration"}:
        source = safe_source(root, page["source"])
        return markdown_to_html(source.read_text(encoding="utf-8"))
    if kind == "json":
        sections: list[str] = []
        for section in page["sections"]:
            page_document = load_json(safe_source(root, section["source"]))
            heading = html.escape(section["title"])
            sections.append(f"<section><h2>{heading}</h2>{render_json_document(page_document, section)}</section>")
        return "".join(sections)
    if kind == "collection":
        return _render_collection_page(root, page)
    if kind == "knowledge":
        return render_knowledge_page(root, page)
    if kind == "mental-model":
        return render_mental_model(load_mental_model(safe_source(root, page["source"])))
    raise ValueError(f"Unsupported page kind: {kind}")


def _write_site_pages(
    root: Path,
    output: Path,
    site: dict[str, Any],
    pages: list[dict[str, Any]],
    asset_version: str,
) -> list[str]:
    built: list[str] = []
    for page in pages:
        filename = "index.html" if page["slug"] == "index" else f'{page["slug"]}.html'
        (output / filename).write_text(
            _page_template(site, page, pages, _render_page_body(root, page), asset_version),
            encoding="utf-8",
            newline="\n",
        )
        built.append(filename)
    return built


def _remove_stale_files(output: Path, stale_files: set[str]) -> None:
    for stale in sorted(stale_files):
        stale_path = (output / stale).resolve()
        try:
            stale_path.relative_to(output)
        except ValueError as error:
            raise ValueError(f"Unsafe stale output path: {stale}") from error
        if stale_path.is_file():
            stale_path.unlink()


def _build_site_in_place(
    root: Path,
    output: Path,
    config_path: Path | None = None,
    cv_document: dict[str, Any] | None = None,
) -> SiteBuildResult:
    root = root.resolve()
    config_path = config_path or root / "site" / "publication.json"
    config = load_json(config_path)
    site = config["site"]
    pages = config["pages"]
    _validate_page_slugs(pages)

    output = _prepare_output(root, output)
    assets_source = safe_source(root, "site/assets")
    previous_manifest_path = output / ".delia-site-manifest.json"
    previous_files = set(load_json(previous_manifest_path).get("files", [])) if previous_manifest_path.exists() else set()
    shutil.copytree(assets_source, output / "assets", dirs_exist_ok=True)
    if cv_document is None:
        cv_document = build_standard_cv(root, output / "assets" / "downloads" / STANDARD_CV_FILENAME)
    else:
        cv_document = {
            **cv_document,
            "output": str(output / "assets" / "downloads" / STANDARD_CV_FILENAME),
        }
    asset_version = sha256_file(output / "assets" / "style.css")[:12]
    (output / ".nojekyll").write_text("", encoding="utf-8")

    built = _write_site_pages(root, output, site, pages, asset_version)

    asset_files = [path.relative_to(output).as_posix() for path in (output / "assets").rglob("*") if path.is_file()]
    current_files = set(built + asset_files + [".nojekyll", ".delia-site-output"])
    _remove_stale_files(output, previous_files - current_files)
    (output / ".delia-site-manifest.json").write_text(
        json.dumps({"files": sorted(current_files)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "output": str(output),
        "pages": built,
        "documents": [cv_document],
        "published_sources_are_allowlisted": True,
        "staging_cleanup": {"removed": 0, "remaining": 0},
    }


def _cleanup_stale_site_builds(
    staging_root: Path,
    output_name: str | None,
    time_budget_seconds: float = 0.25,
    minimum_age_seconds: float = 3600.0,
) -> dict[str, int]:
    deadline = time.monotonic() + max(0.0, time_budget_seconds)
    removed = 0
    pattern = f"{output_name}.staging-*" if output_name else "*.staging-*"
    for stale_staging in staging_root.glob(pattern):
        if time.monotonic() >= deadline:
            break
        try:
            age_seconds = time.time() - stale_staging.stat().st_mtime
        except OSError:
            continue
        if age_seconds < minimum_age_seconds:
            continue
        remove_tree(stale_staging, ignore_errors=True)
        removed += not stale_staging.exists()
    remaining = sum(1 for _ in staging_root.glob(pattern))
    return {"removed": removed, "remaining": remaining}


def _site_runtime_root(root: Path) -> Path:
    project_key = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "delia-rossignol-life" / "site-builds" / project_key


def _relative_staged_path(path: Path, staging: Path, staged_files: list[Path]) -> Path:
    try:
        return path.relative_to(staging)
    except ValueError as error:
        for candidate in staged_files:
            try:
                if candidate.samefile(path):
                    return candidate.relative_to(staging)
            except OSError:
                continue
        raise ValueError(f"Generated document is outside site staging: {path}") from error


def build_site(
    root: Path,
    output: Path,
    config_path: Path | None = None,
    cv_document: dict[str, Any] | None = None,
) -> SiteBuildResult:
    """Build completely in staging, then publish files with rollback protection."""
    root = root.resolve()
    output = output.resolve()
    if output == root:
        raise ValueError("Site output cannot be the project root")
    if output.exists() and any(output.iterdir()) and not (output / ".delia-site-output").exists():
        raise ValueError(f"Refusing to replace unmarked output directory: {output}")
    transaction_id = uuid.uuid4().hex
    staging_root = _site_runtime_root(root)
    staging_root.mkdir(parents=True, exist_ok=True)
    cleanup = _cleanup_stale_site_builds(staging_root, None)
    staging = staging_root / f"{output.name}.staging-{transaction_id}"
    try:
        result = _build_site_in_place(root, staging, config_path, cv_document)
        result["staging_cleanup"] = cleanup
        output.mkdir(parents=True, exist_ok=True)
        lock_path = staging_root / "site-publish.lock"
        with exclusive_directory_lock(lock_path):
            previous_manifest = output / ".delia-site-manifest.json"
            previous_files = set(load_json(previous_manifest).get("files", [])) if previous_manifest.exists() else set()
            staged_files = [path for path in staging.rglob("*") if path.is_file()]
            changes = {output / path.relative_to(staging): path.read_bytes() for path in staged_files}
            atomic_write_bytes_group(changes)
            current_files = {path.relative_to(staging).as_posix() for path in staged_files}
            _remove_stale_files(output, previous_files - current_files)
        result["output"] = str(output)
        for document in result.get("documents", []):
            document_path = Path(document["output"])
            document["output"] = str(output / _relative_staged_path(document_path, staging, staged_files))
        return result
    finally:
        if staging.exists():
            build_failed = sys.exc_info()[0] is not None
            try:
                remove_tree(staging, attempts=3)
            except OSError:
                if not build_failed:
                    raise
