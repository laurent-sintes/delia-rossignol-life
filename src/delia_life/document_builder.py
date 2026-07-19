from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .core import load_json, sha256_file
from .cv_composer import compose_standard_cv
from .pdf_renderer import PAGE_HEIGHT, PAGE_WIDTH, render_standard_cv

STANDARD_CV_FILENAME = "cv-delia-rossignol-signature.pdf"
TEMPLATE_PATH = Path("templates/cv/signature-editorial/template.json")
STRATEGY_PATH = Path("data/style/cv-standard.json")


def _inputs(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    return load_json(root / TEMPLATE_PATH), load_json(root / STRATEGY_PATH)


def build_standard_cv(root: Path, output: Path) -> dict[str, Any]:
    root = root.resolve()
    output = output if output.is_absolute() else root / output
    template, strategy = _inputs(root)
    view = compose_standard_cv(root, template, strategy)
    layout = render_standard_cv(view, output)
    return {
        "id": "standard-cv-signature-editorial",
        "output": str(output.resolve()),
        "pages": int(template["rendering"]["preferred_pages"]),
        "sha256": sha256_file(output),
        "template": view.template_id,
        "template_version": view.template_version,
        "content_strategy": view.strategy_id,
        "source_ids": list(view.source_ids),
        "layout": layout,
    }


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def build_documents(
    root: Path,
    output_dir: Path | None = None,
    public_dir: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = output_dir or root / "output" / "pdf"
    public_dir = public_dir or root / "site" / "assets" / "downloads"
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    if not public_dir.is_absolute():
        public_dir = root / public_dir
    output = output_dir / STANDARD_CV_FILENAME
    public_asset = public_dir / STANDARD_CV_FILENAME
    result = build_standard_cv(root, output)
    _atomic_copy(output, public_asset)
    result["public_output"] = str(public_asset.resolve())
    return {"documents": [result], "ok": True}


def check_documents(root: Path, public_dir: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    public_dir = public_dir or root / "site" / "assets" / "downloads"
    if not public_dir.is_absolute():
        public_dir = root / public_dir
    published = public_dir / STANDARD_CV_FILENAME
    template, strategy = _inputs(root)
    view = compose_standard_cv(root, template, strategy)
    errors: list[str] = []
    temporary = root / ".test-tmp" / f"document-check-{uuid.uuid4().hex}"
    temporary.mkdir(parents=True)
    first_result: dict[str, Any] = {}
    try:
        first = temporary / "first.pdf"
        second = temporary / "second.pdf"
        first_result = build_standard_cv(root, first)
        build_standard_cv(root, second)
        first_bytes = first.read_bytes()
        if first_bytes != second.read_bytes():
            errors.append("standard CV generation is not byte-for-byte reproducible")
        if not published.is_file():
            errors.append(f"published CV is missing: {published.relative_to(root)}")
        elif first_bytes != published.read_bytes():
            errors.append(f"published CV is stale: {published.relative_to(root)}")

        reader = PdfReader(str(first))
        maximum_pages = int(template["rendering"]["maximum_pages"])
        preferred_pages = int(template["rendering"]["preferred_pages"])
        if len(reader.pages) != preferred_pages:
            errors.append(f"standard CV must contain {preferred_pages} pages, found {len(reader.pages)}")
        if len(reader.pages) > maximum_pages:
            errors.append(f"standard CV exceeds maximum page count: {maximum_pages}")
        for index, page in enumerate(reader.pages, start=1):
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            if abs(width - PAGE_WIDTH) > 0.1 or abs(height - PAGE_HEIGHT) > 0.1:
                errors.append(f"page {index} is not A4: {width:.2f} x {height:.2f} points")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        for required in [view.email, view.phone, "construire ensemble une solution concrète"]:
            if required not in text:
                errors.append(f"standard CV is missing required text: {required}")
        for forbidden in ["41 ans", "2 enfants", "30 octobre 1978", "5, rue Jacques Offenbach"]:
            if forbidden.casefold() in text.casefold():
                errors.append(f"standard CV contains forbidden text: {forbidden}")
        if float(first_result.get("layout", {}).get("minimum_y", 0)) < 40:
            errors.append("standard CV content crosses the safe lower page boundary")
    finally:
        shutil.rmtree(temporary, ignore_errors=True)

    return {
        "documents": [first_result],
        "errors": errors,
        "ok": not errors,
        "published_output": str(published.resolve()),
    }
