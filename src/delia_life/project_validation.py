from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
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


def missing_priority_functional_coverage(career_project: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    priority_domains = career_project.get("target_preferences", {}).get("functional_domains", {}).get("priority", [])
    query_families = policy.get("functional_query_families", {})
    return [
        f"offer search policy: missing query family for priority functional domain {identifier}"
        for domain in priority_domains
        for identifier in [_identifier(str(domain))]
        if not query_families.get(identifier)
    ]


def invalid_recommendation_band_thresholds(policy: dict[str, Any]) -> list[str]:
    bands = policy.get("recommendation_bands", {})
    priority = bands.get("priority_minimum_score")
    possible = bands.get("possible_minimum_score")
    if isinstance(priority, (int, float)) and isinstance(possible, (int, float)) and possible > priority:
        return ["offer search policy: possible score threshold cannot exceed priority score threshold"]
    return []


def invalid_offer_source_audit(policy: dict[str, Any], audit: dict[str, Any]) -> list[str]:
    source_domains = set(policy.get("source_domains", []))
    strategy = policy.get("source_strategy", {})
    direct_domains = set(strategy.get("direct_employer_domains", []))
    specialized_domains = set(strategy.get("specialized_domains", []))
    audited_domains = [str(source.get("scan_domain", "")) for source in audit.get("sources", [])]
    errors: list[str] = []
    duplicates = sorted({domain for domain in audited_domains if domain and audited_domains.count(domain) > 1})
    if duplicates:
        errors.append(f"offer source audit: duplicate scan domains: {', '.join(duplicates)}")
    if undeclared := sorted(set(audited_domains) - source_domains):
        errors.append(f"offer source audit: domains missing from offer search policy: {', '.join(undeclared)}")
    for source in audit.get("sources", []):
        domain = str(source.get("scan_domain", ""))
        source_type = source.get("organization_type")
        if source_type == "public_specialized_portal" and domain not in specialized_domains:
            errors.append(f"offer source audit: specialized portal not categorized as specialized: {domain}")
        elif source_type in {"private_employer", "public_employer"} and domain not in direct_domains:
            errors.append(f"offer source audit: employer portal not categorized as direct: {domain}")
    return errors


@dataclass
class ProjectValidationState:
    root: Path
    schemas: dict[str, dict[str, Any]]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_paths: set[Path] = field(default_factory=set)
    loaded_by_contract: dict[str, list[tuple[Path, dict[str, Any]]]] = field(default_factory=dict)
    loaded_single_contracts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def check(self, path: Path, schema_name: str) -> dict[str, Any] | None:
        schema = self.schemas.get(schema_name)
        if schema is None:
            self.errors.append(f"missing schema: {schema_name}")
            return None
        try:
            document = load_json(path)
        except (OSError, json.JSONDecodeError) as error:
            self.errors.append(f"{path.relative_to(self.root)}: invalid JSON: {error}")
            return None
        self.checked_paths.add(path.resolve())
        self.errors.extend(f"{path.relative_to(self.root)}: {message}" for message in validate(document, schema))
        return document


def _load_directory_contracts(state: ProjectValidationState) -> None:
    root = state.root
    directory_contracts = [
        (root / "data" / "review" / "queue", "proposal"),
        (root / "data" / "offers", "job-offer"),
        (root / "private" / "career-project", "career-project"),
        (root / "templates" / "cv", "template"),
        (root / "data" / "sources" / "manifests", "source-manifest"),
        (root / "data" / "knowledge" / "entities", "knowledge-entity"),
        (root / "data" / "knowledge" / "reference", "knowledge-entity"),
        (root / "private" / "knowledge", "knowledge-entity"),
        (root / "private" / "search-criterion", "knowledge-entity"),
        (root / "data" / "applications", "application"),
        (root / "private" / "website-archives", "website-archive"),
    ]
    for directory, schema_name in directory_contracts:
        for path in _json_files(directory):
            if path.name == "progress.json":
                continue
            document = state.check(path, schema_name)
            if document is not None:
                state.loaded_by_contract.setdefault(schema_name, []).append((path, document))


def _load_single_contracts(state: ProjectValidationState) -> None:
    root = state.root
    single_contracts = [
        (root / "data" / "style" / "delia.json", "delia-style"),
        (root / "data" / "style" / "cv-standard.json", "cv-content-profile"),
        (root / "data" / "style" / "cv-ats.json", "ats-cv-content-profile"),
        (root / "data" / "style" / "cv-ats-variants.json", "ats-cv-variants"),
        (root / "data" / "knowledge" / "profile.json", "profile-index"),
        (root / "data" / "knowledge" / "skills.json", "skills-index"),
        (root / "site" / "publication.json", "publication"),
        (root / "config" / "repository.json", "repository-config"),
        (root / "config" / "offer-search.json", "offer-search-policy"),
        (root / "config" / "offer-source-audit.json", "offer-source-audit"),
    ]
    for path, schema_name in single_contracts:
        document = state.check(path, schema_name)
        if document is not None:
            state.loaded_single_contracts[schema_name] = document


def _validate_offer_search_coverage(state: ProjectValidationState) -> None:
    career_projects = [document for _, document in state.loaded_by_contract.get("career-project", [])]
    policy = state.loaded_single_contracts.get("offer-search-policy")
    audit = state.loaded_single_contracts.get("offer-source-audit")
    if policy is not None:
        state.errors.extend(invalid_recommendation_band_thresholds(policy))
        if audit is not None:
            state.errors.extend(invalid_offer_source_audit(policy, audit))
    for career_project in career_projects:
        if policy is not None:
            state.errors.extend(missing_priority_sector_coverage(career_project, policy))
            state.errors.extend(missing_priority_functional_coverage(career_project, policy))


def _validate_proposals_and_knowledge(state: ProjectValidationState) -> None:
    proposals = [document for _, document in state.loaded_by_contract.get("proposal", [])]
    for key in find_unresolved_duplicate_keys(proposals):
        state.errors.append(f"duplicate proposal target: {'/'.join(key)}")

    manifests = [document for _, document in state.loaded_by_contract.get("source-manifest", [])]
    source_ids = {
        identifier
        for manifest in manifests
        for identifier in [str(manifest.get("id", "")), *(str(alias) for alias in manifest.get("aliases", []))]
        if identifier
    }
    proposal_ids = {str(proposal.get("id", "")) for proposal in proposals}
    for path, entity in state.loaded_by_contract.get("knowledge-entity", []):
        expected_type = path.parent.name
        if entity.get("id") != path.stem:
            state.errors.append(f"{path.relative_to(state.root)}: $.id must match filename {path.stem}")
        if entity.get("type") != expected_type:
            state.errors.append(f"{path.relative_to(state.root)}: $.type must match directory {expected_type}")
        for field_name, envelope in entity.get("fields", {}).items():
            for index, provenance in enumerate(envelope.get("provenance", [])):
                proposal_id = str(provenance.get("proposal_id", ""))
                source_id = str(provenance.get("source_id", ""))
                if proposal_id not in proposal_ids:
                    state.errors.append(
                        f"{path.relative_to(state.root)}: $.fields.{field_name}.provenance[{index}] "
                        f"unknown proposal_id {proposal_id}"
                    )
                if source_id not in source_ids:
                    state.errors.append(
                        f"{path.relative_to(state.root)}: $.fields.{field_name}.provenance[{index}] "
                        f"unknown source_id {source_id}"
                    )


def _validate_experiences(state: ProjectValidationState) -> None:
    experience_root = state.root / "data" / "knowledge" / "entities"
    for path, experience_id in missing_experience_missions(experience_root):
        state.errors.append(f"{path.relative_to(state.root)}: experience mission is required ({experience_id})")
    for path, experience_id in missing_experience_responsibilities(experience_root):
        state.errors.append(f"{path.relative_to(state.root)}: experience responsibilities are required ({experience_id})")


def _validate_skill_index(state: ProjectValidationState) -> None:
    index = state.loaded_single_contracts.get("skills-index")
    if index is None:
        return
    skills = index.get("skills", [])
    identifiers = [str(item.get("id", "")) for item in skills if isinstance(item, dict)]
    duplicates = sorted({identifier for identifier in identifiers if identifiers.count(identifier) > 1})
    if duplicates:
        state.errors.append(f"skills index: duplicate ids: {', '.join(duplicates)}")
    entities = {
        (str(document.get("type", "")), str(document.get("id", ""))): document
        for _, document in state.loaded_by_contract.get("knowledge-entity", [])
    }
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        for index_position, reference in enumerate(skill.get("evidence", [])):
            key = (str(reference.get("entity_type", "")), str(reference.get("entity_id", "")))
            entity = entities.get(key)
            field_name = str(reference.get("field", ""))
            if entity is None:
                state.errors.append(
                    f"skills index: {skill.get('id')} evidence[{index_position}] references unknown entity {'/'.join(key)}"
                )
            elif field_name not in entity.get("fields", {}):
                state.errors.append(
                    f"skills index: {skill.get('id')} evidence[{index_position}] references unknown field {field_name}"
                )


def _validate_model_files(state: ProjectValidationState) -> None:
    model_manifest = state.root / "model" / "model.yaml"
    if model_manifest.exists():
        try:
            summary = model_summary(load_mental_model(model_manifest))
            state.checked_paths.update(Path(path).resolve() for path in summary["loaded_files"])
            state.errors.extend(f"mental model: {message}" for message in summary["errors"])
        except (OSError, ValueError) as error:
            state.errors.append(f"mental model: {error}")


def validate_project(root: Path) -> dict[str, Any]:
    resolved_root = root.resolve()
    state = ProjectValidationState(root=resolved_root, schemas=_schema_registry(resolved_root))
    _load_directory_contracts(state)
    _load_single_contracts(state)
    _validate_offer_search_coverage(state)
    _validate_proposals_and_knowledge(state)
    _validate_experiences(state)
    _validate_skill_index(state)
    _validate_model_files(state)

    return {
        "checked_files": len(state.checked_paths),
        "errors": state.errors,
        "warnings": state.warnings,
        "ok": not state.errors,
    }
