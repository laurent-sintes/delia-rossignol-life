from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from .core import load_json, write_json
from .offer_search import load_offer_files, offer_identity
from .storage import remove_tree

OFFER_SCAN_ACTIONS = {"clean-cache", "full", "delta", "send"}
SAFE_RUNTIME_SUFFIX = (".runtime", "offer-search")


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
    queue: list[dict[str, Any]] = []
    for offer in _latest_historical_offers(offers_root):
        status = str(offer.get("verification_status") or "pending")
        verified_at = _verification_date(offer.get("last_verified_at"))
        age = (today - verified_at).days if verified_at is not None else None
        reason: str | None = None
        if status == "pending":
            reason = "annonce en attente de revérification"
        elif status == "active" and scan_mode == "full":
            reason = "revérification complète de l’annonce active"
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
            if isinstance(source, dict) and source.get("scan_priority") in priorities and source.get("scan_domain")
        }
    )
    return {
        "required_source_domains": required_sources,
        "required_query_families": sorted(str(value) for value in policy.get("functional_query_families", {})),
        "required_priority_sectors": sorted(str(value) for value in policy.get("priority_sector_coverage", {})),
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
        "schema_version": 1,
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
        "revalidation_queue": revalidation_queue,
        "revalidation_count": len(revalidation_queue),
        "status": "collecting",
    }
    write_json(manifest_path, manifest)
    return {**manifest, "manifest_path": str(manifest_path)}
