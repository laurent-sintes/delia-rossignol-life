from __future__ import annotations

import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .core import load_json, write_json
from .offer_coverage import configured_sector_functional_pairs
from .offer_search import load_offer_files, offer_identity
from .storage import remove_tree

OFFER_SCAN_ACTIONS = {"clean-cache", "full", "delta", "send"}
SAFE_RUNTIME_SUFFIX = (".runtime", "offer-search")
MANUAL_SOURCE_RECEIPT_STATUSES = {"success", "no_access", "skipped"}


def _safe_runtime_root(runtime_root: Path, workspace_root: Path | None = None) -> Path:
    workspace = (workspace_root or Path.cwd()).resolve()
    candidate = (workspace / runtime_root).resolve() if not runtime_root.is_absolute() else runtime_root.resolve()
    try:
        relative = candidate.relative_to(workspace)
    except ValueError as error:
        raise ValueError("offer scan cache root must stay inside the workspace") from error
    if relative.parts[-2:] != SAFE_RUNTIME_SUFFIX:
        raise ValueError("offer scan cache root must end with .runtime/offer-search")
    return candidate


def clean_offer_scan_cache(runtime_root: Path, workspace_root: Path | None = None) -> dict[str, Any]:
    """Remove only disposable offer-scan state, never versioned business data."""
    safe_root = _safe_runtime_root(runtime_root, workspace_root)
    existed = safe_root.exists()
    remove_tree(safe_root, ignore_errors=False)
    return {
        "action": "clean-cache",
        "cache_cleaned": True,
        "cache_existed": existed,
        "cache_root": str(safe_root),
        "preserved_roots": ["data/offers", "generated/offer-search"],
    }


def _verification_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.date() if parsed.tzinfo is not None else None


def _latest_historical_offers(offers_root: Path) -> list[dict[str, Any]]:
    if not offers_root.exists():
        return []
    latest: dict[str, dict[str, Any]] = {}
    for offer in load_offer_files(offers_root):
        identity = offer_identity(offer)
        current = latest.get(identity)
        priority = (_verification_date(offer.get("last_verified_at")) or date.min, str(offer.get("id") or ""))
        current_priority = (
            _verification_date(current.get("last_verified_at")) or date.min,
            str(current.get("id") or ""),
        ) if current is not None else (date.min, "")
        if current is None or priority > current_priority:
            latest[identity] = offer
    return list(latest.values())


def _revalidation_queue(
    offers_root: Path,
    scan_mode: str,
    today: date,
    maximum_age_days: int,
) -> list[dict[str, Any]]:
    if scan_mode == "full":
        return []
    queue: list[dict[str, Any]] = []
    for offer in _latest_historical_offers(offers_root):
        status = str(offer.get("verification_status") or "pending")
        verified_at = _verification_date(offer.get("last_verified_at"))
        age = (today - verified_at).days if verified_at is not None else None
        reason: str | None = None
        if status == "pending":
            reason = "annonce en attente de revérification"
        elif status == "active" and (age is None or age > maximum_age_days):
            reason = "date de vérification absente" if age is None else f"contrôle datant de {age} jours"
        if reason is None:
            continue
        queue.append(
            {
                "id": offer.get("id"),
                "canonical_offer_id": offer.get("canonical_offer_id"),
                "title": offer.get("title"),
                "employer": offer.get("employer"),
                "source_url": offer.get("source_url"),
                "employer_source_url": offer.get("employer_source_url"),
                "verification_status": status,
                "last_verified_at": offer.get("last_verified_at"),
                "reason": reason,
            }
        )
    return sorted(queue, key=lambda item: (str(item.get("employer") or "").casefold(), str(item.get("title") or "").casefold()))


def _scan_requirements(policy: dict[str, Any], source_audit: dict[str, Any], scan_mode: str) -> dict[str, Any]:
    priorities = {"core", "complementary"} if scan_mode == "full" else {"core"}
    required_sources = sorted(
        {
            str(source.get("scan_domain") or "").casefold().removeprefix("www.")
            for source in source_audit.get("sources", [])
            if isinstance(source, dict)
            and source.get("scan_priority") in priorities
            and source.get("automated_collection", True)
            and source.get("scan_domain")
        }
    )
    configured_manual_sources = policy.get("manual_source_domains")
    manual_sources = sorted(
        {
            str(domain).casefold().removeprefix("www.")
            for priority in priorities
            for domain in (
                configured_manual_sources.get(priority, [])
                if isinstance(configured_manual_sources, dict)
                else []
            )
            if str(domain).strip()
        }
    )
    configured_sector_coverage = policy.get("priority_sector_coverage")
    required_sector_functional_pairs = configured_sector_functional_pairs(policy)
    manual_sector_coverage = {
        domain: sorted(
            str(sector_id)
            for sector_id, domains in (
                configured_sector_coverage.items()
                if isinstance(configured_sector_coverage, dict)
                else []
            )
            if isinstance(domains, list)
            and domain
            in {
                str(value).casefold().removeprefix("www.")
                for value in domains
            }
        )
        for domain in manual_sources
    }
    audited_manual_dimensions = {
        str(source.get("scan_domain") or "").casefold().removeprefix("www."): (
            {str(value) for value in source.get("sectors", [])},
            {str(value) for value in source.get("functional_domains", [])},
        )
        for source in source_audit.get("sources", [])
        if isinstance(source, dict) and source.get("scan_domain")
    }
    manual_pair_coverage = {
        domain: sorted(
            pair
            for pair in required_sector_functional_pairs
            if pair.split("::", 1)[0]
            in audited_manual_dimensions.get(domain, (set(), set()))[0]
            and pair.split("::", 1)[1]
            in audited_manual_dimensions.get(domain, (set(), set()))[1]
        )
        for domain in manual_sources
    }
    return {
        "required_source_domains": required_sources,
        "manual_source_domains": manual_sources,
        "manual_source_sector_coverage": manual_sector_coverage,
        "manual_source_sector_functional_coverage": manual_pair_coverage,
        "required_query_families": sorted(str(value) for value in policy.get("functional_query_families", {})),
        "required_priority_sectors": sorted(str(value) for value in policy.get("priority_sector_coverage", {})),
        "required_sector_functional_pairs": sorted(required_sector_functional_pairs),
    }


def prepare_offer_scan(
    action: str,
    *,
    runtime_root: Path = Path(".runtime/offer-search"),
    offers_root: Path = Path("data/offers"),
    reports_root: Path = Path("generated/offer-search"),
    policy_path: Path = Path("config/offer-search.json"),
    source_audit_path: Path | None = None,
    workspace_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if action not in OFFER_SCAN_ACTIONS:
        raise ValueError(f"unknown offer scan action: {action}")
    safe_runtime_root = _safe_runtime_root(runtime_root, workspace_root)
    if action == "clean-cache":
        return clean_offer_scan_cache(safe_runtime_root, workspace_root)

    effective_now = now or datetime.now().astimezone()
    if effective_now.tzinfo is None:
        raise ValueError("offer scan start time must include a timezone")

    scan_mode = "full" if action in {"full", "send"} else "delta"
    cleanup = clean_offer_scan_cache(safe_runtime_root, workspace_root) if scan_mode == "full" else {
        "action": "clean-cache",
        "cache_cleaned": False,
        "cache_existed": safe_runtime_root.exists(),
        "cache_root": str(safe_runtime_root),
        "preserved_roots": ["data/offers", "generated/offer-search"],
    }
    policy = load_json(policy_path)
    audit_path = source_audit_path or Path(str(policy["regional_source_audit"]))
    source_audit = load_json(audit_path)
    requirements = _scan_requirements(policy, source_audit, scan_mode)
    revalidation_queue = _revalidation_queue(
        offers_root,
        scan_mode,
        effective_now.date(),
        int(policy["active_verification_max_age_days"]),
    )
    session_id = effective_now.strftime("%Y-%m-%d-%H%M%S-%f") + f"-{scan_mode}"
    offer_directory = offers_root / effective_now.date().isoformat() / session_id
    report_path = reports_root / f"{session_id}.json"
    manifest_path = safe_runtime_root / "current.json"
    offer_directory.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": 2,
        "action": action,
        "scan_id": session_id,
        "scan_mode": scan_mode,
        "started_at": effective_now.isoformat(),
        "cache_cleaned": cleanup["cache_cleaned"],
        "history_policy": "fresh-session-only" if scan_mode == "full" else "cumulative-history",
        "offer_output_directory": str(offer_directory),
        "rank_inputs": [str(offer_directory)] if scan_mode == "full" else [str(offers_root)],
        "report_output_path": str(report_path),
        "delivery_requested": action == "send",
        "requirements": requirements,
        "manual_source_receipts": [],
        "collection": None,
        "revalidation_queue": revalidation_queue,
        "revalidation_count": len(revalidation_queue),
        "status": "collecting",
    }
    write_json(manifest_path, manifest)
    return {**manifest, "manifest_path": str(manifest_path)}


def record_manual_source_receipts(
    manifest_path: Path,
    receipt_batch_path: Path,
) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    batch = load_json(receipt_batch_path)
    if not isinstance(manifest, dict) or not manifest.get("scan_id"):
        raise ValueError("invalid offer scan manifest")
    if not isinstance(batch, dict) or batch.get("scan_id") != manifest.get("scan_id"):
        raise ValueError("manual source receipt batch must target the current scan_id")
    requirements = manifest.get("requirements")
    requirements = requirements if isinstance(requirements, dict) else {}
    scan_started_at = str(manifest.get("started_at") or "")
    try:
        parsed_scan_started_at = datetime.fromisoformat(scan_started_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("offer scan manifest has an invalid started_at timestamp") from error
    if parsed_scan_started_at.tzinfo is None:
        raise ValueError("offer scan manifest started_at timestamp must include a timezone")
    required_manual_domains = {
        str(value).casefold().removeprefix("www.")
        for value in requirements.get("manual_source_domains", [])
        if str(value).strip()
    }
    required_query_families = {
        str(value) for value in requirements.get("required_query_families", [])
    }
    required_priority_sectors = {
        str(value) for value in requirements.get("required_priority_sectors", [])
    }
    required_sector_functional_pairs = {
        str(value)
        for value in requirements.get("required_sector_functional_pairs", [])
        if str(value).strip()
    }
    configured_sector_coverage = requirements.get("manual_source_sector_coverage")
    configured_sector_coverage = (
        configured_sector_coverage if isinstance(configured_sector_coverage, dict) else {}
    )
    configured_pair_coverage = requirements.get("manual_source_sector_functional_coverage")
    configured_pair_coverage = (
        configured_pair_coverage if isinstance(configured_pair_coverage, dict) else {}
    )
    receipts = batch.get("receipts")
    if not isinstance(receipts, list) or not receipts:
        raise ValueError("manual source receipt batch must contain at least one receipt")

    normalized_receipts: list[dict[str, Any]] = []
    seen_domains: set[str] = set()
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise ValueError("manual source receipt must be an object")
        domain = str(receipt.get("domain") or "").casefold().removeprefix("www.")
        if domain not in required_manual_domains:
            raise ValueError(f"manual source is not required by this scan: {domain or '(missing)'}")
        if domain in seen_domains:
            raise ValueError(f"duplicate manual source receipt: {domain}")
        seen_domains.add(domain)
        status = str(receipt.get("status") or "")
        if status not in MANUAL_SOURCE_RECEIPT_STATUSES:
            raise ValueError(f"invalid manual source receipt status for {domain}: {status}")
        source_url = str(receipt.get("source_url") or "").strip()
        parsed_url = urlsplit(source_url)
        source_host = parsed_url.netloc.casefold().split("@")[-1].split(":")[0].removeprefix("www.")
        if (
            parsed_url.scheme.casefold() not in {"http", "https"}
            or not source_host
            or not (source_host == domain or source_host.endswith("." + domain))
        ):
            raise ValueError(f"manual source receipt URL does not match {domain}")
        checked_at = str(receipt.get("checked_at") or "")
        try:
            parsed_checked_at = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"invalid manual source receipt timestamp for {domain}") from error
        if parsed_checked_at.tzinfo is None:
            raise ValueError(f"manual source receipt timestamp must include a timezone for {domain}")
        if parsed_checked_at < parsed_scan_started_at:
            raise ValueError(f"manual source receipt predates the current scan for {domain}")
        offers_found = receipt.get("offers_found")
        if not isinstance(offers_found, int) or isinstance(offers_found, bool) or offers_found < 0:
            raise ValueError(f"manual source receipt offers_found must be a non-negative integer for {domain}")
        note = str(receipt.get("note") or "").strip()
        if status != "success" and not note:
            raise ValueError(f"manual source receipt note is required for status {status}: {domain}")
        covered_query_families = {
            str(value)
            for value in receipt.get("covered_query_families", [])
            if str(value).strip()
        }
        unknown_query_families = covered_query_families - required_query_families
        if unknown_query_families:
            raise ValueError(
                f"manual source receipt has unknown query families for {domain}: "
                + ", ".join(sorted(unknown_query_families))
            )
        allowed_priority_sectors = {
            str(value)
            for value in configured_sector_coverage.get(domain, [])
            if str(value).strip()
        }
        covered_priority_sectors = {
            str(value)
            for value in receipt.get("covered_priority_sectors", [])
            if str(value).strip()
        }
        invalid_priority_sectors = covered_priority_sectors - allowed_priority_sectors
        if invalid_priority_sectors:
            raise ValueError(
                f"manual source receipt cannot cover sectors for {domain}: "
                + ", ".join(sorted(invalid_priority_sectors))
            )
        allowed_sector_functional_pairs = {
            str(value)
            for value in configured_pair_coverage.get(domain, [])
            if str(value).strip()
        }
        covered_sector_functional_pair_ids = {
            str(value)
            for value in receipt.get("covered_sector_functional_pairs", [])
            if str(value).strip()
        }
        invalid_sector_functional_pairs = (
            covered_sector_functional_pair_ids - allowed_sector_functional_pairs
        )
        if invalid_sector_functional_pairs:
            raise ValueError(
                f"manual source receipt cannot cover sector-functional pairs for {domain}: "
                + ", ".join(sorted(invalid_sector_functional_pairs))
            )
        unsupported_sector_functional_pairs = {
            pair
            for pair in covered_sector_functional_pair_ids
            if "::" not in pair
            or pair.split("::", 1)[0] not in covered_priority_sectors
            or pair.split("::", 1)[1] not in covered_query_families
        }
        if unsupported_sector_functional_pairs:
            raise ValueError(
                f"manual source receipt pair dimensions are not covered for {domain}: "
                + ", ".join(sorted(unsupported_sector_functional_pairs))
            )
        if status != "success" and (
            covered_query_families
            or covered_priority_sectors
            or covered_sector_functional_pair_ids
        ):
            raise ValueError(
                f"manual source receipt with status {status} cannot declare coverage: {domain}"
            )
        normalized_receipts.append(
            {
                "domain": domain,
                "status": status,
                "source_url": source_url,
                "checked_at": parsed_checked_at.isoformat(),
                "offers_found": offers_found,
                "note": note or None,
                "covered_query_families": sorted(covered_query_families),
                "covered_priority_sectors": sorted(covered_priority_sectors),
                "covered_sector_functional_pairs": sorted(
                    covered_sector_functional_pair_ids
                ),
            }
        )

    existing_receipts = manifest.get("manual_source_receipts")
    receipt_by_domain = {
        str(receipt.get("domain") or ""): receipt
        for receipt in existing_receipts
        if isinstance(receipt, dict) and str(receipt.get("domain") or "")
    } if isinstance(existing_receipts, list) else {}
    receipt_by_domain.update(
        {str(receipt["domain"]): receipt for receipt in normalized_receipts}
    )
    updated_receipts = [receipt_by_domain[domain] for domain in sorted(receipt_by_domain)]
    successful_domains = {
        str(receipt["domain"])
        for receipt in updated_receipts
        if receipt.get("status") == "success"
    }
    missing_domains = sorted(required_manual_domains - successful_domains)
    collection = manifest.get("collection")
    collection = collection if isinstance(collection, dict) else {}
    covered_query_families = {
        str(value) for value in collection.get("covered_query_families", [])
    }
    covered_priority_sectors = {
        str(value) for value in collection.get("covered_priority_sectors", [])
    }
    covered_sector_functional_pair_ids = {
        str(value)
        for value in collection.get("covered_sector_functional_pairs", [])
    }
    visited_sources = {
        str(value) for value in collection.get("visited_sources", []) if str(value).strip()
    }
    for receipt in updated_receipts:
        if receipt.get("status") != "success":
            continue
        covered_query_families.update(
            str(value) for value in receipt.get("covered_query_families", [])
        )
        covered_priority_sectors.update(
            str(value) for value in receipt.get("covered_priority_sectors", [])
        )
        covered_sector_functional_pair_ids.update(
            str(value)
            for value in receipt.get("covered_sector_functional_pairs", [])
        )
        visited_sources.add(str(receipt["source_url"]))
    missing_query_families = sorted(required_query_families - covered_query_families)
    missing_priority_sectors = sorted(required_priority_sectors - covered_priority_sectors)
    missing_sector_functional_pairs = sorted(
        required_sector_functional_pairs - covered_sector_functional_pair_ids
    )
    collection_complete = (
        not missing_domains
        and not collection.get("failed_source_domains", [])
        and not missing_query_families
        and not missing_priority_sectors
        and not missing_sector_functional_pairs
    )
    output_directory = Path(str(manifest.get("offer_output_directory") or ""))
    collected_output_directory = Path(
        str(collection.get("collected_output_directory") or output_directory)
    )
    promoted = bool(collection.get("promoted_to_rank_inputs"))
    if collection_complete and not promoted and collected_output_directory != output_directory:
        output_directory.mkdir(parents=True, exist_ok=True)
        for source_path in sorted(collected_output_directory.glob("*.json")):
            shutil.copy2(source_path, output_directory / source_path.name)
        promoted = True
        collected_output_directory = output_directory
    semantic_review_queue = []
    for entry in collection.get("semantic_review_queue", []):
        if not isinstance(entry, dict):
            continue
        offer_id = str(entry.get("offer_id") or "")
        semantic_review_queue.append(
            {
                **entry,
                "offer_path": str(collected_output_directory / f"{offer_id}.json"),
            }
        )
    updated_collection = {
        **collection,
        "visited_sources": sorted(visited_sources),
        "covered_query_families": sorted(covered_query_families),
        "covered_priority_sectors": sorted(covered_priority_sectors),
        "covered_sector_functional_pairs": sorted(
            covered_sector_functional_pair_ids
        ),
        "missing_query_families": missing_query_families,
        "missing_priority_sectors": missing_priority_sectors,
        "missing_sector_functional_pairs": missing_sector_functional_pairs,
        "collected_output_directory": str(collected_output_directory),
        "promoted_to_rank_inputs": promoted,
        "semantic_review_queue": semantic_review_queue,
        "complete": collection_complete,
    }
    updated_manifest = {
        **manifest,
        "manual_source_receipts": updated_receipts,
        "manual_source_control": {
            "required_count": len(required_manual_domains),
            "recorded_count": len(updated_receipts),
            "successful_count": len(successful_domains),
            "missing_domains": missing_domains,
            "complete": not missing_domains,
        },
        "collection": updated_collection,
        "status": "collected" if collection_complete else "collection-incomplete",
    }
    write_json(manifest_path, updated_manifest)
    return {
        "scan_id": manifest["scan_id"],
        "manifest_path": str(manifest_path),
        "recorded_count": len(normalized_receipts),
        "manual_source_control": updated_manifest["manual_source_control"],
        "collection_complete": collection_complete,
        "promoted_to_rank_inputs": promoted,
    }


def run_offer_scan(
    action: str,
    *,
    runtime_root: Path = Path(".runtime/offer-search"),
    offers_root: Path = Path("data/offers"),
    reports_root: Path = Path("generated/offer-search"),
    semantic_cache_root: Path = Path("generated/offer-semantic-cache"),
    policy_path: Path = Path("config/offer-search.json"),
    source_audit_path: Path | None = None,
    archive_root: Path = Path("private/offer-scan-archives"),
    career_project_path: Path = Path("private/career-project/delia-next-role-2026.json"),
    knowledge_root: Path = Path("data/knowledge"),
) -> dict[str, Any]:
    """Prepare, collect and rank an offer scan without manual coverage declarations."""
    if action not in {"full", "delta"}:
        raise ValueError("run-offer-scan only supports full or delta; sending remains a separate authorized action")
    from .offer_collection import collect_offers
    from .offer_review import reuse_cached_semantic_reviews
    from .offer_search import (
        collect_validated_absent_certifications,
        collect_validated_absent_sector_experience_ids,
        collect_validated_knowledge_evidence_catalog,
        collect_validated_knowledge_tokens,
        collect_validated_profile_completeness,
        collect_validated_sector_experience_months,
        rank_offers,
        semantic_profile_sha256,
    )

    prepared = prepare_offer_scan(
        action,
        runtime_root=runtime_root,
        offers_root=offers_root,
        reports_root=reports_root,
        policy_path=policy_path,
        source_audit_path=source_audit_path,
    )
    manifest_path = Path(str(prepared["manifest_path"]))
    collection = collect_offers(
        manifest_path,
        policy_path=policy_path,
        source_audit_path=source_audit_path,
        archive_root=archive_root,
    )
    manifest = load_json(manifest_path)
    semantic_cache = reuse_cached_semantic_reviews(
        Path(str(collection["collected_output_directory"])),
        knowledge_root=knowledge_root,
        policy_path=policy_path,
        cache_root=semantic_cache_root,
    )
    reused_ids = set(semantic_cache["reused_offer_ids"])
    queued = [
        entry
        for entry in collection.get("semantic_review_queue", [])
        if isinstance(entry, dict) and str(entry.get("offer_id") or "") not in reused_ids
    ]
    collection = {
        **collection,
        "semantic_review_queue": queued,
        "semantic_review_required_count": len(queued),
        "semantic_cache": semantic_cache,
    }
    manifest = {**manifest, "collection": collection}
    write_json(manifest_path, manifest)
    offers = [offer for path in manifest["rank_inputs"] for offer in load_offer_files(Path(str(path)))]
    policy = load_json(policy_path)
    report = rank_offers(
        offers,
        load_json(career_project_path),
        policy,
        collect_validated_knowledge_tokens(knowledge_root),
        visited_sources=list(collection["visited_sources"]),
        complete_profile_dimensions=collect_validated_profile_completeness(knowledge_root),
        sector_experience_months=collect_validated_sector_experience_months(knowledge_root),
        absent_sector_experience_ids=collect_validated_absent_sector_experience_ids(knowledge_root),
        absent_certifications=collect_validated_absent_certifications(knowledge_root),
        knowledge_evidence_catalog=collect_validated_knowledge_evidence_catalog(knowledge_root),
        semantic_profile_fingerprint=semantic_profile_sha256(knowledge_root),
        scan_requirements=manifest.get("requirements"),
        covered_query_families=set(collection["covered_query_families"]),
        covered_priority_sectors=set(collection["covered_priority_sectors"]),
        covered_sector_functional_pairs=set(
            collection.get("covered_sector_functional_pairs", [])
        ),
        manual_source_receipts=manifest.get("manual_source_receipts", []),
        require_scan_coverage=True,
    )
    report_path = Path(str(manifest["report_output_path"]))
    write_json(report_path, report)
    semantic_review_pending = int(report.get("semantic_review", {}).get("pending_count", 0))
    scan_status = (
        "semantic-review-required"
        if semantic_review_pending
        else "complete" if report["finalization_allowed"] else "incomplete"
    )
    final_manifest = {
        **manifest,
        "status": scan_status,
        "completed_at": datetime.now().astimezone().isoformat(),
        "report_summary": {
            key: report[key]
            for key in (
                "candidate_count",
                "unique_count",
                "active_count",
                "eligible_count",
                "excluded_count",
                "selected_count",
                "pool_complete",
                "finalization_allowed",
            )
        }
        | {
            key: report[key]
            for key in (
                "presentation_count",
                "quasi_duplicate_group_count",
                "quasi_duplicate_offer_count",
            )
            if key in report
        }
        | {"semantic_review_pending_count": semantic_review_pending},
    }
    write_json(manifest_path, final_manifest)
    return {
        "action": action,
        "scan_id": manifest["scan_id"],
        "manifest_path": str(manifest_path),
        "report_output_path": str(report_path),
        "collection": collection,
        "semantic_cache": semantic_cache,
        "report_summary": final_manifest["report_summary"],
        "status": final_manifest["status"],
    }
