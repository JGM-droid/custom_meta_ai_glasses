from __future__ import annotations

from pathlib import Path
import json
import platform
import subprocess
import sys


BASE_DIR = Path(__file__).resolve().parent
LATEST_RESPONSE_PATH = BASE_DIR / "results" / "latest_response.json"


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _message_from_payload(payload: dict) -> str:
    glasses_guidance = _clean_text(payload.get("glasses_guidance"))
    if glasses_guidance:
        return glasses_guidance

    intervention = payload.get("intervention", {})
    if isinstance(intervention, dict):
        intervention_message = _clean_text(intervention.get("message"))
        if intervention_message:
            return intervention_message

    task_progress = payload.get("task_progress", {})
    if isinstance(task_progress, dict):
        next_step = _clean_text(task_progress.get("next_step"))
        if next_step:
            return next_step

    return "No guidance is currently available in latest_response.json."


def _speak_with_pyttsx3(message: str) -> bool:
    try:
        import pyttsx3  # type: ignore
    except Exception:
        return False

    try:
        engine = pyttsx3.init()
        engine.say(message)
        engine.runAndWait()
        return True
    except Exception:
        return False


def _speak_with_windows_sapi(message: str) -> bool:
    if platform.system().lower() != "windows":
        return False

    # Escape single quotes for PowerShell single-quoted strings.
    escaped = message.replace("'", "''")
    command = (
        "Add-Type -AssemblyName System.Speech; "
        "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$speaker.Speak('{escaped}')"
    )

    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _speak_message(message: str) -> bool:
    if _speak_with_pyttsx3(message):
        return True

    if _speak_with_windows_sapi(message):
        return True

    return False


def main() -> None:
    if not LATEST_RESPONSE_PATH.exists():
        print(f"Missing file: {LATEST_RESPONSE_PATH}")
        print("Run an analysis first so latest_response.json is available.")
        sys.exit(1)

    try:
        payload = json.loads(LATEST_RESPONSE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in latest_response.json: {exc}")
        sys.exit(1)

    if not isinstance(payload, dict):
        print("latest_response.json must contain a JSON object.")
        sys.exit(1)

    message = _message_from_payload(payload)
    print(f"Speaking: {message}")

    spoke = _speak_message(message)
    if not spoke:
        print("Local TTS unavailable. Install pyttsx3 or run on Windows with PowerShell speech support.")
        sys.exit(1)


if __name__ == "__main__":
    main()
