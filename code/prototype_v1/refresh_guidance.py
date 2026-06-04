from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
RESUME_NOW_PATH = RESULTS_DIR / "resume_now.json"


@dataclass
class StepResult:
    name: str
    ok: bool
    method: str
    detail: str = ""


def _file_signature(path: Path) -> tuple[bool, int, int, str]:
    if not path.exists() or not path.is_file():
        return (False, 0, 0, "")

    try:
        content = path.read_bytes()
        stat = path.stat()
    except OSError:
        return (False, 0, 0, "")

    digest = hashlib.sha256(content).hexdigest()
    return (True, stat.st_mtime_ns, stat.st_size, digest)


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _run_subprocess(script_name: str, args: list[str] | None = None) -> StepResult:
    script_path = BASE_DIR / script_name
    if not script_path.exists() or not script_path.is_file():
        return StepResult(
            name=script_name,
            ok=False,
            method="subprocess",
            detail=f"script not found: {script_path}",
        )

    command = [sys.executable, str(script_path), *(args or [])]
    result = subprocess.run(
        command,
        cwd=str(BASE_DIR),
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        return StepResult(name=script_name, ok=False, method="subprocess", detail=detail)

    return StepResult(name=script_name, ok=True, method="subprocess")


def _run_import_preferred(module_name: str, script_name: str, args: list[str] | None = None) -> StepResult:
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        fallback = _run_subprocess(script_name, args=args)
        if fallback.ok:
            fallback.detail = f"import failed ({exc.__class__.__name__}); used subprocess"
        else:
            fallback.detail = f"import failed ({exc.__class__.__name__}); {fallback.detail}"
        return fallback

    main_func = getattr(module, "main", None)
    if not callable(main_func):
        fallback = _run_subprocess(script_name, args=args)
        if fallback.ok:
            fallback.detail = "module has no callable main(); used subprocess"
        else:
            fallback.detail = f"module has no callable main(); {fallback.detail}"
        return fallback

    if args:
        fallback = _run_subprocess(script_name, args=args)
        if fallback.ok:
            fallback.detail = "arguments required; used subprocess"
        return fallback

    try:
        main_func()
    except Exception as exc:
        fallback = _run_subprocess(script_name, args=args)
        if fallback.ok:
            fallback.detail = f"import execution failed ({exc.__class__.__name__}); used subprocess"
        else:
            fallback.detail = f"import execution failed ({exc.__class__.__name__}); {fallback.detail}"
        return fallback

    return StepResult(name=script_name, ok=True, method="import")


def _print_step_results(step_results: list[StepResult]) -> None:
    print("Pipeline steps:")
    for item in step_results:
        status = "ok" if item.ok else "failed"
        line = f"- {item.name}: {status} via {item.method}"
        if item.detail:
            line += f" ({item.detail})"
        print(line)


def _print_summary(resume_payload: dict[str, Any], resume_updated: bool, failed_steps: list[str]) -> None:
    active_file = resume_payload.get("active_file") if isinstance(resume_payload.get("active_file"), dict) else {}
    guidance = resume_payload.get("guidance_priority") if isinstance(resume_payload.get("guidance_priority"), dict) else {}

    active_file_name = str(active_file.get("active_file_name", "") or "")
    prompt_mode = str(resume_payload.get("prompt_mode", "") or "")
    headline = str(guidance.get("headline", "") or "")
    recommended = str(
        resume_payload.get("recommended_next_action")
        or guidance.get("recommended_action")
        or ""
    )

    print()
    print("Refresh summary:")
    print(f"- active file: {active_file_name or 'unavailable'}")
    print(f"- prompt_mode: {prompt_mode or 'unavailable'}")
    print(f"- guidance headline: {headline or 'unavailable'}")
    print(f"- recommended next action: {recommended or 'unavailable'}")
    print(f"- resume_now.json updated: {resume_updated}")
    if failed_steps:
        print(f"- failed steps: {', '.join(failed_steps)}")
    else:
        print("- failed steps: none")


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    before_sig = _file_signature(RESUME_NOW_PATH)

    pipeline: list[tuple[str, str, str, list[str]]] = [
        ("terminal_error_context", "terminal_error_context", "terminal_error_context.py", []),
        ("coding_context_pack", "coding_context_pack", "coding_context_pack.py", []),
        ("coding_session_snapshot", "coding_session_snapshot", "coding_session_snapshot.py", []),
        ("context_fusion", "context_fusion", "context_fusion.py", []),
        ("glasses_demo_auto", "glasses_demo", "glasses_demo.py", ["--auto"]),
    ]

    step_results: list[StepResult] = []

    for step_name, module_name, script_name, args in pipeline:
        if step_name == "glasses_demo_auto":
            result = _run_subprocess(script_name, args=args)
        else:
            result = _run_import_preferred(module_name, script_name, args=args)

        step_results.append(StepResult(name=step_name, ok=result.ok, method=result.method, detail=result.detail))

        if not result.ok:
            print(f"Warning: step failed: {step_name}. {result.detail}")
            if step_name == "glasses_demo_auto":
                _print_step_results(step_results)
                print()
                print("Fatal: glasses_demo.py --auto failed. resume_now.json may be stale.")
                raise SystemExit(1)

    after_sig = _file_signature(RESUME_NOW_PATH)
    resume_updated = before_sig != after_sig and after_sig[0]

    resume_payload = _safe_load_json(RESUME_NOW_PATH)
    failed_steps = [item.name for item in step_results if not item.ok]

    _print_step_results(step_results)
    _print_summary(resume_payload, resume_updated, failed_steps)


if __name__ == "__main__":
    main()
