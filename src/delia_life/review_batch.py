from __future__ import annotations

from pathlib import Path
from typing import Any

from .core import load_json, utc_now, write_json
from .ingestion import apply_proposal, find_duplicate_keys, transition_proposal


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

    batch = {
        "id": batch_id,
        "proposal_ids": proposal_ids,
        "status": "pending",
        "created_at": utc_now(),
        "history": [{"at": utc_now(), "from": None, "to": "pending", "reviewer": specification.get("created_by", "system")}],
    }
    write_json(batch_path, batch)
    return batch


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
    if action not in {"accept", "reject"}:
        raise ValueError("Batch review action must be accept or reject")
    if apply and action != "accept":
        raise ValueError("Only an accepted batch can be applied")
    batch = load_json(batch_path)
    if batch.get("status") != "pending":
        raise ValueError(f"Only pending batches can be reviewed; current status is {batch.get('status')}")
    proposal_ids = list(batch.get("proposal_ids", []))
    if not proposal_ids:
        raise ValueError("Review batch has no proposals")
    paths = [_proposal_path(queue_root, proposal_id) for proposal_id in proposal_ids]
    proposals = [load_json(path) for path in paths]
    not_pending = [proposal.get("id", "?") for proposal in proposals if proposal.get("status") != "pending"]
    if not_pending:
        raise ValueError(f"All proposals must still be pending: {', '.join(not_pending)}")

    updated_proposals = [transition_proposal(proposal, action, reviewer, note=note) for proposal in proposals]
    # All transitions have succeeded before any file is changed.
    for path, proposal in zip(paths, updated_proposals):
        write_json(path, proposal)

    applied_ids: list[str] = []
    if apply:
        for path, proposal in zip(paths, updated_proposals):
            applied, _ = apply_proposal(proposal, knowledge_root)
            write_json(path, applied)
            applied_ids.append(str(applied["id"]))

    updated_batch = dict(batch)
    updated_batch["status"] = "accepted" if action == "accept" else "rejected"
    history = list(updated_batch.get("history", []))
    history.append(
        {
            "at": utc_now(),
            "from": "pending",
            "to": updated_batch["status"],
            "reviewer": reviewer,
            "note": note,
            "applied_proposal_ids": applied_ids,
        }
    )
    updated_batch["history"] = history
    write_json(batch_path, updated_batch)
    return {"batch": updated_batch, "proposal_ids": proposal_ids, "applied_proposal_ids": applied_ids}
