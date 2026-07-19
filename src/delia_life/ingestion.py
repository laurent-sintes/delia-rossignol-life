from __future__ import annotations

import mimetypes
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

from .core import load_json, sha256_file, stable_id, utc_now, write_json
from .domain import ProposalTarget
from .errors import ConflictError, TransitionError, ValidationError
from .storage import atomic_write_json_group, exclusive_directory_lock

SOURCE_KINDS = {"cv", "diploma", "document", "website", "offer", "feedback"}
CLASSIFICATIONS = {"fact", "claim", "inference"}
STATUSES = {"pending", "accepted", "edited", "rejected"}


def create_file_manifest(path: Path, kind: str, original_uri: str | None = None) -> dict[str, Any]:
    if kind not in SOURCE_KINDS:
        raise ValueError(f"Unsupported source kind: {kind}")
    if not path.is_file():
        raise FileNotFoundError(path)
    content_hash = sha256_file(path)
    return {
        "id": stable_id("src", content_hash),
        "kind": kind,
        "original_name": path.name,
        "original_uri": original_uri,
        "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "sha256": content_hash,
        "size_bytes": path.stat().st_size,
        "ingested_at": utc_now(),
    }


def proposal_key(proposal: dict[str, Any]) -> tuple[str, str, str]:
    return ProposalTarget.from_mapping(proposal["target"]).key


def find_duplicate_keys(proposals: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    seen: set[tuple[str, str, str]] = set()
    duplicates: set[tuple[str, str, str]] = set()
    for proposal in proposals:
        key = proposal_key(proposal)
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return sorted(duplicates)


def find_unresolved_duplicate_keys(proposals: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Return duplicate targets that are not an explicit replacement chain."""
    unresolved: list[tuple[str, str, str]] = []
    for key in find_duplicate_keys(proposals):
        group = [proposal for proposal in proposals if proposal_key(proposal) == key]
        ordered_identifiers = [str(proposal.get("id", "")) for proposal in group]
        identifiers = set(ordered_identifiers)
        replacements = {str(proposal["id"]): proposal.get("replaces_proposal_id") for proposal in group}
        roots = [proposal_id for proposal_id, replaces in replacements.items() if not replaces]
        valid_references = all(replaces is None or str(replaces) in identifiers for replaces in replacements.values())
        successors: dict[str, list[str]] = {proposal_id: [] for proposal_id in identifiers}
        if valid_references:
            for proposal_id, replaces in replacements.items():
                if replaces is not None:
                    successors[str(replaces)].append(proposal_id)
        is_linear = all(len(items) <= 1 for items in successors.values())
        visited: set[str] = set()
        current = roots[0] if len(roots) == 1 else None
        while current is not None and current not in visited:
            visited.add(current)
            children = successors.get(current, [])
            current = children[0] if len(children) == 1 else None
        if (
            len(ordered_identifiers) != len(identifiers)
            or not identifiers
            or "" in identifiers
            or len(roots) != 1
            or not valid_references
            or not is_linear
            or visited != identifiers
        ):
            unresolved.append(key)
    return unresolved


def transition_proposal(
    proposal: dict[str, Any],
    action: str,
    reviewer: str,
    edited_value: Any | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    current = proposal.get("status", "pending")
    if current not in STATUSES:
        raise ValidationError(f"Invalid current status: {current}")
    if action not in {"accept", "edit", "reject", "reopen"}:
        raise ValidationError(f"Unsupported review action: {action}")
    if action != "reopen" and current != "pending":
        raise TransitionError(f"Only pending proposals can be reviewed; current status is {current}")
    if action == "reopen" and current == "pending":
        raise TransitionError("A pending proposal cannot be reopened")
    if action == "reopen" and proposal.get("application"):
        raise TransitionError("An applied proposal cannot be reopened; create a replacement proposal")
    if action == "edit" and edited_value is None:
        raise ValidationError("edited_value is required for edit")

    next_status = {
        "accept": "accepted",
        "edit": "edited",
        "reject": "rejected",
        "reopen": "pending",
    }[action]
    result = dict(proposal)
    result["status"] = next_status
    if action == "edit":
        result["validated_value"] = edited_value
    elif action == "accept":
        result["validated_value"] = result.get("proposed_value")
    elif action == "reopen":
        result.pop("validated_value", None)
    history = list(result.get("history", []))
    history.append(
        {
            "at": utc_now(),
            "from": current,
            "to": next_status,
            "reviewer": reviewer,
            "note": note,
        }
    )
    result["history"] = history
    return result


def prepare_proposal_application(
    proposal: dict[str, Any],
    knowledge_root: Path,
    current_entity: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    status = proposal.get("status")
    if status not in {"accepted", "edited"}:
        raise TransitionError("Only accepted or edited proposals can be applied")
    if proposal.get("application"):
        raise TransitionError("Proposal has already been applied")
    target = ProposalTarget.from_mapping(proposal["target"])
    entity_type, entity_id, field = target.entity_type, target.entity_id, target.field
    for component in (entity_type, entity_id, field):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", component):
            raise ValidationError(f"Unsafe target component: {component}")

    entity_path = target.entity_path(knowledge_root)
    entity = dict(current_entity) if current_entity is not None else load_json(entity_path) if entity_path.exists() else {
        "id": entity_id,
        "type": entity_type,
        "fields": {},
    }
    raw_fields = entity.get("fields", {})
    if not isinstance(raw_fields, dict):
        raise ValidationError(f"Entity fields must be an object: {entity_type}/{entity_id}")
    fields = dict(raw_fields)
    validated_value = proposal.get("validated_value")
    existing = fields.get(field)
    if existing and existing.get("value") != validated_value:
        replaces = proposal.get("replaces_proposal_id")
        existing_proposal_ids = {item.get("proposal_id") for item in existing.get("provenance", [])}
        if not replaces or replaces not in existing_proposal_ids:
            raise ConflictError(f"Conflicting validated value already exists for {entity_type}/{entity_id}/{field}")
    provenance = list(existing.get("provenance", [])) if existing else []
    provenance.append(
        {
            "proposal_id": proposal["id"],
            "source_id": proposal["source"]["id"],
            "locator": proposal["source"]["locator"],
            "applied_at": utc_now(),
        }
    )
    fields[field] = {"value": validated_value, "provenance": provenance}
    entity["fields"] = fields
    entity["updated_at"] = utc_now()
    updated_proposal = dict(proposal)
    updated_proposal["application"] = {
        "applied_at": utc_now(),
        "knowledge_path": entity_path.as_posix(),
    }
    return updated_proposal, entity, entity_path


def apply_proposal(proposal: dict[str, Any], knowledge_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply an in-memory proposal and persist its entity.

    File-based workflows should use ``apply_proposal_file`` so the proposal and
    entity are committed together.
    """
    updated_proposal, entity, entity_path = prepare_proposal_application(proposal, knowledge_root)
    write_json(entity_path, entity)
    return updated_proposal, entity


def apply_proposal_file(proposal_path: Path, knowledge_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    common_root = Path(os.path.commonpath([proposal_path.resolve(), knowledge_root.resolve()]))
    lock_path = common_root / ".delia-locks" / "apply-proposal.lock"
    with exclusive_directory_lock(lock_path):
        proposal = load_json(proposal_path)
        updated_proposal, entity, entity_path = prepare_proposal_application(proposal, knowledge_root)
        atomic_write_json_group({entity_path: entity, proposal_path: updated_proposal})
        return updated_proposal, entity


def _reference_id(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")


def migrate_career_project_entity(
    entity: dict[str, Any],
    person_id: str,
    criterion_entity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a generic validated-entity envelope into the career-project schema.

    The original field envelopes and their provenance remain embedded so the
    migration is lossless and can be rerun deterministically.
    """
    if entity.get("type") != "career-project":
        raise ValueError("Expected a generic career-project entity")
    fields = dict(entity.get("fields", {}))
    target_preferences = dict(fields.get("targets", {}).get("value", {}))
    sectors = dict(target_preferences.get("industry_sectors", {}))
    selected_sectors = list(sectors.get("priority", [])) + list(sectors.get("acceptable", []))

    criterion_rules = {
        "activity_boundaries": ("other", 5, True),
        "functional_preferences": ("other", 3, False),
        "contract_preferences": ("contract_type", 5, True),
        "availability": ("availability", 5, True),
        "mobility_and_schedule_constraints": ("commute", 5, True),
        "work_arrangement": ("work_mode", 4, False),
        "compensation": ("compensation", 5, True),
        "work_environment": ("work_environment", 4, False),
    }
    criteria: list[dict[str, Any]] = []
    for field_name, (dimension, priority, hard_constraint) in criterion_rules.items():
        field = fields.get(field_name)
        if not field:
            continue
        criteria.append(
            {
                "id": f"criterion-{field_name.replace('_', '-')}",
                "dimension": dimension,
                "operator": "custom",
                "value": field.get("value"),
                "priority": priority,
                "hard_constraint": hard_constraint,
                "provenance": list(field.get("provenance", [])),
            }
        )

    if criterion_entity:
        detail_field = dict(criterion_entity.get("fields", {}).get("details", {}))
        details = dict(detail_field.get("value", {}))
        if details:
            criteria.append(
                {
                    "id": str(criterion_entity.get("id", "criterion-imported")),
                    "dimension": details.get("dimension", "other"),
                    "operator": details.get("operator", "custom"),
                    "value": details.get("value"),
                    "priority": details.get("priority", 3),
                    "hard_constraint": bool(details.get("hard_constraint", False)),
                    "provenance": list(detail_field.get("provenance", [])),
                }
            )

    result = dict(entity)
    result.update(
        {
            "person_id": person_id,
            "status": "active",
            "targets": {
                "industry_sector_ids": [_reference_id(str(value)) for value in selected_sectors],
                "job_role_ids": [],
                "location_ids": [],
            },
            "criteria": criteria,
            "target_preferences": target_preferences,
            "migration": "generic-entity-to-career-project-v1",
        }
    )
    availability = fields.get("availability", {}).get("value")
    if availability:
        result["availability"] = availability
    return result
