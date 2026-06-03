from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
OUTPUT_PATH = RESULTS_DIR / "coding_session_snapshot.json"


def _run_git_command(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(BASE_DIR.resolve().parents[1]),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return (result.stdout or "").rstrip()


def _get_git_branch() -> str:
    branch = _run_git_command("branch", "--show-current")
    return branch or "unknown"


def _count_git_changes() -> tuple[int, int]:
    porcelain = _run_git_command("status", "--porcelain")
    modified_files = 0
    staged_files = 0

    for line in porcelain.splitlines():
        if len(line) < 2:
            continue

        index_status = line[0]
        worktree_status = line[1]

        if index_status not in {" ", "?"}:
            staged_files += 1

        if worktree_status not in {" ", "?"}:
            modified_files += 1

    return modified_files, staged_files


def _get_working_directory() -> str:
    return str(Path.cwd().resolve())


def _detect_virtual_environment() -> bool:
    if os.environ.get("VIRTUAL_ENV"):
        return True

    if getattr(sys, "prefix", None) != getattr(sys, "base_prefix", sys.prefix):
        return True

    return False


def build_snapshot() -> dict[str, object]:
    modified_files, staged_files = _count_git_changes()
    return {
        "git_branch": _get_git_branch(),
        "modified_files": modified_files,
        "staged_files": staged_files,
        "working_directory": _get_working_directory(),
        "venv_active": _detect_virtual_environment(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def write_snapshot(snapshot: dict[str, object]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")


def main() -> None:
    snapshot = build_snapshot()
    write_snapshot(snapshot)
    print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()