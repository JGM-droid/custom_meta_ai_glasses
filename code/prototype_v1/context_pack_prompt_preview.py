from __future__ import annotations

from pathlib import Path
import json


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
CODING_CONTEXT_PACK_PATH = RESULTS_DIR / "coding_context_pack.json"
LATEST_RESPONSE_PATH = RESULTS_DIR / "latest_response.json"
OUTPUT_PATH = RESULTS_DIR / "context_pack_prompt_preview.txt"


def _safe_load_json(path: Path) -> dict:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_text(value, fallback: str = "Unknown") -> str:
    text = str(value).strip() if value is not None else ""
    return text if text else fallback


def _join_list(values, limit: int = 5, fallback: str = "None") -> str:
    if not isinstance(values, list):
        return fallback
    items = [str(item).strip() for item in values if str(item).strip()]
    if not items:
        return fallback
    return ", ".join(items[:limit])


def _build_preview(coding_pack: dict, latest_response: dict) -> str:
    branch = _as_text(coding_pack.get("branch"))

    git_intel = coding_pack.get("git_intelligence", {}) if isinstance(coding_pack.get("git_intelligence"), dict) else {}
    git_recommendation = _as_text(git_intel.get("recommendation"), fallback="No recommendation")

    vscode_context = coding_pack.get("vscode_context", {}) if isinstance(coding_pack.get("vscode_context"), dict) else {}
    current_file = _as_text(vscode_context.get("current_file"), fallback="Unknown file")
    recent_modified = _join_list(vscode_context.get("recent_modified_files", []), limit=5, fallback="None")

    session_memory = coding_pack.get("session_memory_summary", {}) if isinstance(coding_pack.get("session_memory_summary"), dict) else {}
    active_task = session_memory.get("active_task", {}) if isinstance(session_memory.get("active_task"), dict) else {}
    active_task_text = _as_text(active_task.get("current_task"), fallback="Unknown task")

    display_priority = {}
    if isinstance(latest_response.get("display_priority"), dict):
        display_priority = latest_response.get("display_priority", {})
    elif isinstance(coding_pack.get("latest_response_summary"), dict):
        summary = coding_pack.get("latest_response_summary", {})
        display_priority = {
            "mode": summary.get("priority_mode", "Unknown"),
            "headline": summary.get("priority_headline", "Unknown"),
            "primary_message": summary.get("priority_message", "Unknown"),
        }

    display_mode = _as_text(display_priority.get("mode"), fallback="Unknown")
    display_headline = _as_text(display_priority.get("headline"), fallback="Unknown")
    display_message = _as_text(display_priority.get("primary_message"), fallback="Unknown")

    error_context = coding_pack.get("error_context", {}) if isinstance(coding_pack.get("error_context"), dict) else {}
    has_errors = bool(error_context.get("has_error_signals", False))
    error_summary = _as_text(error_context.get("summary"), fallback="No error summary available")

    lines = [
        "CONTEXT PACK PROMPT PREVIEW",
        "",
        "Use the following local coding context to improve continuity and prioritization.",
        "",
        "[CODING CONTEXT]",
        f"- Current branch: {branch}",
        f"- Git recommendation: {git_recommendation}",
        f"- Current file: {current_file}",
        f"- Recent modified files: {recent_modified}",
        f"- Active task: {active_task_text}",
        f"- Latest display priority: mode={display_mode}; headline={display_headline}; message={display_message}",
        f"- Error context: has_error_signals={has_errors}; summary={error_summary}",
        "",
        "Use this context as supplementary signal. Do not override image evidence.",
    ]
    return "\n".join(lines)


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    coding_pack = _safe_load_json(CODING_CONTEXT_PACK_PATH)
    latest_response = _safe_load_json(LATEST_RESPONSE_PATH)

    preview = _build_preview(coding_pack, latest_response)
    OUTPUT_PATH.write_text(preview, encoding="utf-8")
    print(preview)
    print()
    print(f"Wrote: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
