from __future__ import annotations

from typing import Any

from .core import normalize_terms


def match_offer(offer: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    known = normalize_terms(knowledge.get("skills", []))
    required = normalize_terms(offer.get("required_skills", []))
    preferred = normalize_terms(offer.get("preferred_skills", []))
    required_hits = sorted(required & known)
    preferred_hits = sorted(preferred & known)
    missing_required = sorted(required - known)
    required_score = len(required_hits) / len(required) if required else 1.0
    preferred_score = len(preferred_hits) / len(preferred) if preferred else 1.0
    score = round((0.75 * required_score + 0.25 * preferred_score) * 100, 1)
    return {
        "score": score,
        "required_matches": required_hits,
        "preferred_matches": preferred_hits,
        "missing_required": missing_required,
        "method": "literal-normalized-v1",
    }


def score_template(template: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    score = 0
    reasons: list[str] = []
    if context.get("ats_required") and template.get("ats_compatible"):
        score += 40
        reasons.append("compatible ATS")
    elif context.get("ats_required"):
        score -= 100
        reasons.append("incompatible avec l'exigence ATS")

    for field, points in (("sectors", 20), ("roles", 20), ("seniority", 10), ("countries", 10)):
        wanted = normalize_terms(context.get(field, []))
        offered = normalize_terms(template.get(field, []))
        overlap = sorted(wanted & offered)
        if overlap:
            score += points
            reasons.append(f"{field}: {', '.join(overlap)}")

    return {"template_id": template["id"], "score": score, "reasons": reasons}


def rank_templates(templates: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
    ranked = [score_template(template, context) for template in templates]
    return sorted(ranked, key=lambda item: (-item["score"], item["template_id"]))
