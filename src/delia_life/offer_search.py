from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .core import load_json
from .offer_scoring import (
    RECOMMENDATION_BAND_ORDER,
    ScoringContext,
    _build_scoring_context,
    _score_offer_with_context,
    plain,
    strings,
    tokens,
)
from .offer_scoring import (
    score_offer as _score_offer,
)

TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}
VERIFICATION_STATUSES = {"active", "closed", "expired", "pending", "unreachable"}


def score_offer(
    offer: dict[str, Any],
    career_project: dict[str, Any],
    policy: dict[str, Any],
    knowledge_tokens: set[str],
    today: date | None = None,
    complete_profile_dimensions: set[str] | None = None,
    sector_experience_months: dict[str, int] | None = None,
    absent_sector_experience_ids: set[str] | None = None,
    absent_certifications: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Preserve the public scoring API while delegating to the focused engine."""
    return _score_offer(
        offer,
        career_project,
        policy,
        knowledge_tokens,
        today,
        complete_profile_dimensions,
        sector_experience_months,
        absent_sector_experience_ids,
        absent_certifications,
    )


def canonical_offer_url(value: str) -> str:
    parts = urlsplit(value.strip())
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_PARAMETERS
    ]
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"), urlencode(query), ""))


def source_origin(value: str) -> str | None:
    """Return a safe HTTP(S) origin for a consulted source label or URL."""
    candidate = value.strip()
    if not candidate:
        return None
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", candidate) and "://" not in candidate:
        return None
    if "://" not in candidate:
        candidate = "https://" + candidate
    parts = urlsplit(candidate)
    if parts.scheme.casefold() not in {"http", "https"} or not parts.netloc:
        return None
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), "", "", ""))


def consulted_source_origins(
    offers: list[dict[str, Any]],
    visited_sources: list[str] | None = None,
) -> list[str]:
    """Merge explicitly visited sites with origins evidenced by collected offers."""
    origins: dict[str, str] = {}
    candidates = list(visited_sources or [])
    for offer in offers:
        candidates.append(str(offer.get("source_url") or offer.get("source_site") or ""))
    for candidate in candidates:
        origin = source_origin(candidate)
        if origin is not None:
            origins.setdefault(origin.casefold(), origin)
    return list(origins.values())


def offer_identity(offer: dict[str, Any]) -> str:
    canonical_id = str(offer.get("canonical_offer_id", "")).strip()
    if canonical_id:
        return "canonical:" + plain(str(offer.get("employer", ""))) + "|" + plain(canonical_id)
    employer_source_url = str(offer.get("employer_source_url", "")).strip()
    if employer_source_url:
        return canonical_offer_url(employer_source_url)
    source_url = str(offer.get("source_url", "")).strip()
    if source_url:
        return canonical_offer_url(source_url)
    return "|".join(
        plain(str(offer.get(field, "")).strip())
        for field in ("employer", "title", "location_label", "contract_type")
    )


def collect_validated_knowledge_tokens(knowledge_root: Path) -> set[str]:
    values: list[str] = []
    for path in sorted(knowledge_root.rglob("*.json")):
        document = load_json(path)
        if isinstance(document, dict):
            for envelope in document.get("fields", {}).values():
                if isinstance(envelope, dict) and "value" in envelope:
                    values.extend(strings(envelope["value"]))
            values.extend(strings(document.get("skills", [])))
    return tokens(values)


def collect_validated_profile_completeness(
    knowledge_root: Path,
    subject_id: str = "delia-rossignol",
) -> set[str]:
    dimensions: set[str] = set()
    for path in sorted(knowledge_root.rglob("*.json")):
        document = load_json(path)
        if not isinstance(document, dict) or document.get("type") != "knowledge-fact":
            continue
        for envelope in document.get("fields", {}).values():
            if not isinstance(envelope, dict):
                continue
            value = envelope.get("value")
            if not isinstance(value, dict):
                continue
            if value.get("subject_id") != subject_id or value.get("complete") is not True:
                continue
            dimension = str(value.get("dimension") or "").strip()
            if dimension:
                dimensions.add(dimension)
    return dimensions


def _validated_field(document: dict[str, Any], field: str) -> Any:
    envelope = document.get("fields", {}).get(field)
    return envelope.get("value") if isinstance(envelope, dict) else None


def _month_index(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", value.strip())
    if match is None:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return year * 12 + month - 1


def _validated_experience_month_range(document: dict[str, Any], today: date) -> tuple[int, int] | None:
    current_month = today.year * 12 + today.month - 1
    for field, end_key in (("timeframe", "end_date"), ("chronology", "known_through"), ("details", "end_date")):
        value = _validated_field(document, field)
        if not isinstance(value, dict):
            continue
        start = _month_index(value.get("start_date"))
        end = _month_index(value.get(end_key))
        if start is not None and end is not None and start <= end:
            return start, min(end, current_month)
    return None


def collect_validated_sector_experience_months(
    knowledge_root: Path,
    today: date | None = None,
) -> dict[str, int]:
    effective_today = today or date.today()
    ranges: dict[str, list[tuple[int, int]]] = {}
    for path in sorted(knowledge_root.rglob("*.json")):
        document = load_json(path)
        if not isinstance(document, dict) or document.get("type") != "experience":
            continue
        sector_ids = _validated_field(document, "industry_sector_ids")
        month_range = _validated_experience_month_range(document, effective_today)
        if not isinstance(sector_ids, list) or month_range is None:
            continue
        for sector_id in sector_ids:
            normalized = str(sector_id).strip()
            if normalized:
                ranges.setdefault(normalized, []).append(month_range)
    totals: dict[str, int] = {}
    for sector_id, periods in ranges.items():
        merged: list[tuple[int, int]] = []
        for start, end in sorted(periods):
            if merged and start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        totals[sector_id] = sum(end - start + 1 for start, end in merged)
    return totals


def collect_validated_absent_sector_experience_ids(
    knowledge_root: Path,
    subject_id: str = "delia-rossignol",
) -> set[str]:
    sector_ids: set[str] = set()
    for path in sorted(knowledge_root.rglob("*.json")):
        document = load_json(path)
        if not isinstance(document, dict) or document.get("type") != "knowledge-fact":
            continue
        for envelope in document.get("fields", {}).values():
            if not isinstance(envelope, dict):
                continue
            value = envelope.get("value")
            if not isinstance(value, dict):
                continue
            if (
                value.get("subject_id") != subject_id
                or value.get("dimension") != "sector_experience"
                or value.get("status") != "absent"
            ):
                continue
            for sector_id in value.get("industry_sector_ids", []):
                normalized = str(sector_id).strip()
                if normalized:
                    sector_ids.add(normalized)
    return sector_ids


def collect_validated_absent_certifications(
    knowledge_root: Path,
    subject_id: str = "delia-rossignol",
) -> dict[str, set[str]]:
    certifications: dict[str, set[str]] = {}
    for path in sorted(knowledge_root.rglob("*.json")):
        document = load_json(path)
        if not isinstance(document, dict) or document.get("type") != "knowledge-fact":
            continue
        for envelope in document.get("fields", {}).values():
            if not isinstance(envelope, dict):
                continue
            value = envelope.get("value")
            if not isinstance(value, dict):
                continue
            if (
                value.get("subject_id") != subject_id
                or value.get("dimension") != "certification"
                or value.get("status") != "absent"
            ):
                continue
            credential_id = str(value.get("credential_id") or "").strip()
            fact_id = str(document.get("id") or "").strip()
            if credential_id and fact_id:
                certifications.setdefault(credential_id, set()).add(f"knowledge-fact:{fact_id}")
    return certifications


@dataclass(frozen=True)
class AssessedOffer:
    offer: dict[str, Any]
    identity: str
    assessment: dict[str, Any]


def _deduplicate_offers(offers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    deduplicated: dict[str, dict[str, Any]] = {}
    for offer in offers:
        identity = offer_identity(offer)
        current = deduplicated.get(identity)
        priority = (_verified_datetime(offer.get("last_verified_at")) or datetime.min.replace(tzinfo=UTC), len(strings(offer)))
        current_priority = (
            _verified_datetime(current.get("last_verified_at")) or datetime.min.replace(tzinfo=UTC),
            len(strings(current)),
        ) if current is not None else (datetime.min.replace(tzinfo=UTC), -1)
        if current is None or priority > current_priority:
            deduplicated[identity] = offer
    return deduplicated


def _source_domain(offer: dict[str, Any]) -> str:
    value = str(offer.get("source_site") or "").strip().casefold()
    if value:
        return value.removeprefix("www.")
    return urlsplit(str(offer.get("source_url") or "")).netloc.casefold().removeprefix("www.")


def _source_kind(offer: dict[str, Any], policy: dict[str, Any]) -> str:
    declared = str(offer.get("source_kind") or "").strip()
    if declared in {"direct_employer", "specialized", "aggregator"}:
        return declared
    domain = _source_domain(offer)
    strategy = policy["source_strategy"]
    if domain in {str(item).casefold().removeprefix("www.") for item in strategy["direct_employer_domains"]}:
        return "direct_employer"
    if domain in {str(item).casefold().removeprefix("www.") for item in strategy["specialized_domains"]}:
        return "specialized"
    return "aggregator"


def _verified_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _verified_date(value: Any) -> date | None:
    verified_at = _verified_datetime(value)
    return verified_at.date() if verified_at is not None else None


def _verification_assessment(
    offer: dict[str, Any],
    policy: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    declared_status = str(offer.get("verification_status") or "pending").strip()
    source_kind = _source_kind(offer, policy)
    if declared_status not in VERIFICATION_STATUSES:
        return {
            "status": "pending",
            "source_kind": source_kind,
            "reason": f"état de vérification invalide : {declared_status}",
        }
    if declared_status != "active":
        reasons = {
            "closed": "annonce fermée",
            "expired": "annonce expirée",
            "pending": "annonce en attente de revérification",
            "unreachable": "page exacte momentanément inaccessible",
        }
        return {"status": declared_status, "source_kind": source_kind, "reason": reasons[declared_status]}

    verified_at = _verified_date(offer.get("last_verified_at"))
    if verified_at is None:
        return {
            "status": "pending",
            "source_kind": source_kind,
            "reason": "date de vérification absente ou invalide",
        }
    maximum_age = int(policy["active_verification_max_age_days"])
    age = (today - verified_at).days
    if age < 0:
        return {
            "status": "pending",
            "source_kind": source_kind,
            "reason": "date de vérification future incohérente",
        }
    if age > maximum_age:
        return {
            "status": "pending",
            "source_kind": source_kind,
            "reason": f"revérification nécessaire : contrôle datant de {age} jours",
        }
    return {"status": "active", "source_kind": source_kind, "reason": None}


def _partition_verified_offers(
    deduplicated: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    today: date,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    active: dict[str, dict[str, Any]] = {}
    excluded: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for identity, offer in deduplicated.items():
        assessment = _verification_assessment(offer, policy, today)
        status = str(assessment["status"])
        counts[status] += 1
        if status == "active":
            active[identity] = {**offer, "source_kind": assessment["source_kind"]}
            continue
        excluded.append(
            {
                "id": offer.get("id"),
                "title": offer.get("title"),
                "employer": offer.get("employer"),
                "source_url": offer.get("source_url"),
                "employer_source_url": offer.get("employer_source_url"),
                "source_site": offer.get("source_site"),
                "phase": "verification",
                "verification_status": status,
                "source_kind": assessment["source_kind"],
                "published_at": offer.get("published_at"),
                "last_verified_at": offer.get("last_verified_at"),
                "contract_type": offer.get("contract_type"),
                "location_label": offer.get("location_label"),
                "summary": offer.get("summary"),
                "verification_reason": assessment["reason"],
                "failures": [assessment["reason"]],
            }
        )
    return active, excluded, {status: counts[status] for status in sorted(VERIFICATION_STATUSES)}


def _assess_offers(
    deduplicated: dict[str, dict[str, Any]],
    context: ScoringContext,
) -> tuple[list[AssessedOffer], list[AssessedOffer]]:
    eligible: list[AssessedOffer] = []
    excluded: list[AssessedOffer] = []
    for identity, offer in deduplicated.items():
        assessment = _score_offer_with_context(offer, context)
        candidate = AssessedOffer(offer=offer, identity=identity, assessment=assessment)
        (eligible if assessment["eligible"] else excluded).append(candidate)
    eligible.sort(
        key=lambda item: (
            RECOMMENDATION_BAND_ORDER[item.assessment["recommendation_band"]],
            -item.assessment["score"],
            item.identity,
            str(item.offer.get("id", "")),
        )
    )
    return eligible, excluded


def _select_diverse_offers(
    eligible: list[AssessedOffer],
    result_limit: int,
    employer_limit: int,
    source_limit: int,
) -> list[AssessedOffer]:
    selected: list[AssessedOffer] = []
    deferred: list[AssessedOffer] = []
    employers: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    for item in eligible:
        employer = plain(str(item.offer.get("employer", "unknown")))
        source = plain(
            str(item.offer.get("source_site", urlsplit(str(item.offer.get("source_url", ""))).netloc or "unknown"))
        )
        if employers[employer] >= employer_limit or sources[source] >= source_limit:
            deferred.append(item)
            continue
        selected.append(item)
        employers[employer] += 1
        sources[source] += 1
        if len(selected) == result_limit:
            selected_ids = {selected_item.identity for selected_item in selected}
            return [candidate for candidate in eligible if candidate.identity in selected_ids]

    selected_ids = {item.identity for item in selected}
    for item in deferred:
        if item.identity not in selected_ids:
            selected.append(item)
            selected_ids.add(item.identity)
        if len(selected) == result_limit:
            break
    selected_ids = {item.identity for item in selected}
    return [candidate for candidate in eligible if candidate.identity in selected_ids]


def _ranked_offer_record(item: AssessedOffer, rank: int) -> dict[str, Any]:
    offer = item.offer
    return {
        "rank": rank,
        "id": offer.get("id"),
        "title": offer.get("title"),
        "employer": offer.get("employer"),
        "source_url": offer.get("source_url"),
        "source_site": offer.get("source_site"),
        "source_kind": offer.get("source_kind"),
        "source_warning": offer.get("source_warning"),
        "employer_source_url": offer.get("employer_source_url"),
        "verification_status": offer.get("verification_status"),
        "last_verified_at": offer.get("last_verified_at"),
        "published_at": offer.get("published_at"),
        "contract_type": offer.get("contract_type"),
        "full_time": offer.get("full_time"),
        "location_label": offer.get("location_label"),
        "sector_labels": offer.get("sector_labels", []),
        "industry_sector_ids": offer.get("industry_sector_ids", []),
        "compensation": offer.get("compensation"),
        "conditions": offer.get("conditions", {}),
        "prerequisites": offer.get("prerequisites", []),
        "summary": offer.get("summary"),
        "recommendation_band": item.assessment["recommendation_band"],
        "assessment": item.assessment,
    }


def _section_counts(offers: list[dict[str, Any]]) -> dict[str, int]:
    return {
        band: sum(offer.get("recommendation_band") == band for offer in offers)
        for band in ("priority", "possible", "informational")
    }


def _ranking_warnings(active_count: int, ranked_count: int, result_limit: int, policy: dict[str, Any]) -> list[str]:
    warnings = []
    if active_count > int(policy["candidate_pool_maximum"]):
        warnings.append(
            f"pool actif plafonné : {active_count} offres vérifiées, {policy['candidate_pool_maximum']} restituées au maximum"
        )
    if ranked_count < result_limit:
        warnings.append(f"seulement {ranked_count} offres éligibles pour une cible de {result_limit}")
    return warnings


def _domain(value: str) -> str:
    origin = source_origin(value)
    return urlsplit(origin).netloc.casefold().removeprefix("www.") if origin else ""


def _scan_coverage(
    requirements: dict[str, Any] | None,
    visited_sources: list[str] | None,
    covered_query_families: set[str] | None,
    covered_priority_sectors: set[str] | None,
    required: bool,
) -> dict[str, Any]:
    declared = isinstance(requirements, dict) and bool(requirements)
    required_sources = {
        str(value).casefold().removeprefix("www.")
        for value in (requirements or {}).get("required_source_domains", [])
        if str(value).strip()
    }
    manual_sources = sorted(
        str(value).casefold().removeprefix("www.")
        for value in (requirements or {}).get("manual_source_domains", [])
        if str(value).strip()
    )
    visited_domains = {_domain(value) for value in visited_sources or [] if _domain(value)}
    required_queries = {str(value) for value in (requirements or {}).get("required_query_families", [])}
    covered_queries = set(covered_query_families or set())
    required_sectors = {str(value) for value in (requirements or {}).get("required_priority_sectors", [])}
    covered_sectors = set(covered_priority_sectors or set())
    missing_sources = sorted(required_sources - visited_domains)
    missing_queries = sorted(required_queries - covered_queries)
    missing_sectors = sorted(required_sectors - covered_sectors)
    complete = (not required) or (declared and not missing_sources and not missing_queries and not missing_sectors)
    return {
        "required": required,
        "requirements_declared": declared,
        "complete": complete,
        "required_source_domains": sorted(required_sources),
        "manual_source_domains": manual_sources,
        "visited_source_domains": sorted(visited_domains),
        "missing_source_domains": missing_sources,
        "required_query_families": sorted(required_queries),
        "covered_query_families": sorted(covered_queries),
        "missing_query_families": missing_queries,
        "required_priority_sectors": sorted(required_sectors),
        "covered_priority_sectors": sorted(covered_sectors),
        "missing_priority_sectors": missing_sectors,
    }


def rank_offers(
    offers: list[dict[str, Any]],
    career_project: dict[str, Any],
    policy: dict[str, Any],
    knowledge_tokens: set[str],
    limit: int | None = None,
    today: date | None = None,
    visited_sources: list[str] | None = None,
    complete_profile_dimensions: set[str] | None = None,
    sector_experience_months: dict[str, int] | None = None,
    absent_sector_experience_ids: set[str] | None = None,
    absent_certifications: dict[str, set[str]] | None = None,
    scan_requirements: dict[str, Any] | None = None,
    covered_query_families: set[str] | None = None,
    covered_priority_sectors: set[str] | None = None,
    require_scan_coverage: bool = False,
) -> dict[str, Any]:
    deduplicated = _deduplicate_offers(offers)
    effective_today = today or date.today()
    active, verification_excluded, verification_counts = _partition_verified_offers(
        deduplicated,
        policy,
        effective_today,
    )
    context = _build_scoring_context(
        career_project,
        policy,
        knowledge_tokens,
        effective_today,
        complete_profile_dimensions,
        sector_experience_months,
        absent_sector_experience_ids,
        absent_certifications,
    )
    eligible, policy_excluded = _assess_offers(active, context)
    maximum_pool = int(policy["candidate_pool_maximum"])
    result_limit = int(policy["result_limit"]) if limit is None else limit
    if result_limit < 1 or result_limit > maximum_pool:
        raise ValueError(f"offer result limit must be between 1 and {maximum_pool}")
    selected = _select_diverse_offers(
        eligible,
        result_limit,
        int(policy["diversity"]["max_per_employer"]),
        int(policy["diversity"]["max_per_source"]),
    )
    ranked = [_ranked_offer_record(item, index) for index, item in enumerate(selected, start=1)]
    pending_offers = sorted(
        (
            item
            for item in verification_excluded
            if item.get("verification_status") == "pending"
        ),
        key=lambda item: (
            plain(str(item.get("employer") or "")),
            plain(str(item.get("title") or "")),
            str(item.get("id") or ""),
        ),
    )
    coverage = _scan_coverage(
        scan_requirements,
        visited_sources,
        covered_query_families,
        covered_priority_sectors,
        require_scan_coverage,
    )
    policy_excluded_ids = {
        str(item.offer.get("id") or item.offer.get("canonical_offer_id") or "")
        for item in policy_excluded
    }
    semantic_review_pending = sorted(
        str(offer.get("id") or offer.get("canonical_offer_id") or "unknown-offer")
        for offer in deduplicated.values()
        if isinstance(offer.get("extraction"), dict)
        and str(offer.get("id") or offer.get("canonical_offer_id") or "") not in policy_excluded_ids
        and offer["extraction"].get("method")
        in {"deterministic-json-ld", "deterministic-html", "deterministic-api"}
        and offer["extraction"].get("review_status") != "completed"
    )
    semantic_review = {
        "complete": not semantic_review_pending,
        "pending_count": len(semantic_review_pending),
        "pending_offer_ids": semantic_review_pending,
    }
    pool_complete = coverage["complete"] and semantic_review["complete"]
    warnings = _ranking_warnings(len(active), len(ranked), result_limit, policy)
    if require_scan_coverage and not coverage["requirements_declared"]:
        warnings.append("couverture de scan incomplète : manifeste de scan absent")
    if coverage["missing_source_domains"]:
        warnings.append("sources non consultées : " + ", ".join(coverage["missing_source_domains"]))
    if coverage["manual_source_domains"]:
        warnings.append(
            "sources exclues de la collecte Python par leurs règles d’accès et à contrôler manuellement : "
            + ", ".join(coverage["manual_source_domains"])
        )
    if coverage["missing_query_families"]:
        warnings.append("familles de requêtes non couvertes : " + ", ".join(coverage["missing_query_families"]))
    if coverage["missing_priority_sectors"]:
        warnings.append("secteurs prioritaires non couverts : " + ", ".join(coverage["missing_priority_sectors"]))
    if semantic_review_pending:
        warnings.append(
            f"revue sémantique requise pour {len(semantic_review_pending)} offre(s) extraite(s) automatiquement"
        )
    return {
        "policy_id": policy["id"],
        "candidate_count": len(offers),
        "unique_count": len(deduplicated),
        "active_count": len(active),
        "verification_counts": verification_counts,
        "verification_excluded_count": len(verification_excluded),
        "pending_offer_count": len(pending_offers),
        "eligible_count": len(eligible),
        "policy_excluded_count": len(policy_excluded),
        "excluded_count": len(verification_excluded) + len(policy_excluded),
        "selected_count": len(ranked),
        "candidate_pool_maximum": maximum_pool,
        "scan_coverage": coverage,
        "semantic_review": semantic_review,
        "active_overflow_count": max(0, len(active) - maximum_pool),
        "pool_complete": pool_complete,
        "report_status": "complete" if pool_complete else "incomplete",
        "finalization_allowed": pool_complete,
        "visited_sources": consulted_source_origins(offers, visited_sources),
        "warnings": warnings,
        "offers": ranked,
        "section_counts": _section_counts(ranked),
        "pending_offers": pending_offers,
        "excluded": verification_excluded + [
            {
                "id": item.offer.get("id"),
                "title": item.offer.get("title"),
                "employer": item.offer.get("employer"),
                "source_url": item.offer.get("source_url"),
                "employer_source_url": item.offer.get("employer_source_url"),
                "contract_type": item.offer.get("contract_type"),
                "location_label": item.offer.get("location_label"),
                "sector_labels": item.offer.get("sector_labels", []),
                "phase": "policy",
                "score": item.assessment["score"],
                "failures": item.assessment["hard_constraint_failures"],
            }
            for item in policy_excluded
        ],
    }


def load_offer_files(path: Path) -> list[dict[str, Any]]:
    paths = [path] if path.is_file() else sorted(path.rglob("*.json"))
    return [document for file_path in paths for document in [load_json(file_path)] if isinstance(document, dict)]
