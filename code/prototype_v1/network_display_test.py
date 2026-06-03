from __future__ import annotations

from pathlib import Path
import json
import socket
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
OUTPUT_PATH = RESULTS_DIR / "network_display_test.json"


def _detect_local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No external traffic is sent; this only selects the local interface.
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        sock.close()
    return ip


def _build_payload(local_ip: str) -> dict[str, Any]:
    api_latest_url = f"http://{local_ip}:8001/latest"
    display_mock_url = f"http://{local_ip}:8002/glasses_display_mock.html"

    return {
        "local_ip": local_ip,
        "server_command": "python -m uvicorn api:app --host 0.0.0.0 --port 8001 --app-dir code/prototype_v1",
        "display_host_command": "python -m http.server 8002 --directory code/prototype_v1",
        "api_latest_url": api_latest_url,
        "glasses_display_mock_url": display_mock_url,
        "checklist": [
            "PC and glasses/phone are on same Wi-Fi",
            "API server is running on 0.0.0.0",
            "Windows firewall allows port 8001",
            "Open display URL from phone/glasses browser",
        ],
    }


def _write_output(payload: dict[str, Any]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _print_summary(payload: dict[str, Any]) -> None:
    print("Network Glasses Display Test")
    print()
    print("Run API server with:")
    print(payload.get("server_command", ""))
    print()
    print("Optional command to host display mock for phone/glasses browser:")
    print(payload.get("display_host_command", ""))
    print()
    print("API latest URL:")
    print(payload.get("api_latest_url", ""))
    print()
    print("Glasses display mock URL:")
    print(payload.get("glasses_display_mock_url", ""))
    print()
    print("Checklist:")
    for item in payload.get("checklist", []):
        print(f"- {item}")
    print()
    print(f"Wrote: {OUTPUT_PATH}")


def main() -> None:
    local_ip = _detect_local_ip()
    payload = _build_payload(local_ip)
    _write_output(payload)
    _print_summary(payload)


if __name__ == "__main__":
    main()
