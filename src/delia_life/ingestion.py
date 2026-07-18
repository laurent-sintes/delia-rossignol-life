from __future__ import annotations

import mimetypes
import re
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
