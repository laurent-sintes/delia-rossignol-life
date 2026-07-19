from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .core import load_json
from .cv_model import CVEducation, CVExperience, CVViewModel, EvidenceRef
from .errors import ValidationError


def _entity(root: Path, entity_type: str, entity_id: str) -> dict[str, Any]:
    return load_json(root / "data" / "knowledge" / "entities" / entity_type / f"{entity_id}.json")


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


def _experience(root: Path, specification: dict[str, Any], maximum_bullets: int, maximum_words: int) -> CVExperience:
    entity = _entity(root, "experience", str(specification["entity_id"]))
    mission, mission_evidence = _field(entity, "mission")
    if "responsibilities" in entity.get("fields", {}):
        responsibilities, responsibility_evidence = _field(entity, "responsibilities")
    else:
        details, responsibility_evidence = _field(entity, "details")
        responsibilities = details.get("responsibilities", []) if isinstance(details, dict) else []
    if not isinstance(responsibilities, list) or not responsibilities:
        raise ValidationError(f"Experience responsibilities are missing: {entity.get('id')}")
    bullet_limit = int(specification["bullet_limit"])
    if bullet_limit < 0 or bullet_limit > maximum_bullets:
        raise ValidationError(f"Invalid bullet limit for {entity.get('id')}: {bullet_limit}")
    for bullet in responsibilities[:bullet_limit]:
        if len(str(bullet).split()) > maximum_words:
            raise ValidationError(f"Responsibility exceeds template word limit: {entity.get('id')}")
    period, period_evidence = _period(entity)
    heading_evidence = _evidence_for_fields(entity, specification.get("heading_evidence_fields", []))
    return CVExperience(
        entity_id=str(entity["id"]),
        period=period,
        heading=str(specification["heading"]),
        mission=str(mission),
        responsibilities=tuple(str(item) for item in responsibilities),
        bullet_limit=bullet_limit,
        evidence=tuple((*mission_evidence, *responsibility_evidence, *period_evidence, *heading_evidence)),
    )


def _education(root: Path, entity_type: str, entity_id: str) -> CVEducation:
    entity = _entity(root, entity_type, entity_id)
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


def compose_standard_cv(root: Path, template: dict[str, Any], strategy: dict[str, Any]) -> CVViewModel:
    if strategy.get("status") != "validated":
        raise ValidationError("CV content strategy must be validated")
    if strategy.get("template_id") != template.get("id"):
        raise ValidationError("CV content strategy and template do not match")
    rules = template["content_rules"]
    profile_summary = str(strategy["profile_summary"])
    if len(profile_summary.split()) > int(rules["profile_max_words"]):
        raise ValidationError("CV profile exceeds template word limit")

    person = _entity(root, "person", str(strategy["person_id"]))
    name, name_evidence = _field(person, "professional_name")
    strengths, strength_evidence = _field(person, "signature_strengths")
    interests, interest_evidence = _field(person, "interests")
    email_entity = _entity(root, "contact-point", str(strategy["email_contact_id"]))
    phone_entity = _entity(root, "contact-point", str(strategy["phone_contact_id"]))
    email_details, email_evidence = _field(email_entity, "details")
    phone_details, phone_evidence = _field(phone_entity, "details")

    style = load_json(root / "data" / "style" / "delia.json")
    signature = next(
        item["text"]
        for item in style["profile_signatures"]
        if item["id"] == strategy["profile_signature_id"] and item["status"] == "validated"
    )

    skill_labels: list[str] = []
    skill_evidence: list[EvidenceRef] = []
    for skill in strategy["key_skills"]:
        skill_labels.append(str(skill["label"]))
        evidence_entity = _entity(root, str(skill["evidence"]["entity_type"]), str(skill["evidence"]["entity_id"]))
        _, evidence = _field(evidence_entity, str(skill["evidence"]["field"]))
        skill_evidence.extend(evidence)
    if strategy.get("include_signature_strengths"):
        skill_labels.extend(str(item) for item in strengths)
        skill_evidence.extend(strength_evidence)
    if len(skill_labels) > int(rules["key_skills_max"]):
        raise ValidationError("CV key skills exceed template limit")

    tools_spec = strategy["tools"]
    tools_entity = _entity(root, str(tools_spec["entity_type"]), str(tools_spec["entity_id"]))
    tools, tools_evidence = _field(tools_entity, str(tools_spec["field"]))
    names = [str(item["name"]) for item in tools]
    levels = {str(item["level"]) for item in tools}
    level = next(iter(levels)) if len(levels) == 1 else "niveaux détaillés"
    tools_line = f"Outils : {', '.join(names)} - niveau {level}"

    experiences = [
        _experience(root, item, int(rules["experience_bullets_max"]), int(rules["bullet_max_words"]))
        for item in strategy["experiences"]
    ]
    recent = tuple(item for item, spec in zip(experiences, strategy["experiences"], strict=True) if spec["group"] == "recent")
    complementary = tuple(
        item for item, spec in zip(experiences, strategy["experiences"], strict=True) if spec["group"] == "complementary"
    )
    education = tuple(
        _education(root, str(item["entity_type"]), str(item["entity_id"]))
        for item in strategy["education"]
    )
    language_entity = _entity(root, "language-proficiency", str(strategy["language_id"]))
    language, language_evidence = _field(language_entity, "details")
    language_line = (
        f"{str(language['language']).capitalize()} · oral et lecture : {language['speaking_level']} · "
        f"écrit : {language['writing_level']} · " + " · ".join(str(item).capitalize() for item in interests)
    )
    all_evidence = [
        *name_evidence,
        *strength_evidence,
        *interest_evidence,
        *email_evidence,
        *phone_evidence,
        *skill_evidence,
        *tools_evidence,
        *language_evidence,
        *(reference for item in experiences for reference in item.evidence),
        *(reference for item in education for reference in item.evidence),
    ]
    return CVViewModel(
        template_id=str(template["id"]),
        template_version=str(template["version"]),
        strategy_id=str(strategy["id"]),
        name=str(name),
        email=str(email_details["value"]),
        phone=str(phone_details["value"]),
        tagline=str(strategy["tagline"]),
        signature=str(signature),
        profile_summary=profile_summary,
        key_skills=tuple(skill_labels),
        tools_line=tools_line,
        recent_experiences=recent,
        complementary_experiences=complementary,
        education=education,
        language_and_interests=language_line,
        photo=(root / str(strategy["photo"])).resolve(),
        evidence=tuple(all_evidence),
    )
