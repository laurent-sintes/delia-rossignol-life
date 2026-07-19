from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from .core import load_json, write_json

TOKEN_PATTERN = re.compile(r"[a-z0-9]{3,}")
STOP_WORDS = {"avec", "dans", "pour", "une", "des", "les", "par", "sur", "ses", "est", "the", "and", "from", "this", "that", "your"}


def _tokens(value: Any) -> set[str]:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii").casefold()
    return {token for token in TOKEN_PATTERN.findall(text) if token not in STOP_WORDS}


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for child in value for item in _strings(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _strings(child)]
    return []


def _field_value(entity: dict[str, Any], name: str) -> Any:
    return entity.get("fields", {}).get(name, {}).get("value")


def _field_sources(entity: dict[str, Any], name: str) -> list[str]:
    provenance = entity.get("fields", {}).get(name, {}).get("provenance", [])
    return sorted({str(item["source_id"]) for item in provenance if item.get("source_id")})


def plan_personal_response(offer: dict[str, Any], knowledge_root: Path) -> dict[str, Any]:
    """Create a traceable evidence plan; it intentionally does not draft prose."""
    offer_text = _strings(offer)
    offer_tokens = set().union(*(_tokens(item) for item in offer_text)) if offer_text else set()
    experience_root = knowledge_root / "experience"
    evidence: list[dict[str, Any]] = []
    for path in sorted(experience_root.glob("*.json")):
        entity = load_json(path)
        field_text = _strings(entity.get("fields", {}))
        matches = sorted(offer_tokens & set().union(*(_tokens(item) for item in field_text))) if field_text else []
        if not matches:
            continue
        mission = _field_value(entity, "mission")
        responsibilities = _field_value(entity, "responsibilities") or _field_value(entity, "details")
        evidence.append(
            {
                "experience_id": entity["id"],
                "matched_terms": matches,
                "relevance_score": len(matches),
                "mission": mission,
                "responsibilities": responsibilities,
                "source_ids": sorted(set(_field_sources(entity, "mission") + _field_sources(entity, "responsibilities") + _field_sources(entity, "details"))),
            }
        )
    evidence.sort(key=lambda item: (-item["relevance_score"], item["experience_id"]))

    posture_path = knowledge_root / "professional-posture" / "delia-rossignol.json"
    posture: list[dict[str, Any]] = []
    if posture_path.exists():
        entity = load_json(posture_path)
        for field, classification in (("site_claims", "claim"), ("validated_inferences", "inference")):
            posture.extend(
                {
                    "statement": statement,
                    "classification": classification,
                    "source_ids": _field_sources(entity, field),
                }
                for statement in _field_value(entity, field) or []
            )

    knowledge_text = _strings([load_json(path) for path in knowledge_root.rglob("*.json")])
    known_tokens = set().union(*(_tokens(item) for item in knowledge_text)) if knowledge_text else set()
    required = [str(item) for item in offer.get("required_skills", [])]
    preferred = [str(item) for item in offer.get("preferred_skills", [])]
    missing = [item for item in required + preferred if not _tokens(item).issubset(known_tokens)]
    return {
        "method": "personal-response-plan-v1",
        "offer": {"id": offer["id"], "title": offer["title"], "employer": offer["employer"]},
        "requirements": {"required_skills": required, "preferred_skills": preferred, "uncovered_terms": missing},
        "professional_posture": posture,
        "experience_evidence": evidence[:5],
        "writing_constraints": [
            "Rédiger au plus dix lignes à partir des seuls éléments listés.",
            "Présenter les inférences comme une posture, jamais comme un fait indépendant.",
            "Ne pas promettre une compétence ou un résultat absent des preuves sélectionnées.",
        ],
    }


def write_personal_response_plan(offer: dict[str, Any], knowledge_root: Path, output: Path) -> dict[str, Any]:
    plan = plan_personal_response(offer, knowledge_root)
    write_json(output, plan)
    return plan
