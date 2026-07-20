from __future__ import annotations

import json
import os
import shutil
import stat
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any

from .core import replace_file
from .errors import TransactionError


def _clear_readonly_and_retry(
    function: Callable[[str], object],
    path: str,
    error_info: tuple[type[BaseException], BaseException, TracebackType | None],
) -> None:
    """Make a blocked entry and its parent removable before retrying."""
    error = error_info[1]
    if not isinstance(error, PermissionError):
        raise error
    blocked = Path(path)
    parent = blocked.parent
    parent.chmod(parent.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR)
    blocked.chmod(blocked.stat().st_mode | stat.S_IWUSR)
    function(path)


def remove_tree(path: Path, attempts: int = 20, delay_seconds: float = 0.05, ignore_errors: bool = False) -> None:
    """Remove a generated tree while tolerating short-lived Windows/OneDrive locks."""
    last_error: OSError | None = None
    effective_attempts = 1 if ignore_errors else max(1, attempts)
    for attempt in range(effective_attempts):
        if not path.exists():
            return
        try:
            shutil.rmtree(path, onerror=_clear_readonly_and_retry)
            return
        except OSError as error:
            last_error = error
            if attempt + 1 < effective_attempts:
                time.sleep(delay_seconds)
    if not ignore_errors and last_error is not None:
        raise last_error


@contextmanager
def exclusive_directory_lock(path: Path, timeout_seconds: float = 10.0) -> Iterator[None]:
    """Acquire a portable inter-process lock using atomic directory creation."""
    deadline = time.monotonic() + timeout_seconds
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            path.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TransactionError(f"Timed out waiting for transaction lock: {path}") from None
            time.sleep(0.05)
    try:
        (path / "owner.json").write_text(
            json.dumps({"pid": os.getpid(), "acquired_at": time.time()}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        yield
    finally:
        remove_tree(path, ignore_errors=True)


def _serialized_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def atomic_write_bytes_group(changes: Mapping[Path, bytes]) -> None:
    """Commit a prepared set of binary/text files with process-level rollback."""
    if not changes:
        return
    transaction_id = uuid.uuid4().hex
    staged: dict[Path, Path] = {}
    backups: dict[Path, bytes | None] = {}
    replaced: list[Path] = []
    try:
        for path, content in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            backups[path] = path.read_bytes() if path.exists() else None
            temporary = path.with_name(f".{path.name}.{transaction_id}.tmp")
            with temporary.open("wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            staged[path] = temporary
        for path, temporary in staged.items():
            replace_file(temporary, path)
            replaced.append(path)
    except Exception as error:
        rollback_errors: list[str] = []
        for path in reversed(replaced):
            try:
                previous = backups[path]
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    recovery = path.with_name(f".{path.name}.{transaction_id}.rollback.tmp")
                    recovery.write_bytes(previous)
                    replace_file(recovery, path)
            except OSError as rollback_error:
                rollback_errors.append(f"{path}: {rollback_error}")
        detail = f"; rollback errors: {'; '.join(rollback_errors)}" if rollback_errors else ""
        raise TransactionError(f"File transaction failed: {error}{detail}") from error
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def atomic_write_json_group(changes: Mapping[Path, Any]) -> None:
    """Commit a prepared group of JSON files and roll back process-level failures.

    Callers must hold an appropriate inter-process lock for the complete read,
    validation and commit sequence.
    """
    if not changes:
        return
    transaction_id = uuid.uuid4().hex
    staged: dict[Path, Path] = {}
    backups: dict[Path, bytes | None] = {}
    replaced: list[Path] = []
    try:
        for path, value in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            backups[path] = path.read_bytes() if path.exists() else None
            temporary = path.with_name(f".{path.name}.{transaction_id}.tmp")
            with temporary.open("wb") as handle:
                handle.write(_serialized_json(value))
                handle.flush()
                os.fsync(handle.fileno())
            staged[path] = temporary
        for path, temporary in staged.items():
            replace_file(temporary, path)
            replaced.append(path)
    except Exception as error:
        rollback_errors: list[str] = []
        for path in reversed(replaced):
            try:
                previous = backups[path]
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    recovery = path.with_name(f".{path.name}.{transaction_id}.rollback.tmp")
                    recovery.write_bytes(previous)
                    replace_file(recovery, path)
            except OSError as rollback_error:
                rollback_errors.append(f"{path}: {rollback_error}")
        detail = f"; rollback errors: {'; '.join(rollback_errors)}" if rollback_errors else ""
        raise TransactionError(f"JSON transaction failed: {error}{detail}") from error
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
