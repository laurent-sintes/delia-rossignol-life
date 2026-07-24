from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from .core import load_json, sha256_file, sha256_json, utc_now, write_json

REVIEWABLE_FIELDS = {
    "summary",
    "location_label",
    "contract_type",
    "full_time",
    "required_skills",
    "preferred_skills",
    "semantic_requirements",
    "semantic_matches",
    "prerequisites",
    "conditions",
    "evidence",
}

EvidenceCatalog = dict[str, frozenset[str]]


def collect_validated_knowledge_evidence_catalog(knowledge_root: Path) -> EvidenceCatalog:
    """Index every validated entity and skill by its available evidence fields."""
    catalog: dict[str, frozenset[str]] = {}
    for path in sorted(knowledge_root.rglob("*.json")):
        document = load_json(path)
        if not isinstance(document, dict):
            continue
        identifier = str(document.get("id") or "").strip()
        entity_type = str(document.get("type") or "").strip()
        fields = document.get("fields")
        if identifier and entity_type and isinstance(fields, dict):
            catalog[f"{entity_type}:{identifier}"] = frozenset(str(field) for field in fields)
        if document.get("status") == "validated" and isinstance(document.get("skills"), list):
            for item in document["skills"]:
                if not isinstance(item, dict):
                    continue
                skill_id = str(item.get("id") or "").strip()
                if skill_id:
                    catalog[f"skill:{skill_id}"] = frozenset(str(field) for field in item if field != "id")
    return catalog


def collect_validated_knowledge_evidence_ids(knowledge_root: Path) -> set[str]:
    """Compatibility projection for callers that only need stable identifiers."""
    return set(collect_validated_knowledge_evidence_catalog(knowledge_root))


def semantic_profile_sha256(knowledge_root: Path) -> str:
    """Fingerprint the complete validated profile used by an LLM review."""
    files = [
        {
            "path": path.relative_to(knowledge_root).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in sorted(knowledge_root.rglob("*.json"))
    ]
    return sha256_json(files)


def _normalized_evidence_text(value: str) -> str:
    without_markup = re.sub(r"<[^>]+>", " ", html.unescape(value))
    normalized = unicodedata.normalize("NFKC", without_markup).casefold()
    return " ".join(normalized.split())


def _archive_path(extraction: dict[str, Any], workspace_root: Path) -> Path | None:
    value = str(extraction.get("source_archive_path") or "").strip()
    if not value:
        return None
    candidate = Path(value)
    return candidate if candidate.is_absolute() else workspace_root / candidate


def _semantic_cache_key(
    source_sha256: str,
    offer_identity: str,
    profile_sha256: str,
    prompt_version: str,
    schema_version: int,
    review_model: str,
) -> str:
    return sha256_json(
        {
            "source_sha256": source_sha256,
            "offer_identity": offer_identity,
            "profile_sha256": profile_sha256,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "review_model": review_model,
        }
    )


def semantic_review_errors(
    offer: dict[str, Any],
    evidence_catalog: EvidenceCatalog,
    profile_sha256: str,
    prompt_version: str,
    schema_version: int,
    *,
    workspace_root: Path | None = None,
    verify_archive: bool = True,
) -> list[str]:
    """Validate coverage, profile evidence and archived offer evidence."""
    errors: list[str] = []
    offer_id = str(offer.get("id") or "<missing>")
    extraction = offer.get("extraction")
    if not isinstance(extraction, dict):
        return [f"{offer_id}: extraction metadata is missing"]
    if extraction.get("review_status") != "completed":
        errors.append(f"{offer_id}: semantic review is not completed")
    if extraction.get("review_schema_version") != schema_version:
        errors.append(f"{offer_id}: semantic review schema is not current")
    if extraction.get("review_prompt_version") != prompt_version:
        errors.append(f"{offer_id}: semantic review prompt is not current")
    if extraction.get("review_profile_sha256") != profile_sha256:
        errors.append(f"{offer_id}: semantic review profile fingerprint is stale")
    review_model = str(extraction.get("review_model") or "").strip()
    if not review_model:
        errors.append(f"{offer_id}: semantic review model is missing")
    cache_key = str(extraction.get("semantic_cache_key") or "")
    source_sha256 = str(extraction.get("source_sha256") or "")
    offer_identity = str(offer.get("canonical_offer_id") or offer_id).strip()
    if cache_key and review_model and cache_key != _semantic_cache_key(
        source_sha256,
        offer_identity,
        profile_sha256,
        prompt_version,
        schema_version,
        review_model,
    ):
        errors.append(f"{offer_id}: semantic cache key does not match review fingerprints")

    requirements = offer.get("semantic_requirements")
    matches = offer.get("semantic_matches")
    if not isinstance(requirements, list) or not requirements:
        errors.append(f"{offer_id}: semantic requirements are missing")
        requirements = []
    if not isinstance(matches, list) or not matches:
        errors.append(f"{offer_id}: semantic matches are missing")
        matches = []

    archive_text = ""
    archive = _archive_path(extraction, workspace_root or Path.cwd())
    if verify_archive:
        if archive is None or not archive.is_file():
            errors.append(f"{offer_id}: archived offer source is missing")
        else:
            expected_sha256 = str(extraction.get("source_sha256") or "")
            if sha256_file(archive) != expected_sha256:
                errors.append(f"{offer_id}: archived offer source fingerprint does not match")
            else:
                archive_text = _normalized_evidence_text(archive.read_text(encoding="utf-8", errors="replace"))

    requirement_ids: list[str] = []
    requirement_by_id: dict[str, dict[str, Any]] = {}
    for requirement in requirements:
        if not isinstance(requirement, dict):
            errors.append(f"{offer_id}: invalid semantic requirement")
            continue
        requirement_id = str(requirement.get("id") or "").strip()
        if not requirement_id or requirement_id in requirement_by_id:
            errors.append(f"{offer_id}: invalid or duplicate semantic requirement id")
            continue
        requirement_ids.append(requirement_id)
        requirement_by_id[requirement_id] = requirement
        if str(requirement.get("importance") or "") not in {"required", "preferred"}:
            errors.append(f"{offer_id}: invalid importance for semantic requirement {requirement_id}")
        if str(requirement.get("kind") or "") not in {
            "mission",
            "skill",
            "experience",
            "qualification",
            "condition",
            "other",
        }:
            errors.append(f"{offer_id}: invalid kind for semantic requirement {requirement_id}")
        if not str(requirement.get("description") or "").strip():
            errors.append(f"{offer_id}: missing description for semantic requirement {requirement_id}")
        offer_evidence = requirement.get("offer_evidence")
        locator = str(offer_evidence.get("locator") or "").strip() if isinstance(offer_evidence, dict) else ""
        excerpt = str(offer_evidence.get("excerpt") or "").strip() if isinstance(offer_evidence, dict) else ""
        if not locator or not excerpt:
            errors.append(f"{offer_id}: missing offer evidence for semantic requirement {requirement_id}")
        elif verify_archive and archive_text and _normalized_evidence_text(excerpt) not in archive_text:
            errors.append(f"{offer_id}: offer excerpt not found in archive for semantic requirement {requirement_id}")

    matched_ids: list[str] = []
    for match in matches:
        if not isinstance(match, dict):
            errors.append(f"{offer_id}: invalid semantic match")
            continue
        requirement_id = str(match.get("requirement_id") or "").strip()
        if not requirement_id or requirement_id in matched_ids:
            errors.append(f"{offer_id}: invalid or duplicate semantic match requirement id")
            continue
        matched_ids.append(requirement_id)
        match_type = str(match.get("match_type") or "")
        if match_type not in {"exact", "transferable", "gap", "unknown"}:
            errors.append(f"{offer_id}: invalid semantic match type for {requirement_id}")
        if str(match.get("llm_confidence") or "") not in {"high", "medium", "low"}:
            errors.append(f"{offer_id}: invalid LLM confidence for {requirement_id}")
        if not str(match.get("rationale") or "").strip():
            errors.append(f"{offer_id}: missing semantic rationale for {requirement_id}")
        refs = match.get("profile_evidence_refs")
        if not isinstance(refs, list):
            errors.append(f"{offer_id}: invalid profile evidence references for {requirement_id}")
            refs = []
        if match_type in {"exact", "transferable"} and not refs:
            errors.append(f"{offer_id}: supported semantic match has no profile evidence for {requirement_id}")
        seen_refs: set[tuple[str, str]] = set()
        for ref in refs:
            if not isinstance(ref, dict):
                errors.append(f"{offer_id}: invalid profile evidence reference for {requirement_id}")
                continue
            evidence_id = str(ref.get("id") or "").strip()
            field = str(ref.get("field") or "").strip()
            key = (evidence_id, field)
            if key in seen_refs:
                errors.append(f"{offer_id}: duplicate profile evidence reference for {requirement_id}")
                continue
            seen_refs.add(key)
            available_fields = evidence_catalog.get(evidence_id)
            if available_fields is None:
                errors.append(f"{offer_id}: unknown profile evidence {evidence_id} for {requirement_id}")
            elif field not in available_fields:
                errors.append(f"{offer_id}: unknown profile evidence field {evidence_id}#{field} for {requirement_id}")

    if set(requirement_ids) != set(matched_ids) or len(requirement_ids) != len(matched_ids):
        missing = sorted(set(requirement_ids) - set(matched_ids))
        unexpected = sorted(set(matched_ids) - set(requirement_ids))
        if missing:
            errors.append(f"{offer_id}: semantic matches omit requirements: {', '.join(missing)}")
        if unexpected:
            errors.append(f"{offer_id}: semantic matches reference unknown requirements: {', '.join(unexpected)}")
    return errors


def apply_offer_semantic_reviews(
    offers_directory: Path,
    review_path: Path,
    knowledge_root: Path = Path("data/knowledge"),
    policy_path: Path = Path("config/offer-search.json"),
    cache_root: Path = Path("generated/offer-semantic-cache"),
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    batch = load_json(review_path)
    policy = load_json(policy_path)
    semantic_policy = policy["semantic_matching"]
    schema_version = int(semantic_policy["review_schema_version"])
    prompt_version = str(semantic_policy["prompt_version"])
    if not isinstance(batch, dict) or batch.get("schema_version") != schema_version:
        raise ValueError("invalid offer semantic review batch")
    reviewed_at = str(batch.get("reviewed_at") or "")
    parsed_reviewed_at = datetime.fromisoformat(reviewed_at)
    if parsed_reviewed_at.tzinfo is None:
        raise ValueError("offer semantic review timestamp must include a timezone")
    review_method = str(batch.get("review_method") or "").strip()
    review_model = str(batch.get("review_model") or "").strip()
    if not review_method or not review_model:
        raise ValueError("offer semantic review method and model are required")
    if batch.get("prompt_version") != prompt_version:
        raise ValueError("offer semantic review prompt version is not current")
    profile_sha256 = semantic_profile_sha256(knowledge_root)
    if batch.get("profile_sha256") != profile_sha256:
        raise ValueError("offer semantic review profile fingerprint is stale")
    reviews = batch.get("reviews")
    if not isinstance(reviews, list) or not reviews:
        raise ValueError("offer semantic review batch is empty")
    evidence_catalog = collect_validated_knowledge_evidence_catalog(knowledge_root)

    candidates: list[tuple[Path, dict[str, Any], dict[str, Any], str]] = []
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
        source_sha256 = str(extraction["source_sha256"])
        offer_identity = str(offer.get("canonical_offer_id") or offer_id).strip()
        cache_key = _semantic_cache_key(
            source_sha256,
            offer_identity,
            profile_sha256,
            prompt_version,
            schema_version,
            review_model,
        )
        updated_offer = {
            **offer,
            **updates,
            "extraction": {
                **extraction,
                "review_status": "completed",
                "ambiguous_fields": [],
                "reviewed_at": reviewed_at,
                "review_method": review_method,
                "review_model": review_model,
                "review_prompt_version": prompt_version,
                "review_profile_sha256": profile_sha256,
                "review_schema_version": schema_version,
                "semantic_cache_key": cache_key,
            },
        }
        errors = semantic_review_errors(
            updated_offer,
            evidence_catalog,
            profile_sha256,
            prompt_version,
            schema_version,
            workspace_root=workspace_root,
        )
        if errors:
            raise ValueError("; ".join(errors))
        candidates.append((offer_path, updated_offer, updates, cache_key))

    reviewed_ids: list[str] = []
    cache_root.mkdir(parents=True, exist_ok=True)
    for offer_path, updated_offer, updates, cache_key in candidates:
        write_json(offer_path, updated_offer)
        extraction = updated_offer["extraction"]
        write_json(
            cache_root / f"{cache_key}.json",
            {
                "schema_version": schema_version,
                "prompt_version": prompt_version,
                "review_model": review_model,
                "review_method": review_method,
                "reviewed_at": reviewed_at,
                "profile_sha256": profile_sha256,
                "source_sha256": extraction["source_sha256"],
                "offer_identity": offer_identity,
                "updates": updates,
            },
        )
        reviewed_ids.append(str(updated_offer["id"]))
    return {
        "review_batch": str(review_path),
        "offers_directory": str(offers_directory),
        "reviewed_count": len(reviewed_ids),
        "reviewed_offer_ids": sorted(reviewed_ids),
        "profile_sha256": profile_sha256,
        "prompt_version": prompt_version,
        "review_model": review_model,
    }


def reuse_cached_semantic_reviews(
    offers_directory: Path,
    knowledge_root: Path = Path("data/knowledge"),
    policy_path: Path = Path("config/offer-search.json"),
    cache_root: Path = Path("generated/offer-semantic-cache"),
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    policy = load_json(policy_path)
    semantic_policy = policy["semantic_matching"]
    schema_version = int(semantic_policy["review_schema_version"])
    prompt_version = str(semantic_policy["prompt_version"])
    profile_sha256 = semantic_profile_sha256(knowledge_root)
    evidence_catalog = collect_validated_knowledge_evidence_catalog(knowledge_root)
    reused_ids: list[str] = []
    for offer_path in sorted(offers_directory.glob("*.json")):
        offer = load_json(offer_path)
        if not isinstance(offer, dict):
            continue
        extraction = offer.get("extraction")
        if not isinstance(extraction, dict):
            continue
        source_sha256 = str(extraction.get("source_sha256") or "")
        if not source_sha256:
            continue
        offer_identity = str(offer.get("canonical_offer_id") or offer.get("id") or offer_path.stem).strip()
        compatible: list[tuple[str, Path, dict[str, Any]]] = []
        for cache_path in sorted(cache_root.glob("*.json")):
            cached = load_json(cache_path)
            if not isinstance(cached, dict):
                continue
            review_model = str(cached.get("review_model") or "")
            cache_key = _semantic_cache_key(
                source_sha256,
                offer_identity,
                profile_sha256,
                prompt_version,
                schema_version,
                review_model,
            )
            if any(
                (
                    cache_path.stem != cache_key,
                    cached.get("schema_version") != schema_version,
                    cached.get("prompt_version") != prompt_version,
                    cached.get("profile_sha256") != profile_sha256,
                    cached.get("source_sha256") != source_sha256,
                    cached.get("offer_identity") != offer_identity,
                    not review_model,
                    not isinstance(cached.get("updates"), dict),
                )
            ):
                continue
            compatible.append((str(cached.get("reviewed_at") or ""), cache_path, cached))
        if not compatible:
            continue
        _, cache_path, cached = max(compatible, key=lambda item: (item[0], item[1].name))
        cache_key = cache_path.stem
        candidate = {
            **offer,
            **cached["updates"],
            "extraction": {
                **extraction,
                "review_status": "completed",
                "ambiguous_fields": [],
                "reviewed_at": cached.get("reviewed_at"),
                "review_method": cached.get("review_method"),
                "review_model": cached.get("review_model"),
                "review_prompt_version": prompt_version,
                "review_profile_sha256": profile_sha256,
                "review_schema_version": schema_version,
                "semantic_cache_key": cache_key,
                "semantic_cache_reused_at": utc_now(),
            },
        }
        if semantic_review_errors(
            candidate,
            evidence_catalog,
            profile_sha256,
            prompt_version,
            schema_version,
            workspace_root=workspace_root,
        ):
            continue
        write_json(offer_path, candidate)
        reused_ids.append(str(candidate.get("id") or offer_path.stem))
    return {
        "cache_root": str(cache_root),
        "profile_sha256": profile_sha256,
        "prompt_version": prompt_version,
        "reused_count": len(reused_ids),
        "reused_offer_ids": sorted(reused_ids),
    }
