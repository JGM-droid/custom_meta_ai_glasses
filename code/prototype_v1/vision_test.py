from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import os

# Find the .env file in the project root
env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(env_path)

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

response = client.responses.create(
    model="gpt-4.1-mini",
    input="You are an AI assistant running on Meta Ray-Ban Display glasses. Introduce yourself in one sentence."
)

print(response.output_text)