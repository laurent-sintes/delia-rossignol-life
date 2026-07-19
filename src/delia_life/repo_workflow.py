from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path
from typing import Any

from .core import load_json, utc_now, write_json
from .document_builder import build_documents, check_documents
from .site_audit import audit_site
from .site_builder import build_site


def _run_git(root: Path, *arguments: str, required: bool = True) -> str | None:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        if required:
            message = result.stderr.strip() or result.stdout.strip() or f"git {' '.join(arguments)} failed"
            raise ValueError(message)
        return None
    return result.stdout.strip()


def _normalized_remote(url: str) -> str:
    value = url.strip().removesuffix(".git").removesuffix("/")
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value.removeprefix("git@github.com:")
    return value.casefold()


def git_snapshot(root: Path, expected_remote: str | None = None, publish_branch: str | None = None) -> dict[str, Any]:
    branch = _run_git(root, "branch", "--show-current") or ""
    remote = _run_git(root, "remote", "get-url", "origin", required=False)
    porcelain = _run_git(root, "status", "--porcelain=v1") or ""
    has_head = _run_git(root, "rev-parse", "--verify", "HEAD", required=False) is not None
    upstream = _run_git(root, "rev-parse", "--abbrev-ref", "@{upstream}", required=False) if has_head else None
    ahead = behind = None
    if upstream:
        counts = _run_git(root, "rev-list", "--left-right", "--count", "@{upstream}...HEAD")
        if counts:
            behind_text, ahead_text = counts.split()
            ahead, behind = int(ahead_text), int(behind_text)
    remote_matches = None
    if expected_remote:
        remote_matches = remote is not None and _normalized_remote(remote) == _normalized_remote(expected_remote)
    return {
        "branch": branch,
        "publish_branch": publish_branch,
        "on_publish_branch": publish_branch is None or branch == publish_branch,
        "origin": remote,
        "expected_remote": expected_remote,
        "origin_matches": remote_matches,
        "has_commits": has_head,
        "is_clean": not porcelain,
        "changes": porcelain.splitlines(),
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
    }


def assert_publish_ready(snapshot: dict[str, Any]) -> None:
    errors: list[str] = []
    if not snapshot["has_commits"]:
        errors.append("repository has no commit")
    if not snapshot["is_clean"]:
        errors.append("working tree is not clean")
    if not snapshot["origin"]:
        errors.append("origin remote is missing")
    elif snapshot["origin_matches"] is False:
        errors.append("origin does not match configured expected_remote")
    if not snapshot["on_publish_branch"]:
        errors.append(f"current branch is not {snapshot['publish_branch']}")
    if snapshot["behind"] not in {None, 0}:
        errors.append("local branch is behind its upstream")
    if errors:
        raise ValueError("; ".join(errors))


def _runtime_paths(root: Path) -> tuple[Path, Path]:
    runtime = root / ".runtime"
    runtime.mkdir(exist_ok=True)
    return runtime / "preview.json", runtime / "preview.log"


def _preview_responds(host: str, port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/.delia-site-output", timeout=1) as response:
            return response.status == 200 and response.read(32).startswith(b"generated")
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return False


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.3)
        return connection.connect_ex((host, port)) != 0


def preview_status(root: Path) -> dict[str, Any]:
    state_path, _ = _runtime_paths(root)
    if not state_path.exists():
        return {"running": False}
    state = load_json(state_path)
    state["running"] = _preview_responds(state["host"], int(state["port"]))
    return state


def start_preview(root: Path, site_dir: Path, host: str, port: int) -> dict[str, Any]:
    current = preview_status(root)
    if current.get("running"):
        if current.get("host") == host and int(current.get("port", 0)) == port:
            current["reused"] = True
            return current
        raise ValueError(f"A preview is already running at {current.get('url')}")
    if not _port_is_free(host, port):
        raise ValueError(f"Port {host}:{port} is already in use")
    if not (site_dir / "index.html").is_file():
        raise ValueError(f"Site has not been built: {site_dir}")

    state_path, log_path = _runtime_paths(root)
    command = [sys.executable, "-m", "http.server", str(port), "--bind", host, "--directory", str(site_dir)]
    options: dict[str, Any] = {
        "cwd": root,
        "stdin": subprocess.DEVNULL,
    }
    log = log_path.open("a", encoding="utf-8")
    options["stdout"] = log
    options["stderr"] = subprocess.STDOUT
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        options["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **options)
    finally:
        log.close()

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ValueError(f"Preview server exited early; see {log_path}")
        if _preview_responds(host, port):
            break
        time.sleep(0.1)
    else:
        process.terminate()
        raise ValueError(f"Preview server did not start; see {log_path}")

    state = {
        "running": True,
        "reused": False,
        "pid": process.pid,
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}/",
        "site_dir": str(site_dir.resolve()),
        "started_at": utc_now(),
    }
    write_json(state_path, state)
    return state


def stop_preview(root: Path) -> dict[str, Any]:
    state_path, _ = _runtime_paths(root)
    state = preview_status(root)
    if not state_path.exists():
        return {"stopped": False, "reason": "no preview state"}
    pid = int(state.get("pid", 0))
    if state.get("running") and pid > 0:
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and _preview_responds(state["host"], int(state["port"])):
            time.sleep(0.1)
    state_path.unlink(missing_ok=True)
    return {"stopped": True, "pid": pid, "url": state.get("url")}


def _run_quality_gate(root: Path, command: list[str], failure_message: str) -> None:
    result = subprocess.run(command, cwd=root, check=False)
    if result.returncode != 0:
        raise ValueError(failure_message)


def review_content(root: Path, output: Path, host: str, port: int) -> dict[str, Any]:
    documents = build_documents(root)
    _run_quality_gate(
        root,
        [sys.executable, "-m", "ruff", "check", "src", "scripts", "tests"],
        "lint failed",
    )
    _run_quality_gate(root, [sys.executable, "-m", "mypy"], "static typing failed")
    _run_quality_gate(
        root,
        [sys.executable, "-m", "coverage", "run", "-m", "unittest", "discover", "-s", "tests", "-v"],
        "tests failed",
    )
    _run_quality_gate(
        root,
        [sys.executable, "-m", "coverage", "report"],
        "coverage threshold failed",
    )
    _run_quality_gate(
        root,
        [sys.executable, str(root / "scripts" / "delia_life.py"), "check"],
        "project validation failed",
    )
    document_check = check_documents(root)
    if not document_check["ok"]:
        raise ValueError("document validation failed: " + "; ".join(document_check["errors"]))
    audit = audit_site(root)
    if not audit["ok"]:
        raise ValueError("site audit failed")
    build = build_site(root, output)
    preview = start_preview(root, output.resolve(), host, port)
    config = load_repository_config(root)
    snapshot = git_snapshot(root, config["expected_remote"], config["publish_branch"])
    return {
        "lint": "passed",
        "typing": "passed",
        "tests": "passed",
        "coverage": "passed",
        "validation": "passed",
        "documents": documents,
        "document_check": document_check,
        "audit": audit,
        "build": build,
        "preview": preview,
        "git": snapshot,
    }


def prepare_commit(root: Path, output: Path, host: str, port: int) -> dict[str, Any]:
    """Backward-compatible name for the reviewed content workflow."""
    return review_content(root, output, host, port)


def load_repository_config(root: Path) -> dict[str, Any]:
    return load_json(root / "config" / "repository.json")
