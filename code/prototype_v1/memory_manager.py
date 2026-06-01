from pathlib import Path
import json
from datetime import datetime

MEMORY_FILE = Path(__file__).parent / "results" / "session_memory.json"


def load_memory():
    if not MEMORY_FILE.exists():
        return []

    with open(MEMORY_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def save_observation(image_name, analysis_text):
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    memory = load_memory()

    observation = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "image_name": image_name,
        "analysis": analysis_text,
    }

    memory.append(observation)

    memory = memory[-5:]

    with open(MEMORY_FILE, "w", encoding="utf-8") as file:
        json.dump(memory, file, indent=2)


def format_recent_memory():
    memory = load_memory()

    if not memory:
        return "No previous observations yet."

    formatted = []

    for item in memory:
        formatted.append(
            f"- Time: {item['timestamp']}\n"
            f"  Image: {item['image_name']}\n"
            f"  Analysis: {item['analysis']}"
        )

    return "\n\n".join(formatted)