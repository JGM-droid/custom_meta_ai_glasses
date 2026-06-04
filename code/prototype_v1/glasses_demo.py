from __future__ import annotations

import argparse
from pathlib import Path
import json
import subprocess
import sys
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
RESULTS_DIR = BASE_DIR / "results"
CODING_CONTEXT_SCRIPT = BASE_DIR / "coding_context_pack.py"
RESUME_NOW_SCRIPT = BASE_DIR / "resume_now.py"
CONTEXT_FUSION_SCRIPT = BASE_DIR / "context_fusion.py"
RESUME_NOW_OUTPUT = RESULTS_DIR / "resume_now.json"
OUTPUT_PATH = RESULTS_DIR / "glasses_demo.json"
DISPLAY_MOCK_PATH = BASE_DIR / "glasses_display_mock.html"
TERMINAL_ERROR_OUTPUT = RESULTS_DIR / "terminal_error_context.json"
CODING_CONTEXT_OUTPUT = RESULTS_DIR / "coding_context_pack.json"
CONTEXT_FUSION_OUTPUT = RESULTS_DIR / "context_fusion.json"
PROJECT_MEMORY_PATH = PROJECT_ROOT / "AGENTS.md"

SCENARIO_GUIDANCE = {
    "normal": {
        "level": "info",
        "headline": "Continue Implementation",
        "recommended_action": "Continue the next implementation step.",
    },
    "error": {
        "level": "critical",
        "headline": "Resolve Error First",
        "recommended_action": "Review and resolve the current error before continuing.",
    },
    "git": {
        "level": "high",
        "headline": "Review Git Changes",
        "recommended_action": "Review your git changes before continuing.",
    },
    "switch": {
        "level": "low",
        "headline": "Possible Task Switch",
        "recommended_action": "Confirm whether you want to continue the current task.",
    },
    "stuck": {
        "level": "medium",
        "headline": "Possible Blocker",
        "recommended_action": "Break the task into a smaller next step.",
    },
}

GUIDANCE_PRIORITY_RANK = {
    "critical": 5,
    "high": 4,
    "medium": 3,
    "low": 2,
    "info": 1,
}

FILE_FOCUS_GUIDANCE: dict[str, dict[str, Any]] = {
    "api.py": {
        "current_focus": "FastAPI endpoint development",
        "suggested_checks": [
            "Verify endpoint request/response schema consistency.",
            "Confirm fallback behavior and HTTP status handling.",
            "Run a quick local /latest smoke test before tunnel testing.",
        ],
    },
    "context_fusion.py": {
        "current_focus": "Context fusion development",
        "suggested_checks": [
            "Confirm source selection order remains Error > Git > Snapshot.",
            "Validate missing input files are handled without crashes.",
            "Check fused output fields for active_file and guidance consistency.",
        ],
    },
    "glasses_display_mock.html": {
        "current_focus": "Display/UI development",
        "suggested_checks": [
            "Verify polling updates guidance and active-file lines every cycle.",
            "Confirm API URL override and same-origin fallback both work.",
            "Test visual fallback when active file context is unavailable.",
        ],
    },
    "active_editor_context.py": {
        "current_focus": "VS Code signal development",
        "suggested_checks": [
            "Validate active_editor_state.json parsing and invalid JSON fallback.",
            "Confirm output schema remains stable for context fusion input.",
            "Check timestamps and event_type values update as expected.",
        ],
    },
    "ngrok_demo_launcher.py": {
        "current_focus": "Deployment guidance",
        "suggested_checks": [
            "Verify ngrok tunnel is online and /latest responds over HTTPS.",
            "Confirm final display URL includes a reachable API /latest path.",
            "Re-run normal/error/git scenarios and verify remote display updates.",
        ],
    },
}

GENERIC_FILE_FOCUS = {
    "current_focus": "General development",
    "suggested_checks": [
        "Review the current file changes and ensure intent is clear.",
        "Run a focused smoke test for the module you are editing.",
        "Confirm output artifacts match expected schema and freshness.",
    ],
}

REPO_NAME = "custom_meta_ai_glasses"


def _load_project_memory_summary() -> dict[str, str]:
    summary = {
        "project_name": REPO_NAME,
        "architecture": "Architecture summary unavailable",
        "milestone": "Milestone unavailable",
    }

    if not PROJECT_MEMORY_PATH.exists() or not PROJECT_MEMORY_PATH.is_file():
        return summary

    try:
        text = PROJECT_MEMORY_PATH.read_text(encoding="utf-8")
    except OSError:
        return summary

    lines = text.splitlines()
    architecture_lines: list[str] = []
    in_architecture = False

    for index, raw in enumerate(lines):
        line = raw.strip()
        lower = line.lower()

        if lower == "project:" and index + 1 < len(lines):
            summary["project_name"] = _as_text(lines[index + 1].strip(), fallback=summary["project_name"])

        if lower == "current architecture:":
            in_architecture = True
            continue

        if in_architecture:
            if not line:
                continue
            if line.endswith(":") and lower != "current architecture:":
                in_architecture = False
                continue
            architecture_lines.append(line)

        if lower == "current milestone:" and index + 1 < len(lines):
            summary["milestone"] = _as_text(lines[index + 1].strip(), fallback=summary["milestone"])

    if architecture_lines:
        summary["architecture"] = " ".join(architecture_lines)

    return summary


def _select_prompt_mode(payload: dict[str, Any]) -> str:
    guidance = payload.get("guidance_priority") if isinstance(payload.get("guidance_priority"), dict) else {}
    guidance_source = _as_text(guidance.get("source"), fallback="").lower()
    has_terminal_error = bool(payload.get("has_terminal_error", False))

    active_file = payload.get("active_file") if isinstance(payload.get("active_file"), dict) else {}
    active_file_name = _as_text(active_file.get("active_file_name"), fallback="")
    active_file_lower = active_file_name.lower()

    if has_terminal_error or "terminal_error" in guidance_source:
        return "error_resolution"

    if active_file_lower == "glasses_display_mock.html":
        return "display_ui"

    if active_file_lower == "ngrok_demo_launcher.py" or "deploy" in guidance_source or "tunnel" in guidance_source:
        return "deployment"

    if "git_intelligence" in guidance_source:
        if active_file_lower in {"api.py", "context_fusion.py", "active_editor_context.py"}:
            return "file_development"
        return "git_review"

    if active_file_name:
        return "file_development"

    return "file_development"


def _build_mode_prompt(mode: str, payload: dict[str, Any], project_memory: dict[str, str]) -> str:
    guidance = payload.get("guidance_priority") if isinstance(payload.get("guidance_priority"), dict) else {}
    active_file = payload.get("active_file") if isinstance(payload.get("active_file"), dict) else {}

    guidance_headline = _as_text(guidance.get("headline"), fallback="Resume guidance")
    recommended_next_action = _as_text(
        payload.get("recommended_next_action"),
        fallback=_as_text(guidance.get("recommended_action"), fallback="Continue current implementation."),
    )
    current_focus = _as_text(payload.get("current_focus"), fallback="General development")
    active_file_name = _as_text(active_file.get("active_file_name"), fallback="unavailable")
    checks = payload.get("suggested_checks") if isinstance(payload.get("suggested_checks"), list) else []
    checks_block = "\n".join([f"- {str(item).strip()}" for item in checks if str(item).strip()])

    common_header = (
        f"Project: {_as_text(project_memory.get('project_name'), fallback=REPO_NAME)}\n"
        "Project Memory:\n"
        f"- Architecture: {_as_text(project_memory.get('architecture'), fallback='Architecture summary unavailable')}\n"
        f"- Current Milestone: {_as_text(project_memory.get('milestone'), fallback='Milestone unavailable')}\n\n"
        f"Current active file: {active_file_name}\n"
        f"Current focus: {current_focus}\n"
        f"Guidance headline: {guidance_headline}\n"
        f"Recommended next action: {recommended_next_action}\n\n"
    )

    safety_block = (
        "Safety constraints:\n"
        "- Do not modify unrelated files.\n"
        "- Report findings before making changes unless explicitly asked.\n"
        "- Preserve existing architecture.\n"
        "- Keep changes minimal."
    )

    mode_body = {
        "error_resolution": (
            "Task Mode: Error Resolution\n"
            "Please debug the current failure.\n"
            "- Identify root cause first.\n"
            "- Explain why the failure occurs.\n"
            "- Propose the smallest safe fix.\n"
            "- Validate with focused checks before broader changes.\n"
        ),
        "git_review": (
            "Task Mode: Git Review\n"
            "Please inspect the current modified/staged changes.\n"
            "- Summarize what changed.\n"
            "- Identify risks/regressions.\n"
            "- Recommend the next commit step.\n"
            "- Do not make code changes yet.\n"
        ),
        "display_ui": (
            "Task Mode: Display/UI Development\n"
            "Please verify display behavior for the glasses UI.\n"
            "- Verify rendering of guidance and active-file context.\n"
            "- Verify polling and state refresh behavior.\n"
            "- Verify mobile and desktop behavior remain intact.\n"
        ),
        "deployment": (
            "Task Mode: Deployment\n"
            "Please verify launch and tunnel deployment flow.\n"
            "- Verify launcher sequence and process health.\n"
            "- Verify tunnel accessibility.\n"
            "- Verify key API/display endpoints respond correctly.\n"
        ),
        "file_development": (
            "Task Mode: File Development\n"
            "Please focus on the currently active file.\n"
            "- Explain its current purpose in the architecture.\n"
            "- Recommend the next implementation step.\n"
            "- Keep changes aligned with existing architecture.\n"
        ),
    }.get(mode, "Task Mode: File Development\nPlease continue with focused file-level implementation.\n")

    checks_section = "Suggested checks:\n" + (checks_block if checks_block else "- No suggested checks available.") + "\n\n"

    return common_header + mode_body + "\n" + checks_section + safety_block


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_text(value: Any, fallback: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text if text else fallback


def _run_script(script_path: Path, args: list[str] | None = None) -> dict[str, Any]:
    command = [sys.executable, str(script_path), *(args or [])]
    if not script_path.exists() or not script_path.is_file():
        warning = f"Warning: Script not found: {script_path}"
        print(warning)
        return {
            "script": script_path.name,
            "ok": False,
            "returncode": None,
            "warning": warning,
        }

    result = subprocess.run(
        command,
        cwd=str(BASE_DIR),
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        warning = f"Warning: {script_path.name} exited with code {result.returncode}."
        print(warning)
        stderr = (result.stderr or "").strip()
        if stderr:
            print(stderr)
    return {
        "script": script_path.name,
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
    }


def _build_demo_payload(script_results: list[dict[str, Any]], resume_payload: dict[str, Any], speak_enabled: bool) -> dict[str, Any]:
    guidance = resume_payload.get("guidance_priority", {}) if isinstance(resume_payload.get("guidance_priority"), dict) else {}
    return {
        "speak_enabled": speak_enabled,
        "script_results": [
            {
                "script": item.get("script", ""),
                "ok": bool(item.get("ok", False)),
                "returncode": item.get("returncode"),
            }
            for item in script_results
        ],
        "guidance": {
            "headline": _as_text(guidance.get("headline"), fallback="Resume guidance"),
            "recommended_action": _as_text(
                guidance.get("recommended_action"),
                fallback=_as_text(resume_payload.get("recommended_next_action"), fallback="Continue current implementation."),
            ),
            "level": _as_text(guidance.get("level"), fallback="info"),
        },
        "current_file": _as_text(resume_payload.get("current_file"), fallback=""),
        "display_mock_path": str(DISPLAY_MOCK_PATH),
        "resume_output_path": str(RESUME_NOW_OUTPUT),
    }


def _print_demo_summary(payload: dict[str, Any]) -> None:
    guidance = payload.get("guidance", {}) if isinstance(payload.get("guidance"), dict) else {}
    print("GLASSES DEMO")
    print()
    print(f"Guidance headline: {_as_text(guidance.get('headline'), fallback='Resume guidance')}")
    print(f"Recommended action: {_as_text(guidance.get('recommended_action'), fallback='Continue current implementation.')}")
    print(f"Guidance level: {_as_text(guidance.get('level'), fallback='info')}")
    print(f"Current file: {_as_text(payload.get('current_file'), fallback='')}")
    print(f"Display mock path: {_as_text(payload.get('display_mock_path'), fallback='')}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate demo guidance payloads for glasses display testing.")
    parser.add_argument("--speak", action="store_true", help="Enable spoken guidance in default mode.")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Select highest-priority guidance from available real sources.",
    )
    parser.add_argument(
        "--use-real-git",
        action="store_true",
        help="Use guidance from results/coding_context_pack.json when git risk is medium/high.",
    )
    parser.add_argument(
        "--use-real-errors",
        action="store_true",
        help="Use guidance from results/terminal_error_context.json when a terminal error is present.",
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIO_GUIDANCE.keys()),
        help="Generate deterministic resume payload for a specific scenario.",
    )
    return parser.parse_args()


def _build_scenario_resume_payload(scenario: str) -> dict[str, Any]:
    guidance = SCENARIO_GUIDANCE[scenario]
    return {
        "recommended_next_action": guidance["recommended_action"],
        "current_file": "",
        "guidance_priority": {
            "level": guidance["level"],
            "headline": guidance["headline"],
            "recommended_action": guidance["recommended_action"],
        },
    }


def _active_file_defaults() -> dict[str, Any]:
    return {
        "active_file_name": "",
        "active_file_path": "",
        "language_id": "",
        "is_dirty": False,
        "event_type": "",
    }


def _load_active_file_context() -> tuple[bool, dict[str, Any]]:
    fusion_payload = _safe_load_json(CONTEXT_FUSION_OUTPUT)
    if not fusion_payload:
        return False, _active_file_defaults()

    if not bool(fusion_payload.get("active_file_available", False)):
        return False, _active_file_defaults()

    active_file = fusion_payload.get("active_file") if isinstance(fusion_payload.get("active_file"), dict) else {}
    if not active_file:
        return False, _active_file_defaults()

    return True, {
        "active_file_name": _as_text(active_file.get("active_file_name"), fallback=""),
        "active_file_path": _as_text(active_file.get("active_file_path"), fallback=""),
        "language_id": _as_text(active_file.get("language_id"), fallback=""),
        "is_dirty": bool(active_file.get("is_dirty", False)),
        "event_type": _as_text(active_file.get("event_type"), fallback=""),
    }


def _with_active_file_context(resume_payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(resume_payload) if isinstance(resume_payload, dict) else {}
    active_file_available, active_file = _load_active_file_context()

    payload["active_file_available"] = active_file_available
    payload["active_file"] = active_file

    if active_file_available and _as_text(active_file.get("active_file_name"), fallback=""):
        payload["current_file"] = _as_text(active_file.get("active_file_name"), fallback="")

    payload["active_file_display"] = {
        "current_file": f"Current file: {_as_text(active_file.get('active_file_name'), fallback='unavailable') if active_file_available else 'unavailable'}",
        "language": f"Language: {_as_text(active_file.get('language_id'), fallback='unknown') if active_file_available else 'unknown'}",
        "dirty": f"Dirty: {bool(active_file.get('is_dirty', False)) if active_file_available else False}",
    }

    file_name = _as_text(active_file.get("active_file_name"), fallback="") if active_file_available else ""
    file_focus = FILE_FOCUS_GUIDANCE.get(file_name, GENERIC_FILE_FOCUS)
    payload["current_focus"] = _as_text(file_focus.get("current_focus"), fallback=GENERIC_FILE_FOCUS["current_focus"])

    checks = file_focus.get("suggested_checks") if isinstance(file_focus.get("suggested_checks"), list) else []
    payload["suggested_checks"] = [str(item).strip() for item in checks if str(item).strip()]
    if not payload["suggested_checks"]:
        payload["suggested_checks"] = list(GENERIC_FILE_FOCUS["suggested_checks"])

    project_memory = _load_project_memory_summary()

    payload["prompt_mode"] = _select_prompt_mode(payload)
    payload["ai_prompt"] = _build_mode_prompt(payload["prompt_mode"], payload, project_memory)

    return payload


def _build_terminal_error_resume_payload() -> dict[str, Any] | None:
    payload = _safe_load_json(TERMINAL_ERROR_OUTPUT)
    if not payload or payload.get("has_terminal_error") is not True:
        return None

    guidance = payload.get("guidance_priority")
    if not isinstance(guidance, dict):
        return None

    level = _as_text(guidance.get("level"), fallback="critical")
    headline = _as_text(guidance.get("headline"), fallback="Resolve Error First")
    recommended_action = _as_text(
        guidance.get("recommended_action"),
        fallback=_as_text(payload.get("recommended_action"), fallback="Review and resolve the current error before continuing."),
    )

    return {
        "has_terminal_error": True,
        "recommended_next_action": recommended_action,
        "current_file": "",
        "guidance_priority": {
            "level": level,
            "source": "terminal_error_context",
            "headline": headline,
            "recommended_action": recommended_action,
        },
    }


def _build_git_intelligence_resume_payload() -> dict[str, Any] | None:
    payload = _safe_load_json(CODING_CONTEXT_OUTPUT)
    git_info = payload.get("git_intelligence") if isinstance(payload, dict) else None
    if not isinstance(git_info, dict):
        return None

    risk_level = _as_text(git_info.get("risk_level")).lower()
    if risk_level not in {"medium", "high"}:
        return None

    recommended_action = _as_text(
        git_info.get("recommendation"),
        fallback="Review your git changes before continuing.",
    )

    return {
        "recommended_next_action": recommended_action,
        "current_file": "",
        "guidance_priority": {
            "level": "high",
            "source": "git_intelligence",
            "headline": "Review Git Changes",
            "recommended_action": recommended_action,
        },
    }


def _guidance_level(payload: dict[str, Any]) -> str:
    guidance = payload.get("guidance_priority") if isinstance(payload, dict) else None
    if not isinstance(guidance, dict):
        return "info"
    return _as_text(guidance.get("level"), fallback="info").lower()


def _guidance_rank(payload: dict[str, Any]) -> int:
    return GUIDANCE_PRIORITY_RANK.get(_guidance_level(payload), 1)


def main() -> None:
    args = _parse_args()
    speak_enabled = bool(args.speak)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    _run_script(CONTEXT_FUSION_SCRIPT)

    if args.auto:
        candidates: list[dict[str, Any]] = []

        terminal_resume_payload = _build_terminal_error_resume_payload()
        if terminal_resume_payload:
            terminal_guidance = terminal_resume_payload.get("guidance_priority", {})
            if isinstance(terminal_guidance, dict):
                terminal_guidance["level"] = "critical"
                terminal_guidance["source"] = "terminal_error_context"
            candidates.append(
                {
                    "source": "terminal_error_context",
                    "script": "terminal_error_context",
                    "resume_payload": terminal_resume_payload,
                }
            )

        git_resume_payload = _build_git_intelligence_resume_payload()
        if git_resume_payload:
            candidates.append(
                {
                    "source": "git_intelligence",
                    "script": "git_intelligence",
                    "resume_payload": git_resume_payload,
                }
            )

        if args.scenario:
            scenario_resume_payload = _build_scenario_resume_payload(args.scenario)
            candidates.append(
                {
                    "source": "scenario",
                    "script": f"scenario:{args.scenario}",
                    "resume_payload": scenario_resume_payload,
                }
            )

        if candidates:
            selected = max(candidates, key=lambda item: _guidance_rank(item["resume_payload"]))
            selected_resume_payload = _with_active_file_context(selected["resume_payload"])

            RESUME_NOW_OUTPUT.write_text(json.dumps(selected_resume_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            demo_payload = _build_demo_payload(
                script_results=[
                    {
                        "script": selected["script"],
                        "ok": True,
                        "returncode": 0,
                    }
                ],
                resume_payload=selected_resume_payload,
                speak_enabled=speak_enabled,
            )
            demo_payload["source"] = selected["source"]
            OUTPUT_PATH.write_text(json.dumps(demo_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            print(f"Selected Source: {selected['source']}")
            _print_demo_summary(demo_payload)
            print()
            print(f"Wrote: {RESUME_NOW_OUTPUT}")
            print(f"Wrote: {OUTPUT_PATH}")
            return

        print("Source: fallback")

    if args.use_real_git:
        real_git_resume_payload = _build_git_intelligence_resume_payload()
        if real_git_resume_payload:
            real_git_resume_payload = _with_active_file_context(real_git_resume_payload)
            RESUME_NOW_OUTPUT.write_text(json.dumps(real_git_resume_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            demo_payload = _build_demo_payload(
                script_results=[
                    {
                        "script": "git_intelligence",
                        "ok": True,
                        "returncode": 0,
                    }
                ],
                resume_payload=real_git_resume_payload,
                speak_enabled=speak_enabled,
            )
            demo_payload["source"] = "git_intelligence"
            OUTPUT_PATH.write_text(json.dumps(demo_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            print("Source: git_intelligence")
            _print_demo_summary(demo_payload)
            print()
            print(f"Wrote: {RESUME_NOW_OUTPUT}")
            print(f"Wrote: {OUTPUT_PATH}")
            return

        print("Source: fallback")

    if args.use_real_errors:
        real_error_resume_payload = _build_terminal_error_resume_payload()
        if real_error_resume_payload:
            real_error_resume_payload = _with_active_file_context(real_error_resume_payload)
            RESUME_NOW_OUTPUT.write_text(json.dumps(real_error_resume_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            demo_payload = _build_demo_payload(
                script_results=[
                    {
                        "script": "terminal_error_context",
                        "ok": True,
                        "returncode": 0,
                    }
                ],
                resume_payload=real_error_resume_payload,
                speak_enabled=speak_enabled,
            )
            demo_payload["source"] = "terminal_error_context"
            OUTPUT_PATH.write_text(json.dumps(demo_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            print("Source: terminal_error_context")
            _print_demo_summary(demo_payload)
            print()
            print(f"Wrote: {RESUME_NOW_OUTPUT}")
            print(f"Wrote: {OUTPUT_PATH}")
            return

        print("Source: fallback")

    if args.scenario:
        resume_payload = _with_active_file_context(_build_scenario_resume_payload(args.scenario))
        RESUME_NOW_OUTPUT.write_text(json.dumps(resume_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        demo_payload = _build_demo_payload(
            script_results=[
                {
                    "script": f"scenario:{args.scenario}",
                    "ok": True,
                    "returncode": 0,
                }
            ],
            resume_payload=resume_payload,
            speak_enabled=speak_enabled,
        )
        demo_payload["scenario"] = args.scenario
        OUTPUT_PATH.write_text(json.dumps(demo_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"GLASSES DEMO (scenario: {args.scenario})")
        _print_demo_summary(demo_payload)
        print()
        print(f"Wrote: {RESUME_NOW_OUTPUT}")
        print(f"Wrote: {OUTPUT_PATH}")
        return

    script_results = []
    script_results.append(_run_script(CODING_CONTEXT_SCRIPT))
    script_results.append(_run_script(RESUME_NOW_SCRIPT, ["--speak"] if speak_enabled else []))

    resume_payload = _safe_load_json(RESUME_NOW_OUTPUT)
    if not resume_payload:
        print(f"Warning: Could not load resume output from {RESUME_NOW_OUTPUT}")
    else:
        resume_payload = _with_active_file_context(resume_payload)
        RESUME_NOW_OUTPUT.write_text(json.dumps(resume_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    demo_payload = _build_demo_payload(script_results, resume_payload, speak_enabled)
    OUTPUT_PATH.write_text(json.dumps(demo_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    _print_demo_summary(demo_payload)
    print()
    print(f"Wrote: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
