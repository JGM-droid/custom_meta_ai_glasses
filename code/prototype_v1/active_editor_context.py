from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
INPUT_PATH = RESULTS_DIR / "active_editor_state.json"
OUTPUT_PATH = RESULTS_DIR / "active_editor_context.json"


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def build_active_editor_context() -> dict[str, Any]:
    raw_state = _safe_load_json(INPUT_PATH)
    signal_available = bool(raw_state)

    return {
        "source": "active_editor_state.json",
        "signal_available": signal_available,
        "active_file_path": str(raw_state.get("active_file_path", "") or ""),
        "active_file_name": str(raw_state.get("active_file_name", "") or ""),
        "language_id": str(raw_state.get("language_id", "") or ""),
        "is_dirty": bool(raw_state.get("is_dirty", False)),
        "workspace_name": str(raw_state.get("workspace_name", "") or ""),
        "event_type": str(raw_state.get("event_type", "") or ""),
        "state_timestamp": str(raw_state.get("timestamp", "") or ""),
        "context_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def write_active_editor_context(context: dict[str, Any]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(context, indent=2), encoding="utf-8")


def main() -> None:
    context = build_active_editor_context()
    write_active_editor_context(context)

    if "--test" in sys.argv[1:]:
        print("ACTIVE EDITOR CONTEXT TEST")
        print(json.dumps(context, indent=2))
        print(f"Wrote: {OUTPUT_PATH}")
        return

    print(json.dumps(context, indent=2))


if __name__ == "__main__":
    main()