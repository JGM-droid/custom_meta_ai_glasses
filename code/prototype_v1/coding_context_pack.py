from __future__ import annotations

from pathlib import Path
import json
import re
import subprocess
import sys
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parents[1]
RESULTS_DIR = BASE_DIR / "results"
OUTPUT_PATH = RESULTS_DIR / "coding_context_pack.json"
LATEST_RESPONSE_PATH = RESULTS_DIR / "latest_response.json"
SESSION_MEMORY_PATH = RESULTS_DIR / "session_memory.json"
MILESTONE_HISTORY_PATH = RESULTS_DIR / "milestone_history.json"

ERROR_SIGNALS = [
    "Traceback",
    "Exception",
    "Error",
    "Failed",
    "ModuleNotFoundError",
    "ImportError",
    "SyntaxError",
    "Port already in use",
    "No module named",
    "Permission denied",
]

TEXT_SCAN_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".log",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".html",
    ".js",
    ".ts",
    ".ps1",
    ".bat",
    ".sh",
}

MAX_SCAN_FILE_BYTES = 512_000


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


def _build_git_intelligence(git_status_summary: dict[str, Any], changed_files: list[dict[str, str]]) -> dict[str, str]:
    is_clean = bool(git_status_summary.get("is_clean", True))
    staged_count = int(git_status_summary.get("staged_count", 0) or 0)
    untracked_count = int(git_status_summary.get("untracked_count", 0) or 0)

    if staged_count > 0:
        return {
            "recommendation": "Verify staged changes before commit",
            "reason": "Staged files exist and should be checked before finalizing the commit.",
            "risk_level": "medium",
            "next_command": "git diff --staged",
        }

    if is_clean:
        return {
            "recommendation": "Ready for next feature",
            "reason": "Working tree is clean with no pending changes.",
            "risk_level": "low",
            "next_command": "",
        }

    if untracked_count > 0:
        return {
            "recommendation": "Review untracked files before committing",
            "reason": "Untracked files can be accidentally omitted or unintentionally included.",
            "risk_level": "medium",
            "next_command": "git status",
        }

    modified_count = len(changed_files)
    if modified_count <= 2:
        return {
            "recommendation": "Review changes, then commit",
            "reason": "Only a small number of files are modified.",
            "risk_level": "low",
            "next_command": "git diff",
        }

    return {
        "recommendation": "Review carefully before committing",
        "reason": "Many files are modified, which increases the chance of unintended changes.",
        "risk_level": "medium",
        "next_command": "git status && git diff",
    }


def _is_scannable_text_file(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    if "__pycache__" in path.parts:
        return False
    if path.suffix.lower() not in TEXT_SCAN_SUFFIXES:
        return False
    try:
        if path.stat().st_size > MAX_SCAN_FILE_BYTES:
            return False
    except OSError:
        return False
    return True


def _collect_recent_result_like_files(limit: int = 5) -> list[Path]:
    candidates: list[Path] = []
    relevant_dirs = [
        RESULTS_DIR,
        REPO_ROOT / "testing_logs",
    ]
    for base in relevant_dirs:
        if not base.exists() or not base.is_dir():
            continue
        for path in base.rglob("*"):
            if _is_scannable_text_file(path):
                candidates.append(path)
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[:limit]


def _build_error_context(changed_files: list[dict[str, str]], vscode_context: dict[str, Any]) -> dict[str, Any]:
    candidate_paths: list[Path] = []

    for item in changed_files:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("path", "") or "").strip()
        if not rel:
            continue
        candidate_paths.append(REPO_ROOT / rel)

    recent_modified = vscode_context.get("recent_modified_files", []) if isinstance(vscode_context, dict) else []
    if isinstance(recent_modified, list):
        for rel in recent_modified[:5]:
            rel_text = str(rel or "").strip()
            if not rel_text:
                continue
            candidate_paths.append(REPO_ROOT / rel_text)

    candidate_paths.extend(_collect_recent_result_like_files(limit=5))

    unique_paths: list[Path] = []
    seen = set()
    for path in candidate_paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(path)

    found_files: list[str] = []
    found_keywords: list[str] = []
    signal_map = {signal.lower(): signal for signal in ERROR_SIGNALS}

    for path in unique_paths:
        if not _is_scannable_text_file(path):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        lowered = content.lower()
        matched_here = []
        for key, signal in signal_map.items():
            if key in lowered:
                matched_here.append(signal)

        if matched_here:
            found_files.append(_to_repo_relative(path))
            for signal in matched_here:
                if signal not in found_keywords:
                    found_keywords.append(signal)

    has_error_signals = bool(found_keywords)
    if has_error_signals:
        file_preview = ", ".join(found_files[:3])
        keyword_preview = ", ".join(found_keywords[:4])
        summary = _truncate(
            f"Potential error signals found in {len(found_files)} file(s): {keyword_preview}."
            f" First files: {file_preview}.",
            220,
        )
        suggested_next_step = "Open flagged files, confirm current failure, and run the suggested git/repro command."
    else:
        summary = "No common error signals detected in recent local context files."
        suggested_next_step = "Continue with current workflow and rerun context pack after any failures."

    return {
        "has_error_signals": has_error_signals,
        "error_files": found_files,
        "error_keywords": found_keywords,
        "summary": summary,
        "suggested_next_step": suggested_next_step,
    }


def _build_task_switch_context(
    session_memory_summary: dict[str, Any] | None,
    vscode_context: dict[str, Any],
    latest_response_summary: dict[str, Any] | None,
    git_intelligence: dict[str, str],
    error_context: dict[str, Any],
) -> dict[str, str | bool]:
    memory = session_memory_summary if isinstance(session_memory_summary, dict) else {}
    active_task = memory.get("active_task", {}) if isinstance(memory.get("active_task"), dict) else {}

    previous_task = str(active_task.get("current_task", "") or "").strip()
    has_active_task = bool(previous_task and previous_task.lower() != "unknown")

    current_file = str(vscode_context.get("current_file", "") or "").strip()
    recent_modified = vscode_context.get("recent_modified_files", []) if isinstance(vscode_context.get("recent_modified_files"), list) else []
    recent_modified_text = ", ".join(str(item) for item in recent_modified[:3]) if recent_modified else "none"
    current_context = f"file={current_file if current_file else 'unknown'}; recent_modified={recent_modified_text}"

    latest = latest_response_summary if isinstance(latest_response_summary, dict) else {}
    continuity = str(latest.get("task_continuity", "") or "").strip().lower()

    has_errors = bool(error_context.get("has_error_signals", False)) if isinstance(error_context, dict) else False
    git_recommendation = str(git_intelligence.get("recommendation", "Review git state")) if isinstance(git_intelligence, dict) else "Review git state"

    if not has_active_task:
        return {
            "possible_task_switch": False,
            "reason": "No active task is available, so task-switch detection is not applied.",
            "previous_task": "",
            "current_context": current_context,
            "suggested_action": "Start or capture an active task before evaluating task switches.",
        }

    if continuity == "task switch":
        return {
            "possible_task_switch": True,
            "reason": "Latest response indicates the developer may have switched tasks.",
            "previous_task": previous_task,
            "current_context": current_context,
            "suggested_action": "Confirm whether the workflow changed, then either resume previous task or continue the new one.",
        }

    if has_errors:
        return {
            "possible_task_switch": False,
            "reason": "Error signals are present; prioritize error review before inferring a task switch.",
            "previous_task": previous_task,
            "current_context": current_context,
            "suggested_action": "Review error context and resolve blocker first.",
        }

    task_terms = {token for token in re.findall(r"[a-z0-9]+", previous_task.lower()) if len(token) >= 4}
    file_terms = {token for token in re.findall(r"[a-z0-9]+", current_file.lower()) if len(token) >= 3}
    overlap = task_terms.intersection(file_terms)

    if current_file and task_terms and not overlap:
        return {
            "possible_task_switch": True,
            "reason": "Current file appears unrelated to the active task; developer may have switched tasks.",
            "previous_task": previous_task,
            "current_context": current_context,
            "suggested_action": "Use caution and verify intent; if this is a switch, update active task context."
            if "unknown" not in git_recommendation.lower()
            else "Use caution and verify intent before continuing.",
        }

    return {
        "possible_task_switch": False,
        "reason": "No clear local signal that the developer may have switched tasks.",
        "previous_task": previous_task,
        "current_context": current_context,
        "suggested_action": "Continue active task and monitor continuity on the next analysis run.",
    }


def _build_developer_stuck_context(
    task_switch_context: dict[str, Any],
    error_context: dict[str, Any],
    git_intelligence: dict[str, Any],
    session_memory_summary: dict[str, Any] | None,
    latest_response_summary: dict[str, Any] | None,
    vscode_context: dict[str, Any],
) -> dict[str, str | bool]:
    task_switch = task_switch_context if isinstance(task_switch_context, dict) else {}
    errors = error_context if isinstance(error_context, dict) else {}
    git = git_intelligence if isinstance(git_intelligence, dict) else {}
    session = session_memory_summary if isinstance(session_memory_summary, dict) else {}
    latest = latest_response_summary if isinstance(latest_response_summary, dict) else {}
    vscode = vscode_context if isinstance(vscode_context, dict) else {}

    has_error_signals = bool(errors.get("has_error_signals", False))
    latest_stuck = bool(latest.get("stuck", False))
    possible_task_switch = bool(task_switch.get("possible_task_switch", False))

    active_task = session.get("active_task", {}) if isinstance(session.get("active_task"), dict) else {}
    current_task = str(active_task.get("current_task", "") or "").strip()
    next_step = str(active_task.get("next_recommended_step", "") or "").strip()
    observation_count = int(session.get("observation_count", 0) or 0)

    repeated_task_signal = observation_count >= 3 and bool(current_task) and current_task.lower() != "unknown"
    repeated_step_signal = observation_count >= 3 and bool(next_step) and next_step.lower() != "unknown"

    current_file = str(vscode.get("current_file", "") or "").strip()
    same_file_multiple_observations = observation_count >= 2 and bool(current_file)

    git_risk = str(git.get("risk_level", "low") or "low").strip().lower()
    no_progress_indicators = (
        not has_error_signals
        and not latest_stuck
        and not possible_task_switch
        and git_risk == "low"
    )

    if has_error_signals:
        return {
            "possibly_stuck": True,
            "stuck_reason": "Developer may be stuck due to a possible blocker from current error signals.",
            "confidence": "high",
            "recommended_action": "Review and resolve the current error before continuing.",
        }

    if latest_stuck:
        return {
            "possibly_stuck": True,
            "stuck_reason": "Latest response indicates the developer may be stuck with a possible blocker.",
            "confidence": "high",
            "recommended_action": "Consider breaking the task into a smaller next step.",
        }

    if possible_task_switch:
        return {
            "possibly_stuck": True,
            "stuck_reason": "Developer may be stuck because a possible task switch was detected.",
            "confidence": "medium",
            "recommended_action": "Confirm whether you intend to continue the current task.",
        }

    if repeated_task_signal or repeated_step_signal:
        reason_parts = []
        if repeated_task_signal:
            reason_parts.append("same active task appears repeatedly")
        if repeated_step_signal:
            reason_parts.append("same next step appears repeatedly")
        reason_detail = " and ".join(reason_parts) if reason_parts else "repeated local context signals"
        return {
            "possibly_stuck": True,
            "stuck_reason": f"Developer may be stuck because the {reason_detail}, suggesting a possible blocker.",
            "confidence": "medium",
            "recommended_action": "Consider breaking the task into a smaller next step.",
        }

    if same_file_multiple_observations and no_progress_indicators:
        return {
            "possibly_stuck": True,
            "stuck_reason": "Developer may be stuck because the current file has remained the same with no obvious progress indicators.",
            "confidence": "low",
            "recommended_action": "Continue current implementation.",
        }

    return {
        "possibly_stuck": False,
        "stuck_reason": "No strong local signal that the developer may be stuck.",
        "confidence": "low",
        "recommended_action": "Continue current implementation.",
    }


def _build_guidance_priority(
    error_context: dict[str, Any],
    git_intelligence: dict[str, Any],
    task_switch_context: dict[str, Any],
    developer_stuck_context: dict[str, Any],
    session_memory_summary: dict[str, Any] | None,
    latest_response_summary: dict[str, Any] | None,
) -> dict[str, str]:
    errors = error_context if isinstance(error_context, dict) else {}
    git = git_intelligence if isinstance(git_intelligence, dict) else {}
    task_switch = task_switch_context if isinstance(task_switch_context, dict) else {}
    stuck = developer_stuck_context if isinstance(developer_stuck_context, dict) else {}

    has_error_signals = bool(errors.get("has_error_signals", False))
    git_risk = str(git.get("risk_level", "low") or "low").strip().lower()
    possible_task_switch = bool(task_switch.get("possible_task_switch", False))
    possibly_stuck = bool(stuck.get("possibly_stuck", False))

    if has_error_signals:
        return {
            "level": "critical",
            "source": "error_context",
            "headline": "Resolve Error First",
            "message": "Potential error signals detected.",
            "recommended_action": "Review and resolve the current error before continuing.",
        }

    if git_risk == "high":
        return {
            "level": "high",
            "source": "git_intelligence",
            "headline": "Review Git State",
            "message": "Git risk requires attention.",
            "recommended_action": "Review git status before continuing.",
        }

    if possibly_stuck and not possible_task_switch:
        return {
            "level": "medium",
            "source": "developer_stuck_context",
            "headline": "Possible Blocker",
            "message": "You may be stuck.",
            "recommended_action": "Break the task into a smaller next step.",
        }

    if possible_task_switch:
        return {
            "level": "low",
            "source": "task_switch_context",
            "headline": "Possible Task Switch",
            "message": "You may have switched tasks.",
            "recommended_action": "Confirm whether you intend to continue.",
        }

    _ = session_memory_summary
    _ = latest_response_summary
    return {
        "level": "info",
        "source": "continuation",
        "headline": "Continue Implementation",
        "message": "No significant blockers detected.",
        "recommended_action": "Continue current implementation.",
    }


def _build_progress_context(
    git_intelligence: dict[str, Any],
    vscode_context: dict[str, Any],
    session_memory_summary: dict[str, Any] | None,
    latest_response_summary: dict[str, Any] | None,
    guidance_priority: dict[str, Any],
) -> dict[str, str | bool]:
    git = git_intelligence if isinstance(git_intelligence, dict) else {}
    vscode = vscode_context if isinstance(vscode_context, dict) else {}
    session = session_memory_summary if isinstance(session_memory_summary, dict) else {}
    latest = latest_response_summary if isinstance(latest_response_summary, dict) else {}
    guidance = guidance_priority if isinstance(guidance_priority, dict) else {}

    active_task = session.get("active_task", {}) if isinstance(session.get("active_task"), dict) else {}
    last_completed_step = str(active_task.get("last_completed_step", "") or "").strip()
    next_recommended_step = str(active_task.get("next_recommended_step", "") or "").strip()

    git_risk = str(git.get("risk_level", "low") or "low").strip().lower()
    guidance_level = str(guidance.get("level", "info") or "info").strip().lower()
    guidance_action = str(guidance.get("recommended_action", "") or "").strip()

    current_file = str(vscode.get("current_file", "") or "").strip().lower()
    recent_modified = vscode.get("recent_modified_files", []) if isinstance(vscode.get("recent_modified_files"), list) else []
    recent_text = " ".join(str(item).lower() for item in recent_modified[:5])

    expected_file_match = re.search(r"[a-zA-Z0-9_./-]+\.[a-zA-Z0-9]+", next_recommended_step)
    expected_file = expected_file_match.group(0).lower() if expected_file_match else ""
    moved_to_expected_file = bool(expected_file and (expected_file in current_file or expected_file in recent_text))

    latest_stuck = bool(latest.get("stuck", False))
    working_tree_clean_signal = git_risk == "low"
    guidance_downgraded_signal = guidance_level == "info" and not latest_stuck
    completed_step_signal = bool(last_completed_step and last_completed_step.lower() != "unknown")
    next_step_signal = bool(next_recommended_step and next_recommended_step.lower() != "unknown")

    next_expected_action = guidance_action or next_recommended_step or "Continue current implementation."
    completed_step = last_completed_step if completed_step_signal else ""

    if completed_step_signal and guidance_downgraded_signal:
        return {
            "progress_detected": True,
            "confidence": "high",
            "reason": "Possible progress detected: a step appears completed and guidance is now continuation-level.",
            "completed_step": completed_step,
            "next_expected_action": next_expected_action,
        }

    if completed_step_signal or moved_to_expected_file or (working_tree_clean_signal and next_step_signal):
        reason = "Possible progress detected from local workflow signals."
        if moved_to_expected_file:
            reason = "Possible progress detected: file activity appears aligned with the expected next file."
        elif working_tree_clean_signal and next_step_signal:
            reason = "Possible progress detected: working tree appears clean and the next step is defined."
        elif completed_step_signal:
            reason = "Possible progress detected: a task step appears completed."
        return {
            "progress_detected": True,
            "confidence": "medium",
            "reason": reason,
            "completed_step": completed_step,
            "next_expected_action": next_expected_action,
        }

    if working_tree_clean_signal or guidance_downgraded_signal:
        return {
            "progress_detected": True,
            "confidence": "low",
            "reason": "Possible progress detected: blocker pressure appears reduced in current local context.",
            "completed_step": completed_step,
            "next_expected_action": next_expected_action,
        }

    return {
        "progress_detected": False,
        "confidence": "low",
        "reason": "No clear local evidence of possible progress detected.",
        "completed_step": completed_step,
        "next_expected_action": next_expected_action,
    }


def _load_milestone_history() -> list[str]:
    payload = _safe_load_json(MILESTONE_HISTORY_PATH)
    if not isinstance(payload, dict):
        return []
    items = payload.get("completed_milestones", [])
    if not isinstance(items, list):
        return []

    cleaned: list[str] = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _save_milestone_history(completed_milestones: list[str]) -> None:
    payload = {
        "completed_milestones": completed_milestones,
        "milestone_count": len(completed_milestones),
    }
    MILESTONE_HISTORY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_milestone_context(
    progress_context: dict[str, Any],
    session_memory_summary: dict[str, Any] | None,
    guidance_priority: dict[str, Any],
    git_intelligence: dict[str, Any],
    latest_response_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    progress = progress_context if isinstance(progress_context, dict) else {}
    session = session_memory_summary if isinstance(session_memory_summary, dict) else {}
    guidance = guidance_priority if isinstance(guidance_priority, dict) else {}
    git = git_intelligence if isinstance(git_intelligence, dict) else {}
    latest = latest_response_summary if isinstance(latest_response_summary, dict) else {}

    active_task = session.get("active_task", {}) if isinstance(session.get("active_task"), dict) else {}
    current_milestone = str(active_task.get("current_task", "") or "").strip() or "Unknown milestone"

    progress_detected = bool(progress.get("progress_detected", False))
    completed_step = str(progress.get("completed_step", "") or "").strip()
    next_step = str(active_task.get("next_recommended_step", "") or "").strip()

    major_wording = bool(re.search(r"\b(implement|integration|engine|detection|tracking|recovery|priority|context|milestone)\b", completed_step.lower()))
    task_advancement = bool(completed_step and next_step and completed_step.lower() != next_step.lower())
    reduced_blocker_pressure = (
        str(guidance.get("level", "info") or "info").strip().lower() == "info"
        and str(git.get("risk_level", "low") or "low").strip().lower() == "low"
        and not bool(latest.get("stuck", False))
    )

    completed_milestones = _load_milestone_history()
    candidate_milestone = ""
    if progress_detected and completed_step and (major_wording or task_advancement or reduced_blocker_pressure):
        candidate_milestone = completed_step

    if candidate_milestone:
        existing = {item.lower() for item in completed_milestones}
        if candidate_milestone.lower() not in existing:
            completed_milestones.append(candidate_milestone)

    _save_milestone_history(completed_milestones)

    milestone_count = len(completed_milestones)
    project_progress_summary = f"{milestone_count} milestone completed." if milestone_count == 1 else f"{milestone_count} milestones completed."

    return {
        "current_milestone": current_milestone,
        "completed_milestones": completed_milestones,
        "milestone_count": milestone_count,
        "project_progress_summary": project_progress_summary,
    }


def _build_context_pack() -> dict[str, Any]:
    branch = _get_branch()
    git_status_summary, changed_files = _get_git_status_summary()
    git_intelligence = _build_git_intelligence(git_status_summary, changed_files)
    latest_response_summary = _build_latest_response_summary()
    session_memory_summary = _build_session_memory_summary()
    vscode_context = _build_vscode_context()
    error_context = _build_error_context(changed_files, vscode_context)
    task_switch_context = _build_task_switch_context(
        session_memory_summary,
        vscode_context,
        latest_response_summary,
        git_intelligence,
        error_context,
    )
    developer_stuck_context = _build_developer_stuck_context(
        task_switch_context,
        error_context,
        git_intelligence,
        session_memory_summary,
        latest_response_summary,
        vscode_context,
    )
    guidance_priority = _build_guidance_priority(
        error_context,
        git_intelligence,
        task_switch_context,
        developer_stuck_context,
        session_memory_summary,
        latest_response_summary,
    )
    progress_context = _build_progress_context(
        git_intelligence,
        vscode_context,
        session_memory_summary,
        latest_response_summary,
        guidance_priority,
    )
    milestone_context = _build_milestone_context(
        progress_context,
        session_memory_summary,
        guidance_priority,
        git_intelligence,
        latest_response_summary,
    )

    pack = {
        "branch": branch,
        "git_status_summary": git_status_summary,
        "changed_files": changed_files,
        "git_intelligence": git_intelligence,
        "latest_response_summary": latest_response_summary,
        "session_memory_summary": session_memory_summary,
        "vscode_context": vscode_context,
        "error_context": error_context,
        "task_switch_context": task_switch_context,
        "developer_stuck_context": developer_stuck_context,
        "guidance_priority": guidance_priority,
        "progress_context": progress_context,
        "milestone_context": milestone_context,
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

    git_intelligence = pack.get("git_intelligence")
    if isinstance(git_intelligence, dict):
        print("Git intelligence:")
        print(f"- Recommendation: {git_intelligence.get('recommendation', '')}")
        print(f"- Risk: {git_intelligence.get('risk_level', '')}")
        print(f"- Reason: {git_intelligence.get('reason', '')}")
        next_command = str(git_intelligence.get("next_command", "") or "").strip()
        print(f"- Next command: {next_command if next_command else '<none>'}")

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

    error_context = pack.get("error_context")
    if isinstance(error_context, dict):
        print("Error context:")
        print(f"- Has signals: {error_context.get('has_error_signals', False)}")
        error_keywords = error_context.get("error_keywords", [])
        if isinstance(error_keywords, list) and error_keywords:
            print(f"- Keywords: {', '.join(str(item) for item in error_keywords[:5])}")
        else:
            print("- Keywords: none")
        error_files = error_context.get("error_files", [])
        if isinstance(error_files, list) and error_files:
            print(f"- Files: {', '.join(str(item) for item in error_files[:3])}")
        else:
            print("- Files: none")
        print(f"- Summary: {error_context.get('summary', '')}")
        print(f"- Next step: {error_context.get('suggested_next_step', '')}")

    task_switch_context = pack.get("task_switch_context")
    if isinstance(task_switch_context, dict):
        print("Task switch context:")
        print(f"- Possible switch: {task_switch_context.get('possible_task_switch', False)}")
        print(f"- Previous task: {task_switch_context.get('previous_task', '')}")
        print(f"- Current context: {task_switch_context.get('current_context', '')}")
        print(f"- Suggested action: {task_switch_context.get('suggested_action', '')}")

    developer_stuck_context = pack.get("developer_stuck_context")
    if isinstance(developer_stuck_context, dict):
        print("Developer stuck context:")
        print(f"- Possibly stuck: {developer_stuck_context.get('possibly_stuck', False)}")
        print(f"- Confidence: {developer_stuck_context.get('confidence', 'low')}")
        print(f"- Reason: {developer_stuck_context.get('stuck_reason', '')}")
        print(f"- Recommended action: {developer_stuck_context.get('recommended_action', '')}")

    guidance_priority = pack.get("guidance_priority")
    if isinstance(guidance_priority, dict):
        print("Guidance Priority:")
        print(f"- Level: {guidance_priority.get('level', 'info')}")
        print(f"- Source: {guidance_priority.get('source', 'continuation')}")
        print(f"- Headline: {guidance_priority.get('headline', '')}")
        print(f"- Recommended action: {guidance_priority.get('recommended_action', '')}")

    progress_context = pack.get("progress_context")
    if isinstance(progress_context, dict):
        print("Progress Context:")
        print(f"- Progress detected: {progress_context.get('progress_detected', False)}")
        print(f"- Confidence: {progress_context.get('confidence', 'low')}")
        print(f"- Reason: {progress_context.get('reason', '')}")
        print(f"- Completed step: {progress_context.get('completed_step', '')}")
        print(f"- Next expected action: {progress_context.get('next_expected_action', '')}")

    milestone_context = pack.get("milestone_context")
    if isinstance(milestone_context, dict):
        completed = milestone_context.get("completed_milestones", [])
        latest_completed = ""
        if isinstance(completed, list) and completed:
            latest_completed = str(completed[-1])
        print("Milestone Context:")
        print(f"- Current milestone: {milestone_context.get('current_milestone', '')}")
        print(f"- Milestone count: {milestone_context.get('milestone_count', 0)}")
        print(f"- Latest completed milestone: {latest_completed}")

    print(f"Wrote: {OUTPUT_PATH}")


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    pack = _build_context_pack()
    OUTPUT_PATH.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_summary(pack)


if __name__ == "__main__":
    main()
