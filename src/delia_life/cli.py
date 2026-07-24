from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Protocol

from .core import load_json, sha256_file, write_json


class SubparserRegistry(Protocol):
    def add_parser(self, name: str, **kwargs: Any) -> argparse.ArgumentParser: ...


def _json_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def command_check(args: argparse.Namespace) -> int:
    from .project_validation import validate_project

    result = validate_project(args.root)
    _print(result)
    return 0 if result["ok"] else 1


def command_manifest(args: argparse.Namespace) -> int:
    from .ingestion import create_file_manifest

    manifest = create_file_manifest(args.path, args.kind, args.uri)
    if args.output:
        write_json(args.output, manifest)
    _print(manifest)
    return 0


def command_review(args: argparse.Namespace) -> int:
    from .ingestion import transition_proposal

    proposal = load_json(args.path)
    updated = transition_proposal(proposal, args.action, args.reviewer, args.value, args.note)
    write_json(args.path, updated)
    _print(updated)
    return 0


def command_apply(args: argparse.Namespace) -> int:
    from .ingestion import apply_proposal_file

    _, entity = apply_proposal_file(args.path, args.knowledge_root)
    _print(entity)
    return 0


def command_create_batch(args: argparse.Namespace) -> int:
    from .review_batch import create_review_batch

    batch = create_review_batch(load_json(args.specification), args.queue_root, args.output)
    _print(batch)
    return 0


def command_review_batch(args: argparse.Namespace) -> int:
    from .review_batch import review_batch

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
    from .ingestion import migrate_career_project_entity

    entity = load_json(args.path)
    criterion = load_json(args.criterion) if args.criterion else None
    migrated = migrate_career_project_entity(entity, args.person_id, criterion)
    write_json(args.path, migrated)
    _print(migrated)
    return 0


def command_match(args: argparse.Namespace) -> int:
    from .recommendation import match_offer

    _print(match_offer(load_json(args.offer), load_json(args.knowledge)))
    return 0


def command_rank_offers(args: argparse.Namespace) -> int:
    from .offer_search import (
        collect_validated_absent_certifications,
        collect_validated_absent_sector_experience_ids,
        collect_validated_knowledge_evidence_catalog,
        collect_validated_knowledge_tokens,
        collect_validated_profile_completeness,
        collect_validated_sector_experience_months,
        load_offer_files,
        rank_offers,
        semantic_profile_sha256,
    )

    offers = [offer for path in args.offers for offer in load_offer_files(path)]
    scan_manifest = load_json(args.scan_manifest) if args.scan_manifest is not None and args.scan_manifest.is_file() else None
    scan_requirements = scan_manifest.get("requirements") if isinstance(scan_manifest, dict) else None
    collection = scan_manifest.get("collection") if isinstance(scan_manifest, dict) else None
    collection = collection if isinstance(collection, dict) else {}
    visited_sources = list(dict.fromkeys([*collection.get("visited_sources", []), *(args.visited_sources or [])]))
    covered_query_families = set(collection.get("covered_query_families", [])) | set(args.covered_query_families)
    covered_priority_sectors = set(collection.get("covered_priority_sectors", [])) | set(args.covered_priority_sectors)
    covered_sector_functional_pairs = set(
        collection.get("covered_sector_functional_pairs", [])
    )
    result = rank_offers(
        offers,
        load_json(args.career_project),
        load_json(args.policy),
        collect_validated_knowledge_tokens(args.knowledge_root),
        visited_sources=visited_sources,
        complete_profile_dimensions=collect_validated_profile_completeness(args.knowledge_root),
        sector_experience_months=collect_validated_sector_experience_months(args.knowledge_root),
        absent_sector_experience_ids=collect_validated_absent_sector_experience_ids(args.knowledge_root),
        absent_certifications=collect_validated_absent_certifications(args.knowledge_root),
        knowledge_evidence_catalog=collect_validated_knowledge_evidence_catalog(args.knowledge_root),
        semantic_profile_fingerprint=semantic_profile_sha256(args.knowledge_root),
        scan_requirements=scan_requirements,
        covered_query_families=covered_query_families,
        covered_priority_sectors=covered_priority_sectors,
        covered_sector_functional_pairs=covered_sector_functional_pairs,
        manual_source_receipts=scan_manifest.get("manual_source_receipts", [])
        if isinstance(scan_manifest, dict)
        else [],
        require_scan_coverage=args.require_complete_pool,
    )
    if args.output:
        write_json(args.output, result)
    if isinstance(scan_manifest, dict) and args.scan_manifest is not None:
        semantic_pending = int(result.get("semantic_review", {}).get("pending_count", 0))
        status = (
            "semantic-review-required"
            if semantic_pending
            else "complete" if result["finalization_allowed"] else "incomplete"
        )
        write_json(
            args.scan_manifest,
            {
                **scan_manifest,
                "status": status,
                "report_summary": {
                    "candidate_count": result["candidate_count"],
                    "unique_count": result["unique_count"],
                    "active_count": result["active_count"],
                    "eligible_count": result["eligible_count"],
                    "excluded_count": result["excluded_count"],
                    "selected_count": result["selected_count"],
                    "presentation_count": result["presentation_count"],
                    "quasi_duplicate_group_count": result["quasi_duplicate_group_count"],
                    "quasi_duplicate_offer_count": result["quasi_duplicate_offer_count"],
                    "pool_complete": result["pool_complete"],
                    "finalization_allowed": result["finalization_allowed"],
                    "semantic_review_pending_count": semantic_pending,
                },
            },
        )
    _print(result)
    return 3 if args.require_complete_pool and not result["finalization_allowed"] else 0


def command_offer_scan(args: argparse.Namespace) -> int:
    from .offer_scan import prepare_offer_scan

    result = prepare_offer_scan(
        args.action,
        runtime_root=args.runtime_root,
        offers_root=args.offers_root,
        reports_root=args.reports_root,
        policy_path=args.policy,
        source_audit_path=args.source_audit,
    )
    _print(result)
    return 0


def command_record_offer_source_receipts(args: argparse.Namespace) -> int:
    from .offer_scan import record_manual_source_receipts

    result = record_manual_source_receipts(args.scan_manifest, args.receipt_batch)
    _print(result)
    return 0


def command_collect_offers(args: argparse.Namespace) -> int:
    from .offer_collection import collect_offers

    result = collect_offers(
        args.scan_manifest,
        policy_path=args.policy,
        source_audit_path=args.source_audit,
        archive_root=args.archive_root,
    )
    _print(result)
    return 0 if result["complete"] else 3


def command_run_offer_scan(args: argparse.Namespace) -> int:
    from .offer_scan import run_offer_scan

    result = run_offer_scan(
        args.action,
        runtime_root=args.runtime_root,
        offers_root=args.offers_root,
        reports_root=args.reports_root,
        semantic_cache_root=args.semantic_cache_root,
        policy_path=args.policy,
        source_audit_path=args.source_audit,
        archive_root=args.archive_root,
        career_project_path=args.career_project,
        knowledge_root=args.knowledge_root,
    )
    _print(result)
    return 0 if result["status"] == "complete" else 3


def command_prepare_offer_feedback_email(args: argparse.Namespace) -> int:
    from .offer_feedback_email import prepare_offer_feedback_email

    result = prepare_offer_feedback_email(
        load_json(args.report),
        args.recipient,
        args.site_url,
        args.cv_pdf,
        args.output,
        args.offer_ids,
        bcc=args.bcc,
    )
    _print(result)
    return 0


def command_apply_offer_semantic_reviews(args: argparse.Namespace) -> int:
    from .offer_review import apply_offer_semantic_reviews

    _print(
        apply_offer_semantic_reviews(
            args.offers_directory,
            args.review_batch,
            args.knowledge_root,
            args.policy,
            args.cache_root,
        )
    )
    return 0


def command_plan_personal_response(args: argparse.Namespace) -> int:
    from .application_plan import write_personal_response_plan

    plan = write_personal_response_plan(load_json(args.offer), args.knowledge_root, args.output)
    _print(plan)
    return 0


def command_select_template(args: argparse.Namespace) -> int:
    from .recommendation import rank_templates

    templates = [load_json(path) for path in args.templates]
    _print(rank_templates(templates, load_json(args.context)))
    return 0


def command_track(args: argparse.Namespace) -> int:
    from .tracking import append_event

    application = load_json(args.application)
    updated = append_event(application, args.event_type, dict(args.details))
    write_json(args.application, updated)
    _print(updated)
    return 0


def command_crawl(args: argparse.Namespace) -> int:
    from .website import crawl_site

    manifest = crawl_site(
        args.url,
        args.output,
        args.max_pages,
        args.delay,
        timeout_seconds=args.timeout,
        retries=args.retries,
        resume=not args.no_resume,
        max_response_bytes=args.max_bytes,
        allow_private_networks=args.allow_private_networks,
    )
    _print({"id": manifest["id"], "records": len(manifest["records"]), "truncated": manifest["truncated"]})
    return 0


def command_build_site(args: argparse.Namespace) -> int:
    from .site_builder import build_site

    _print(build_site(args.root, args.output, args.config))
    return 0


def command_build_documents(args: argparse.Namespace) -> int:
    from .document_builder import build_documents

    _print(build_documents(args.root, args.output_dir, args.public_dir))
    return 0


def command_check_documents(args: argparse.Namespace) -> int:
    from .document_builder import check_documents

    result = check_documents(args.root, args.public_dir)
    _print(result)
    return 0 if result["ok"] else 1


def command_site_audit(args: argparse.Namespace) -> int:
    from .site_audit import audit_site

    result = audit_site(args.root, args.config)
    _print(result)
    return 0 if result["ok"] else 1


def command_model_check(args: argparse.Namespace) -> int:
    from .mental_model import load_mental_model, model_summary

    summary = model_summary(load_mental_model(args.manifest))
    _print(summary)
    return 0 if summary["ok"] else 1


def command_model_impact(args: argparse.Namespace) -> int:
    from .mental_model import load_mental_model, model_impact, model_summary

    model = load_mental_model(args.manifest)
    summary = model_summary(model)
    if not summary["ok"]:
        raise ValueError("Mental model is invalid; run model-check")
    _print(model_impact(model, args.concept))
    return 0


def _add_project_commands(subparsers: SubparserRegistry) -> None:
    check = subparsers.add_parser("check", help="validate project data")
    check.add_argument("--root", type=Path, default=Path.cwd())
    check.set_defaults(func=command_check)

    hash_parser = subparsers.add_parser("hash", help="calculate a SHA-256 digest")
    hash_parser.add_argument("path", type=Path)
    hash_parser.set_defaults(func=lambda args: print(sha256_file(args.path)) or 0)


def _add_ingestion_commands(subparsers: SubparserRegistry) -> None:
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


def _add_offer_commands(subparsers: SubparserRegistry) -> None:
    from .offer_feedback_email import DEFAULT_FEEDBACK_BCC

    match = subparsers.add_parser("match-offer", help="score literal skill coverage")
    match.add_argument("offer", type=Path)
    match.add_argument("knowledge", type=Path)
    match.set_defaults(func=command_match)

    offer_scan = subparsers.add_parser(
        "offer-scan",
        help="prepare an isolated full scan, cumulative delta scan, cache cleanup or send workflow",
    )
    offer_scan.add_argument("action", choices=["clean-cache", "full", "delta", "send"])
    offer_scan.add_argument("--runtime-root", type=Path, default=Path(".runtime/offer-search"))
    offer_scan.add_argument("--offers-root", type=Path, default=Path("data/offers"))
    offer_scan.add_argument("--reports-root", type=Path, default=Path("generated/offer-search"))
    offer_scan.add_argument("--policy", type=Path, default=Path("config/offer-search.json"))
    offer_scan.add_argument("--source-audit", type=Path)
    offer_scan.set_defaults(func=command_offer_scan)

    source_receipts = subparsers.add_parser(
        "record-offer-source-receipts",
        help="record traceable manual source controls for the current offer scan",
    )
    source_receipts.add_argument("receipt_batch", type=Path)
    source_receipts.add_argument(
        "--scan-manifest",
        type=Path,
        default=Path(".runtime/offer-search/current.json"),
    )
    source_receipts.set_defaults(func=command_record_offer_source_receipts)

    collect = subparsers.add_parser(
        "collect-offers",
        help="collect current offers from every source required by a prepared scan manifest",
    )
    collect.add_argument("--scan-manifest", type=Path, default=Path(".runtime/offer-search/current.json"))
    collect.add_argument("--policy", type=Path, default=Path("config/offer-search.json"))
    collect.add_argument("--source-audit", type=Path)
    collect.add_argument("--archive-root", type=Path, default=Path("private/offer-scan-archives"))
    collect.set_defaults(func=command_collect_offers)

    run_scan = subparsers.add_parser(
        "run-offer-scan",
        help="prepare, collect and strictly rank a full or delta offer scan",
    )
    run_scan.add_argument("action", choices=["full", "delta"])
    run_scan.add_argument("--runtime-root", type=Path, default=Path(".runtime/offer-search"))
    run_scan.add_argument("--offers-root", type=Path, default=Path("data/offers"))
    run_scan.add_argument("--reports-root", type=Path, default=Path("generated/offer-search"))
    run_scan.add_argument(
        "--semantic-cache-root",
        type=Path,
        default=Path("generated/offer-semantic-cache"),
    )
    run_scan.add_argument("--policy", type=Path, default=Path("config/offer-search.json"))
    run_scan.add_argument("--source-audit", type=Path)
    run_scan.add_argument("--archive-root", type=Path, default=Path("private/offer-scan-archives"))
    run_scan.add_argument(
        "--career-project",
        type=Path,
        default=Path("private/career-project/delia-next-role-2026.json"),
    )
    run_scan.add_argument("--knowledge-root", type=Path, default=Path("data/knowledge"))
    run_scan.set_defaults(func=command_run_offer_scan)

    rank = subparsers.add_parser("rank-offers", help="rank a collected offer pool against Delia's validated career project")
    rank.add_argument("offers", type=Path, nargs="+", help="one or more job-offer JSON files or directories")
    rank.add_argument("--career-project", type=Path, default=Path("private/career-project/delia-next-role-2026.json"))
    rank.add_argument("--policy", type=Path, default=Path("config/offer-search.json"))
    rank.add_argument("--knowledge-root", type=Path, default=Path("data/knowledge"))
    rank.add_argument("--scan-manifest", type=Path)
    rank.add_argument("--covered-query-family", dest="covered_query_families", action="append", default=[])
    rank.add_argument("--covered-priority-sector", dest="covered_priority_sectors", action="append", default=[])
    rank.add_argument(
        "--require-complete-pool",
        action="store_true",
        help="return exit code 3 when the scan manifest coverage is incomplete",
    )
    rank.add_argument(
        "--visited-source",
        dest="visited_sources",
        action="append",
        help="HTTP(S) site consulted during the search; repeat for every visited site",
    )
    rank.add_argument("--output", type=Path)
    rank.set_defaults(func=command_rank_offers)

    semantic_review = subparsers.add_parser(
        "apply-offer-semantic-reviews",
        help="apply a traceable LLM semantic review batch to collected offers",
    )
    semantic_review.add_argument("offers_directory", type=Path)
    semantic_review.add_argument("review_batch", type=Path)
    semantic_review.add_argument("--knowledge-root", type=Path, default=Path("data/knowledge"))
    semantic_review.add_argument("--policy", type=Path, default=Path("config/offer-search.json"))
    semantic_review.add_argument(
        "--cache-root",
        type=Path,
        default=Path("generated/offer-semantic-cache"),
    )
    semantic_review.set_defaults(func=command_apply_offer_semantic_reviews)

    feedback_email = subparsers.add_parser(
        "prepare-offer-feedback-email",
        help="prepare a non-sending email draft for an offer selection",
    )
    feedback_email.add_argument("report", type=Path, help="rank-offers JSON report")
    feedback_email.add_argument("--recipient", required=True)
    feedback_email.add_argument("--bcc", default=DEFAULT_FEEDBACK_BCC)
    feedback_email.add_argument("--site-url", required=True)
    feedback_email.add_argument("--cv-pdf", type=Path, default=Path("site/assets/downloads/cv-delia-rossignol-signature.pdf"))
    feedback_email.add_argument("--output", type=Path, required=True)
    feedback_email.add_argument("--offer-id", dest="offer_ids", action="append")
    feedback_email.set_defaults(func=command_prepare_offer_feedback_email)

    response_plan = subparsers.add_parser("plan-personal-response", help="create a traceable evidence plan for a personal response")
    response_plan.add_argument("offer", type=Path)
    response_plan.add_argument("--knowledge-root", type=Path, default=Path("data/knowledge/entities"))
    response_plan.add_argument("--output", type=Path, required=True)
    response_plan.set_defaults(func=command_plan_personal_response)


def _add_application_commands(subparsers: SubparserRegistry) -> None:
    select = subparsers.add_parser("select-template", help="rank templates for a context")
    select.add_argument("context", type=Path)
    select.add_argument("templates", type=Path, nargs="+")
    select.set_defaults(func=command_select_template)

    track = subparsers.add_parser("track-event", help="append an application event")
    track.add_argument("application", type=Path)
    track.add_argument("event_type")
    track.add_argument("--details", type=_json_value, default={})
    track.set_defaults(func=command_track)


def _add_publication_commands(subparsers: SubparserRegistry) -> None:
    crawl = subparsers.add_parser("crawl-site", help="archive a bounded same-origin website")
    crawl.add_argument("url")
    crawl.add_argument("--output", type=Path, required=True)
    crawl.add_argument("--max-pages", type=int, default=50)
    crawl.add_argument("--delay", type=float, default=0.5)
    crawl.add_argument("--timeout", type=float, default=30)
    crawl.add_argument("--retries", type=int, default=1)
    crawl.add_argument("--max-bytes", type=int, default=20 * 1024 * 1024)
    crawl.add_argument("--allow-private-networks", action="store_true")
    crawl.add_argument("--no-resume", action="store_true")
    crawl.set_defaults(func=command_crawl)

    site = subparsers.add_parser("build-site", help="build the allowlisted static GitHub Pages site")
    site.add_argument("--root", type=Path, default=Path.cwd())
    site.add_argument("--output", type=Path, default=Path("_site"))
    site.add_argument("--config", type=Path)
    site.set_defaults(func=command_build_site)

    documents = subparsers.add_parser("build-documents", help="build deterministic public application documents")
    documents.add_argument("--root", type=Path, default=Path.cwd())
    documents.add_argument("--output-dir", type=Path)
    documents.add_argument("--public-dir", type=Path)
    documents.set_defaults(func=command_build_documents)

    document_check = subparsers.add_parser(
        "check-documents",
        help="verify document reproducibility, content and published freshness",
    )
    document_check.add_argument("--root", type=Path, default=Path.cwd())
    document_check.add_argument("--public-dir", type=Path)
    document_check.set_defaults(func=command_check_documents)

    audit = subparsers.add_parser("site-audit", help="audit the allowlisted public projection")
    audit.add_argument("--root", type=Path, default=Path.cwd())
    audit.add_argument("--config", type=Path)
    audit.set_defaults(func=command_site_audit)


def _add_model_commands(subparsers: SubparserRegistry) -> None:
    model_check = subparsers.add_parser("model-check", help="validate the YAML mental model")
    model_check.add_argument("--manifest", type=Path, default=Path("model/model.yaml"))
    model_check.set_defaults(func=command_model_check)

    impact = subparsers.add_parser("model-impact", help="show relations affected by a concept refactor")
    impact.add_argument("concept")
    impact.add_argument("--manifest", type=Path, default=Path("model/model.yaml"))
    impact.set_defaults(func=command_model_impact)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="delia-life", description="Deterministic Delia career tooling")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_project_commands(subparsers)
    _add_ingestion_commands(subparsers)
    _add_offer_commands(subparsers)
    _add_application_commands(subparsers)
    _add_publication_commands(subparsers)
    _add_model_commands(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
