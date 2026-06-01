from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import base64
import os
import sys

from context_aware_prompt import build_prompt
from memory_manager import save_observation

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

# Send to OpenAI
response = client.responses.create(
    model="gpt-4.1-mini",
    input=[
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
    ],
)

analysis_text = response.output_text

# Save observation to memory
save_observation(image_path.name, analysis_text)

print(f"\nAnalyzing image: {image_path.name}")
print("\n=== CONTEXT-AWARE TASK GUIDANCE ===\n")
print(analysis_text)