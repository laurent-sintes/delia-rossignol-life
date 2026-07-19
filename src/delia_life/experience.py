from __future__ import annotations

from pathlib import Path

from .core import load_json


def _has_non_empty_list(value: object) -> bool:
    return isinstance(value, list) and bool(value)


def missing_experience_missions(knowledge_root: Path) -> list[tuple[Path, str]]:
    """Return validated experience records without a non-empty mission statement."""
    missing: list[tuple[Path, str]] = []
    experience_root = knowledge_root / "experience"
    for path in sorted(experience_root.glob("*.json")):
        document = load_json(path)
        mission = document.get("fields", {}).get("mission", {}).get("value")
        if not isinstance(mission, str) or not mission.strip():
            missing.append((path, str(document.get("id", path.stem))))
    return missing


def missing_experience_responsibilities(knowledge_root: Path) -> list[tuple[Path, str]]:
    """Return experiences without validated responsibilities in either supported storage shape."""
    missing: list[tuple[Path, str]] = []
    experience_root = knowledge_root / "experience"
    for path in sorted(experience_root.glob("*.json")):
        document = load_json(path)
        fields = document.get("fields", {})
        direct = fields.get("responsibilities", {}).get("value")
        embedded = fields.get("details", {}).get("value", {}).get("responsibilities")
        if not _has_non_empty_list(direct) and not _has_non_empty_list(embedded):
            missing.append((path, str(document.get("id", path.stem))))
    return missing
