from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
from typing import Any

from voice_readout import _speak_message


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
CODING_CONTEXT_SCRIPT = BASE_DIR / "coding_context_pack.py"
SESSION_RECOVERY_SCRIPT = BASE_DIR / "session_recovery.py"
CODING_CONTEXT_PATH = RESULTS_DIR / "coding_context_pack.json"
SESSION_RECOVERY_PATH = RESULTS_DIR / "session_recovery.json"
OUTPUT_PATH = RESULTS_DIR / "resume_now.json"


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


def _run_script(script_path: Path) -> None:
    if not script_path.exists() or not script_path.is_file():
        return
    subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(BASE_DIR),
        check=False,
        capture_output=True,
        text=True,
    )


def _build_resume_now_payload(coding_pack: dict[str, Any], session_recovery: dict[str, Any]) -> dict[str, Any]:
    git_intelligence = coding_pack.get("git_intelligence", {}) if isinstance(coding_pack.get("git_intelligence"), dict) else {}
    error_context = coding_pack.get("error_context", {}) if isinstance(coding_pack.get("error_context"), dict) else {}
    task_switch_context = coding_pack.get("task_switch_context", {}) if isinstance(coding_pack.get("task_switch_context"), dict) else {}
    guidance_priority = coding_pack.get("guidance_priority", {}) if isinstance(coding_pack.get("guidance_priority"), dict) else {}

    current_task = _as_text(session_recovery.get("last_active_task"), fallback="Unknown task")
    current_file = _as_text(session_recovery.get("current_file"), fallback="")

    git_risk = _as_text(git_intelligence.get("risk_level"), fallback="low").lower()
    git_state = _as_text(git_intelligence.get("recommendation"), fallback="No git recommendation")

    has_error_signals = bool(error_context.get("has_error_signals", False))
    error_summary = _as_text(error_context.get("summary"), fallback="No error context available")

    possible_task_switch = bool(task_switch_context.get("possible_task_switch", False))
    guidance_action = str(guidance_priority.get("recommended_action", "") or "").strip()

    if guidance_action:
        recommended_next_action = guidance_action
    elif has_error_signals:
        recommended_next_action = "Review error context first and resolve the blocker before continuing development."
    elif git_risk in {"medium", "high"}:
        recommended_next_action = "Review git state first (status/diff) before resuming implementation."
    elif possible_task_switch:
        recommended_next_action = "You may have switched tasks. Confirm whether to continue the current task or switch focus."
    else:
        recommended_next_action = _as_text(
            session_recovery.get("recommended_continuation"),
            fallback="Continue with the next recommended implementation step.",
        )

    return {
        "current_task": current_task,
        "current_file": current_file,
        "git_risk": git_risk,
        "git_state": git_state,
        "possible_task_switch": possible_task_switch,
        "has_error_signals": has_error_signals,
        "error_context": error_summary,
        "recommended_next_action": recommended_next_action,
        "guidance_priority": guidance_priority,
    }


def _build_conversational_spoken_message(payload: dict[str, Any]) -> str:
    task = _as_text(payload.get("current_task"), fallback="an unknown task")
    current_file = _as_text(payload.get("current_file"), fallback="unknown")
    git_state = _as_text(payload.get("git_state"), fallback="no git recommendation available")
    next_step = _as_text(payload.get("recommended_next_action"), fallback="continue with the next implementation step")
    guidance_priority = payload.get("guidance_priority", {}) if isinstance(payload.get("guidance_priority"), dict) else {}
    guidance_level = _as_text(guidance_priority.get("level"), fallback="").lower()
    guidance_headline = _as_text(guidance_priority.get("headline"), fallback="")
    guidance_source = _as_text(guidance_priority.get("source"), fallback="")
    guidance_action = str(guidance_priority.get("recommended_action", "") or "").strip()

    possible_task_switch = bool(payload.get("possible_task_switch", False))
    has_error_signals = bool(payload.get("has_error_signals", False))
    git_risk = _as_text(payload.get("git_risk"), fallback="low").lower()

    sentences = [
        "Welcome back.",
        f"You were working on {task}.",
        f"Your current file is {current_file}.",
    ]

    if guidance_action:
        if guidance_headline and guidance_source and guidance_level:
            sentences.append(
                f"Priority {guidance_level} guidance from {guidance_source}: {guidance_headline}. Your next step is {guidance_action}."
            )
        else:
            sentences.append(f"Your next step is {guidance_action}.")
    elif possible_task_switch:
        sentences.append("You may have switched tasks. Confirm whether you want to continue before making changes.")
    elif has_error_signals:
        sentences.append("Before continuing, review the error context first and resolve the blocker.")
    elif git_risk in {"medium", "high"}:
        sentences.append("Before continuing, review your git state before resuming implementation.")
    else:
        sentences.append(f"Your git status is {git_state}, and your next step is {next_step}.")

    return " ".join(sentences)


def _speak_recommendation(payload: dict[str, Any]) -> None:
    message = _build_conversational_spoken_message(payload)
    if not message:
        print("Warning: No recommended next action available for voice readout.")
        return

    print()
    print("Spoken message:")
    print(message)

    try:
        if not _speak_message(message):
            print("Warning: Voice readout unavailable for spoken guidance.")
    except Exception as exc:
        print(f"Warning: Voice readout failed: {exc}")


def _print_resume_now(payload: dict[str, Any]) -> None:
    guidance_priority = payload.get("guidance_priority", {}) if isinstance(payload.get("guidance_priority"), dict) else {}

    print("RESUME NOW")
    print()
    print("Current task:")
    print(payload.get("current_task", "Unknown task"))
    print()
    print("Current file:")
    print(payload.get("current_file", ""))
    print()
    print("Git state:")
    print(payload.get("git_state", "No git recommendation"))
    print()
    print("Possible task switch:")
    print("Yes" if payload.get("possible_task_switch", False) else "No")
    print()
    print("Error context:")
    print(payload.get("error_context", "No error context available"))
    print()
    print("Recommended next action:")
    print(payload.get("recommended_next_action", "Continue current workflow."))
    print()
    print("Guidance level:")
    print(guidance_priority.get("level", "info"))
    print()
    print("Guidance headline:")
    print(guidance_priority.get("headline", ""))
    print()
    print("Guidance source:")
    print(guidance_priority.get("source", "continuation"))


def main() -> None:
    speak_enabled = "--speak" in sys.argv[1:]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    _run_script(CODING_CONTEXT_SCRIPT)
    _run_script(SESSION_RECOVERY_SCRIPT)

    coding_pack = _safe_load_json(CODING_CONTEXT_PATH)
    session_recovery = _safe_load_json(SESSION_RECOVERY_PATH)

    payload = _build_resume_now_payload(coding_pack, session_recovery)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_resume_now(payload)
    if speak_enabled:
        _speak_recommendation(payload)
    print()
    print(f"Wrote: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
