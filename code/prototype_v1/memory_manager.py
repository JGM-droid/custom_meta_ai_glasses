from pathlib import Path
import json
from datetime import datetime

MEMORY_FILE = Path(__file__).parent / "results" / "session_memory.json"


def get_default_memory():
    """Return the default memory structure."""
    return {
        "active_task": {
            "current_task": "Unknown",
            "last_completed_step": "Unknown",
            "next_recommended_step": "Unknown",
        },
        "observations": [],
    }


def load_memory():
    """Load memory from disk.

    Supports both the new dictionary-based memory format and the older
    list-based format used earlier in the prototype.
    """
    if not MEMORY_FILE.exists():
        return get_default_memory()

    with open(MEMORY_FILE, "r", encoding="utf-8") as file:
        data = json.load(file)

    if isinstance(data, list):
        return {
            "active_task": {
                "current_task": "Unknown",
                "last_completed_step": "Unknown",
                "next_recommended_step": "Unknown",
            },
            "observations": data[-5:],
        }

    return data


def write_memory(memory):
    """Write memory to disk."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(MEMORY_FILE, "w", encoding="utf-8") as file:
        json.dump(memory, file, indent=2)


def save_observation(image_name, analysis_text):
    """Save a new visual observation."""
    memory = load_memory()

    observation = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "image_name": image_name,
        "analysis": analysis_text,
    }

    memory["observations"].append(observation)
    memory["observations"] = memory["observations"][-5:]

    write_memory(memory)


def get_active_task():
    """Return the current active task."""
    memory = load_memory()
    return memory.get("active_task", get_default_memory()["active_task"])


def update_active_task(task_name, completed_step, next_step):
    """Update the current active task."""
    memory = load_memory()

    memory["active_task"] = {
        "current_task": task_name or "Unknown",
        "last_completed_step": completed_step or "Unknown",
        "next_recommended_step": next_step or "Unknown",
    }

    write_memory(memory)


def get_task_summary():
    """Build an ACTIVE TASK block for prompt injection."""
    active_task = get_active_task()

    return (
        f"Current task: {active_task['current_task']}\n"
        f"Last completed step: {active_task['last_completed_step']}\n"
        f"Next recommended step: {active_task['next_recommended_step']}"
    )


def format_recent_memory():
    """Format recent observations for prompt injection."""
    memory = load_memory()
    observations = memory.get("observations", [])

    if not observations:
        return "No previous observations yet."

    formatted = []

    for item in observations:
        formatted.append(
            f"- Time: {item['timestamp']}\n"
            f"  Image: {item['image_name']}\n"
            f"  Analysis: {item['analysis']}"
        )

    return "\n\n".join(formatted)