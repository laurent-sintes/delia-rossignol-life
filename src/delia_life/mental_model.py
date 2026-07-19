from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path
from typing import Any

ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
CONCEPT_KINDS = {"entity", "process", "artifact", "event", "assessment", "value_object"}
PRIVACY_LEVELS = {"public", "private", "mixed"}
CARDINALITIES = {"one_to_one", "one_to_many", "many_to_one", "many_to_many"}


def _yaml_module() -> Any:
    try:
        return importlib.import_module("yaml")
    except ModuleNotFoundError:
        project_root = Path(__file__).resolve().parents[2]
        local_validation_dependency = project_root / ".tools" / "validation"
        if local_validation_dependency.is_dir():
            sys.path.insert(0, str(local_validation_dependency))
            return importlib.import_module("yaml")
        raise ValueError("PyYAML is required; install the project with: python -m pip install -e .") from None


def _load_yaml(path: Path) -> dict[str, Any]:
    yaml = _yaml_module()
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return value


def _safe_model_file(model_dir: Path, relative: str) -> Path:
    candidate = (model_dir / relative).resolve()
    try:
        candidate.relative_to(model_dir.resolve())
    except ValueError as error:
        raise ValueError(f"Model file escapes model directory: {relative}") from error
    if candidate.suffix.casefold() not in {".yaml", ".yml"}:
        raise ValueError(f"Model file must be YAML: {relative}")
    return candidate


def load_mental_model(manifest_path: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest = _load_yaml(manifest_path)
    model_dir = manifest_path.parent
    concepts: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    loaded_files = [manifest_path]
    for relative in manifest.get("concept_files", []):
        path = _safe_model_file(model_dir, str(relative))
        concepts.extend(_load_yaml(path).get("concepts", []))
        loaded_files.append(path)
    for relative in manifest.get("relation_files", []):
        path = _safe_model_file(model_dir, str(relative))
        relations.extend(_load_yaml(path).get("relations", []))
        loaded_files.append(path)
    return {
        **manifest,
        "concepts": concepts,
        "relations": relations,
        "loaded_files": [str(path) for path in loaded_files],
    }


def validate_mental_model(model: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not model.get("model_version"):
        errors.append("model_version is required")
    concepts = model.get("concepts", [])
    relations = model.get("relations", [])
    if not isinstance(concepts, list) or not concepts:
        errors.append("at least one concept is required")
        return errors

    concept_ids: set[str] = set()
    required_concept_fields = {"id", "label", "kind", "description", "privacy", "storage", "key_attributes"}
    for index, concept in enumerate(concepts):
        if not isinstance(concept, dict):
            errors.append(f"concept[{index}] must be a mapping")
            continue
        missing = sorted(required_concept_fields - concept.keys())
        if missing:
            errors.append(f"concept[{index}] missing: {', '.join(missing)}")
        concept_id = str(concept.get("id", ""))
        if not ID_PATTERN.fullmatch(concept_id):
            errors.append(f"invalid concept id: {concept_id!r}")
        elif concept_id in concept_ids:
            errors.append(f"duplicate concept id: {concept_id}")
        concept_ids.add(concept_id)
        if concept.get("kind") not in CONCEPT_KINDS:
            errors.append(f"{concept_id}: invalid kind {concept.get('kind')!r}")
        if concept.get("privacy") not in PRIVACY_LEVELS:
            errors.append(f"{concept_id}: invalid privacy {concept.get('privacy')!r}")
        if not isinstance(concept.get("key_attributes"), list):
            errors.append(f"{concept_id}: key_attributes must be a list")

    relation_ids: set[str] = set()
    required_relation_fields = {"id", "from", "to", "label", "cardinality", "required"}
    for index, relation in enumerate(relations):
        if not isinstance(relation, dict):
            errors.append(f"relation[{index}] must be a mapping")
            continue
        missing = sorted(required_relation_fields - relation.keys())
        if missing:
            errors.append(f"relation[{index}] missing: {', '.join(missing)}")
        relation_id = str(relation.get("id", ""))
        if not ID_PATTERN.fullmatch(relation_id):
            errors.append(f"invalid relation id: {relation_id!r}")
        elif relation_id in relation_ids:
            errors.append(f"duplicate relation id: {relation_id}")
        relation_ids.add(relation_id)
        for endpoint in ("from", "to"):
            if relation.get(endpoint) not in concept_ids:
                errors.append(f"{relation_id}: unknown {endpoint} concept {relation.get(endpoint)!r}")
        if relation.get("cardinality") not in CARDINALITIES:
            errors.append(f"{relation_id}: invalid cardinality {relation.get('cardinality')!r}")
        if not isinstance(relation.get("required"), bool):
            errors.append(f"{relation_id}: required must be boolean")

    invariant_ids: set[str] = set()
    for invariant in model.get("invariants", []):
        invariant_id = str(invariant.get("id", "")) if isinstance(invariant, dict) else ""
        if not ID_PATTERN.fullmatch(invariant_id):
            errors.append(f"invalid invariant id: {invariant_id!r}")
        elif invariant_id in invariant_ids:
            errors.append(f"duplicate invariant id: {invariant_id}")
        invariant_ids.add(invariant_id)
        if not isinstance(invariant, dict) or not invariant.get("rule"):
            errors.append(f"{invariant_id or 'invariant'}: rule is required")
    return errors


def model_summary(model: dict[str, Any]) -> dict[str, Any]:
    errors = validate_mental_model(model)
    return {
        "model_version": model.get("model_version"),
        "namespace": model.get("namespace"),
        "concept_count": len(model.get("concepts", [])),
        "relation_count": len(model.get("relations", [])),
        "invariant_count": len(model.get("invariants", [])),
        "loaded_files": model.get("loaded_files", []),
        "errors": errors,
        "ok": not errors,
    }


def model_impact(model: dict[str, Any], concept_id: str) -> dict[str, Any]:
    concepts = {concept["id"]: concept for concept in model.get("concepts", []) if isinstance(concept, dict) and "id" in concept}
    if concept_id not in concepts:
        raise ValueError(f"Unknown concept: {concept_id}")
    outgoing = [relation for relation in model.get("relations", []) if relation.get("from") == concept_id]
    incoming = [relation for relation in model.get("relations", []) if relation.get("to") == concept_id]
    neighbors = sorted({relation["to"] for relation in outgoing} | {relation["from"] for relation in incoming})
    return {
        "concept": concepts[concept_id],
        "incoming_relations": incoming,
        "outgoing_relations": outgoing,
        "neighbor_concepts": neighbors,
        "relation_count": len(incoming) + len(outgoing),
    }
