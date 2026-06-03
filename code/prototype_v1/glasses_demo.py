from __future__ import annotations

import argparse
from pathlib import Path
import json
import subprocess
import sys
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
CODING_CONTEXT_SCRIPT = BASE_DIR / "coding_context_pack.py"
RESUME_NOW_SCRIPT = BASE_DIR / "resume_now.py"
RESUME_NOW_OUTPUT = RESULTS_DIR / "resume_now.json"
OUTPUT_PATH = RESULTS_DIR / "glasses_demo.json"
DISPLAY_MOCK_PATH = BASE_DIR / "glasses_display_mock.html"

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


def main() -> None:
    args = _parse_args()
    speak_enabled = bool(args.speak)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.scenario:
        resume_payload = _build_scenario_resume_payload(args.scenario)
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

    demo_payload = _build_demo_payload(script_results, resume_payload, speak_enabled)
    OUTPUT_PATH.write_text(json.dumps(demo_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    _print_demo_summary(demo_payload)
    print()
    print(f"Wrote: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
