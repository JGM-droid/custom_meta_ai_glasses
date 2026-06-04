from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from active_editor_context import build_active_editor_context, write_active_editor_context
except Exception:
    build_active_editor_context = None  # type: ignore[assignment]
    write_active_editor_context = None  # type: ignore[assignment]


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
TERMINAL_ERROR_PATH = RESULTS_DIR / "terminal_error_context.json"
CODING_CONTEXT_PATH = RESULTS_DIR / "coding_context_pack.json"
SESSION_SNAPSHOT_PATH = RESULTS_DIR / "coding_session_snapshot.json"
ACTIVE_EDITOR_CONTEXT_PATH = RESULTS_DIR / "active_editor_context.json"
OUTPUT_PATH = RESULTS_DIR / "context_fusion.json"


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _as_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_text(value: Any, fallback: str = "unknown") -> str:
    text = str(value).strip() if value is not None else ""
    return text if text else fallback


def _default_guidance(source: str, headline: str, message: str, recommended_action: str, level: str = "info") -> dict[str, str]:
    return {
        "level": level,
        "source": source,
        "headline": headline,
        "message": message,
        "recommended_action": recommended_action,
    }


def _load_terminal_error_context() -> dict[str, Any]:
    payload = _safe_load_json(TERMINAL_ERROR_PATH)
    if not payload:
        return {}

    guidance = payload.get("guidance_priority")
    if isinstance(guidance, dict):
        payload["guidance_priority"] = guidance
    else:
        payload["guidance_priority"] = _default_guidance(
            source="terminal_error_context",
            headline="No Terminal Error",
            message="No terminal error context is available.",
            recommended_action="Continue current implementation.",
        )
    return payload


def _load_coding_context() -> dict[str, Any]:
    payload = _safe_load_json(CODING_CONTEXT_PATH)
    if not payload:
        return {}
    return payload


def _load_snapshot_context() -> dict[str, Any]:
    payload = _safe_load_json(SESSION_SNAPSHOT_PATH)
    if not payload:
        return {}
    return payload


def _load_active_editor_context() -> dict[str, Any]:
    payload = _safe_load_json(ACTIVE_EDITOR_CONTEXT_PATH)
    if not payload:
        return {}
    return payload


def _refresh_active_editor_context() -> None:
    """Refresh active_editor_context.json from active_editor_state.json when helpers are importable."""
    if not callable(build_active_editor_context) or not callable(write_active_editor_context):
        return

    try:
        context = build_active_editor_context()
        if isinstance(context, dict):
            write_active_editor_context(context)
    except Exception:
        # Context fusion must remain resilient even if active editor refresh fails.
        return


def _active_file_payload(active_editor_context: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    if not active_editor_context:
        return False, {
            "active_file_name": "",
            "active_file_path": "",
            "language_id": "",
            "is_dirty": False,
            "event_type": "",
        }

    return True, {
        "active_file_name": _as_text(active_editor_context.get("active_file_name"), ""),
        "active_file_path": _as_text(active_editor_context.get("active_file_path"), ""),
        "language_id": _as_text(active_editor_context.get("language_id"), ""),
        "is_dirty": bool(active_editor_context.get("is_dirty", False)),
        "event_type": _as_text(active_editor_context.get("event_type"), ""),
    }


def _snapshot_guidance(snapshot: dict[str, Any]) -> dict[str, str]:
    modified_files = _as_int(snapshot.get("modified_files"), 0)
    staged_files = _as_int(snapshot.get("staged_files"), 0)

    if modified_files > 0 or staged_files > 0:
        return _default_guidance(
            source="snapshot_context",
            headline="Review Working Tree",
            message="Local changes are present in the working tree.",
            recommended_action="Review the modified and staged files before continuing.",
            level="medium",
        )

    return _default_guidance(
        source="snapshot_context",
        headline="Continue Implementation",
        message="No local file churn is present in the snapshot.",
        recommended_action="Continue current implementation.",
        level="info",
    )


def _git_guidance(coding_context: dict[str, Any]) -> dict[str, str]:
    guidance = coding_context.get("guidance_priority")
    if isinstance(guidance, dict):
        return {
            "level": _as_text(guidance.get("level"), "info"),
            "source": _as_text(guidance.get("source"), "git_intelligence"),
            "headline": _as_text(guidance.get("headline"), "Review Git State"),
            "message": _as_text(guidance.get("message"), "Git risk requires attention."),
            "recommended_action": _as_text(guidance.get("recommended_action"), "Review git status before continuing."),
        }

    git_intelligence = coding_context.get("git_intelligence") if isinstance(coding_context.get("git_intelligence"), dict) else {}
    risk_level = _as_text(git_intelligence.get("risk_level"), "low").lower()
    recommendation = _as_text(git_intelligence.get("recommendation"), "Review Git State")
    reason = _as_text(git_intelligence.get("reason"), "Git changes require attention.")
    next_command = _as_text(git_intelligence.get("next_command"), "")

    recommended_action = recommendation
    if next_command:
        recommended_action = f"{recommendation}. Run: {next_command}"

    return {
        "level": "high" if risk_level in {"medium", "high"} else "info",
        "source": "git_intelligence",
        "headline": recommendation,
        "message": reason,
        "recommended_action": recommended_action,
    }


def _select_context(
    terminal_error: dict[str, Any],
    coding_context: dict[str, Any],
    snapshot: dict[str, Any],
) -> tuple[str, dict[str, str]]:
    has_terminal_error = bool(terminal_error.get("has_terminal_error", False))
    if has_terminal_error:
        guidance = terminal_error.get("guidance_priority") if isinstance(terminal_error.get("guidance_priority"), dict) else {}
        return "terminal_error_context", {
            "level": _as_text(guidance.get("level"), "critical"),
            "source": _as_text(guidance.get("source"), "terminal_error_context"),
            "headline": _as_text(guidance.get("headline"), "Terminal Error Detected"),
            "message": _as_text(guidance.get("message"), _as_text(terminal_error.get("summary"), "Terminal error detected.")),
            "recommended_action": _as_text(guidance.get("recommended_action"), _as_text(terminal_error.get("recommended_action"), "Resolve the terminal error first.")),
        }

    git_intelligence = coding_context.get("git_intelligence") if isinstance(coding_context.get("git_intelligence"), dict) else {}
    git_risk = _as_text(git_intelligence.get("risk_level"), "low").lower()
    if git_risk in {"medium", "high"}:
        return "coding_context_pack", _git_guidance(coding_context)

    modified_files = _as_int(snapshot.get("modified_files"), 0)
    staged_files = _as_int(snapshot.get("staged_files"), 0)
    if modified_files > 0 or staged_files > 0:
        return "snapshot_context", _snapshot_guidance(snapshot)

    return "fallback", _default_guidance(
        source="fallback",
        headline="Continue Implementation",
        message="No higher-priority local signal is available.",
        recommended_action="Continue current implementation.",
        level="info",
    )


def _build_payload() -> dict[str, Any]:
    _refresh_active_editor_context()

    terminal_error = _load_terminal_error_context()
    coding_context = _load_coding_context()
    snapshot = _load_snapshot_context()
    active_editor_context = _load_active_editor_context()
    active_file_available, active_file = _active_file_payload(active_editor_context)

    selected_source, guidance_priority = _select_context(terminal_error, coding_context, snapshot)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "active_branch": _as_text(
            snapshot.get("git_branch")
            or coding_context.get("branch")
            or coding_context.get("git_branch"),
            "unknown",
        ),
        "modified_files": _as_int(snapshot.get("modified_files"), 0),
        "staged_files": _as_int(snapshot.get("staged_files"), 0),
        "has_terminal_error": bool(terminal_error.get("has_terminal_error", False)),
        "active_file_available": active_file_available,
        "active_file": active_file,
        "selected_source": selected_source,
        "guidance_priority": guidance_priority,
    }


def _write_output(payload: dict[str, Any]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    payload = _build_payload()
    _write_output(payload)
    active_file = payload.get("active_file") if isinstance(payload.get("active_file"), dict) else {}
    active_file_name = _as_text(active_file.get("active_file_name"), "unavailable")
    print("Context Fusion Engine")
    print(f"Selected source: {payload['selected_source']}")
    print(f"Active branch: {payload['active_branch']}")
    print(f"Modified files: {payload['modified_files']}")
    print(f"Staged files: {payload['staged_files']}")
    print("Active File:")
    print(f"- {active_file_name}")
    print(f"Wrote: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()