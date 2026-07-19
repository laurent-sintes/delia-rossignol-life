from __future__ import annotations

import re
import unicodedata
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .core import load_json

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}
STOPWORDS = {
    "avec",
    "cette",
    "dans",
    "des",
    "elle",
    "entre",
    "est",
    "les",
    "leur",
    "nous",
    "offre",
    "pour",
    "sur",
    "une",
    "vous",
}


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def _tokens(value: Any) -> set[str]:
    return {token for token in TOKEN_PATTERN.findall(_plain(" ".join(_strings(value)))) if len(token) >= 4 and token not in STOPWORDS}


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _strings(child)]
    return []


def canonical_offer_url(value: str) -> str:
    parts = urlsplit(value.strip())
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_PARAMETERS
    ]
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"), urlencode(query), ""))


def offer_identity(offer: dict[str, Any]) -> str:
    source_url = str(offer.get("source_url", "")).strip()
    if source_url:
        return canonical_offer_url(source_url)
    return "|".join(
        _plain(str(offer.get(field, "")).strip())
        for field in ("employer", "title", "location_label", "contract_type")
    )


def collect_validated_knowledge_tokens(knowledge_root: Path) -> set[str]:
    values: list[str] = []
    for path in sorted(knowledge_root.rglob("*.json")):
        document = load_json(path)
        if isinstance(document, dict):
            for envelope in document.get("fields", {}).values():
                if isinstance(envelope, dict) and "value" in envelope:
                    values.extend(_strings(envelope["value"]))
            values.extend(_strings(document.get("skills", [])))
    return _tokens(values)


def _criterion(career_project: dict[str, Any], identifier: str) -> Any:
    for criterion in career_project.get("criteria", []):
        if criterion.get("id") == identifier:
            return criterion.get("value")
    return None


def _contract(value: str) -> str:
    normalized = _plain(value).replace("-", " ").strip()
    aliases = {
        "contrat a duree indeterminee": "cdi",
        "cdi": "cdi",
        "interim": "interim",
        "mission interim": "interim",
        "travail temporaire": "interim",
        "freelance": "freelance",
        "independant": "freelance",
        "temps partiel": "temps partiel",
    }
    return aliases.get(normalized, normalized)


def _iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None


def _annual_compensation(value: Any, period: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    multipliers = {"hour": 35 * 52, "month": 12, "year": 1}
    multiplier = multipliers.get(str(period).casefold())
    return float(value) * multiplier if multiplier is not None else None


def _offer_text(offer: dict[str, Any]) -> str:
    selected = {
        key: offer.get(key)
        for key in (
            "title",
            "summary",
            "industry_sector_ids",
            "sector_labels",
            "functional_domains",
            "required_skills",
            "preferred_skills",
            "conditions",
        )
    }
    return " ".join(_strings(selected))


def score_offer(
    offer: dict[str, Any],
    career_project: dict[str, Any],
    policy: dict[str, Any],
    knowledge_tokens: set[str],
    today: date | None = None,
) -> dict[str, Any]:
    today = today or datetime.now(UTC).date()
    weights = policy["weights"]
    score = 0.0
    reasons: list[str] = []
    gaps: list[str] = []
    unknowns: list[str] = []
    failures: list[str] = []
    text = _plain(_offer_text(offer))

    contract = _contract(str(offer.get("contract_type", "")))
    preferred_contracts = {_contract(value) for value in policy["contracts"]["preferred"]}
    acceptable_contracts = {_contract(value) for value in policy["contracts"]["acceptable"]}
    excluded_contracts = {_contract(value) for value in policy["contracts"]["excluded"]}
    if not contract:
        unknowns.append("type de contrat non précisé")
    elif contract in excluded_contracts:
        failures.append(f"contrat exclu : {offer.get('contract_type')}")
    elif contract in preferred_contracts:
        score += float(weights["contract"])
        reasons.append("CDI, contrat prioritaire")
    elif contract in acceptable_contracts:
        score += float(weights["contract"]) * 0.4
        reasons.append("mission d’intérim envisageable")
    else:
        failures.append(f"contrat hors politique de recherche : {offer.get('contract_type')}")

    conditions = offer.get("conditions", {}) if isinstance(offer.get("conditions"), dict) else {}
    if offer.get("full_time") is False or conditions.get("full_time") is False:
        failures.append("offre à temps partiel")
    elif offer.get("full_time") is None:
        unknowns.append("temps plein à confirmer")

    targets = career_project.get("target_preferences", {})
    sectors = targets.get("industry_sectors", {})
    priority_sectors = [_plain(value) for value in sectors.get("priority", [])]
    acceptable_sectors = [_plain(value) for value in sectors.get("acceptable", [])]
    excluded_sectors = [_plain(value) for value in sectors.get("excluded", [])]
    matched_excluded_sector = next((value for value in excluded_sectors if value and value in text), None)
    matched_priority_sector = next((value for value in priority_sectors if value and value in text), None)
    matched_acceptable_sector = next((value for value in acceptable_sectors if value and value in text), None)
    if matched_excluded_sector:
        failures.append(f"secteur exclu : {matched_excluded_sector}")
    elif matched_priority_sector:
        emphasis = policy.get("sector_emphasis", {})
        emphasized_labels = {_plain(value) for value in emphasis.get("labels", [])}
        sector_multiplier = float(emphasis.get("multiplier", 1.0)) if matched_priority_sector in emphasized_labels else 1.0
        score += float(weights["sector"]) * sector_multiplier
        label = "secteur très recherché" if sector_multiplier > 1 else "secteur prioritaire"
        reasons.append(f"{label} : {matched_priority_sector}")
    elif matched_acceptable_sector:
        score += float(weights["sector"]) * 0.55
        reasons.append(f"secteur acceptable : {matched_acceptable_sector}")
    else:
        unknowns.append("adéquation sectorielle à confirmer")

    domains = targets.get("functional_domains", {})
    priority_domains = [_plain(value) for value in domains.get("priority", [])]
    acceptable_domains = [_plain(value) for value in domains.get("acceptable", [])]
    matched_priority_domain = next((value for value in priority_domains if value and value in text), None)
    matched_acceptable_domain = next((value for value in acceptable_domains if value and value in text), None)
    if matched_priority_domain:
        score += float(weights["functional_domain"])
        reasons.append(f"activité prioritaire : {matched_priority_domain}")
    elif matched_acceptable_domain:
        score += float(weights["functional_domain"]) * 0.6
        reasons.append(f"activité cohérente : {matched_acceptable_domain}")
    else:
        gaps.append("domaine fonctionnel peu explicite")

    offer_tokens = _tokens(
        {
            "title": offer.get("title"),
            "summary": offer.get("summary"),
            "required_skills": offer.get("required_skills", []),
            "preferred_skills": offer.get("preferred_skills", []),
        }
    )
    overlap = sorted(offer_tokens & knowledge_tokens)
    if overlap:
        ratio = min(1.0, len(overlap) / max(5, min(20, len(offer_tokens))))
        score += float(weights["knowledge_overlap"]) * ratio
        reasons.append("expérience transférable : " + ", ".join(overlap[:5]))
    else:
        gaps.append("aucun recouvrement littéral démontré avec la base validée")

    published_at = _iso_date(offer.get("published_at"))
    if published_at is None:
        unknowns.append("date de publication inconnue")
    else:
        age_days = max(0, (today - published_at).days)
        freshness_days = int(policy["freshness_days"])
        if age_days <= 7:
            score += float(weights["freshness"])
            reasons.append("offre publiée depuis moins de 8 jours")
        elif age_days <= freshness_days:
            score += float(weights["freshness"]) * 0.6
            reasons.append(f"offre publiée il y a {age_days} jours")
        else:
            gaps.append(f"offre ancienne : {age_days} jours")

    boundaries = _criterion(career_project, "criterion-activity-boundaries") or {}
    for excluded in boundaries.get("excluded", []):
        if _plain(str(excluded)) in text:
            failures.append(f"activité exclue : {excluded}")
    if "equipe" in text or "collabor" in text:
        score += float(weights["constraints"])
        reasons.append("dimension collective explicite")
    else:
        unknowns.append("travail en équipe à confirmer")

    arrangement = _criterion(career_project, "criterion-work-arrangement") or {}
    for field, label in (("sunday_work", "travail le dimanche"), ("evening_work", "travail en soirée")):
        if arrangement.get(field) is False and conditions.get(field) is True:
            failures.append(label)
    compensation = offer.get("compensation", {}) if isinstance(offer.get("compensation"), dict) else {}
    expected_compensation = _criterion(career_project, "criterion-compensation") or {}
    offered_maximum = _annual_compensation(compensation.get("maximum"), compensation.get("period"))
    minimum_expected = expected_compensation.get("fixed_minimum_gross")
    if isinstance(offered_maximum, (int, float)) and isinstance(minimum_expected, (int, float)) and offered_maximum < minimum_expected:
        failures.append("rémunération maximale sous le minimum validé")
    elif not compensation or offered_maximum is None:
        unknowns.append("rémunération non précisée")

    return {
        "eligible": not failures,
        "score": round(max(0.0, score), 1),
        "reasons": reasons,
        "gaps": gaps,
        "unknowns": unknowns,
        "hard_constraint_failures": failures,
        "knowledge_keyword_matches": overlap,
    }


def rank_offers(
    offers: list[dict[str, Any]],
    career_project: dict[str, Any],
    policy: dict[str, Any],
    knowledge_tokens: set[str],
    limit: int | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    deduplicated: dict[str, dict[str, Any]] = {}
    for offer in offers:
        identity = offer_identity(offer)
        current = deduplicated.get(identity)
        if current is None or len(_strings(offer)) > len(_strings(current)):
            deduplicated[identity] = offer

    scored: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for offer in deduplicated.values():
        assessment = score_offer(offer, career_project, policy, knowledge_tokens, today)
        record = {**offer, "assessment": assessment}
        (scored if assessment["eligible"] else excluded).append(record)
    scored.sort(key=lambda item: (-item["assessment"]["score"], offer_identity(item), str(item.get("id", ""))))

    result_limit = limit or int(policy["result_limit"])
    employer_limit = int(policy["diversity"]["max_per_employer"])
    source_limit = int(policy["diversity"]["max_per_source"])
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    employers: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    for item in scored:
        employer = _plain(str(item.get("employer", "unknown")))
        source = _plain(str(item.get("source_site", urlsplit(str(item.get("source_url", ""))).netloc or "unknown")))
        if employers[employer] >= employer_limit or sources[source] >= source_limit:
            deferred.append(item)
            continue
        selected.append(item)
        employers[employer] += 1
        sources[source] += 1
        if len(selected) == result_limit:
            break
    if len(selected) < result_limit:
        selected_ids = {offer_identity(item) for item in selected}
        for item in deferred:
            if offer_identity(item) not in selected_ids:
                selected.append(item)
                selected_ids.add(offer_identity(item))
            if len(selected) == result_limit:
                break

    ranked = []
    for index, item in enumerate(selected, start=1):
        ranked.append(
            {
                "rank": index,
                "id": item.get("id"),
                "title": item.get("title"),
                "employer": item.get("employer"),
                "source_url": item.get("source_url"),
                "source_site": item.get("source_site"),
                "published_at": item.get("published_at"),
                "contract_type": item.get("contract_type"),
                "full_time": item.get("full_time"),
                "location_label": item.get("location_label"),
                "sector_labels": item.get("sector_labels", []),
                "industry_sector_ids": item.get("industry_sector_ids", []),
                "compensation": item.get("compensation"),
                "conditions": item.get("conditions", {}),
                "summary": item.get("summary"),
                "assessment": item["assessment"],
            }
        )
    warnings = []
    if len(offers) < int(policy["candidate_pool_minimum"]):
        warnings.append(f"pool incomplet : {len(offers)} offres collectées, {policy['candidate_pool_minimum']} attendues")
    if len(ranked) < result_limit:
        warnings.append(f"seulement {len(ranked)} offres éligibles pour une cible de {result_limit}")
    return {
        "policy_id": policy["id"],
        "candidate_count": len(offers),
        "unique_count": len(deduplicated),
        "eligible_count": len(scored),
        "excluded_count": len(excluded),
        "warnings": warnings,
        "offers": ranked,
        "excluded": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "employer": item.get("employer"),
                "failures": item["assessment"]["hard_constraint_failures"],
            }
            for item in excluded
        ],
    }


def load_offer_files(path: Path) -> list[dict[str, Any]]:
    paths = [path] if path.is_file() else sorted(path.rglob("*.json"))
    return [document for file_path in paths for document in [load_json(file_path)] if isinstance(document, dict)]
