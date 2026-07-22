from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .core import load_json, write_json

REVIEWABLE_FIELDS = {
    "summary",
    "location_label",
    "contract_type",
    "full_time",
    "required_skills",
    "preferred_skills",
    "prerequisites",
    "conditions",
    "evidence",
}


def apply_offer_semantic_reviews(offers_directory: Path, review_path: Path) -> dict[str, Any]:
    batch = load_json(review_path)
    if not isinstance(batch, dict) or batch.get("schema_version") != 1:
        raise ValueError("invalid offer semantic review batch")
    reviewed_at = str(batch.get("reviewed_at") or "")
    parsed_reviewed_at = datetime.fromisoformat(reviewed_at)
    if parsed_reviewed_at.tzinfo is None:
        raise ValueError("offer semantic review timestamp must include a timezone")
    review_method = str(batch.get("review_method") or "").strip()
    if not review_method:
        raise ValueError("offer semantic review method is required")
    reviews = batch.get("reviews")
    if not isinstance(reviews, list) or not reviews:
        raise ValueError("offer semantic review batch is empty")

    reviewed_ids: list[str] = []
    for review in reviews:
        if not isinstance(review, dict):
            raise ValueError("invalid offer semantic review entry")
        offer_id = str(review.get("offer_id") or "").strip()
        offer_path = offers_directory / f"{offer_id}.json"
        if not offer_id or not offer_path.is_file():
            raise ValueError(f"unknown reviewed offer: {offer_id or '<missing>'}")
        offer = load_json(offer_path)
        if not isinstance(offer, dict) or offer.get("id") != offer_id:
            raise ValueError(f"reviewed offer identity mismatch: {offer_id}")
        extraction = offer.get("extraction")
        if not isinstance(extraction, dict) or not extraction.get("source_sha256"):
            raise ValueError(f"reviewed offer has no archived source proof: {offer_id}")
        updates = review.get("updates")
        if not isinstance(updates, dict) or not updates:
            raise ValueError(f"review has no updates: {offer_id}")
        unexpected = set(updates) - REVIEWABLE_FIELDS
        if unexpected:
            raise ValueError(f"unsupported semantic review fields for {offer_id}: {sorted(unexpected)}")
        updated_offer = {
            **offer,
            **updates,
            "extraction": {
                **extraction,
                "review_status": "completed",
                "ambiguous_fields": [],
                "reviewed_at": reviewed_at,
                "review_method": review_method,
            },
        }
        write_json(offer_path, updated_offer)
        reviewed_ids.append(offer_id)
    return {
        "review_batch": str(review_path),
        "offers_directory": str(offers_directory),
        "reviewed_count": len(reviewed_ids),
        "reviewed_offer_ids": sorted(reviewed_ids),
    }
