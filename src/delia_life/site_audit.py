from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any

from .core import load_json
from .site_builder import _nested_value, safe_source

PRESENTATIONS = {None, "detail", "badge"}
CARD_VARIANTS = {None, "continuity-foundation", "continuity-context", "continuity-highlight"}
TECHNICAL_LABEL_PATTERN = re.compile(r"\b(valid\w*|validation|provenance|claim|inference)\b", re.IGNORECASE)


@dataclass
class SiteAuditResult:
    errors: list[dict[str, str]] = dataclass_field(default_factory=list)
    warnings: list[dict[str, str]] = dataclass_field(default_factory=list)
    inspected_cards: int = 0

    def error(self, location: str, message: str) -> None:
        self.errors.append({"location": location, "message": message})

    def warning(self, location: str, message: str) -> None:
        self.warnings.append({"location": location, "message": message})

    def report(self) -> dict[str, Any]:
        return {
            "ok": not self.errors,
            "inspected_cards": self.inspected_cards,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def _audit_field(
    document: dict[str, Any],
    field: dict[str, Any],
    card_location: str,
    result: SiteAuditResult,
) -> bool:
    label = str(field.get("label", ""))
    path = field.get("path")
    presentation = field.get("presentation")
    location = f"{card_location}/{label or path or 'unlabelled'}"
    if presentation not in PRESENTATIONS:
        result.error(location, f"unsupported presentation: {presentation}")
    if not path or not label:
        result.error(location, "knowledge field requires path and label")
        return False
    try:
        value = _nested_value(document, str(path))
    except ValueError as error:
        result.error(location, str(error))
        return False
    if value is None or value == "" or value == []:
        result.warning(location, "allowlisted field has no value and will not be published")
        return False
    if presentation == "badge" and (
        isinstance(value, dict)
        or (isinstance(value, list) and any(isinstance(item, (dict, list)) for item in value))
    ):
        result.error(location, "badge presentation requires scalar values")
    if TECHNICAL_LABEL_PATTERN.search(label):
        result.warning(location, "public label appears to expose an internal validation term")
    return True


def _audit_card(root: Path, slug: str, card: dict[str, Any], result: SiteAuditResult) -> None:
    result.inspected_cards += 1
    location = f"{slug}/{card.get('title', 'untitled')}"
    try:
        document = load_json(safe_source(root, str(card["source"])))
    except (KeyError, FileNotFoundError, ValueError) as error:
        result.error(location, str(error))
        return
    fields = card.get("fields", [])
    if card.get("variant") not in CARD_VARIANTS:
        result.error(location, f"unsupported card variant: {card.get('variant')}")
    if not fields:
        result.error(location, "knowledge card has no explicit fields")
        return
    published = sum(_audit_field(document, field, location, result) for field in fields)
    if not published:
        result.error(location, "knowledge card publishes no values")


def _audit_page(root: Path, page: dict[str, Any], result: SiteAuditResult) -> None:
    if page.get("kind") != "knowledge":
        return
    slug = str(page.get("slug", "untitled"))
    for section in page.get("sections", []):
        for card in section.get("cards", []):
            _audit_card(root, slug, card, result)


def audit_site(root: Path, config_path: Path | None = None) -> dict[str, Any]:
    """Audit the public projection before build, without changing its content."""
    root = root.resolve()
    config = load_json(config_path or root / "site" / "publication.json")
    result = SiteAuditResult()
    for page in config.get("pages", []):
        _audit_page(root, page, result)
    return result.report()
