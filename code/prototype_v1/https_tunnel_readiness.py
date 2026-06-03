from __future__ import annotations

import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
OUTPUT_PATH = RESULTS_DIR / "https_tunnel_readiness.json"

LOCAL_API_COMMAND = "python -m uvicorn api:app --host 0.0.0.0 --port 8001 --app-dir code/prototype_v1"
LOCAL_DISPLAY_COMMAND = "python -m http.server 8002 --bind 0.0.0.0 --directory code/prototype_v1"
EXAMPLE_DISPLAY_URL = (
    "https://<DISPLAY_TUNNEL_HOST>/glasses_display_mock.html"
    "?api=https://<API_TUNNEL_HOST>/latest"
)

META_DISPLAY_NOTES = [
    "Meta Ray-Ban Display Web App testing needs HTTPS URLs instead of plain local HTTP endpoints.",
    "A tunnel makes the phone-accessible page and API reachable from outside the local machine.",
    "Using a separate HTTPS URL for the API keeps the existing glasses_display_mock.html query-parameter override path intact.",
    "Do not expose local services until both local ports respond correctly on the LAN first.",
]

SUCCESS_CRITERIA = [
    "FastAPI responds locally at http://127.0.0.1:8001/latest.",
    "Display page responds locally at http://127.0.0.1:8002/glasses_display_mock.html.",
    "An HTTPS tunnel exists for port 8001 and forwards to the local API.",
    "An HTTPS tunnel exists for port 8002 and forwards to the local display page.",
    "Opening the display HTTPS URL with ?api=https://<API_TUNNEL_HOST>/latest loads live data instead of the waiting state.",
]


def build_readiness_payload() -> dict[str, object]:
    return {
        "local_api_command": LOCAL_API_COMMAND,
        "local_display_command": LOCAL_DISPLAY_COMMAND,
        "api_tunnel_needed": True,
        "display_tunnel_needed": True,
        "example_display_url_with_api_param": EXAMPLE_DISPLAY_URL,
        "meta_display_notes": META_DISPLAY_NOTES,
        "success_criteria": SUCCESS_CRITERIA,
        "setup_steps": [
            "1. Start the FastAPI backend on 0.0.0.0:8001.",
            f"   {LOCAL_API_COMMAND}",
            "2. Start the display web server on 0.0.0.0:8002.",
            f"   {LOCAL_DISPLAY_COMMAND}",
            "3. Create an HTTPS tunnel for port 8001 with your preferred tunnel tool.",
            "   Example patterns: ngrok http 8001  |  cloudflared tunnel --url http://127.0.0.1:8001",
            "4. Create an HTTPS tunnel for port 8002 with your preferred tunnel tool.",
            "   Example patterns: ngrok http 8002  |  cloudflared tunnel --url http://127.0.0.1:8002",
            "5. Open the display tunnel URL and pass the HTTPS API URL through the api query parameter.",
            f"   {EXAMPLE_DISPLAY_URL}",
            "6. Confirm the display page renders current payload data from /latest over HTTPS.",
        ],
    }


def write_payload(payload: dict[str, object]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def print_guide(payload: dict[str, object]) -> None:
    print("HTTPS TUNNEL READINESS")
    print()
    for step in payload.get("setup_steps", []):
        print(step)
    print()
    print("Why HTTPS matters:")
    for note in payload.get("meta_display_notes", []):
        print(f"- {note}")


def main() -> None:
    payload = build_readiness_payload()
    write_payload(payload)
    print_guide(payload)


if __name__ == "__main__":
    main()