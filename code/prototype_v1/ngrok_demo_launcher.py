from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


BASE_DIR = Path(__file__).resolve().parent
API_COMMAND = [
    sys.executable,
    "-m",
    "uvicorn",
    "api:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8001",
    "--app-dir",
    str(BASE_DIR),
]
DISPLAY_COMMAND = [
    sys.executable,
    "-m",
    "http.server",
    "8002",
    "--directory",
    str(BASE_DIR),
]
API_TUNNEL_COMMAND = ["ngrok", "http", "8001"]
DISPLAY_TUNNEL_COMMAND = ["ngrok", "http", "8002"]
DEMO_NORMAL_COMMAND = [
    sys.executable,
    str(BASE_DIR / "glasses_demo.py"),
    "--scenario",
    "normal",
]
NGROK_API_URL = "http://127.0.0.1:4040/api/tunnels"


def _start_process(command: list[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(command, cwd=str(BASE_DIR))


def _terminate_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _load_ngrok_tunnels() -> dict[str, Any]:
    with urlopen(NGROK_API_URL, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def _extract_https_urls(payload: dict[str, Any]) -> tuple[str, str]:
    api_tunnel_url = ""
    display_tunnel_url = ""

    tunnels = payload.get("tunnels", []) if isinstance(payload, dict) else []
    for tunnel in tunnels:
        if not isinstance(tunnel, dict):
            continue

        public_url = str(tunnel.get("public_url", "")).strip()
        config = tunnel.get("config", {}) if isinstance(tunnel.get("config"), dict) else {}
        addr = str(config.get("addr", "")).strip().lower()

        if not public_url.startswith("https://"):
            continue

        if addr.endswith(":8001") and not api_tunnel_url:
            api_tunnel_url = public_url.rstrip("/")
        if addr.endswith(":8002") and not display_tunnel_url:
            display_tunnel_url = public_url.rstrip("/")

    return api_tunnel_url, display_tunnel_url


def _fetch_tunnel_urls() -> tuple[str, str]:
    deadline = time.time() + 15
    last_error = ""

    while time.time() < deadline:
        try:
            payload = _load_ngrok_tunnels()
            api_tunnel_url, display_tunnel_url = _extract_https_urls(payload)
            if api_tunnel_url and display_tunnel_url:
                return api_tunnel_url, display_tunnel_url
            last_error = "ngrok tunnels found, but HTTPS URLs for ports 8001 and 8002 were not both available yet."
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(exc)

        time.sleep(1)

    troubleshooting = [
        "ngrok local API was unavailable or incomplete.",
        f"Checked: {NGROK_API_URL}",
        "Verify ngrok started successfully and its local inspector is enabled.",
        "Verify both tunnels are running for ports 8001 and 8002.",
    ]
    if last_error:
        troubleshooting.append(f"Last error: {last_error}")

    print("\n".join(troubleshooting))
    return "", ""


def main() -> int:
    if shutil.which("ngrok") is None:
        print("ngrok is not available on PATH. Install ngrok separately, ensure it is on PATH, and rerun this launcher.")
        return 1

    api_process: subprocess.Popen[str] | None = None
    display_process: subprocess.Popen[str] | None = None
    api_tunnel_process: subprocess.Popen[str] | None = None
    display_tunnel_process: subprocess.Popen[str] | None = None

    try:
        api_process = _start_process(API_COMMAND)
        display_process = _start_process(DISPLAY_COMMAND)
        api_tunnel_process = _start_process(API_TUNNEL_COMMAND)
        display_tunnel_process = _start_process(DISPLAY_TUNNEL_COMMAND)

        time.sleep(3)
        api_tunnel_url, display_tunnel_url = _fetch_tunnel_urls()
        if not api_tunnel_url or not display_tunnel_url:
            return 1

        final_display_url = f"{display_tunnel_url}/glasses_display_mock.html?api={api_tunnel_url}/latest"
        demo_result = subprocess.run(DEMO_NORMAL_COMMAND, cwd=str(BASE_DIR), check=False)

        print("NGROK DEMO LAUNCHER")
        print()
        print(f"API tunnel URL: {api_tunnel_url}")
        print(f"Display tunnel URL: {display_tunnel_url}")
        print(f"Final display URL: {final_display_url}")
        print("Test command: python code/prototype_v1/glasses_demo.py --scenario error")
        print(f"glasses_demo.py --scenario normal exited with code {demo_result.returncode}")
        print("Press Ctrl+C to stop the local servers and ngrok tunnels.")

        while True:
            if api_process.poll() is not None:
                print(f"API server exited with code {api_process.returncode}")
                break
            if display_process.poll() is not None:
                print(f"Display server exited with code {display_process.returncode}")
                break
            if api_tunnel_process.poll() is not None:
                print(f"ngrok API tunnel exited with code {api_tunnel_process.returncode}")
                break
            if display_tunnel_process.poll() is not None:
                print(f"ngrok display tunnel exited with code {display_tunnel_process.returncode}")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _terminate_process(api_tunnel_process)
        _terminate_process(display_tunnel_process)
        _terminate_process(api_process)
        _terminate_process(display_process)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())