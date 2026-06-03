from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
from typing import Any


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

    current_task = _as_text(session_recovery.get("last_active_task"), fallback="Unknown task")
    current_file = _as_text(session_recovery.get("current_file"), fallback="")

    git_risk = _as_text(git_intelligence.get("risk_level"), fallback="low").lower()
    git_state = _as_text(git_intelligence.get("recommendation"), fallback="No git recommendation")

    has_error_signals = bool(error_context.get("has_error_signals", False))
    error_summary = _as_text(error_context.get("summary"), fallback="No error context available")

    possible_task_switch = bool(task_switch_context.get("possible_task_switch", False))
    switch_text = "Yes" if possible_task_switch else "No"

    if has_error_signals:
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
        "git_state": git_state,
        "possible_task_switch": possible_task_switch,
        "error_context": error_summary,
        "recommended_next_action": recommended_next_action,
    }


def _print_resume_now(payload: dict[str, Any]) -> None:
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


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    _run_script(CODING_CONTEXT_SCRIPT)
    _run_script(SESSION_RECOVERY_SCRIPT)

    coding_pack = _safe_load_json(CODING_CONTEXT_PATH)
    session_recovery = _safe_load_json(SESSION_RECOVERY_PATH)

    payload = _build_resume_now_payload(coding_pack, session_recovery)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_resume_now(payload)
    print()
    print(f"Wrote: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
