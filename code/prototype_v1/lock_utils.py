from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Iterable, Literal


def process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_lock_pid(lock_path: Path) -> int | None:
    if not lock_path.exists() or not lock_path.is_file():
        return None

    try:
        raw = lock_path.read_text(encoding="utf-8").strip().splitlines()[0]
        return int(raw)
    except (OSError, ValueError, IndexError):
        return None


@dataclass(frozen=True)
class LockAcquireResult:
    status: Literal["acquired", "duplicate_running", "stale_clear_failed"]
    existing_pid: int | None = None
    stale_clear_error: OSError | None = None


def acquire_single_instance_lock_core(
    lock_path: Path,
    *,
    owner_pid: int,
    metadata_lines: Iterable[str],
) -> LockAcquireResult:
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            existing_pid = read_lock_pid(lock_path)
            if existing_pid is not None and process_is_running(existing_pid):
                return LockAcquireResult(status="duplicate_running", existing_pid=existing_pid)

            try:
                lock_path.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                return LockAcquireResult(
                    status="stale_clear_failed",
                    existing_pid=existing_pid,
                    stale_clear_error=exc,
                )
            continue

        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for line in metadata_lines:
                handle.write(f"{line}\n")
        return LockAcquireResult(status="acquired")


def release_single_instance_lock_if_owned(lock_path: Path, *, owner_pid: int) -> None:
    current_pid = read_lock_pid(lock_path)
    if current_pid != owner_pid:
        return

    try:
        lock_path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return
