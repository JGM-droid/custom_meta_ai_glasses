from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import base64
import os
import sys
import re
from typing import Any

from context_aware_prompt import build_prompt
from memory_manager import save_observation, update_active_task


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
prompt = build_prompt()

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

# Save observation and then attach extracted task continuity fields.
save_observation(image_path.name, analysis_text)

task_fields = _extract_task_fields(analysis_text)
update_active_task(
    task_fields["current_task"],
    task_fields["last_completed_step"],
    task_fields["next_recommended_step"],
)

print(f"\nAnalyzing image: {image_path.name}")
print("\n=== CONTEXT-AWARE TASK GUIDANCE ===\n")
print(analysis_text)