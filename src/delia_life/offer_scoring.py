from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from math import ceil
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
    location_markers: tuple[str, ...]
    priority_sectors: tuple[str, ...]
    acceptable_sectors: tuple[str, ...]
    excluded_sectors: tuple[str, ...]
    priority_domains: tuple[tuple[str, tuple[str, ...]], ...]
    acceptable_domains: tuple[tuple[str, tuple[str, ...]], ...]
    profile_family_filters: tuple[dict[str, Any], ...]
    complete_profile_dimensions: frozenset[str]
    sector_experience_months: dict[str, int]
    absent_sector_experience_ids: frozenset[str]
    absent_certifications: dict[str, frozenset[str]]
    knowledge_tokens: frozenset[str]
    knowledge_evidence_catalog: dict[str, frozenset[str]]
    semantic_importance_weights: dict[str, float]
    semantic_match_factors: dict[str, float]
    freshness_days: int
    activity_exclusions: tuple[tuple[str, str], ...]
    work_arrangement: dict[str, Any]
    initial_search_schedule_preference: dict[str, Any]
    target_job_roles: dict[str, Any]
    expected_compensation: dict[str, Any]
    priority_minimum_score: float
    possible_minimum_score: float
    warn_on_missing_employer_page: bool


@dataclass
class ScoreState:
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    knowledge_keyword_matches: list[str] = field(default_factory=list)
    semantic_matches: list[dict[str, Any]] = field(default_factory=list)
    semantic_required_uncertainties: list[str] = field(default_factory=list)
    matching_method: str = "lexical_fallback"
    prerequisite_alerts: list[dict[str, Any]] = field(default_factory=list)
    application_barriers: list[str] = field(default_factory=list)
    profile_family_matches: list[dict[str, Any]] = field(default_factory=list)
    recommendation_band: str = "possible"
    recommendation_reasons: list[str] = field(default_factory=list)
    preference_alerts: list[str] = field(default_factory=list)
    maximum_recommendation_band: str | None = None
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
            "semantic_matches": self.semantic_matches,
            "semantic_required_uncertainties": self.semantic_required_uncertainties,
            "matching_method": self.matching_method,
            "prerequisite_alerts": self.prerequisite_alerts,
            "application_barriers": self.application_barriers,
            "profile_family_matches": self.profile_family_matches,
            "recommendation_band": self.recommendation_band,
            "recommendation_reasons": self.recommendation_reasons,
            "preference_alerts": self.preference_alerts,
            "maximum_recommendation_band": self.maximum_recommendation_band,
            "forced_to_end": self.forced_to_end,
        }


def _build_scoring_context(
    career_project: dict[str, Any],
    policy: dict[str, Any],
    knowledge_tokens: set[str],
    today: date | None,
    complete_profile_dimensions: set[str] | None = None,
    sector_experience_months: dict[str, int] | None = None,
    absent_sector_experience_ids: set[str] | None = None,
    absent_certifications: dict[str, set[str]] | None = None,
    knowledge_evidence_catalog: dict[str, frozenset[str]] | None = None,
) -> ScoringContext:
    targets = career_project.get("target_preferences", {})
    sectors = targets.get("industry_sectors", {})
    domains = targets.get("functional_domains", {})
    query_families = policy.get("functional_query_families", {})
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
        location_markers=tuple(
            plain(str(value)) for value in policy.get("collector", {}).get("location_markers", [])
        ),
        priority_sectors=tuple(plain(value) for value in sectors.get("priority", [])),
        acceptable_sectors=tuple(plain(value) for value in sectors.get("acceptable", [])),
        excluded_sectors=tuple(plain(value) for value in sectors.get("excluded", [])),
        priority_domains=_domain_matchers(domains.get("priority", []), query_families),
        acceptable_domains=_domain_matchers(domains.get("acceptable", []), query_families),
        profile_family_filters=tuple(
            rule for rule in policy.get("profile_family_filters", []) if isinstance(rule, dict)
        ),
        complete_profile_dimensions=frozenset(complete_profile_dimensions or set()),
        sector_experience_months=dict(sector_experience_months or {}),
        absent_sector_experience_ids=frozenset(absent_sector_experience_ids or set()),
        absent_certifications={
            identifier: frozenset(evidence_ids)
            for identifier, evidence_ids in (absent_certifications or {}).items()
        },
        knowledge_tokens=frozenset(knowledge_tokens),
        knowledge_evidence_catalog=dict(knowledge_evidence_catalog or {}),
        semantic_importance_weights={
            key: float(value)
            for key, value in policy["semantic_matching"]["importance_weights"].items()
        },
        semantic_match_factors={
            key: float(value)
            for key, value in policy["semantic_matching"]["match_factors"].items()
        },
        freshness_days=int(policy["freshness_days"]),
        activity_exclusions=activity_exclusions,
        work_arrangement=_criterion(career_project, "criterion-work-arrangement") or {},
        initial_search_schedule_preference=(
            _criterion(career_project, "criterion-initial-search-schedule-preference") or {}
        ),
        target_job_roles=_criterion(career_project, "criterion-target-job-roles") or {},
        expected_compensation=_criterion(career_project, "criterion-compensation") or {},
        priority_minimum_score=priority_minimum_score,
        possible_minimum_score=possible_minimum_score,
        warn_on_missing_employer_page=bool(
            policy.get("source_strategy", {}).get("warn_on_missing_employer_page", True)
        ),
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


def _apply_location_rules(offer: dict[str, Any], context: ScoringContext, state: ScoreState) -> None:
    location = plain(str(offer.get("location_label") or ""))
    if not location or location in {"lieu non communique", "non communique"}:
        return
    if context.location_markers and not any(marker in location for marker in context.location_markers):
        state.failures.append(f"localisation hors zone de recherche : {offer.get('location_label')}")


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
        state.score += float(context.weights["sector"])
        state.reasons.append(f"secteur prioritaire : {matched_priority}")
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


def _apply_lexical_fallback(offer: dict[str, Any], context: ScoringContext, state: ScoreState) -> None:
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
        state.score += float(context.weights["semantic_match"]) * ratio
        state.reasons.append("expérience transférable : " + ", ".join(overlap[:5]))
    else:
        state.gaps.append("aucun recouvrement littéral démontré avec la base validée")


def _apply_semantic_matches(offer: dict[str, Any], context: ScoringContext, state: ScoreState) -> None:
    requirements = offer.get("semantic_requirements")
    matches = offer.get("semantic_matches")
    if not isinstance(requirements, list) or not requirements or not isinstance(matches, list) or not matches:
        _apply_lexical_fallback(offer, context, state)
        return

    state.matching_method = "llm_semantic_evidence"
    requirement_by_id = {
        str(requirement.get("id") or ""): requirement
        for requirement in requirements
        if isinstance(requirement, dict) and str(requirement.get("id") or "")
    }
    match_by_requirement = {
        str(match.get("requirement_id") or ""): match
        for match in matches
        if isinstance(match, dict) and str(match.get("requirement_id") or "")
    }
    earned = 0.0
    possible = 0.0
    supported_count = 0
    for requirement_id, requirement in requirement_by_id.items():
        match = match_by_requirement.get(requirement_id, {})
        importance = str(requirement.get("importance") or "required")
        weight = context.semantic_importance_weights.get(importance, 0.0)
        if weight == 0:
            continue
        possible += weight
        match_type = str(match.get("match_type") or "unknown")
        refs = match.get("profile_evidence_refs", [])
        valid_refs: list[dict[str, str]] = []
        invalid_evidence: list[str] = []
        if isinstance(refs, list):
            for ref in refs:
                if not isinstance(ref, dict):
                    invalid_evidence.append("<référence invalide>")
                    continue
                evidence_id = str(ref.get("id") or "").strip()
                field = str(ref.get("field") or "").strip()
                if field not in context.knowledge_evidence_catalog.get(evidence_id, frozenset()):
                    invalid_evidence.append(f"{evidence_id}#{field}")
                else:
                    valid_refs.append({"id": evidence_id, "field": field})
        supported = match_type in {"exact", "transferable"} and bool(valid_refs) and not invalid_evidence
        effective_type = match_type if supported or match_type in {"gap", "unknown"} else "unknown"
        scoring_confidence = {
            "exact": "high",
            "transferable": "medium",
            "gap": "high",
            "unknown": "low",
        }[effective_type]
        if supported:
            earned += weight * context.semantic_match_factors[effective_type]
            supported_count += 1
        elif invalid_evidence:
            state.unknowns.append(
                "preuve de rapprochement sémantique inconnue : " + ", ".join(invalid_evidence)
            )
        elif effective_type == "gap":
            description = str(requirement.get("description") or "exigence non couverte")
            state.gaps.append("écart sémantique : " + description)
            if importance == "required":
                state.application_barriers.append(f"exigence obligatoire non couverte : {description}")
        elif effective_type == "unknown":
            description = str(requirement.get("description") or "exigence ambiguë")
            state.unknowns.append(
                "rapprochement sémantique à confirmer : " + description
            )
            if importance == "required":
                state.semantic_required_uncertainties.append(description)
        state.semantic_matches.append(
            {
                **match,
                "requirement": requirement,
                "effective_match_type": effective_type,
                "scoring_confidence": scoring_confidence,
                "validated_profile_evidence_refs": valid_refs,
            }
        )

    if possible:
        state.score += float(context.weights["semantic_match"]) * min(1.0, earned / possible)
    if supported_count:
        state.reasons.append(f"rapprochement sémantique sourcé : {supported_count} exigence(s) couverte(s)")
    elif possible:
        state.gaps.append("aucun rapprochement sémantique sourcé avec le profil validé")


def _normalized_markers(rule: dict[str, Any], field_name: str) -> tuple[str, ...]:
    return tuple(plain(value) for value in strings(rule.get(field_name, [])) if value.strip())


def _contains_marker(text: str, marker: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", text) is not None


def _apply_profile_family_rules(offer: dict[str, Any], context: ScoringContext, state: ScoreState) -> None:
    title = plain(str(offer.get("title") or ""))
    profile_text = plain(
        " ".join(
            strings(
                {
                    "title": offer.get("title"),
                    "summary": offer.get("summary"),
                    "functional_domains": offer.get("functional_domains", []),
                    "required_skills": offer.get("required_skills", []),
                    "preferred_skills": offer.get("preferred_skills", []),
                    "prerequisites": offer.get("prerequisites", []),
                }
            )
        )
    )
    for rule in context.profile_family_filters:
        title_matches = [
            marker for marker in _normalized_markers(rule, "strong_title_markers") if _contains_marker(title, marker)
        ]
        family_matches = [
            marker
            for marker in _normalized_markers(rule, "family_markers")
            if _contains_marker(profile_text, marker)
        ]
        technical_matches = [
            marker
            for marker in _normalized_markers(rule, "technical_markers")
            if _contains_marker(profile_text, marker)
        ]
        minimum_technical = int(rule.get("minimum_technical_markers", 1))
        strong_title = bool(title_matches)
        technical_signature = bool(family_matches) and len(technical_matches) >= minimum_technical
        if not strong_title and not technical_signature:
            continue
        label = str(rule.get("label") or rule.get("id") or "famille de profil exclue")
        state.profile_family_matches.append(
            {
                "id": rule.get("id"),
                "label": label,
                "confidence": "high" if strong_title else "medium",
                "title_markers": title_matches,
                "family_markers": family_matches,
                "technical_markers": technical_matches,
            }
        )
        if rule.get("decision") == "exclude":
            state.failures.append(f"famille de profil exclue : {label}")


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


def _apply_source_quality_rules(offer: dict[str, Any], context: ScoringContext, state: ScoreState) -> None:
    warnings: list[str] = []
    custom_warning = str(offer.get("source_warning") or "").strip()
    if custom_warning:
        warnings.append(custom_warning)
    if (
        context.warn_on_missing_employer_page
        and str(offer.get("source_kind") or "").strip() == "aggregator"
        and not str(offer.get("employer_source_url") or "").strip()
    ):
        warnings.append(
            "annonce accessible sur un site tiers, mais non retrouvée sur le site de l’employeur ; "
            "vérifier sa disponibilité avant de candidater"
        )
    state.unknowns.extend(warning for warning in warnings if warning not in state.unknowns)


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


def _title_markers(items: Any) -> tuple[str, ...]:
    if not isinstance(items, list):
        return ()
    return tuple(
        plain(str(marker))
        for item in items
        if isinstance(item, dict)
        for marker in item.get("title_markers", [])
        if str(marker).strip()
    )


def _semantic_condition_requires_regular_saturday(offer: dict[str, Any]) -> bool:
    requirements = offer.get("semantic_requirements")
    if not isinstance(requirements, list):
        return False
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        if requirement.get("importance") != "required" or requirement.get("kind") != "condition":
            continue
        evidence = requirement.get("offer_evidence")
        evidence_text = evidence if isinstance(evidence, dict) else {}
        text = plain(
            " ".join(
                (
                    str(requirement.get("description") or ""),
                    str(evidence_text.get("excerpt") or ""),
                )
            )
        )
        if any(
            marker in text
            for marker in (
                "tous les samedis",
                "chaque samedi",
                "du lundi au samedi",
                "samedi obligatoire",
                "samedis obligatoires",
                "every saturday",
            )
        ):
            return True
    return False


def _apply_initial_search_preferences(
    offer: dict[str, Any],
    conditions: dict[str, Any],
    context: ScoringContext,
    state: ScoreState,
) -> None:
    schedule_preference = context.initial_search_schedule_preference
    if (
        schedule_preference.get("phase") == "initial"
        and schedule_preference.get("regular_saturday_work") == "strongly_avoid"
    ):
        raw_schedule = offer.get("schedule")
        schedule = raw_schedule if isinstance(raw_schedule, dict) else {}
        saturday_frequency = plain(
            str(
                conditions.get("saturday_work_frequency")
                or schedule.get("saturday_work_frequency")
                or ""
            )
        )
        saturday_required = (
            saturday_frequency in {"regular", "weekly", "every saturday", "tous les samedis"}
            or _semantic_condition_requires_regular_saturday(offer)
        )
        if saturday_required:
            state.preference_alerts.append(
                "travail régulier le samedi à éviter pendant la première phase de recherche"
            )
            state.application_barriers.append(
                "préférence de première phase non satisfaite : travail régulier le samedi"
            )

    title = plain(str(offer.get("title") or ""))
    deprioritized = _title_markers(context.target_job_roles.get("deprioritized"))
    priority = _title_markers(context.target_job_roles.get("priority"))
    if (
        deprioritized
        and any(_contains_marker(title, marker) for marker in deprioritized)
        and not any(_contains_marker(title, marker) for marker in priority)
    ):
        state.preference_alerts.append(
            "poste de vente sans responsabilité élargie, dépriorisé dans la recherche actuelle"
        )
        state.maximum_recommendation_band = "possible"


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
                    "industry_sector_ids": ["banque-et-assurance"],
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
        if status not in {*status_messages, "met"}:
            status = "unknown"
        description = str(prerequisite.get("description") or "prérequis non décrit").strip()
        mandatory = prerequisite.get("mandatory") is True
        kind = str(prerequisite.get("kind", "other"))
        sector_ids = prerequisite.get("industry_sector_ids")
        normalized_sector_ids = {
            str(value).strip() for value in sector_ids if str(value).strip()
        } if isinstance(sector_ids, list) else set()
        minimum_years = prerequisite.get("minimum_years")
        credential_id = str(prerequisite.get("credential_id") or "").strip()
        profile_evidence_ids = {
            str(value).strip()
            for value in prerequisite.get("profile_evidence_ids", [])
            if str(value).strip()
        }
        automatically_met = False
        validated_sector_absence = bool(
            normalized_sector_ids & context.absent_sector_experience_ids
        )
        documented_months = 0
        required_months = 0
        if normalized_sector_ids and isinstance(minimum_years, (int, float)):
            documented_months = max(
                (context.sector_experience_months.get(sector_id, 0) for sector_id in normalized_sector_ids),
                default=0,
            )
            required_months = ceil(float(minimum_years) * 12)
            if documented_months >= required_months:
                status = "met"
                automatically_met = True
        if not automatically_met and validated_sector_absence:
            status = "unmet"
        validated_certification_absence = bool(
            kind == "certification"
            and credential_id
            and profile_evidence_ids & context.absent_certifications.get(credential_id, frozenset())
        )
        if kind == "certification":
            status = "unmet" if validated_certification_absence else ("met" if status == "met" else "not_demonstrated")
        if status == "met":
            if automatically_met:
                state.reasons.append(
                    f"prérequis sectoriel couvert : {documented_months} mois validés pour {required_months} requis"
                )
            continue
        complete_qualification_inventory = (
            kind == "qualification" and "credentials" in context.complete_profile_dimensions
        )
        if mandatory and complete_qualification_inventory and status in {"not_demonstrated", "unknown"}:
            status = "unmet"
        state.prerequisite_alerts.append(
            {
                "id": prerequisite.get("id"),
                "kind": kind,
                "description": description,
                "mandatory": mandatory,
                "status": status,
                "message": status_messages[status],
            }
        )
        if status == "unmet" and mandatory and complete_qualification_inventory:
            state.failures.append(f"diplôme obligatoire non satisfait : {description}")
        elif status == "unmet" and mandatory and validated_certification_absence:
            state.failures.append(f"certification obligatoire non satisfaite : {description}")
        elif (
            status == "unmet"
            and mandatory
            and validated_sector_absence
            and isinstance(minimum_years, (int, float))
            and minimum_years > 0
        ):
            state.failures.append(f"expérience sectorielle obligatoire non satisfaite : {description}")
        elif status == "unmet" and mandatory:
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
    elif mandatory_uncertainties or state.semantic_required_uncertainties:
        state.recommendation_band = "possible"
        state.recommendation_reasons = ["exigence ou prérequis obligatoire non démontré ou à vérifier"]
    elif bounded_score >= context.priority_minimum_score:
        state.recommendation_band = "priority"
        state.recommendation_reasons = ["forte correspondance sans prérequis obligatoire incertain"]
    else:
        state.recommendation_band = "possible"
        state.recommendation_reasons = [
            f"score compris entre {context.possible_minimum_score:g} et {context.priority_minimum_score:g}"
        ]
    if state.maximum_recommendation_band == "possible" and state.recommendation_band == "priority":
        state.recommendation_band = "possible"
        state.recommendation_reasons = list(state.preference_alerts)


def _score_offer_with_context(offer: dict[str, Any], context: ScoringContext) -> dict[str, Any]:
    state = ScoreState()
    text = plain(_offer_text(offer))
    functional_text = plain(_functional_offer_text(offer))
    conditions = offer.get("conditions", {}) if isinstance(offer.get("conditions"), dict) else {}
    _apply_contract_rules(offer, context, state)
    _apply_location_rules(offer, context, state)
    _apply_work_time_rules(offer, conditions, state)
    _apply_sector_rules(text, context, state)
    _apply_functional_domain_rules(functional_text, context, state)
    _apply_profile_family_rules(offer, context, state)
    _apply_semantic_matches(offer, context, state)
    _apply_freshness_rules(offer, context, state)
    _apply_activity_rules(text, context, state)
    _apply_source_quality_rules(offer, context, state)
    _apply_arrangement_and_compensation_rules(offer, conditions, context, state)
    _apply_initial_search_preferences(offer, conditions, context, state)
    _apply_prerequisite_rules(offer, context, state)
    _finalize_recommendation(context, state)
    return state.as_dict()


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
    knowledge_evidence_catalog: dict[str, frozenset[str]] | None = None,
) -> dict[str, Any]:
    return _score_offer_with_context(
        offer,
        _build_scoring_context(
            career_project,
            policy,
            knowledge_tokens,
            today,
            complete_profile_dimensions,
            sector_experience_months,
            absent_sector_experience_ids,
            absent_certifications,
            knowledge_evidence_catalog,
        ),
    )
