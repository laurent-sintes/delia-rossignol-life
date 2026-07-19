from __future__ import annotations

import mimetypes
import re
import unicodedata
from pathlib import Path
from typing import Any

from .core import load_json, sha256_file, stable_id, utc_now, write_json


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
    target = proposal["target"]
    return (
        str(target["entity_type"]).casefold(),
        str(target["entity_id"]).casefold(),
        str(target["field"]).casefold(),
    )


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
        identifiers = {str(proposal.get("id", "")) for proposal in group}
        replacements = {str(proposal["id"]): proposal.get("replaces_proposal_id") for proposal in group}
        roots = [proposal_id for proposal_id, replaces in replacements.items() if not replaces]
        valid_references = all(replaces is None or replaces in identifiers for replaces in replacements.values())
        if len(roots) != 1 or not valid_references:
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
        raise ValueError(f"Invalid current status: {current}")
    if action not in {"accept", "edit", "reject", "reopen"}:
        raise ValueError(f"Unsupported review action: {action}")
    if action != "reopen" and current != "pending":
        raise ValueError(f"Only pending proposals can be reviewed; current status is {current}")
    if action == "reopen" and current == "pending":
        raise ValueError("A pending proposal cannot be reopened")
    if action == "edit" and edited_value is None:
        raise ValueError("edited_value is required for edit")

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


def apply_proposal(proposal: dict[str, Any], knowledge_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    status = proposal.get("status")
    if status not in {"accepted", "edited"}:
        raise ValueError("Only accepted or edited proposals can be applied")
    if proposal.get("application"):
        raise ValueError("Proposal has already been applied")
    target = proposal["target"]
    entity_type = str(target["entity_type"])
    entity_id = str(target["entity_id"])
    field = str(target["field"])
    for value in (entity_type, entity_id, field):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError(f"Unsafe target component: {value}")

    entity_path = knowledge_root / entity_type / f"{entity_id}.json"
    entity = load_json(entity_path) if entity_path.exists() else {
        "id": entity_id,
        "type": entity_type,
        "fields": {},
    }
    fields = dict(entity.get("fields", {}))
    value = proposal.get("validated_value")
    existing = fields.get(field)
    if existing and existing.get("value") != value:
        replaces = proposal.get("replaces_proposal_id")
        existing_proposal_ids = {item.get("proposal_id") for item in existing.get("provenance", [])}
        if not replaces or replaces not in existing_proposal_ids:
            raise ValueError(f"Conflicting validated value already exists for {entity_type}/{entity_id}/{field}")
    provenance = list(existing.get("provenance", [])) if existing else []
    provenance.append(
        {
            "proposal_id": proposal["id"],
            "source_id": proposal["source"]["id"],
            "locator": proposal["source"]["locator"],
            "applied_at": utc_now(),
        }
    )
    fields[field] = {"value": value, "provenance": provenance}
    entity["fields"] = fields
    entity["updated_at"] = utc_now()
    write_json(entity_path, entity)

    updated_proposal = dict(proposal)
    updated_proposal["application"] = {
        "applied_at": utc_now(),
        "knowledge_path": entity_path.as_posix(),
    }
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
