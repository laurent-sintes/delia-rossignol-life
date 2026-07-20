from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .core import load_json
from .cv_model import (
    CVContinuityGroup,
    CVEducation,
    CVExperience,
    CVHighlight,
    CVHighlightCard,
    CVSequenceStep,
    CVViewModel,
    EvidenceRef,
)
from .errors import ValidationError
from .pdf_layout import CVLayoutRules

EntityCache = dict[tuple[str, str], dict[str, Any]]


@dataclass
class CompositionContext:
    root: Path
    rules: dict[str, Any]
    cache: EntityCache = field(default_factory=dict)

    @property
    def maximum_bullets(self) -> int:
        return int(self.rules["experience_bullets_max"])

    @property
    def maximum_words(self) -> int:
        return int(self.rules["bullet_max_words"])

    @property
    def maximum_sequence_steps(self) -> int:
        return int(self.rules.get("experience_sequence_steps_max", 0))


@dataclass(frozen=True)
class ProfileComposition:
    name: str
    email: str
    phone: str
    signature: str
    key_skills: tuple[str, ...]
    tools_line: str
    interests: tuple[Any, ...]
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True)
class ExperienceComposition:
    all_experiences: tuple[CVExperience, ...]
    continuity_groups: tuple[CVContinuityGroup, ...]
    recent: tuple[CVExperience, ...]
    complementary: tuple[CVExperience, ...]


@dataclass(frozen=True)
class EducationComposition:
    items: tuple[CVEducation, ...]
    language_line: str
    language_evidence: tuple[EvidenceRef, ...]


def _entity(root: Path, entity_type: str, entity_id: str, cache: EntityCache | None = None) -> dict[str, Any]:
    key = (entity_type, entity_id)
    if cache is not None and key in cache:
        return cache[key]
    paths = (
        root / "data" / "knowledge" / "entities" / entity_type / f"{entity_id}.json",
        root / "data" / "knowledge" / "reference" / entity_type / f"{entity_id}.json",
    )
    for path in paths:
        if path.exists():
            entity = load_json(path)
            if cache is not None:
                cache[key] = entity
            return entity
    raise ValidationError(f"Knowledge entity is missing: {entity_type}/{entity_id}")


def _field(entity: dict[str, Any], name: str) -> tuple[Any, tuple[EvidenceRef, ...]]:
    envelope = entity.get("fields", {}).get(name)
    if not isinstance(envelope, dict) or "value" not in envelope:
        raise ValidationError(f"Validated field is missing: {entity.get('type')}/{entity.get('id')}/{name}")
    evidence = tuple(
        EvidenceRef(
            proposal_id=str(item["proposal_id"]),
            source_id=str(item["source_id"]),
            locator=str(item["locator"]),
        )
        for item in envelope.get("provenance", [])
    )
    if not evidence:
        raise ValidationError(f"Validated field has no provenance: {entity.get('type')}/{entity.get('id')}/{name}")
    return envelope["value"], evidence


def _deep(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValidationError(f"Composition path is missing: {path}")
        current = current[part]
    return current


def _date(value: Any) -> str:
    raw = str(value)
    if len(raw) >= 7 and raw[4] == "-":
        return f"{raw[5:7]}/{raw[:4]}"
    return raw[:4]


def _period(entity: dict[str, Any]) -> tuple[str, tuple[EvidenceRef, ...]]:
    for field_name in ("timeframe", "chronology", "details"):
        if field_name not in entity.get("fields", {}):
            continue
        details, evidence = _field(entity, field_name)
        if not isinstance(details, dict):
            continue
        start = details.get("start_date", details.get("start_year"))
        end = details.get("end_date", details.get("end_year", details.get("known_through")))
        if start is not None and end is not None:
            return f"{_date(start)} - {_date(end)}", evidence
    raise ValidationError(f"Experience period cannot be derived: {entity.get('id')}")


def _evidence_for_fields(entity: dict[str, Any], fields: Iterable[str]) -> tuple[EvidenceRef, ...]:
    evidence: list[EvidenceRef] = []
    for name in fields:
        _, field_evidence = _field(entity, name)
        evidence.extend(field_evidence)
    return tuple(evidence)


def _referenced_field(
    context: CompositionContext,
    specification: dict[str, Any],
) -> tuple[Any, tuple[EvidenceRef, ...]]:
    entity = _entity(
        context.root,
        str(specification["entity_type"]),
        str(specification["entity_id"]),
        context.cache,
    )
    return _field(entity, str(specification["field"]))


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)


def _responsibility_sequence(
    entity_id: str,
    responsibilities: tuple[str, ...],
    sequence: Any,
    maximum_words: int,
    maximum_sequence_steps: int,
) -> tuple[CVSequenceStep, ...]:
    if not isinstance(sequence, list) or not 2 <= len(sequence) <= maximum_sequence_steps:
        raise ValidationError(f"Invalid responsibility sequence for {entity_id}")
    group_sizes: list[int] = []
    for step in sequence:
        raw_size = step.get("responsibility_count") if isinstance(step, dict) else None
        if not isinstance(raw_size, int) or isinstance(raw_size, bool) or raw_size <= 0:
            raise ValidationError(f"Invalid responsibility sequence counts for {entity_id}")
        group_sizes.append(raw_size)
    if sum(group_sizes) != len(responsibilities):
        raise ValidationError(f"Responsibility sequence must cover every responsibility for {entity_id}")
    result: list[CVSequenceStep] = []
    start = 0
    for step, size in zip(sequence, group_sizes, strict=True):
        label = str(step.get("label", "")).strip()
        if not label:
            raise ValidationError(f"Responsibility sequence label is missing for {entity_id}")
        step_responsibilities = responsibilities[start : start + size]
        if len(" ".join(step_responsibilities).split()) > maximum_words:
            raise ValidationError(f"Responsibility sequence step exceeds template word limit: {entity_id}")
        result.append(CVSequenceStep(label=label, responsibilities=step_responsibilities))
        start += size
    return tuple(result)


def _experience_responsibilities(entity: dict[str, Any]) -> tuple[list[Any], tuple[EvidenceRef, ...]]:
    if "responsibilities" in entity.get("fields", {}):
        responsibilities, evidence = _field(entity, "responsibilities")
    else:
        details, evidence = _field(entity, "details")
        responsibilities = details.get("responsibilities", []) if isinstance(details, dict) else []
    if not isinstance(responsibilities, list) or not responsibilities:
        raise ValidationError(f"Experience responsibilities are missing: {entity.get('id')}")
    return responsibilities, evidence


def _organization_display(
    context: CompositionContext,
    specification: dict[str, Any],
    entity_id: str,
) -> tuple[str, str, tuple[EvidenceRef, ...]]:
    organization_spec = specification.get("organization_display")
    if not organization_spec:
        return "", "", ()
    organization_value, evidence = _referenced_field(context, organization_spec["evidence"])
    name = str(organization_spec["name"])
    tagline = str(organization_spec.get("tagline", ""))
    searchable = _flatten_text(organization_value).casefold()
    if any(value and value.casefold() not in searchable for value in (name, tagline)):
        raise ValidationError(f"Organization display is not supported by validated knowledge: {entity_id}")
    return name, tagline, evidence


def _context_display(
    context: CompositionContext,
    specification: dict[str, Any],
    entity_id: str,
) -> tuple[str, tuple[EvidenceRef, ...]]:
    label = str(specification.get("context_label", ""))
    if not label:
        return "", ()
    evidence_spec = specification.get("context_evidence")
    if not isinstance(evidence_spec, dict):
        raise ValidationError(f"Experience context has no evidence: {entity_id}")
    _, evidence = _referenced_field(context, evidence_spec)
    return label, evidence


def _experience_highlight(
    context: CompositionContext,
    specification: dict[str, Any],
    entity_id: str,
) -> tuple[CVHighlight | None, tuple[EvidenceRef, ...]]:
    highlight_spec = specification.get("highlight")
    if not highlight_spec:
        return None, ()
    cards_spec = highlight_spec.get("cards")
    if not isinstance(cards_spec, list) or not 2 <= len(cards_spec) <= context.maximum_sequence_steps:
        raise ValidationError(f"Experience highlight must define a valid card sequence: {entity_id}")
    cards: list[CVHighlightCard] = []
    evidence: list[EvidenceRef] = []
    for card_spec in cards_spec:
        card_label = str(card_spec.get("label", "")).strip()
        item_specs = card_spec.get("items")
        if not card_label or not isinstance(item_specs, list) or not item_specs:
            raise ValidationError(f"Experience highlight card is incomplete: {entity_id}")
        items: list[str] = []
        for item_spec in item_specs:
            item_label = str(item_spec.get("label", "")).strip()
            if not item_label:
                raise ValidationError(f"Experience highlight item label is missing: {entity_id}")
            _, item_evidence = _referenced_field(context, item_spec["evidence"])
            items.append(item_label)
            evidence.extend(item_evidence)
        cards.append(CVHighlightCard(label=card_label, items=tuple(items)))
    return CVHighlight(label=str(highlight_spec["label"]), cards=tuple(cards)), tuple(evidence)


def _experience(
    context: CompositionContext,
    specification: dict[str, Any],
) -> CVExperience:
    entity = _entity(context.root, "experience", str(specification["entity_id"]), context.cache)
    entity_id = str(entity.get("id"))
    mission, mission_evidence = _field(entity, "mission")
    responsibilities, responsibility_evidence = _experience_responsibilities(entity)
    bullet_limit = int(specification["bullet_limit"])
    if bullet_limit < 0 or bullet_limit > context.maximum_bullets:
        raise ValidationError(f"Invalid bullet limit for {entity.get('id')}: {bullet_limit}")
    display_responsibilities = tuple(str(item) for item in responsibilities)
    sequence_steps: tuple[CVSequenceStep, ...] = ()
    if "responsibility_sequence" in specification:
        if bullet_limit != 0:
            raise ValidationError(f"Responsibility sequence cannot be combined with bullets for {entity.get('id')}")
        sequence_steps = _responsibility_sequence(
            str(entity.get("id")),
            display_responsibilities,
            specification["responsibility_sequence"],
            context.maximum_words,
            context.maximum_sequence_steps,
        )
    for bullet in display_responsibilities[:bullet_limit]:
        if len(bullet.split()) > context.maximum_words:
            raise ValidationError(f"Responsibility exceeds template word limit: {entity.get('id')}")
    period, period_evidence = _period(entity)
    heading_evidence = _evidence_for_fields(entity, specification.get("heading_evidence_fields", []))
    organization_name, organization_tagline, organization_evidence = _organization_display(
        context, specification, entity_id
    )
    context_label, context_evidence = _context_display(context, specification, entity_id)
    highlight, highlight_evidence = _experience_highlight(context, specification, entity_id)
    return CVExperience(
        entity_id=str(entity["id"]),
        period=period,
        heading=str(specification["heading"]),
        mission=str(mission),
        responsibilities=display_responsibilities,
        bullet_limit=bullet_limit,
        responsibility_sequence=sequence_steps,
        organization_name=organization_name,
        organization_tagline=organization_tagline,
        context_label=context_label,
        highlight=highlight,
        evidence=tuple(
            (
                *mission_evidence,
                *responsibility_evidence,
                *period_evidence,
                *heading_evidence,
                *organization_evidence,
                *context_evidence,
                *highlight_evidence,
            )
        ),
    )


def _continuity_group(
    context: CompositionContext,
    specification: dict[str, Any],
    experiences_by_id: dict[str, CVExperience],
    experience_entities: dict[str, dict[str, Any]],
) -> CVContinuityGroup:
    group_id = str(specification["id"])
    experience_ids = tuple(str(item) for item in specification["experience_ids"])
    try:
        experiences = tuple(experiences_by_id[item] for item in experience_ids)
    except KeyError as error:
        raise ValidationError(f"Continuity group references an unknown experience: {group_id}") from error
    shared_responsibilities = experiences[0].responsibilities
    if any(item.responsibilities != shared_responsibilities for item in experiences[1:]):
        raise ValidationError(f"Continuity group responsibilities differ: {group_id}")

    job_role_id = str(specification["job_role_id"])
    relation_evidence: list[EvidenceRef] = []
    for experience_id in experience_ids:
        job_role_ids, evidence = _field(experience_entities[experience_id], "job_role_ids")
        if not isinstance(job_role_ids, list) or job_role_id not in job_role_ids:
            raise ValidationError(f"Continuity group job role is not validated for {experience_id}")
        relation_evidence.extend(evidence)
    for current_id, previous_id in zip(experience_ids, experience_ids[1:], strict=False):
        validated_previous_id, evidence = _field(experience_entities[current_id], "previous_experience_id")
        if validated_previous_id != previous_id:
            raise ValidationError(f"Continuity group chronology is not validated: {current_id}")
        relation_evidence.extend(evidence)

    role_entity = _entity(context.root, "job-role", job_role_id, context.cache)
    role_details, role_evidence = _field(role_entity, "details")
    if not isinstance(role_details, dict) or not role_details.get("name"):
        raise ValidationError(f"Continuity group job role is incomplete: {job_role_id}")
    sequence = _responsibility_sequence(
        group_id,
        shared_responsibilities,
        specification["responsibility_sequence"],
        context.maximum_words,
        context.maximum_sequence_steps,
    )
    period = f"{experiences[-1].period.split(' - ', 1)[0]} - {experiences[0].period.rsplit(' - ', 1)[-1]}"
    return CVContinuityGroup(
        group_id=group_id,
        label=str(specification["label"]),
        context_label=str(specification["context_label"]),
        period=period,
        job_role=str(role_details["name"]),
        experiences=experiences,
        responsibility_sequence=sequence,
        evidence=tuple((*relation_evidence, *role_evidence)),
    )


def _education(context: CompositionContext, entity_type: str, entity_id: str) -> CVEducation:
    entity = _entity(context.root, entity_type, entity_id, context.cache)
    details, evidence = _field(entity, "details")
    if not isinstance(details, dict):
        raise ValidationError(f"Education details must be structured: {entity_id}")
    if "awarded_year" in details:
        primary = f"{details['awarded_year']} · {details['name']} · {details['level']}"
        secondary = str(details["issuer"])
    elif "program" in details:
        primary = f"{str(details.get('end_date', details.get('start_date', '')))[:4]} · {details['program']}"
        secondary = str(details["institution"])
    elif "program_stage" in details:
        primary = f"{details['year']} · {str(details['program_stage']).capitalize()}"
        secondary = str(details["institution"])
    else:
        raise ValidationError(f"Unsupported education structure: {entity_id}")
    return CVEducation(entity_id=entity_id, primary=primary, secondary=secondary, evidence=evidence)


def _profile_signature(root: Path, strategy: dict[str, Any]) -> str:
    style = load_json(root / "data" / "style" / "delia.json")
    return str(
        next(
            item["text"]
            for item in style["profile_signatures"]
            if item["id"] == strategy["profile_signature_id"] and item["status"] == "validated"
        )
    )


def _key_skills(
    context: CompositionContext,
    strategy: dict[str, Any],
    strengths: Any,
    strength_evidence: tuple[EvidenceRef, ...],
) -> tuple[list[str], list[EvidenceRef]]:
    labels: list[str] = []
    evidence_refs: list[EvidenceRef] = []
    for skill in strategy["key_skills"]:
        labels.append(str(skill["label"]))
        evidence_spec = skill["evidence"]
        evidence_entity = _entity(
            context.root,
            str(evidence_spec["entity_type"]),
            str(evidence_spec["entity_id"]),
            context.cache,
        )
        _, evidence = _field(evidence_entity, str(evidence_spec["field"]))
        evidence_refs.extend(evidence)
    if strategy.get("include_signature_strengths"):
        labels.extend(str(item) for item in strengths)
        evidence_refs.extend(strength_evidence)
    if len(labels) > int(context.rules["key_skills_max"]):
        raise ValidationError("CV key skills exceed template limit")
    return labels, evidence_refs


def _tools_summary(context: CompositionContext, strategy: dict[str, Any]) -> tuple[str, tuple[EvidenceRef, ...]]:
    specification = strategy["tools"]
    entity = _entity(
        context.root,
        str(specification["entity_type"]),
        str(specification["entity_id"]),
        context.cache,
    )
    tools, evidence = _field(entity, str(specification["field"]))
    names = [str(item["name"]) for item in tools]
    levels = {str(item["level"]) for item in tools}
    level = next(iter(levels)) if len(levels) == 1 else "niveaux détaillés"
    return f"Outils : {', '.join(names)} - niveau {level}", evidence


def _validated_profile_summary(strategy: dict[str, Any], template: dict[str, Any]) -> str:
    if strategy.get("status") != "validated":
        raise ValidationError("CV content strategy must be validated")
    if strategy.get("template_id") != template.get("id"):
        raise ValidationError("CV content strategy and template do not match")
    summary = str(strategy["profile_summary"])
    if len(summary.split()) > int(template["content_rules"]["profile_max_words"]):
        raise ValidationError("CV profile exceeds template word limit")
    return summary


def _compose_profile(context: CompositionContext, strategy: dict[str, Any]) -> ProfileComposition:
    person = _entity(context.root, "person", str(strategy["person_id"]), context.cache)
    name, name_evidence = _field(person, "professional_name")
    strengths, strength_evidence = _field(person, "signature_strengths")
    interests, interest_evidence = _field(person, "interests")
    email_entity = _entity(context.root, "contact-point", str(strategy["email_contact_id"]), context.cache)
    phone_entity = _entity(context.root, "contact-point", str(strategy["phone_contact_id"]), context.cache)
    email_details, email_evidence = _field(email_entity, "details")
    phone_details, phone_evidence = _field(phone_entity, "details")
    signature = _profile_signature(context.root, strategy)
    skill_labels, skill_evidence = _key_skills(context, strategy, strengths, strength_evidence)
    tools_line, tools_evidence = _tools_summary(context, strategy)
    return ProfileComposition(
        name=str(name),
        email=str(email_details["value"]),
        phone=str(phone_details["value"]),
        signature=signature,
        key_skills=tuple(skill_labels),
        tools_line=tools_line,
        interests=tuple(interests),
        evidence=tuple(
            (
                *name_evidence,
                *strength_evidence,
                *interest_evidence,
                *email_evidence,
                *phone_evidence,
                *skill_evidence,
                *tools_evidence,
            )
        ),
    )


def _validate_continuity_membership(
    strategy: dict[str, Any],
    continuity_groups: tuple[CVContinuityGroup, ...],
) -> set[str]:
    grouped_experience_ids = {
        experience.entity_id for group in continuity_groups for experience in group.experiences
    }
    configured_group_ids = {str(item["id"]) for item in strategy.get("continuity_groups", [])}
    for specification in strategy["experiences"]:
        declared_group_id = specification.get("continuity_group_id")
        if declared_group_id and declared_group_id not in configured_group_ids:
            raise ValidationError(f"Experience references an unknown continuity group: {declared_group_id}")
        if bool(declared_group_id) != (str(specification["entity_id"]) in grouped_experience_ids):
            raise ValidationError(f"Continuity group membership is inconsistent: {specification['entity_id']}")
    return grouped_experience_ids


def _compose_experiences(context: CompositionContext, strategy: dict[str, Any]) -> ExperienceComposition:
    experiences = tuple(_experience(context, item) for item in strategy["experiences"])
    experiences_by_id = {item.entity_id: item for item in experiences}
    experience_entities = {
        item.entity_id: _entity(context.root, "experience", item.entity_id, context.cache)
        for item in experiences
    }
    continuity_groups = tuple(
        _continuity_group(context, item, experiences_by_id, experience_entities)
        for item in strategy.get("continuity_groups", [])
    )
    grouped_experience_ids = _validate_continuity_membership(strategy, continuity_groups)
    recent = tuple(
        item
        for item, specification in zip(experiences, strategy["experiences"], strict=True)
        if specification["group"] == "recent" and item.entity_id not in grouped_experience_ids
    )
    complementary = tuple(
        item
        for item, specification in zip(experiences, strategy["experiences"], strict=True)
        if specification["group"] == "complementary"
    )
    return ExperienceComposition(
        all_experiences=experiences,
        continuity_groups=continuity_groups,
        recent=recent,
        complementary=complementary,
    )


def _compose_education(
    context: CompositionContext,
    strategy: dict[str, Any],
    interests: tuple[Any, ...],
) -> EducationComposition:
    items = tuple(
        _education(context, str(item["entity_type"]), str(item["entity_id"]))
        for item in strategy["education"]
    )
    language_entity = _entity(
        context.root,
        "language-proficiency",
        str(strategy["language_id"]),
        context.cache,
    )
    language, language_evidence = _field(language_entity, "details")
    language_line = (
        f"{str(language['language']).capitalize()} · oral et lecture : {language['speaking_level']} · "
        f"écrit : {language['writing_level']} · " + " · ".join(str(item).capitalize() for item in interests)
    )
    return EducationComposition(
        items=items,
        language_line=language_line,
        language_evidence=language_evidence,
    )


def _composition_evidence(
    profile: ProfileComposition,
    experiences: ExperienceComposition,
    education: EducationComposition,
) -> tuple[EvidenceRef, ...]:
    return tuple(
        (
            *profile.evidence,
            *education.language_evidence,
            *(reference for group in experiences.continuity_groups for reference in group.evidence),
            *(reference for item in experiences.all_experiences for reference in item.evidence),
            *(reference for item in education.items for reference in item.evidence),
        )
    )


def compose_standard_cv(root: Path, template: dict[str, Any], strategy: dict[str, Any]) -> CVViewModel:
    rules = template["content_rules"]
    context = CompositionContext(root=root, rules=rules)
    profile_summary = _validated_profile_summary(strategy, template)
    profile = _compose_profile(context, strategy)
    experiences = _compose_experiences(context, strategy)
    education = _compose_education(context, strategy, profile.interests)
    return CVViewModel(
        template_id=str(template["id"]),
        template_version=str(template["version"]),
        layout_rules=CVLayoutRules.from_mapping(template["rendering"]["layout"]),
        strategy_id=str(strategy["id"]),
        name=profile.name,
        email=profile.email,
        phone=profile.phone,
        tagline=str(strategy["tagline"]),
        signature=profile.signature,
        profile_summary=profile_summary,
        key_skills=profile.key_skills,
        tools_line=profile.tools_line,
        recent_continuity_groups=experiences.continuity_groups,
        recent_experiences=experiences.recent,
        complementary_experiences=experiences.complementary,
        education=education.items,
        language_and_interests=education.language_line,
        photo=(root / str(strategy["photo"])).resolve(),
        evidence=_composition_evidence(profile, experiences, education),
    )
