from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
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


def score_offer(
    offer: dict[str, Any],
    career_project: dict[str, Any],
    policy: dict[str, Any],
    knowledge_tokens: set[str],
    today: date | None = None,
) -> dict[str, Any]:
    """Preserve the public scoring API while delegating to the focused engine."""
    return _score_offer(offer, career_project, policy, knowledge_tokens, today)


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
        if current is None or len(strings(offer)) > len(strings(current)):
            deduplicated[identity] = offer
    return deduplicated


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
            return selected

    selected_ids = {item.identity for item in selected}
    for item in deferred:
        if item.identity not in selected_ids:
            selected.append(item)
            selected_ids.add(item.identity)
        if len(selected) == result_limit:
            break
    return selected


def _ranked_offer_record(item: AssessedOffer, rank: int) -> dict[str, Any]:
    offer = item.offer
    return {
        "rank": rank,
        "id": offer.get("id"),
        "title": offer.get("title"),
        "employer": offer.get("employer"),
        "source_url": offer.get("source_url"),
        "source_site": offer.get("source_site"),
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


def _ranking_warnings(candidate_count: int, ranked_count: int, result_limit: int, policy: dict[str, Any]) -> list[str]:
    warnings = []
    if candidate_count < int(policy["candidate_pool_minimum"]):
        warnings.append(
            f"pool incomplet : {candidate_count} offres collectées, {policy['candidate_pool_minimum']} attendues"
        )
    if ranked_count < result_limit:
        warnings.append(f"seulement {ranked_count} offres éligibles pour une cible de {result_limit}")
    return warnings


def rank_offers(
    offers: list[dict[str, Any]],
    career_project: dict[str, Any],
    policy: dict[str, Any],
    knowledge_tokens: set[str],
    limit: int | None = None,
    today: date | None = None,
    visited_sources: list[str] | None = None,
) -> dict[str, Any]:
    deduplicated = _deduplicate_offers(offers)
    context = _build_scoring_context(career_project, policy, knowledge_tokens, today)
    eligible, excluded = _assess_offers(deduplicated, context)
    result_limit = limit or int(policy["result_limit"])
    selected = _select_diverse_offers(
        eligible,
        result_limit,
        int(policy["diversity"]["max_per_employer"]),
        int(policy["diversity"]["max_per_source"]),
    )
    ranked = [_ranked_offer_record(item, index) for index, item in enumerate(selected, start=1)]
    return {
        "policy_id": policy["id"],
        "candidate_count": len(offers),
        "unique_count": len(deduplicated),
        "eligible_count": len(eligible),
        "excluded_count": len(excluded),
        "visited_sources": consulted_source_origins(offers, visited_sources),
        "warnings": _ranking_warnings(len(offers), len(ranked), result_limit, policy),
        "offers": ranked,
        "section_counts": _section_counts(ranked),
        "excluded": [
            {
                "id": item.offer.get("id"),
                "title": item.offer.get("title"),
                "employer": item.offer.get("employer"),
                "score": item.assessment["score"],
                "failures": item.assessment["hard_constraint_failures"],
            }
            for item in excluded
        ],
    }


def load_offer_files(path: Path) -> list[dict[str, Any]]:
    paths = [path] if path.is_file() else sorted(path.rglob("*.json"))
    return [document for file_path in paths for document in [load_json(file_path)] if isinstance(document, dict)]
