"""watch_latest_image.py — COMPATIBILITY / PROTOTYPE SCRIPT

This file preserves the original direct single-image analysis workflow for
backward compatibility and historical verification.

It is not the canonical backend startup path, must not be used for new
Investigation Session development, and remains temporarily to support older
single-image scripts and manual verification flows.

CANONICAL BACKEND STARTUP COMMAND:
    .\venv\Scripts\python.exe code\prototype_v1\start_assistant.py
"""

from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import base64
import os
import sys
import re
import json
from typing import Any

from context_aware_prompt import build_prompt
from fix_writer import save_latest_fix
from memory_manager import save_observation, update_active_task
from voice_readout import speak_latest_response


def _extract_task_fields(analysis_text):
    """Parse ACTIVE TASK fields from model output with safe fallbacks.

    The prompt requests labeled lines, so we parse by label and default to
    "Unknown" if any field is missing.
    """
    fields = {
        "current_task": "Unknown",
        "last_completed_step": "Unknown",
        "next_recommended_step": "Unknown",
    }

    patterns = {
        "current_task": r"Current\s+task\s*:\s*(.+)",
        "last_completed_step": r"Last\s+completed\s+step\s*:\s*(.+)",
        "next_recommended_step": r"Next\s+recommended\s+step\s*:\s*(.+)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, analysis_text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value:
                fields[key] = value

    return fields


def _safe_text(value, fallback="Unknown"):
    text = str(value).strip() if value is not None else ""
    return text if text else fallback


def _join_items(values, limit=5):
    if not isinstance(values, list):
        return "None"
    items = [str(item).strip() for item in values if str(item).strip()]
    if not items:
        return "None"
    return ", ".join(items[:limit])


def _load_coding_context_pack_text():
    context_pack_path = Path(__file__).resolve().parent / "results" / "coding_context_pack.json"
    if not context_pack_path.exists() or not context_pack_path.is_file():
        return ""

    try:
        payload = json.loads(context_pack_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""

    if not isinstance(payload, dict):
        return ""

    git_intelligence = payload.get("git_intelligence", {}) if isinstance(payload.get("git_intelligence"), dict) else {}
    vscode_context = payload.get("vscode_context", {}) if isinstance(payload.get("vscode_context"), dict) else {}
    session_summary = payload.get("session_memory_summary", {}) if isinstance(payload.get("session_memory_summary"), dict) else {}
    active_task = session_summary.get("active_task", {}) if isinstance(session_summary.get("active_task"), dict) else {}
    latest_summary = payload.get("latest_response_summary", {}) if isinstance(payload.get("latest_response_summary"), dict) else {}
    error_context = payload.get("error_context", {}) if isinstance(payload.get("error_context"), dict) else {}

    lines = [
        f"- Current branch: {_safe_text(payload.get('branch'))}",
        f"- Git recommendation: {_safe_text(git_intelligence.get('recommendation'), fallback='No recommendation')}",
        f"- Current file: {_safe_text(vscode_context.get('current_file'), fallback='Unknown file')}",
        f"- Recent modified files: {_join_items(vscode_context.get('recent_modified_files', []), limit=5)}",
        f"- Active task: {_safe_text(active_task.get('current_task'), fallback='Unknown task')}",
        (
            "- Latest display priority: "
            f"mode={_safe_text(latest_summary.get('priority_mode'))}; "
            f"headline={_safe_text(latest_summary.get('priority_headline'))}; "
            f"message={_safe_text(latest_summary.get('priority_message'))}"
        ),
        f"- Error context summary: {_safe_text(error_context.get('summary'), fallback='No error summary available')}",
    ]
    return "\n".join(lines)

# Load .env from project root
env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(env_path)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Ensure image path was provided
if len(sys.argv) < 2:
    raise ValueError("Please provide an image path.")

image_path = Path(sys.argv[1])

if not image_path.exists():
    raise FileNotFoundError(f"Image not found: {image_path}")

# Determine MIME type
mime_type = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}[image_path.suffix.lower()]

# Read image
with open(image_path, "rb") as image_file:
    base64_image = base64.b64encode(image_file.read()).decode("utf-8")

# Build context-aware prompt
coding_context_pack_text = _load_coding_context_pack_text()
prompt = build_prompt(supplementary_coding_context=coding_context_pack_text)

input_payload: Any = [
    {
        "role": "user",
        "content": [
            {
                "type": "input_text",
                "text": prompt,
            },
            {
                "type": "input_image",
                "image_url": f"data:{mime_type};base64,{base64_image}",
            },
        ],
    }
]

# Send to OpenAI
response = client.responses.create(
    model="gpt-4.1-mini",
    input=input_payload,
)

analysis_text = response.output_text
save_latest_fix(image_path.name, analysis_text)

# Save observation and then attach extracted task continuity fields.
save_observation(image_path.name, analysis_text)

task_fields = _extract_task_fields(analysis_text)
update_active_task(
    task_fields["current_task"],
    task_fields["last_completed_step"],
    task_fields["next_recommended_step"],
)

try:
    spoke, detail = speak_latest_response(print_message=True)
    if not spoke:
        print(f"Warning: Automatic voice readout unavailable: {detail}")
except Exception as exc:
    print(f"Warning: Automatic voice readout failed: {exc}")

print(f"\nAnalyzing image: {image_path.name}")
print("\n=== CONTEXT-AWARE TASK GUIDANCE ===\n")
print(analysis_text)