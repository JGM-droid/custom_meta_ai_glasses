from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parents[1]
RESULTS_DIR = BASE_DIR / "results"
OUTPUT_PATH = RESULTS_DIR / "coding_context_pack.json"
LATEST_RESPONSE_PATH = RESULTS_DIR / "latest_response.json"
SESSION_MEMORY_PATH = RESULTS_DIR / "session_memory.json"


def _run_git(args: list[str]) -> tuple[bool, str]:
    command = ["git", "-C", str(REPO_ROOT), *args]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        return False, stderr or stdout or "git command failed"
    return True, (result.stdout or "").strip()


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _truncate(value: Any, max_len: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return text[:max_len]
    return text[: max_len - 1].rstrip() + "…"


def _get_branch() -> str:
    ok, out = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    return out if ok and out else "unknown"


def _parse_porcelain_line(line: str) -> tuple[str, str] | None:
    if len(line) < 4:
        return None
    status_code = line[:2]
    path_text = line[3:].strip()
    if " -> " in path_text:
        path_text = path_text.split(" -> ", 1)[1].strip()
    return status_code, path_text


def _get_git_status_summary() -> tuple[dict[str, Any], list[dict[str, str]]]:
    ok, out = _run_git(["status", "--porcelain"])
    if not ok:
        summary = {
            "is_git_repo": False,
            "is_clean": True,
            "staged_count": 0,
            "unstaged_count": 0,
            "untracked_count": 0,
            "note": out,
        }
        return summary, []

    lines = [line for line in out.splitlines() if line.strip()]
    staged = 0
    unstaged = 0
    untracked = 0
    changed_files: list[dict[str, str]] = []

    for line in lines:
        parsed = _parse_porcelain_line(line)
        if not parsed:
            continue
        code, path_text = parsed
        x = code[0]
        y = code[1]

        if code == "??":
            untracked += 1
            changed_files.append({"path": path_text, "state": "untracked"})
            continue

        if x != " ":
            staged += 1
        if y != " ":
            unstaged += 1

        state_parts = []
        if x != " ":
            state_parts.append("staged")
        if y != " ":
            state_parts.append("unstaged")
        state = "+".join(state_parts) if state_parts else "tracked"
        changed_files.append({"path": path_text, "state": state})

    summary = {
        "is_git_repo": True,
        "is_clean": len(lines) == 0,
        "staged_count": staged,
        "unstaged_count": unstaged,
        "untracked_count": untracked,
    }
    return summary, changed_files


def _build_latest_response_summary() -> dict[str, Any] | None:
    payload = _safe_load_json(LATEST_RESPONSE_PATH)
    if payload is None:
        return None

    display_priority = payload.get("display_priority", {}) if isinstance(payload.get("display_priority"), dict) else {}

    return {
        "timestamp": payload.get("timestamp", "Unknown"),
        "image_analyzed": payload.get("image_analyzed", "Unknown"),
        "task_continuity": payload.get("task_continuity", "Unknown"),
        "stuck": bool(payload.get("stuck_status", {}).get("is_stuck", False)) if isinstance(payload.get("stuck_status"), dict) else False,
        "priority_mode": display_priority.get("mode", "Unknown"),
        "priority_headline": _truncate(display_priority.get("headline", ""), 64),
        "priority_message": _truncate(display_priority.get("primary_message", ""), 120),
    }


def _build_session_memory_summary() -> dict[str, Any] | None:
    payload = _safe_load_json(SESSION_MEMORY_PATH)
    if payload is None:
        return None

    active_task = payload.get("active_task", {}) if isinstance(payload.get("active_task"), dict) else {}
    observations = payload.get("observations", []) if isinstance(payload.get("observations"), list) else []

    return {
        "active_task": {
            "current_task": active_task.get("current_task", "Unknown"),
            "last_completed_step": _truncate(active_task.get("last_completed_step", "Unknown"), 120),
            "next_recommended_step": _truncate(active_task.get("next_recommended_step", "Unknown"), 120),
        },
        "observation_count": len(observations),
    }


def _iter_context_files() -> list[Path]:
    files: list[Path] = []
    for path in BASE_DIR.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts:
            continue
        if "results" in path.parts:
            continue
        files.append(path)
    return files


def _to_repo_relative(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _build_vscode_context() -> dict[str, Any]:
    candidate_files = _iter_context_files()
    python_files = [path for path in candidate_files if path.suffix.lower() == ".py"]

    python_sorted = sorted(
        python_files,
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    modified_sorted = sorted(
        candidate_files,
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    current_file_path = python_sorted[0] if python_sorted else None
    current_directory = current_file_path.parent if current_file_path else BASE_DIR

    return {
        "current_file": _to_repo_relative(current_file_path) if current_file_path else "",
        "current_directory": _to_repo_relative(current_directory),
        "recent_python_files": [_to_repo_relative(path) for path in python_sorted[:5]],
        "recent_modified_files": [_to_repo_relative(path) for path in modified_sorted[:5]],
    }


def _build_context_pack() -> dict[str, Any]:
    branch = _get_branch()
    git_status_summary, changed_files = _get_git_status_summary()

    pack = {
        "branch": branch,
        "git_status_summary": git_status_summary,
        "changed_files": changed_files,
        "latest_response_summary": _build_latest_response_summary(),
        "session_memory_summary": _build_session_memory_summary(),
        "vscode_context": _build_vscode_context(),
    }
    return pack


def _print_summary(pack: dict[str, Any]) -> None:
    print("Coding Context Pack")
    print(f"Branch: {pack.get('branch', 'unknown')}")

    status = pack.get("git_status_summary", {}) if isinstance(pack.get("git_status_summary"), dict) else {}
    print(
        "Git status: "
        f"clean={status.get('is_clean', True)}; "
        f"staged={status.get('staged_count', 0)}; "
        f"unstaged={status.get('unstaged_count', 0)}; "
        f"untracked={status.get('untracked_count', 0)}"
    )

    changed_files = pack.get("changed_files", []) if isinstance(pack.get("changed_files"), list) else []
    if changed_files:
        print("Changed files:")
        for item in changed_files:
            if not isinstance(item, dict):
                continue
            print(f"- {item.get('path', 'unknown')} ({item.get('state', 'unknown')})")
    else:
        print("Changed files: none")

    latest = pack.get("latest_response_summary")
    if isinstance(latest, dict):
        print(
            "Latest response: "
            f"image={latest.get('image_analyzed', 'Unknown')}; "
            f"continuity={latest.get('task_continuity', 'Unknown')}; "
            f"mode={latest.get('priority_mode', 'Unknown')}; "
            f"stuck={latest.get('stuck', False)}"
        )
        message = latest.get("priority_message", "")
        if message:
            print(f"Priority message: {message}")
    else:
        print("Latest response: unavailable")

    memory = pack.get("session_memory_summary")
    if isinstance(memory, dict):
        active = memory.get("active_task", {}) if isinstance(memory.get("active_task"), dict) else {}
        print(
            "Active task: "
            f"{active.get('current_task', 'Unknown')} | "
            f"Next: {active.get('next_recommended_step', 'Unknown')}"
        )
        print(f"Observation count: {memory.get('observation_count', 0)}")
    else:
        print("Session memory: unavailable")

    vscode_context = pack.get("vscode_context")
    if isinstance(vscode_context, dict):
        print("VS Code context:")
        print(f"- Current file: {vscode_context.get('current_file', '')}")
        print(f"- Current directory: {vscode_context.get('current_directory', '')}")

        python_files = vscode_context.get("recent_python_files", [])
        if isinstance(python_files, list) and python_files:
            print(f"- Recent Python files: {', '.join(str(item) for item in python_files[:5])}")
        else:
            print("- Recent Python files: none")

        modified_files = vscode_context.get("recent_modified_files", [])
        if isinstance(modified_files, list) and modified_files:
            print(f"- Recent modified files: {', '.join(str(item) for item in modified_files[:5])}")
        else:
            print("- Recent modified files: none")

    print(f"Wrote: {OUTPUT_PATH}")


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    pack = _build_context_pack()
    OUTPUT_PATH.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_summary(pack)


if __name__ == "__main__":
    main()
