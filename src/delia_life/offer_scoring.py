from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
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

RECOMMENDATION_BAND_ORDER = {
    "priority": 0,
    "possible": 1,
    "informational": 2,
    "excluded": 3,
}


def plain(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in strings(child)]
    return []


def tokens(value: Any) -> set[str]:
    return {
        token
        for token in TOKEN_PATTERN.findall(plain(" ".join(strings(value))))
        if len(token) >= 4 and token not in STOPWORDS
    }


def _criterion(career_project: dict[str, Any], identifier: str) -> Any:
    for criterion in career_project.get("criteria", []):
        if criterion.get("id") == identifier:
            return criterion.get("value")
    return None


def _contract(value: str) -> str:
    normalized = plain(value).replace("-", " ").strip()
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
    return " ".join(strings(selected))


def _functional_offer_text(offer: dict[str, Any]) -> str:
    selected = {
        key: offer.get(key)
        for key in (
            "title",
            "summary",
            "functional_domains",
            "required_skills",
            "preferred_skills",
            "conditions",
        )
    }
    return " ".join(strings(selected))


def _domain_matchers(domains: list[Any], query_families: dict[str, Any]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    matchers: list[tuple[str, tuple[str, ...]]] = []
    for value in domains:
        label = str(value)
        identifier = re.sub(r"[^a-z0-9]+", "-", plain(label)).strip("-")
        aliases = [label, *strings(query_families.get(identifier, []))]
        normalized = tuple(dict.fromkeys(plain(alias) for alias in aliases if alias.strip()))
        matchers.append((plain(label), normalized))
    return tuple(matchers)


@dataclass(frozen=True)
class ScoringContext:
    today: date
    weights: dict[str, Any]
    preferred_contracts: frozenset[str]
    acceptable_contracts: frozenset[str]
    excluded_contracts: frozenset[str]
    priority_sectors: tuple[str, ...]
    acceptable_sectors: tuple[str, ...]
    excluded_sectors: tuple[str, ...]
    emphasized_sectors: frozenset[str]
    sector_multiplier: float
    priority_domains: tuple[tuple[str, tuple[str, ...]], ...]
    acceptable_domains: tuple[tuple[str, tuple[str, ...]], ...]
    knowledge_tokens: frozenset[str]
    freshness_days: int
    activity_exclusions: tuple[tuple[str, str], ...]
    work_arrangement: dict[str, Any]
    expected_compensation: dict[str, Any]
    priority_minimum_score: float
    possible_minimum_score: float


@dataclass
class ScoreState:
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    knowledge_keyword_matches: list[str] = field(default_factory=list)
    prerequisite_alerts: list[dict[str, Any]] = field(default_factory=list)
    application_barriers: list[str] = field(default_factory=list)
    recommendation_band: str = "possible"
    recommendation_reasons: list[str] = field(default_factory=list)
    forced_to_end: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "eligible": not self.failures,
            "score": round(min(100.0, max(0.0, self.score)), 1),
            "reasons": self.reasons,
            "gaps": self.gaps,
            "unknowns": self.unknowns,
            "hard_constraint_failures": self.failures,
            "knowledge_keyword_matches": self.knowledge_keyword_matches,
            "prerequisite_alerts": self.prerequisite_alerts,
            "application_barriers": self.application_barriers,
            "recommendation_band": self.recommendation_band,
            "recommendation_reasons": self.recommendation_reasons,
            "forced_to_end": self.forced_to_end,
        }


def _build_scoring_context(
    career_project: dict[str, Any],
    policy: dict[str, Any],
    knowledge_tokens: set[str],
    today: date | None,
) -> ScoringContext:
    targets = career_project.get("target_preferences", {})
    sectors = targets.get("industry_sectors", {})
    domains = targets.get("functional_domains", {})
    query_families = policy.get("functional_query_families", {})
    emphasis = policy.get("sector_emphasis", {})
    boundaries = _criterion(career_project, "criterion-activity-boundaries") or {}
    activity_exclusions = tuple((plain(str(value)), str(value)) for value in boundaries.get("excluded", []))
    recommendation_policy = policy.get("recommendation_bands", {})
    priority_minimum_score = float(recommendation_policy.get("priority_minimum_score", 75))
    possible_minimum_score = float(recommendation_policy.get("possible_minimum_score", 50))
    if possible_minimum_score > priority_minimum_score:
        raise ValueError("possible recommendation score cannot exceed priority recommendation score")
    return ScoringContext(
        today=today or datetime.now(UTC).date(),
        weights=policy["weights"],
        preferred_contracts=frozenset(_contract(value) for value in policy["contracts"]["preferred"]),
        acceptable_contracts=frozenset(_contract(value) for value in policy["contracts"]["acceptable"]),
        excluded_contracts=frozenset(_contract(value) for value in policy["contracts"]["excluded"]),
        priority_sectors=tuple(plain(value) for value in sectors.get("priority", [])),
        acceptable_sectors=tuple(plain(value) for value in sectors.get("acceptable", [])),
        excluded_sectors=tuple(plain(value) for value in sectors.get("excluded", [])),
        emphasized_sectors=frozenset(plain(value) for value in emphasis.get("labels", [])),
        sector_multiplier=float(emphasis.get("multiplier", 1.0)),
        priority_domains=_domain_matchers(domains.get("priority", []), query_families),
        acceptable_domains=_domain_matchers(domains.get("acceptable", []), query_families),
        knowledge_tokens=frozenset(knowledge_tokens),
        freshness_days=int(policy["freshness_days"]),
        activity_exclusions=activity_exclusions,
        work_arrangement=_criterion(career_project, "criterion-work-arrangement") or {},
        expected_compensation=_criterion(career_project, "criterion-compensation") or {},
        priority_minimum_score=priority_minimum_score,
        possible_minimum_score=possible_minimum_score,
    )


def _apply_contract_rules(offer: dict[str, Any], context: ScoringContext, state: ScoreState) -> None:
    contract = _contract(str(offer.get("contract_type", "")))
    if not contract:
        state.unknowns.append("type de contrat non précisé")
    elif contract in context.excluded_contracts:
        state.failures.append(f"contrat exclu : {offer.get('contract_type')}")
    elif contract in context.preferred_contracts:
        state.score += float(context.weights["contract"])
        state.reasons.append("CDI, contrat prioritaire")
    elif contract in context.acceptable_contracts:
        state.score += float(context.weights["contract"]) * 0.4
        state.reasons.append("mission d’intérim envisageable")
    else:
        state.failures.append(f"contrat hors politique de recherche : {offer.get('contract_type')}")


def _apply_work_time_rules(offer: dict[str, Any], conditions: dict[str, Any], state: ScoreState) -> None:
    if offer.get("full_time") is False or conditions.get("full_time") is False:
        state.failures.append("offre à temps partiel")
    elif offer.get("full_time") is None:
        state.unknowns.append("temps plein à confirmer")


def _apply_sector_rules(text: str, context: ScoringContext, state: ScoreState) -> None:
    matched_excluded = next((value for value in context.excluded_sectors if value and value in text), None)
    matched_priority = next((value for value in context.priority_sectors if value and value in text), None)
    matched_acceptable = next((value for value in context.acceptable_sectors if value and value in text), None)
    if matched_excluded:
        state.failures.append(f"secteur exclu : {matched_excluded}")
    elif matched_priority:
        multiplier = context.sector_multiplier if matched_priority in context.emphasized_sectors else 1.0
        state.score += float(context.weights["sector"]) * multiplier
        label = "secteur très recherché" if multiplier > 1 else "secteur prioritaire"
        state.reasons.append(f"{label} : {matched_priority}")
    elif matched_acceptable:
        state.score += float(context.weights["sector"]) * 0.55
        state.reasons.append(f"secteur acceptable : {matched_acceptable}")
    else:
        state.unknowns.append("adéquation sectorielle à confirmer")


def _apply_functional_domain_rules(text: str, context: ScoringContext, state: ScoreState) -> None:
    matched_priority = next(
        (label for label, aliases in context.priority_domains if any(alias in text for alias in aliases)),
        None,
    )
    matched_acceptable = next(
        (label for label, aliases in context.acceptable_domains if any(alias in text for alias in aliases)),
        None,
    )
    if matched_priority:
        state.score += float(context.weights["functional_domain"])
        state.reasons.append(f"activité prioritaire : {matched_priority}")
    elif matched_acceptable:
        state.score += float(context.weights["functional_domain"]) * 0.6
        state.reasons.append(f"activité cohérente : {matched_acceptable}")
    else:
        state.gaps.append("domaine fonctionnel peu explicite")


def _apply_knowledge_overlap(offer: dict[str, Any], context: ScoringContext, state: ScoreState) -> None:
    offer_tokens = tokens(
        {
            "title": offer.get("title"),
            "summary": offer.get("summary"),
            "required_skills": offer.get("required_skills", []),
            "preferred_skills": offer.get("preferred_skills", []),
        }
    )
    overlap = sorted(offer_tokens & context.knowledge_tokens)
    state.knowledge_keyword_matches = overlap
    if overlap:
        ratio = min(1.0, len(overlap) / max(5, min(20, len(offer_tokens))))
        state.score += float(context.weights["knowledge_overlap"]) * ratio
        state.reasons.append("expérience transférable : " + ", ".join(overlap[:5]))
    else:
        state.gaps.append("aucun recouvrement littéral démontré avec la base validée")


def _apply_freshness_rules(offer: dict[str, Any], context: ScoringContext, state: ScoreState) -> None:
    published_at = _iso_date(offer.get("published_at"))
    if published_at is None:
        state.unknowns.append("date de publication inconnue")
        return
    age_days = max(0, (context.today - published_at).days)
    if age_days <= 7:
        state.score += float(context.weights["freshness"])
        state.reasons.append("offre publiée depuis moins de 8 jours")
    elif age_days <= context.freshness_days:
        state.score += float(context.weights["freshness"]) * 0.6
        state.reasons.append(f"offre publiée il y a {age_days} jours")
    else:
        state.gaps.append(f"offre ancienne : {age_days} jours")


def _apply_activity_rules(text: str, context: ScoringContext, state: ScoreState) -> None:
    for normalized, original in context.activity_exclusions:
        if normalized in text:
            state.failures.append(f"activité exclue : {original}")
    if "equipe" in text or "collabor" in text:
        state.score += float(context.weights["constraints"])
        state.reasons.append("dimension collective explicite")
    else:
        state.unknowns.append("travail en équipe à confirmer")


def _apply_arrangement_and_compensation_rules(
    offer: dict[str, Any],
    conditions: dict[str, Any],
    context: ScoringContext,
    state: ScoreState,
) -> None:
    for field_name, label in (("sunday_work", "travail le dimanche"), ("evening_work", "travail en soirée")):
        if context.work_arrangement.get(field_name) is False and conditions.get(field_name) is True:
            state.failures.append(label)
    compensation = offer.get("compensation", {}) if isinstance(offer.get("compensation"), dict) else {}
    offered_maximum = _annual_compensation(compensation.get("maximum"), compensation.get("period"))
    minimum_expected = context.expected_compensation.get("fixed_minimum_gross")
    if (
        isinstance(offered_maximum, (int, float))
        and isinstance(minimum_expected, (int, float))
        and offered_maximum < minimum_expected
    ):
        state.failures.append("rémunération maximale sous le minimum validé")
    elif not compensation or offered_maximum is None:
        state.unknowns.append("rémunération non précisée")


def _apply_prerequisite_rules(offer: dict[str, Any], context: ScoringContext, state: ScoreState) -> None:
    prerequisites = offer.get("prerequisites")
    if not isinstance(prerequisites, list):
        conditions = offer.get("conditions")
        if isinstance(conditions, dict) and conditions.get("insurance_experience_required") is True:
            prerequisites = [
                {
                    "id": "legacy-experience-assurantielle",
                    "kind": "sector_experience",
                    "description": "Expérience préalable dans le domaine assurantiel",
                    "mandatory": True,
                    "profile_status": "not_demonstrated",
                }
            ]
        else:
            return
    status_messages = {
        "not_demonstrated": "non démontré dans les connaissances validées",
        "unmet": "non satisfait d’après les connaissances validées",
        "unknown": "correspondance avec le profil à vérifier",
    }
    for prerequisite in prerequisites:
        if not isinstance(prerequisite, dict):
            continue
        status = str(prerequisite.get("profile_status", "unknown"))
        if status == "met":
            continue
        if status not in status_messages:
            status = "unknown"
        description = str(prerequisite.get("description") or "prérequis non décrit").strip()
        mandatory = prerequisite.get("mandatory") is True
        state.prerequisite_alerts.append(
            {
                "id": prerequisite.get("id"),
                "kind": prerequisite.get("kind", "other"),
                "description": description,
                "mandatory": mandatory,
                "status": status,
                "message": status_messages[status],
            }
        )
        if status == "unmet" and mandatory:
            state.application_barriers.append(f"prérequis obligatoire non satisfait : {description}")


def _finalize_recommendation(context: ScoringContext, state: ScoreState) -> None:
    bounded_score = min(100.0, max(0.0, state.score))
    mandatory_uncertainties = [
        item
        for item in state.prerequisite_alerts
        if item["mandatory"] and item["status"] in {"not_demonstrated", "unknown"}
    ]
    if state.failures:
        state.recommendation_band = "excluded"
        state.recommendation_reasons = ["incompatibilité certaine avec la politique de recherche"]
    elif state.application_barriers:
        state.recommendation_band = "informational"
        state.recommendation_reasons = list(state.application_barriers)
        state.forced_to_end = True
    elif bounded_score < context.possible_minimum_score:
        state.recommendation_band = "informational"
        state.recommendation_reasons = [
            f"score inférieur au seuil de candidature possible ({context.possible_minimum_score:g})"
        ]
    elif mandatory_uncertainties:
        state.recommendation_band = "possible"
        state.recommendation_reasons = ["prérequis obligatoire non démontré ou à vérifier"]
    elif bounded_score >= context.priority_minimum_score:
        state.recommendation_band = "priority"
        state.recommendation_reasons = ["forte correspondance sans prérequis obligatoire incertain"]
    else:
        state.recommendation_band = "possible"
        state.recommendation_reasons = [
            f"score compris entre {context.possible_minimum_score:g} et {context.priority_minimum_score:g}"
        ]


def _score_offer_with_context(offer: dict[str, Any], context: ScoringContext) -> dict[str, Any]:
    state = ScoreState()
    text = plain(_offer_text(offer))
    functional_text = plain(_functional_offer_text(offer))
    conditions = offer.get("conditions", {}) if isinstance(offer.get("conditions"), dict) else {}
    _apply_contract_rules(offer, context, state)
    _apply_work_time_rules(offer, conditions, state)
    _apply_sector_rules(text, context, state)
    _apply_functional_domain_rules(functional_text, context, state)
    _apply_knowledge_overlap(offer, context, state)
    _apply_freshness_rules(offer, context, state)
    _apply_activity_rules(text, context, state)
    _apply_arrangement_and_compensation_rules(offer, conditions, context, state)
    _apply_prerequisite_rules(offer, context, state)
    _finalize_recommendation(context, state)
    return state.as_dict()


def score_offer(
    offer: dict[str, Any],
    career_project: dict[str, Any],
    policy: dict[str, Any],
    knowledge_tokens: set[str],
    today: date | None = None,
) -> dict[str, Any]:
    return _score_offer_with_context(offer, _build_scoring_context(career_project, policy, knowledge_tokens, today))
