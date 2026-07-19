from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .core import load_json
from .site_builder import _nested_value, safe_source

PRESENTATIONS = {None, "detail", "badge"}
TECHNICAL_LABEL_PATTERN = re.compile(r"\b(valid\w*|validation|provenance|claim|inference)\b", re.IGNORECASE)


def audit_site(root: Path, config_path: Path | None = None) -> dict[str, Any]:
    """Audit the public projection before build, without changing its content."""
    root = root.resolve()
    config = load_json(config_path or root / "site" / "publication.json")
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    inspected_cards = 0
    for page in config.get("pages", []):
        if page.get("kind") != "knowledge":
            continue
        slug = str(page.get("slug", "untitled"))
        for section in page.get("sections", []):
            for card in section.get("cards", []):
                inspected_cards += 1
                location = f"{slug}/{card.get('title', 'untitled')}"
                try:
                    document = load_json(safe_source(root, str(card["source"])))
                except (KeyError, FileNotFoundError, ValueError) as error:
                    errors.append({"location": location, "message": str(error)})
                    continue
                fields = card.get("fields", [])
                if not fields:
                    errors.append({"location": location, "message": "knowledge card has no explicit fields"})
                    continue
                published = 0
                for field in fields:
                    label, path, presentation = str(field.get("label", "")), field.get("path"), field.get("presentation")
                    field_location = f"{location}/{label or path or 'unlabelled'}"
                    if presentation not in PRESENTATIONS:
                        errors.append({"location": field_location, "message": f"unsupported presentation: {presentation}"})
                    if not path or not label:
                        errors.append({"location": field_location, "message": "knowledge field requires path and label"})
                        continue
                    try:
                        value = _nested_value(document, str(path))
                    except ValueError as error:
                        errors.append({"location": field_location, "message": str(error)})
                        continue
                    if value is None or value == "" or value == []:
                        warnings.append({"location": field_location, "message": "allowlisted field has no value and will not be published"})
                        continue
                    published += 1
                    if presentation == "badge" and (isinstance(value, dict) or (isinstance(value, list) and any(isinstance(item, (dict, list)) for item in value))):
                        errors.append({"location": field_location, "message": "badge presentation requires scalar values"})
                    if TECHNICAL_LABEL_PATTERN.search(label):
                        warnings.append({"location": field_location, "message": "public label appears to expose an internal validation term"})
                if not published:
                    errors.append({"location": location, "message": "knowledge card publishes no values"})
    return {"ok": not errors, "inspected_cards": inspected_cards, "errors": errors, "warnings": warnings}
