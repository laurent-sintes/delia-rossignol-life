from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.document_builder import build_documents  # noqa: E402
from delia_life.repo_workflow import (  # noqa: E402
    assert_publish_ready,
    git_snapshot,
    load_repository_config,
    prepare_commit,
    preview_status,
    review_content,
    review_operational,
    start_preview,
    stop_preview,
)
from delia_life.site_builder import build_site  # noqa: E402


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> int:
    config = load_repository_config(ROOT)
    parser = argparse.ArgumentParser(description="Deterministic commit and publish preflight")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare-commit", help="test, validate, build and start the preview")
    prepare.add_argument("--output", type=Path, default=ROOT / "_site")
    prepare.add_argument("--host", default=config["preview_host"])
    prepare.add_argument("--port", type=int, default=config["preview_port"])

    review = commands.add_parser("review-content", help="test, validate, build and deploy a local preview")
    review.add_argument("--output", type=Path, default=ROOT / "_site")
    review.add_argument("--host", default=config["preview_host"])
    review.add_argument("--port", type=int, default=config["preview_port"])

    commands.add_parser("review-operational", help="test and validate code or operational data without rebuilding documents")

    start = commands.add_parser("preview-start", help="build and start the preview")
    start.add_argument("--output", type=Path, default=ROOT / "_site")
    start.add_argument("--host", default=config["preview_host"])
    start.add_argument("--port", type=int, default=config["preview_port"])

    commands.add_parser("preview-status", help="show preview status")
    commands.add_parser("preview-stop", help="stop the managed preview")
    commands.add_parser("publish-check", help="verify that the repository can be pushed safely")
    args = parser.parse_args()

    try:
        if args.command == "prepare-commit":
            emit(prepare_commit(ROOT, args.output, args.host, args.port))
        elif args.command == "review-content":
            emit(review_content(ROOT, args.output, args.host, args.port))
        elif args.command == "review-operational":
            emit(review_operational(ROOT))
        elif args.command == "preview-start":
            build_documents(ROOT)
            build_site(ROOT, args.output)
            emit(start_preview(ROOT, args.output.resolve(), args.host, args.port))
        elif args.command == "preview-status":
            emit(preview_status(ROOT))
        elif args.command == "preview-stop":
            emit(stop_preview(ROOT))
        elif args.command == "publish-check":
            snapshot = git_snapshot(ROOT, config["expected_remote"], config["publish_branch"])
            assert_publish_ready(snapshot)
            emit(snapshot)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


raise SystemExit(main())
