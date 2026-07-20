from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core import load_json, sha256_json, utc_now, write_json
from .errors import ConflictError
from .ingestion import find_duplicate_keys, prepare_proposal_application, transition_proposal
from .storage import atomic_write_json_group, exclusive_directory_lock


@dataclass(frozen=True)
class BatchReviewDecision:
    action: str
    reviewer: str
    note: str | None
    apply: bool


@dataclass(frozen=True)
class LoadedReviewBatch:
    batch: dict[str, Any]
    proposal_ids: tuple[str, ...]
    paths: tuple[Path, ...]
    proposals: tuple[dict[str, Any], ...]


def _proposal_path(queue_root: Path, proposal_id: str) -> Path:
    if not proposal_id or "/" in proposal_id or "\\" in proposal_id or proposal_id in {".", ".."}:
        raise ValueError(f"Unsafe proposal id: {proposal_id!r}")
    return queue_root / f"{proposal_id}.json"


def create_review_batch(specification: dict[str, Any], queue_root: Path, batch_path: Path) -> dict[str, Any]:
    """Create a review batch that references existing pending proposals.

    A batch deliberately stores proposal identifiers rather than copies of their
    content: the evidence stays in the review queue and cannot be silently
    altered between presentation and decision.
    """
    batch_id = str(specification.get("id", "")).strip()
    proposal_ids = list(specification.get("proposal_ids", []))
    if not batch_id:
        raise ValueError("A review batch requires an id")
    if not proposal_ids or not all(isinstance(item, str) and item.strip() for item in proposal_ids):
        raise ValueError("A review batch requires one or more proposal_ids")
    if len(set(proposal_ids)) != len(proposal_ids):
        raise ValueError("A review batch cannot reference a proposal more than once")
    if batch_path.exists():
        raise ValueError(f"Review batch already exists: {batch_path}")

    proposals = [load_json(_proposal_path(queue_root, proposal_id)) for proposal_id in proposal_ids]
    not_pending = [proposal["id"] for proposal in proposals if proposal.get("status") != "pending"]
    if not_pending:
        raise ValueError(f"Only pending proposals can enter a batch: {', '.join(not_pending)}")
    duplicates = find_duplicate_keys(proposals)
    if duplicates:
        rendered = ", ".join("/".join(item) for item in duplicates)
        raise ValueError(f"Batch contains duplicate proposal targets: {rendered}")

    proposal_hashes = {str(proposal["id"]): sha256_json(proposal) for proposal in proposals}
    timestamp = utc_now()
    batch = {
        "id": batch_id,
        "proposal_ids": proposal_ids,
        "status": "pending",
        "created_at": timestamp,
        "proposal_hashes": proposal_hashes,
        "history": [{"at": timestamp, "from": None, "to": "pending", "reviewer": specification.get("created_by", "system")}],
    }
    write_json(batch_path, batch)
    return batch


def _validate_review_decision(decision: BatchReviewDecision) -> None:
    if decision.action not in {"accept", "reject"}:
        raise ValueError("Batch review action must be accept or reject")
    if decision.apply and decision.action != "accept":
        raise ValueError("Only an accepted batch can be applied")


def _load_review_batch(batch_path: Path, queue_root: Path) -> LoadedReviewBatch:
    batch = load_json(batch_path)
    if batch.get("status") != "pending":
        raise ValueError(f"Only pending batches can be reviewed; current status is {batch.get('status')}")
    proposal_ids = tuple(batch.get("proposal_ids", []))
    if not proposal_ids:
        raise ValueError("Review batch has no proposals")
    paths = tuple(_proposal_path(queue_root, proposal_id) for proposal_id in proposal_ids)
    proposals = tuple(load_json(path) for path in paths)
    expected_hashes = dict(batch.get("proposal_hashes", {}))
    changed = [
        str(proposal.get("id", "?"))
        for proposal in proposals
        if expected_hashes.get(str(proposal.get("id", ""))) != sha256_json(proposal)
    ]
    if changed:
        raise ConflictError(f"Proposals changed after batch creation: {', '.join(changed)}")
    not_pending = [proposal.get("id", "?") for proposal in proposals if proposal.get("status") != "pending"]
    if not_pending:
        raise ValueError(f"All proposals must still be pending: {', '.join(not_pending)}")
    return LoadedReviewBatch(batch=batch, proposal_ids=proposal_ids, paths=paths, proposals=proposals)


def _transition_batch_proposals(
    loaded: LoadedReviewBatch,
    decision: BatchReviewDecision,
) -> tuple[dict[str, Any], ...]:
    return tuple(
        transition_proposal(proposal, decision.action, decision.reviewer, note=decision.note)
        for proposal in loaded.proposals
    )


def _stage_proposal_changes(
    loaded: LoadedReviewBatch,
    updated_proposals: tuple[dict[str, Any], ...],
    knowledge_root: Path,
    apply: bool,
) -> tuple[dict[Path, Any], list[str]]:
    if not apply:
        return dict(zip(loaded.paths, updated_proposals, strict=True)), []
    changes: dict[Path, Any] = {}
    applied_ids: list[str] = []
    staged_entities: dict[Path, dict[str, Any]] = {}
    for path, proposal in zip(loaded.paths, updated_proposals, strict=True):
        target = proposal["target"]
        entity_path = knowledge_root / str(target["entity_type"]) / f'{target["entity_id"]}.json'
        applied, entity, entity_path = prepare_proposal_application(
            proposal,
            knowledge_root,
            staged_entities.get(entity_path),
        )
        staged_entities[entity_path] = entity
        changes[path] = applied
        applied_ids.append(str(applied["id"]))
    changes.update(staged_entities)
    return changes, applied_ids


def _complete_review_batch(
    batch: dict[str, Any],
    decision: BatchReviewDecision,
    applied_ids: list[str],
) -> dict[str, Any]:
    updated = dict(batch)
    updated["status"] = "accepted" if decision.action == "accept" else "rejected"
    history = list(updated.get("history", []))
    history.append(
        {
            "at": utc_now(),
            "from": "pending",
            "to": updated["status"],
            "reviewer": decision.reviewer,
            "note": decision.note,
            "applied_proposal_ids": applied_ids,
        }
    )
    updated["history"] = history
    return updated


def review_batch(
    batch_path: Path,
    queue_root: Path,
    knowledge_root: Path,
    action: str,
    reviewer: str,
    note: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Record one uniform human decision for every proposal in a pending batch."""
    decision = BatchReviewDecision(action=action, reviewer=reviewer, note=note, apply=apply)
    _validate_review_decision(decision)
    common_root = Path(os.path.commonpath([batch_path.resolve(), queue_root.resolve(), knowledge_root.resolve()]))
    lock_path = common_root / ".delia-locks" / "review-batch.lock"
    with exclusive_directory_lock(lock_path):
        loaded = _load_review_batch(batch_path, queue_root)
        updated_proposals = _transition_batch_proposals(loaded, decision)
        changes, applied_ids = _stage_proposal_changes(loaded, updated_proposals, knowledge_root, apply)
        updated_batch = _complete_review_batch(loaded.batch, decision, applied_ids)
        changes[batch_path] = updated_batch
        atomic_write_json_group(changes)
        return {
            "batch": updated_batch,
            "proposal_ids": list(loaded.proposal_ids),
            "applied_proposal_ids": applied_ids,
        }
