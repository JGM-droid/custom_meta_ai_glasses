from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
OUTPUT_PATH = RESULTS_DIR / "https_tunnel_test_runner.json"

LOCAL_API_COMMAND = "python -m uvicorn api:app --host 0.0.0.0 --port 8001 --app-dir code/prototype_v1"
LOCAL_DISPLAY_COMMAND = "python -m http.server 8002 --bind 0.0.0.0 --directory code/prototype_v1"


def _clean_url(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().rstrip("/")


def _build_final_display_test_url(api_tunnel_url: str, display_tunnel_url: str) -> str:
    if not api_tunnel_url or not display_tunnel_url:
        return "<DISPLAY_TUNNEL_URL>/glasses_display_mock.html?api=<API_TUNNEL_URL>/latest"
    return f"{display_tunnel_url}/glasses_display_mock.html?api={api_tunnel_url}/latest"


def _placeholder_note() -> str:
    return (
        "Set API_TUNNEL_URL and DISPLAY_TUNNEL_URL in your shell before running this script. "
        "Example: $env:API_TUNNEL_URL='https://your-api-tunnel.example'; "
        "$env:DISPLAY_TUNNEL_URL='https://your-display-tunnel.example'"
    )


def build_payload() -> dict[str, object]:
    api_tunnel_url = _clean_url(os.environ.get("API_TUNNEL_URL"))
    display_tunnel_url = _clean_url(os.environ.get("DISPLAY_TUNNEL_URL"))
    final_display_test_url = _build_final_display_test_url(api_tunnel_url, display_tunnel_url)

    env_present = bool(api_tunnel_url and display_tunnel_url)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "api_tunnel_url": api_tunnel_url or "<API_TUNNEL_URL>",
        "display_tunnel_url": display_tunnel_url or "<DISPLAY_TUNNEL_URL>",
        "final_display_test_url": final_display_test_url,
        "local_api_command": LOCAL_API_COMMAND,
        "local_display_command": LOCAL_DISPLAY_COMMAND,
        "success_criteria": [
            "HTTPS display page loads",
            "Display fetches HTTPS API",
            "Scenario changes update display automatically",
            "No localhost or local IP is required in the final URL",
        ],
        "environment_variables_present": env_present,
        "setup_note": None if env_present else _placeholder_note(),
    }


def write_payload(payload: dict[str, object]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def print_workflow(payload: dict[str, object]) -> None:
    print("HTTPS TUNNEL TEST RUNNER")
    print()
    print("Test workflow:")
    print(f"1. Start local API: {LOCAL_API_COMMAND}")
    print(f"2. Start local display server: {LOCAL_DISPLAY_COMMAND}")
    print("3. Start HTTPS tunnel for API")
    print("4. Start HTTPS tunnel for display")
    print(f"5. Open: {payload['final_display_test_url']}")
    print()

    if payload["environment_variables_present"]:
        print("Environment variables detected.")
        print(f"API_TUNNEL_URL: {payload['api_tunnel_url']}")
        print(f"DISPLAY_TUNNEL_URL: {payload['display_tunnel_url']}")
        print(f"Final test URL: {payload['final_display_test_url']}")
    else:
        print("Environment variables are missing.")
        print(_placeholder_note())
        print("The final URL is shown as a placeholder until both variables are set.")


def main() -> None:
    payload = build_payload()
    write_payload(payload)
    print_workflow(payload)


if __name__ == "__main__":
    main()