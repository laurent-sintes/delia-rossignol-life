from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .core import load_json, sha256_file, write_json
from .experience import missing_experience_missions, missing_experience_responsibilities
from .ingestion import (
    apply_proposal,
    create_file_manifest,
    find_duplicate_keys,
    find_unresolved_duplicate_keys,
    migrate_career_project_entity,
    transition_proposal,
)
from .application_plan import write_personal_response_plan
from .mental_model import load_mental_model, model_impact, model_summary
from .recommendation import match_offer, rank_templates
from .review_batch import create_review_batch, review_batch
from .schema import validate
from .site_audit import audit_site
from .site_builder import build_site
from .tracking import append_event
from .website import slurp_site


def _json_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def command_check(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    errors: list[str] = []
    schema_dir = root / "schemas"
    schema_by_name = {path.stem.replace(".schema", ""): load_json(path) for path in schema_dir.glob("*.schema.json")}
    checks = [
        (root / "data" / "review" / "queue", "proposal"),
        (root / "data" / "offers", "job-offer"),
        (root / "private" / "career-project", "career-project"),
        (root / "templates" / "cv", "template"),
    ]
    checked = 0
    for directory, schema_name in checks:
        schema = schema_by_name.get(schema_name)
        if schema is None:
            errors.append(f"missing schema: {schema_name}")
            continue
        for path in directory.rglob("*.json"):
            checked += 1
            for message in validate(load_json(path), schema):
                errors.append(f"{path.relative_to(root)}: {message}")

    queue = [load_json(path) for path in (root / "data" / "review" / "queue").glob("*.json")]
    for key in find_unresolved_duplicate_keys(queue):
        errors.append(f"duplicate proposal target: {'/'.join(key)}")
    experience_root = root / "data" / "knowledge" / "entities"
    for path, experience_id in missing_experience_missions(experience_root):
        checked += 1
        errors.append(f"{path.relative_to(root)}: experience mission is required ({experience_id})")
    for path, experience_id in missing_experience_responsibilities(experience_root):
        checked += 1
        errors.append(f"{path.relative_to(root)}: experience responsibilities are required ({experience_id})")
    model_manifest = root / "model" / "model.yaml"
    if model_manifest.exists():
        try:
            summary = model_summary(load_mental_model(model_manifest))
            checked += len(summary["loaded_files"])
            errors.extend(f"mental model: {message}" for message in summary["errors"])
        except ValueError as error:
            errors.append(f"mental model: {error}")
    result = {"checked_files": checked, "errors": errors, "ok": not errors}
    _print(result)
    return 0 if not errors else 1


def command_manifest(args: argparse.Namespace) -> int:
    manifest = create_file_manifest(args.path, args.kind, args.uri)
    if args.output:
        write_json(args.output, manifest)
    _print(manifest)
    return 0


def command_review(args: argparse.Namespace) -> int:
    proposal = load_json(args.path)
    updated = transition_proposal(proposal, args.action, args.reviewer, args.value, args.note)
    write_json(args.path, updated)
    _print(updated)
    return 0


def command_apply(args: argparse.Namespace) -> int:
    proposal = load_json(args.path)
    updated, entity = apply_proposal(proposal, args.knowledge_root)
    write_json(args.path, updated)
    _print(entity)
    return 0


def command_create_batch(args: argparse.Namespace) -> int:
    batch = create_review_batch(load_json(args.specification), args.queue_root, args.output)
    _print(batch)
    return 0


def command_review_batch(args: argparse.Namespace) -> int:
    result = review_batch(
        args.batch,
        args.queue_root,
        args.knowledge_root,
        args.action,
        args.reviewer,
        args.note,
        args.apply,
    )
    _print(result)
    return 0


def command_migrate_career_project(args: argparse.Namespace) -> int:
    entity = load_json(args.path)
    criterion = load_json(args.criterion) if args.criterion else None
    migrated = migrate_career_project_entity(entity, args.person_id, criterion)
    write_json(args.path, migrated)
    _print(migrated)
    return 0


def command_match(args: argparse.Namespace) -> int:
    _print(match_offer(load_json(args.offer), load_json(args.knowledge)))
    return 0


def command_plan_personal_response(args: argparse.Namespace) -> int:
    plan = write_personal_response_plan(load_json(args.offer), args.knowledge_root, args.output)
    _print(plan)
    return 0


def command_select_template(args: argparse.Namespace) -> int:
    templates = [load_json(path) for path in args.templates]
    _print(rank_templates(templates, load_json(args.context)))
    return 0


def command_track(args: argparse.Namespace) -> int:
    application = load_json(args.application)
    updated = append_event(application, args.event_type, dict(args.details))
    write_json(args.application, updated)
    _print(updated)
    return 0


def command_slurp(args: argparse.Namespace) -> int:
    manifest = slurp_site(args.url, args.output, args.max_pages, args.delay, timeout_seconds=args.timeout, retries=args.retries, resume=not args.no_resume)
    _print({"id": manifest["id"], "records": len(manifest["records"]), "truncated": manifest["truncated"]})
    return 0


def command_build_site(args: argparse.Namespace) -> int:
    _print(build_site(args.root, args.output, args.config))
    return 0


def command_site_audit(args: argparse.Namespace) -> int:
    result = audit_site(args.root, args.config)
    _print(result)
    return 0 if result["ok"] else 1


def command_model_check(args: argparse.Namespace) -> int:
    summary = model_summary(load_mental_model(args.manifest))
    _print(summary)
    return 0 if summary["ok"] else 1


def command_model_impact(args: argparse.Namespace) -> int:
    model = load_mental_model(args.manifest)
    summary = model_summary(model)
    if not summary["ok"]:
        raise ValueError("Mental model is invalid; run model-check")
    _print(model_impact(model, args.concept))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="delia-life", description="Deterministic Delia career tooling")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="validate project data")
    check.add_argument("--root", type=Path, default=Path.cwd())
    check.set_defaults(func=command_check)

    hash_parser = subparsers.add_parser("hash", help="calculate a SHA-256 digest")
    hash_parser.add_argument("path", type=Path)
    hash_parser.set_defaults(func=lambda args: print(sha256_file(args.path)) or 0)

    manifest = subparsers.add_parser("manifest", help="create a source manifest")
    manifest.add_argument("path", type=Path)
    manifest.add_argument("--kind", required=True, choices=["cv", "diploma", "document", "website", "offer", "feedback"])
    manifest.add_argument("--uri")
    manifest.add_argument("--output", type=Path)
    manifest.set_defaults(func=command_manifest)

    review = subparsers.add_parser("review", help="record a review decision")
    review.add_argument("path", type=Path)
    review.add_argument("action", choices=["accept", "edit", "reject", "reopen"])
    review.add_argument("--reviewer", required=True)
    review.add_argument("--value", type=_json_value)
    review.add_argument("--note")
    review.set_defaults(func=command_review)

    apply_parser = subparsers.add_parser("apply-proposal", help="apply a validated proposal to the knowledge base")
    apply_parser.add_argument("path", type=Path)
    apply_parser.add_argument("--knowledge-root", type=Path, default=Path("data/knowledge/entities"))
    apply_parser.set_defaults(func=command_apply)

    create_batch = subparsers.add_parser("create-review-batch", help="create a traceable batch of pending proposals")
    create_batch.add_argument("specification", type=Path, help="JSON file with id and proposal_ids")
    create_batch.add_argument("--queue-root", type=Path, default=Path("data/review/queue"))
    create_batch.add_argument("--output", type=Path, required=True)
    create_batch.set_defaults(func=command_create_batch)

    review_batch_parser = subparsers.add_parser("review-batch", help="accept or reject a pending review batch")
    review_batch_parser.add_argument("batch", type=Path)
    review_batch_parser.add_argument("action", choices=["accept", "reject"])
    review_batch_parser.add_argument("--reviewer", required=True)
    review_batch_parser.add_argument("--note")
    review_batch_parser.add_argument("--apply", action="store_true")
    review_batch_parser.add_argument("--queue-root", type=Path, default=Path("data/review/queue"))
    review_batch_parser.add_argument("--knowledge-root", type=Path, default=Path("data/knowledge/entities"))
    review_batch_parser.set_defaults(func=command_review_batch)

    migrate_project = subparsers.add_parser(
        "migrate-career-project",
        help="migrate a generic validated entity to the career-project schema",
    )
    migrate_project.add_argument("path", type=Path)
    migrate_project.add_argument("--person-id", required=True)
    migrate_project.add_argument("--criterion", type=Path)
    migrate_project.set_defaults(func=command_migrate_career_project)

    match = subparsers.add_parser("match-offer", help="score literal skill coverage")
    match.add_argument("offer", type=Path)
    match.add_argument("knowledge", type=Path)
    match.set_defaults(func=command_match)

    response_plan = subparsers.add_parser("plan-personal-response", help="create a traceable evidence plan for a personal response")
    response_plan.add_argument("offer", type=Path)
    response_plan.add_argument("--knowledge-root", type=Path, default=Path("data/knowledge/entities"))
    response_plan.add_argument("--output", type=Path, required=True)
    response_plan.set_defaults(func=command_plan_personal_response)

    select = subparsers.add_parser("select-template", help="rank templates for a context")
    select.add_argument("context", type=Path)
    select.add_argument("templates", type=Path, nargs="+")
    select.set_defaults(func=command_select_template)

    track = subparsers.add_parser("track-event", help="append an application event")
    track.add_argument("application", type=Path)
    track.add_argument("event_type")
    track.add_argument("--details", type=_json_value, default={})
    track.set_defaults(func=command_track)

    slurp = subparsers.add_parser("slurp-site", help="archive a bounded same-origin website")
    slurp.add_argument("url")
    slurp.add_argument("--output", type=Path, required=True)
    slurp.add_argument("--max-pages", type=int, default=50)
    slurp.add_argument("--delay", type=float, default=0.5)
    slurp.add_argument("--timeout", type=float, default=30)
    slurp.add_argument("--retries", type=int, default=1)
    slurp.add_argument("--no-resume", action="store_true")
    slurp.set_defaults(func=command_slurp)

    site = subparsers.add_parser("build-site", help="build the allowlisted static GitHub Pages site")
    site.add_argument("--root", type=Path, default=Path.cwd())
    site.add_argument("--output", type=Path, default=Path("_site"))
    site.add_argument("--config", type=Path)
    site.set_defaults(func=command_build_site)

    audit = subparsers.add_parser("site-audit", help="audit the allowlisted public projection")
    audit.add_argument("--root", type=Path, default=Path.cwd())
    audit.add_argument("--config", type=Path)
    audit.set_defaults(func=command_site_audit)

    model_check = subparsers.add_parser("model-check", help="validate the YAML mental model")
    model_check.add_argument("--manifest", type=Path, default=Path("model/model.yaml"))
    model_check.set_defaults(func=command_model_check)

    impact = subparsers.add_parser("model-impact", help="show relations affected by a concept refactor")
    impact.add_argument("concept")
    impact.add_argument("--manifest", type=Path, default=Path("model/model.yaml"))
    impact.set_defaults(func=command_model_impact)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
