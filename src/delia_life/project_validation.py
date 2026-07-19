from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .core import load_json
from .experience import missing_experience_missions, missing_experience_responsibilities
from .ingestion import find_unresolved_duplicate_keys
from .mental_model import load_mental_model, model_summary
from .schema import validate


def _schema_registry(root: Path) -> dict[str, dict[str, Any]]:
    return {
        path.stem.removesuffix(".schema"): load_json(path)
        for path in sorted((root / "schemas").glob("*.schema.json"))
    }


def _json_files(directory: Path, recursive: bool = True) -> Iterable[Path]:
    if not directory.exists():
        return []
    return sorted(directory.rglob("*.json") if recursive else directory.glob("*.json"))


def _identifier(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def missing_priority_sector_coverage(career_project: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    priority_sectors = career_project.get("target_preferences", {}).get("industry_sectors", {}).get("priority", [])
    coverage = policy.get("priority_sector_coverage", {})
    source_domains = set(policy.get("source_domains", []))
    errors: list[str] = []
    for sector in priority_sectors:
        identifier = _identifier(str(sector))
        sources = coverage.get(identifier, [])
        if not sources:
            errors.append(f"offer search policy: missing source coverage for priority sector {identifier}")
        elif unknown_domains := sorted(set(sources) - source_domains):
            errors.append(
                f"offer search policy: source coverage for {identifier} uses undeclared domains: {', '.join(unknown_domains)}"
            )
    return errors


def validate_project(root: Path) -> dict[str, Any]:
    root = root.resolve()
    schemas = _schema_registry(root)
    errors: list[str] = []
    warnings: list[str] = []
    checked_paths: set[Path] = set()

    def check(path: Path, schema_name: str) -> dict[str, Any] | None:
        schema = schemas.get(schema_name)
        if schema is None:
            errors.append(f"missing schema: {schema_name}")
            return None
        try:
            document = load_json(path)
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{path.relative_to(root)}: invalid JSON: {error}")
            return None
        checked_paths.add(path.resolve())
        errors.extend(f"{path.relative_to(root)}: {message}" for message in validate(document, schema))
        return document

    directory_contracts = [
        (root / "data" / "review" / "queue", "proposal"),
        (root / "data" / "offers", "job-offer"),
        (root / "private" / "career-project", "career-project"),
        (root / "templates" / "cv", "template"),
        (root / "data" / "sources" / "manifests", "source-manifest"),
        (root / "data" / "knowledge" / "entities", "knowledge-entity"),
        (root / "private" / "knowledge", "knowledge-entity"),
        (root / "private" / "search-criterion", "knowledge-entity"),
        (root / "data" / "applications", "application"),
        (root / "private" / "website-archives", "website-archive"),
    ]
    loaded_by_contract: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for directory, schema_name in directory_contracts:
        for path in _json_files(directory):
            if path.name == "progress.json":
                continue
            document = check(path, schema_name)
            if document is not None:
                loaded_by_contract.setdefault(schema_name, []).append((path, document))

    single_contracts = [
        (root / "data" / "style" / "delia.json", "delia-style"),
        (root / "data" / "style" / "cv-standard.json", "cv-content-profile"),
        (root / "data" / "knowledge" / "profile.json", "profile-index"),
        (root / "data" / "knowledge" / "skills.json", "skills-index"),
        (root / "site" / "publication.json", "publication"),
        (root / "config" / "repository.json", "repository-config"),
        (root / "config" / "offer-search.json", "offer-search-policy"),
    ]
    loaded_single_contracts: dict[str, dict[str, Any]] = {}
    for path, schema_name in single_contracts:
        document = check(path, schema_name)
        if document is not None:
            loaded_single_contracts[schema_name] = document

    career_projects = [document for _, document in loaded_by_contract.get("career-project", [])]
    policy = loaded_single_contracts.get("offer-search-policy")
    for career_project in career_projects:
        if policy is not None:
            errors.extend(missing_priority_sector_coverage(career_project, policy))

    proposals = [document for _, document in loaded_by_contract.get("proposal", [])]
    for key in find_unresolved_duplicate_keys(proposals):
        errors.append(f"duplicate proposal target: {'/'.join(key)}")

    manifests = [document for _, document in loaded_by_contract.get("source-manifest", [])]
    source_ids = {
        identifier
        for manifest in manifests
        for identifier in [str(manifest.get("id", "")), *(str(alias) for alias in manifest.get("aliases", []))]
        if identifier
    }
    proposal_ids = {str(proposal.get("id", "")) for proposal in proposals}
    for path, entity in loaded_by_contract.get("knowledge-entity", []):
        expected_type = path.parent.name
        if entity.get("id") != path.stem:
            errors.append(f"{path.relative_to(root)}: $.id must match filename {path.stem}")
        if entity.get("type") != expected_type:
            errors.append(f"{path.relative_to(root)}: $.type must match directory {expected_type}")
        for field_name, envelope in entity.get("fields", {}).items():
            for index, provenance in enumerate(envelope.get("provenance", [])):
                proposal_id = str(provenance.get("proposal_id", ""))
                source_id = str(provenance.get("source_id", ""))
                if proposal_id not in proposal_ids:
                    errors.append(f"{path.relative_to(root)}: $.fields.{field_name}.provenance[{index}] unknown proposal_id {proposal_id}")
                if source_id not in source_ids:
                    errors.append(f"{path.relative_to(root)}: $.fields.{field_name}.provenance[{index}] unknown source_id {source_id}")

    experience_root = root / "data" / "knowledge" / "entities"
    for path, experience_id in missing_experience_missions(experience_root):
        errors.append(f"{path.relative_to(root)}: experience mission is required ({experience_id})")
    for path, experience_id in missing_experience_responsibilities(experience_root):
        errors.append(f"{path.relative_to(root)}: experience responsibilities are required ({experience_id})")

    model_manifest = root / "model" / "model.yaml"
    if model_manifest.exists():
        try:
            summary = model_summary(load_mental_model(model_manifest))
            checked_paths.update(Path(path).resolve() for path in summary["loaded_files"])
            errors.extend(f"mental model: {message}" for message in summary["errors"])
        except (OSError, ValueError) as error:
            errors.append(f"mental model: {error}")

    return {
        "checked_files": len(checked_paths),
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }
