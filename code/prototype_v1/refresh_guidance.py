from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import importlib
import json
from pathlib import Path
import argparse
import contextlib
import io
import subprocess
import sys
import time
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


def _run_import_preferred(
    module_name: str,
    script_name: str,
    args: list[str] | None = None,
    suppress_output: bool = False,
) -> StepResult:
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
        if suppress_output:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                main_func()
        else:
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


def _run_refresh_once(verbose: bool = True) -> tuple[dict[str, Any], bool, list[str], list[StepResult]]:
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
            result = _run_import_preferred(module_name, script_name, args=args, suppress_output=not verbose)

        step_results.append(StepResult(name=step_name, ok=result.ok, method=result.method, detail=result.detail))

        if not result.ok:
            print(f"Warning: step failed: {step_name}. {result.detail}")
            if step_name == "glasses_demo_auto":
                if verbose:
                    _print_step_results(step_results)
                    print()
                print("Fatal: glasses_demo.py --auto failed. resume_now.json may be stale.")
                raise SystemExit(1)

    after_sig = _file_signature(RESUME_NOW_PATH)
    resume_updated = before_sig != after_sig and after_sig[0]
    resume_payload = _safe_load_json(RESUME_NOW_PATH)
    failed_steps = [item.name for item in step_results if not item.ok]

    if verbose:
        _print_step_results(step_results)
        _print_summary(resume_payload, resume_updated, failed_steps)

    return resume_payload, resume_updated, failed_steps, step_results


def _status_fields(resume_payload: dict[str, Any]) -> tuple[str, str, str]:
    active_file = resume_payload.get("active_file") if isinstance(resume_payload.get("active_file"), dict) else {}
    guidance = resume_payload.get("guidance_priority") if isinstance(resume_payload.get("guidance_priority"), dict) else {}

    active_file_name = str(active_file.get("active_file_name", "") or "")
    prompt_mode = str(resume_payload.get("prompt_mode", "") or "")
    headline = str(guidance.get("headline", "") or "")
    return active_file_name, prompt_mode, headline


def _print_watch_status(
    resume_payload: dict[str, Any],
    resume_updated: bool,
    failed_steps: list[str],
) -> None:
    active_file_name, prompt_mode, headline = _status_fields(resume_payload)
    now_text = datetime.now().strftime("%H:%M:%S")

    print(f"[{now_text}]")
    print(f"active_file={active_file_name or 'unavailable'}")
    print(f"prompt_mode={prompt_mode or 'unavailable'}")
    print(f"guidance={headline or 'unavailable'}")
    print(f"resume_updated={resume_updated}")
    if failed_steps:
        print(f"failed_steps={','.join(failed_steps)}")


def _watch_loop(interval_seconds: int = 5) -> None:
    print(f"Watch mode started. Refresh interval: {interval_seconds}s. Press Ctrl+C to stop.")

    previous_key: tuple[str, str, str] | None = None
    first_cycle = True

    try:
        while True:
            resume_payload, resume_updated, failed_steps, _ = _run_refresh_once(verbose=False)
            current_key = _status_fields(resume_payload)

            if first_cycle or current_key != previous_key:
                _print_watch_status(resume_payload, resume_updated, failed_steps)
                previous_key = current_key
                first_cycle = False

            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\nWatch mode stopped.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh the local guidance pipeline and resume output.")
    parser.add_argument("--watch", action="store_true", help="Run refresh continuously every 5 seconds.")
    return parser.parse_args()


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    args = _parse_args()

    if args.watch:
        _watch_loop(interval_seconds=5)
        return

    _run_refresh_once(verbose=True)


if __name__ == "__main__":
    main()
