from __future__ import annotations

from pathlib import Path
import json
import sys
from typing import Any

from resume_now import _build_conversational_spoken_message, _build_resume_now_payload
from voice_readout import _speak_message


BASE_DIR = Path(__file__).resolve().parent
DEMO_CONTEXT_DIR = BASE_DIR / "results" / "demo_context"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_scenarios() -> dict[str, dict[str, dict[str, Any]]]:
    return {
        "clean_continue": {
            "coding_context_pack": {
                "git_intelligence": {
                    "risk_level": "low",
                    "recommendation": "Ready for next feature",
                    "reason": "Working tree is clean with no pending changes.",
                    "next_command": "",
                },
                "error_context": {
                    "has_error_signals": False,
                    "summary": "No common error signals detected in recent local context files.",
                },
                "task_switch_context": {
                    "possible_task_switch": False,
                    "reason": "No clear local signal that the developer may have switched tasks.",
                },
                "guidance_priority": {
                    "level": "info",
                    "source": "continuation",
                    "headline": "Continue Implementation",
                    "message": "No significant blockers detected.",
                    "recommended_action": "Continue current implementation.",
                },
            },
            "session_recovery": {
                "last_active_task": "Implement V3.8 demo runner",
                "current_file": "code/prototype_v1/dev_demo_scenarios.py",
                "recommended_continuation": "Continue current implementation.",
            },
        },
        "git_review": {
            "coding_context_pack": {
                "git_intelligence": {
                    "risk_level": "high",
                    "recommendation": "Review Git State",
                    "reason": "Modified and untracked files require review before continuing.",
                    "next_command": "git status",
                },
                "error_context": {
                    "has_error_signals": False,
                    "summary": "No common error signals detected in recent local context files.",
                },
                "task_switch_context": {
                    "possible_task_switch": False,
                    "reason": "No clear local signal that the developer may have switched tasks.",
                },
                "guidance_priority": {
                    "level": "high",
                    "source": "git_intelligence",
                    "headline": "Review Git State",
                    "message": "Git risk requires attention.",
                    "recommended_action": "Review git status before continuing.",
                },
            },
            "session_recovery": {
                "last_active_task": "Finalize guidance integration",
                "current_file": "code/prototype_v1/resume_now.py",
                "recommended_continuation": "Continue with the next recommended implementation step.",
            },
        },
        "error_blocker": {
            "coding_context_pack": {
                "git_intelligence": {
                    "risk_level": "low",
                    "recommendation": "Review changes, then commit",
                    "reason": "Only a small number of files are modified.",
                    "next_command": "git diff",
                },
                "error_context": {
                    "has_error_signals": True,
                    "summary": "Potential error signals found in local files: Traceback, ModuleNotFoundError.",
                },
                "task_switch_context": {
                    "possible_task_switch": False,
                    "reason": "Error review should be prioritized before task-switch inference.",
                },
                "guidance_priority": {
                    "level": "critical",
                    "source": "error_context",
                    "headline": "Resolve Error First",
                    "message": "Potential error signals detected.",
                    "recommended_action": "Review and resolve the current error before continuing.",
                },
            },
            "session_recovery": {
                "last_active_task": "Fix startup import failure",
                "current_file": "code/prototype_v1/watch_latest_image.py",
                "recommended_continuation": "Continue with the next recommended implementation step.",
            },
        },
    }


def _run_scenario(name: str, scenario: dict[str, dict[str, Any]], speak_enabled: bool) -> None:
    coding_pack = scenario.get("coding_context_pack", {})
    session_recovery = scenario.get("session_recovery", {})

    scenario_dir = DEMO_CONTEXT_DIR / name
    _write_json(scenario_dir / "coding_context_pack.json", coding_pack)
    _write_json(scenario_dir / "session_recovery.json", session_recovery)

    payload = _build_resume_now_payload(coding_pack, session_recovery)
    spoken_message = _build_conversational_spoken_message(payload)

    guidance = payload.get("guidance_priority", {}) if isinstance(payload.get("guidance_priority"), dict) else {}

    print(f"Scenario: {name}")
    print(f"Current task: {payload.get('current_task', 'Unknown task')}")
    print(f"Current file: {payload.get('current_file', '')}")
    print(f"Guidance priority: {guidance.get('level', 'info')} | {guidance.get('headline', '')} | {guidance.get('source', 'continuation')}")
    print(f"Recommended action: {payload.get('recommended_next_action', 'Continue current implementation.')}")
    print(f"Voice preview: {spoken_message}")

    if speak_enabled:
        try:
            if not _speak_message(spoken_message):
                print("Warning: Voice playback unavailable for scenario preview.")
        except Exception as exc:
            print(f"Warning: Voice playback failed for scenario preview: {exc}")

    print()


def main() -> None:
    speak_enabled = "--speak" in sys.argv[1:]
    scenarios = _build_scenarios()

    DEMO_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)

    print("Developer Workflow Demo Scenarios")
    print()

    for name in ["clean_continue", "git_review", "error_blocker"]:
        _run_scenario(name, scenarios[name], speak_enabled)

    print(f"Demo context written under: {DEMO_CONTEXT_DIR}")


if __name__ == "__main__":
    main()
