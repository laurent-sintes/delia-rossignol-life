from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

COMMAND_PATTERN = re.compile(r"python\s+scripts/(?P<script>delia_life|repo_flow)\.py\s+(?P<command>[a-z][a-z0-9-]*)")
SKILL_REFERENCE_PATTERN = re.compile(r"\$([a-z][a-z0-9-]+)")
REQUIRED_SKILL_SNIPPETS = {
    "ingest-delia-knowledge": ("review-content",),
    "manage-delia-templates": ("review-content",),
    "match-delia-offers": ("review-operational",),
    "manage-delia-offer-scans": (
        "revalidation_queue",
        "--scan-manifest",
        "--covered-query-family",
        "--covered-priority-sector",
    ),
    "search-delia-offers": (
        "credential_id",
        "revalidation_queue",
        "--scan-manifest",
        "--covered-query-family",
        "--covered-priority-sector",
        "review-operational",
    ),
    "share-delia-offer-selection": ("finalization_allowed: false", "--limit", "100", "review-operational"),
}


def _parser_commands(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    commands: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_parser" or not node.args:
            continue
        value = node.args[0]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            commands.add(value.value)
    return commands


def _read_skill(path: Path) -> tuple[dict[str, Any], str]:
    content = path.read_text(encoding="utf-8")
    parts = content.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError("SKILL.md must start with YAML frontmatter")
    metadata = yaml.safe_load(parts[1])
    if not isinstance(metadata, dict):
        raise ValueError("skill frontmatter must be an object")
    return metadata, parts[2]


def validate_skill_catalog(root: Path) -> dict[str, Any]:
    """Validate skill metadata and every documented project command."""
    skills_root = root / ".codex" / "skills"
    allowed_commands = {
        "delia_life": _parser_commands(root / "src" / "delia_life" / "cli.py"),
        "repo_flow": _parser_commands(root / "scripts" / "repo_flow.py"),
    }
    errors: list[str] = []
    skill_names: list[str] = []
    skill_bodies: dict[str, tuple[Path, str]] = {}
    for skill_file in sorted(skills_root.glob("*/SKILL.md")):
        folder_name = skill_file.parent.name
        try:
            metadata, body = _read_skill(skill_file)
        except (OSError, ValueError, yaml.YAMLError) as error:
            errors.append(f"{skill_file.relative_to(root)}: {error}")
            continue
        unexpected = set(metadata) - {"name", "description"}
        if unexpected:
            errors.append(f"{skill_file.relative_to(root)}: unsupported frontmatter keys: {sorted(unexpected)}")
        name = metadata.get("name")
        description = metadata.get("description")
        if name != folder_name:
            errors.append(f"{skill_file.relative_to(root)}: name must match folder {folder_name}")
        if not isinstance(description, str) or not description.strip():
            errors.append(f"{skill_file.relative_to(root)}: description is required")
        if isinstance(name, str):
            skill_names.append(name)
            skill_bodies[name] = (skill_file, body)
        for match in COMMAND_PATTERN.finditer(body):
            script = match.group("script")
            command = match.group("command")
            if command not in allowed_commands[script]:
                errors.append(f"{skill_file.relative_to(root)}: unknown {script}.py command {command}")
    duplicates = sorted({name for name in skill_names if skill_names.count(name) > 1})
    if duplicates:
        errors.append(f"duplicate skill names: {duplicates}")
    known_skills = set(skill_names)
    for name, (skill_file, body) in skill_bodies.items():
        for reference in SKILL_REFERENCE_PATTERN.findall(body):
            if reference not in known_skills:
                errors.append(f"{skill_file.relative_to(root)}: unknown skill reference ${reference}")
        for snippet in REQUIRED_SKILL_SNIPPETS.get(name, ()):
            if snippet not in body:
                errors.append(f"{skill_file.relative_to(root)}: required workflow marker is missing: {snippet}")
        if name in {"manage-delia-offer-scans", "search-delia-offers", "share-delia-offer-selection"} and re.search(
            r"(?:limite|plafond|max(?:imum)?)\D{0,12}50\b", body, re.IGNORECASE
        ):
            errors.append(f"{skill_file.relative_to(root)}: obsolete 50-result limit")
    return {
        "ok": not errors,
        "skills": len(skill_names),
        "errors": errors,
        "commands": {key: sorted(value) for key, value in allowed_commands.items()},
    }
