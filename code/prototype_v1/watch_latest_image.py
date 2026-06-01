from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import base64
import os
import sys

env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(env_path)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

if len(sys.argv) < 2:
    raise ValueError("Please provide an image path.")

image_path = Path(sys.argv[1])

if not image_path.exists():
    raise FileNotFoundError(f"Image not found: {image_path}")

mime_type = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}[image_path.suffix.lower()]

with open(image_path, "rb") as image_file:
    base64_image = base64.b64encode(image_file.read()).decode("utf-8")

prompt = """
You are a wearable AI assistant for Meta Ray-Ban Display glasses.

Analyze this image as if the user is looking at it through smart glasses.

Return:
1. What the user appears to be looking at
2. What task the user may be trying to complete
3. The next 3 practical steps the user should take
4. Any warnings or risks you notice

Keep the answer concise and useful.
"""

response = client.responses.create(
    model="gpt-4.1-mini",
    input=[
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {
                    "type": "input_image",
                    "image_url": f"data:{mime_type};base64,{base64_image}",
                },
            ],
        }
    ],
)

print(f"\nAnalyzing image: {image_path.name}")
print("\n=== TASK GUIDANCE ===\n")
print(response.output_text)