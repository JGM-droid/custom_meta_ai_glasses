from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import base64
import os

# Load .env from project root
env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(env_path)

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

# Path to image
image_path = Path(__file__).parent / "test_images" / "test_image.png"

# Read image and convert to base64
with open(image_path, "rb") as image_file:
    base64_image = base64.b64encode(image_file.read()).decode("utf-8")

response = client.responses.create(
    model="gpt-4.1-mini",
    input=[
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Describe everything you can see in this image."
                },
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{base64_image}"
                }
            ]
        }
    ]
)

print("\n=== IMAGE ANALYSIS ===\n")
print(response.output_text)