from __future__ import annotations

import html
import json
import re
import shutil
import urllib.parse
from pathlib import Path
from typing import Any

from .core import load_json
from .mental_model import load_mental_model, model_summary


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
INLINE_PATTERN = re.compile(r"`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)")


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
        else:
            label = html.escape(match.group(2) or "")
            target = match.group(3) or ""
            parsed = urllib.parse.urlsplit(target)
            safe_relative = not parsed.scheme and not parsed.netloc and not target.startswith("//")
            if parsed.scheme in {"https", "http", "mailto"} or safe_relative:
                chunks.append(f'<a href="{html.escape(target, quote=True)}">{label}</a>')
            else:
                chunks.append(label)
        position = match.end()
    chunks.append(html.escape(text[position:]))
    return "".join(chunks)


def markdown_to_html(markdown: str) -> str:
    output: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    in_code = False
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{render_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            output.append(f"</{list_kind}>")
            list_kind = None

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.startswith("```"):
            flush_paragraph()
            close_list()
            if in_code:
                output.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(raw_line)
            continue
        if not line.strip():
            flush_paragraph()
            close_list()
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            output.append(f"<h{level}>{render_inline(heading.group(2))}</h{level}>")
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", line)
        numbered = re.match(r"^\d+\.\s+(.+)$", line)
        if bullet or numbered:
            flush_paragraph()
            wanted = "ul" if bullet else "ol"
            if list_kind != wanted:
                close_list()
                output.append(f"<{wanted}>")
                list_kind = wanted
            match = bullet or numbered
            output.append(f"<li>{render_inline(match.group(1))}</li>")
            continue
        paragraph.append(line.strip())

    if in_code:
        output.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
    flush_paragraph()
    close_list()
    return "\n".join(output)


def _label(name: str, labels: dict[str, str]) -> str:
    return labels.get(name, name.replace("_", " ").replace("-", " ").capitalize())


def _render_scalar(value: Any) -> str:
    if value is None or value == "":
        return '<span class="empty">À renseigner</span>'
    if isinstance(value, bool):
        return "Oui" if value else "Non"
    return html.escape(str(value))


def _render_value(value: Any, item_fields: list[str] | None, labels: dict[str, str]) -> str:
    if isinstance(value, list):
        if not value:
            return '<span class="empty">Aucune information publiée</span>'
        if all(not isinstance(item, (dict, list)) for item in value):
            return "<ul>" + "".join(f"<li>{_render_scalar(item)}</li>" for item in value) + "</ul>"
        if not item_fields:
            raise ValueError("item_fields is required to publish structured list items")
        cards: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("Mixed structured and scalar list cannot be published")
            rows = "".join(
                f"<dt>{html.escape(_label(field, labels))}</dt><dd>{_render_scalar(item.get(field))}</dd>"
                for field in item_fields
            )
            cards.append(f'<article class="data-card"><dl>{rows}</dl></article>')
        return '<div class="card-grid">' + "".join(cards) + "</div>"
    if isinstance(value, dict):
        if not item_fields:
            raise ValueError("item_fields is required to publish object values")
        rows = "".join(
            f"<dt>{html.escape(_label(field, labels))}</dt><dd>{_render_scalar(value.get(field))}</dd>"
            for field in item_fields
        )
        return f"<dl>{rows}</dl>"
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


def _page_template(site: dict[str, Any], page: dict[str, Any], navigation: list[dict[str, Any]], body: str) -> str:
    nav = "".join(
        f'<a href="{"index.html" if item["slug"] == "index" else item["slug"] + ".html"}"'
        f'{" aria-current=\"page\"" if item["slug"] == page["slug"] else ""}>{html.escape(item["title"])}</a>'
        for item in navigation
    )
    title = html.escape(page["title"])
    site_title = html.escape(site["title"])
    description = html.escape(site.get("description", ""), quote=True)
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{description}">
  <title>{title} · {site_title}</title>
  <link rel="stylesheet" href="assets/style.css">
</head>
<body>
  <header class="site-header">
    <a class="brand" href="index.html">{site_title}</a>
    <nav aria-label="Navigation principale">{nav}</nav>
  </header>
  <main>
    <p class="eyebrow">Dossier professionnel structuré</p>
    <h1>{title}</h1>
    {body}
  </main>
  <footer>Informations publiées depuis une base de connaissances validée.</footer>
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


def build_site(root: Path, output: Path, config_path: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    config_path = config_path or root / "site" / "publication.json"
    config = load_json(config_path)
    site = config["site"]
    pages = config["pages"]
    slugs: set[str] = set()
    for page in pages:
        slug = page["slug"]
        if not SLUG_PATTERN.fullmatch(slug) or slug in slugs:
            raise ValueError(f"Invalid or duplicate page slug: {slug}")
        slugs.add(slug)
    if "index" not in slugs:
        raise ValueError("Publication requires an index page")

    output = _prepare_output(root, output)
    assets_source = safe_source(root, "site/assets")
    previous_manifest_path = output / ".delia-site-manifest.json"
    previous_files = set(load_json(previous_manifest_path).get("files", [])) if previous_manifest_path.exists() else set()
    shutil.copytree(assets_source, output / "assets", dirs_exist_ok=True)
    (output / ".nojekyll").write_text("", encoding="utf-8")

    built: list[str] = []
    for page in pages:
        kind = page["kind"]
        if kind in {"markdown", "administration"}:
            source = safe_source(root, page["source"])
            body = markdown_to_html(source.read_text(encoding="utf-8"))
            if kind == "administration":
                body += render_skill_catalog(root)
        elif kind == "json":
            sections: list[str] = []
            for section in page["sections"]:
                source = safe_source(root, section["source"])
                document = load_json(source)
                heading = html.escape(section["title"])
                sections.append(f"<section><h2>{heading}</h2>{render_json_document(document, section)}</section>")
            body = "".join(sections)
        elif kind == "collection":
            pattern = page["source_glob"]
            prefix = pattern.split("*", 1)[0].rstrip("/\\")
            safe_source(root, prefix)
            documents = sorted(root.glob(pattern))
            cards: list[str] = []
            for source in documents:
                safe_source(root, source.relative_to(root).as_posix())
                document = load_json(source)
                name = html.escape(str(document.get("name", source.parent.name)))
                cards.append(f'<article class="template-card"><h2>{name}</h2>{render_json_document(document, page)}</article>')
            body = '<div class="card-grid">' + "".join(cards) + "</div>"
        elif kind == "mental-model":
            source = safe_source(root, page["source"])
            body = render_mental_model(load_mental_model(source))
        else:
            raise ValueError(f"Unsupported page kind: {kind}")
        filename = "index.html" if page["slug"] == "index" else f'{page["slug"]}.html'
        (output / filename).write_text(_page_template(site, page, pages, body), encoding="utf-8", newline="\n")
        built.append(filename)

    asset_files = [path.relative_to(output).as_posix() for path in (output / "assets").rglob("*") if path.is_file()]
    current_files = set(built + asset_files + [".nojekyll", ".delia-site-output"])
    for stale in sorted(previous_files - current_files):
        stale_path = (output / stale).resolve()
        try:
            stale_path.relative_to(output)
        except ValueError as error:
            raise ValueError(f"Unsafe stale output path: {stale}") from error
        if stale_path.is_file():
            stale_path.unlink()
    (output / ".delia-site-manifest.json").write_text(
        json.dumps({"files": sorted(current_files)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {"output": str(output), "pages": built, "published_sources_are_allowlisted": True}
