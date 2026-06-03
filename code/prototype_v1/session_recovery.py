from __future__ import annotations

from pathlib import Path
import json
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
CODING_CONTEXT_PACK_PATH = RESULTS_DIR / "coding_context_pack.json"
LATEST_RESPONSE_PATH = RESULTS_DIR / "latest_response.json"
SESSION_MEMORY_PATH = RESULTS_DIR / "session_memory.json"
OUTPUT_PATH = RESULTS_DIR / "session_recovery.json"


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_text(value: Any, fallback: str = "Unknown") -> str:
    text = str(value).strip() if value is not None else ""
    return text if text else fallback


def _normalize_risk(value: Any) -> str:
    risk = _as_text(value, fallback="low").lower()
    return risk if risk in {"low", "medium", "high"} else "low"


def _build_recovery_payload(coding_pack: dict[str, Any], latest_response: dict[str, Any], session_memory: dict[str, Any]) -> dict[str, Any]:
    coding_session_summary = coding_pack.get("session_memory_summary", {}) if isinstance(coding_pack.get("session_memory_summary"), dict) else {}
    coding_active_task = coding_session_summary.get("active_task", {}) if isinstance(coding_session_summary.get("active_task"), dict) else {}

    session_active_task = session_memory.get("active_task", {}) if isinstance(session_memory.get("active_task"), dict) else {}

    task_progress = latest_response.get("task_progress", {}) if isinstance(latest_response.get("task_progress"), dict) else {}

    display_priority_latest = latest_response.get("display_priority", {}) if isinstance(latest_response.get("display_priority"), dict) else {}
    display_priority_summary = coding_pack.get("latest_response_summary", {}) if isinstance(coding_pack.get("latest_response_summary"), dict) else {}

    display_priority = {
        "mode": _as_text(display_priority_latest.get("mode") or display_priority_summary.get("priority_mode")),
        "headline": _as_text(display_priority_latest.get("headline") or display_priority_summary.get("priority_headline")),
        "primary_message": _as_text(display_priority_latest.get("primary_message") or display_priority_summary.get("priority_message")),
        "status": _as_text(display_priority_latest.get("status"), fallback="Unknown"),
    }

    last_active_task = _as_text(
        coding_active_task.get("current_task")
        or session_active_task.get("current_task")
        or latest_response.get("current_task")
    )
    last_completed_step = _as_text(
        coding_active_task.get("last_completed_step")
        or session_active_task.get("last_completed_step")
    )
    next_recommended_step = _as_text(
        coding_active_task.get("next_recommended_step")
        or session_active_task.get("next_recommended_step")
        or task_progress.get("next_step")
    )

    vscode_context = coding_pack.get("vscode_context", {}) if isinstance(coding_pack.get("vscode_context"), dict) else {}
    current_file = _as_text(vscode_context.get("current_file"), fallback="")
    current_branch = _as_text(coding_pack.get("branch"), fallback="unknown")

    git_intelligence = coding_pack.get("git_intelligence", {}) if isinstance(coding_pack.get("git_intelligence"), dict) else {}
    git_recommendation = _as_text(git_intelligence.get("recommendation"), fallback="No git recommendation")
    git_risk = _normalize_risk(git_intelligence.get("risk_level"))

    error_context = coding_pack.get("error_context", {}) if isinstance(coding_pack.get("error_context"), dict) else {}
    has_error_signals = bool(error_context.get("has_error_signals", False))
    error_summary = _as_text(error_context.get("summary"), fallback="No error context available")

    has_active_task = bool(last_active_task and last_active_task != "Unknown")
    git_blocker = git_risk in {"medium", "high"}
    error_blocker = has_error_signals
    ready_to_continue = has_active_task and not git_blocker and not error_blocker

    if error_blocker:
        recommended_continuation = "Review error context first, resolve blocker, then continue the active task."
    elif git_blocker:
        recommended_continuation = "Review git state first, then continue coding once workspace changes are understood."
    else:
        candidate = next_recommended_step if next_recommended_step != "Unknown" else display_priority.get("primary_message", "")
        recommended_continuation = _as_text(candidate, fallback="Continue with the next planned implementation step.")

    return {
        "last_active_task": last_active_task,
        "last_completed_step": last_completed_step,
        "next_recommended_step": next_recommended_step,
        "current_file": current_file,
        "current_branch": current_branch,
        "git_recommendation": git_recommendation,
        "error_summary": error_summary,
        "display_priority": display_priority,
        "ready_to_continue": ready_to_continue,
        "recommended_continuation": recommended_continuation,
    }


def _print_terminal_summary(payload: dict[str, Any]) -> None:
    display_priority = payload.get("display_priority", {}) if isinstance(payload.get("display_priority"), dict) else {}
    headline = _as_text(display_priority.get("headline"), fallback="Unknown")
    primary_message = _as_text(display_priority.get("primary_message"), fallback="Unknown")

    print("Session Recovery Summary")
    print(f"- Last active task: {payload.get('last_active_task', 'Unknown')}")
    print(f"- Last completed step: {payload.get('last_completed_step', 'Unknown')}")
    print(f"- Next recommended step: {payload.get('next_recommended_step', 'Unknown')}")
    print(f"- Current file: {payload.get('current_file', '')}")
    print(f"- Current branch: {payload.get('current_branch', 'unknown')}")
    print(f"- Git recommendation: {payload.get('git_recommendation', 'No git recommendation')}")
    print(f"- Error context summary: {payload.get('error_summary', 'No error context available')}")
    print(f"- Display priority: {headline} | {primary_message}")
    print(f"- ready_to_continue: {payload.get('ready_to_continue', False)}")
    print(f"- Recommended continuation: {payload.get('recommended_continuation', '')}")
    print(f"Wrote: {OUTPUT_PATH}")


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    coding_pack = _safe_load_json(CODING_CONTEXT_PACK_PATH)
    latest_response = _safe_load_json(LATEST_RESPONSE_PATH)
    session_memory = _safe_load_json(SESSION_MEMORY_PATH)

    payload = _build_recovery_payload(coding_pack, latest_response, session_memory)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_terminal_summary(payload)


if __name__ == "__main__":
    main()
