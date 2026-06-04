from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


BASE_DIR = Path(__file__).resolve().parent
NGROK_FALLBACK = Path(
    r"C:\Users\jesse\Downloads\ngrok-v3-stable-windows-amd64\ngrok.exe"
)
NGROK_GLOBAL_CONFIG = Path(r"C:\Users\jesse\AppData\Local\ngrok\ngrok.yml")

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
# No separate display server — glasses_display_mock.html is served by the FastAPI app.
DEMO_NORMAL_COMMAND = [
    sys.executable,
    str(BASE_DIR / "glasses_demo.py"),
    "--scenario",
    "normal",
]
NGROK_API_URL = "http://127.0.0.1:4040/api/tunnels"


def _write_ngrok_config(tmp_dir: str) -> str:
    """Write a temporary ngrok config that starts the API tunnel."""
    config_path = Path(tmp_dir) / "ngrok_tunnels.yml"
    config_path.write_text(
        'version: "2"\n'
        "tunnels:\n"
        "  api:\n"
        "    proto: http\n"
        "    addr: 8001\n",
        encoding="utf-8",
    )
    return str(config_path)


def _find_ngrok() -> str | None:
    """Return the resolved ngrok executable path, or None if not found."""
    on_path = shutil.which("ngrok")
    if on_path:
        return on_path
    if NGROK_FALLBACK.is_file():
        return str(NGROK_FALLBACK)
    return None


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

    return api_tunnel_url, api_tunnel_url  # single tunnel serves both display and API


def _fetch_tunnel_urls() -> tuple[str, str]:
    deadline = time.time() + 15
    last_error = ""

    while time.time() < deadline:
        try:
            payload = _load_ngrok_tunnels()
            api_tunnel_url, display_tunnel_url = _extract_https_urls(payload)
            if api_tunnel_url:
                return api_tunnel_url, display_tunnel_url
            last_error = "ngrok tunnels found, but HTTPS URL for port 8001 was not available yet."
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
    ngrok_exe = _find_ngrok()
    if ngrok_exe is None:
        print(
            "ngrok was not found on PATH or at the fallback location:\n"
            f"  {NGROK_FALLBACK}\n"
            "Install ngrok separately, place ngrok.exe on PATH or at the fallback path, and rerun this launcher."
        )
        return 1

    api_process: subprocess.Popen[str] | None = None
    ngrok_process: subprocess.Popen[str] | None = None
    tmp_dir = tempfile.mkdtemp()

    try:
        ngrok_config = _write_ngrok_config(tmp_dir)
        ngrok_command = [ngrok_exe, "start", "--all", "--config", str(NGROK_GLOBAL_CONFIG), "--config", ngrok_config]

        api_process = _start_process(API_COMMAND)
        ngrok_process = _start_process(ngrok_command)

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
            if ngrok_process.poll() is not None:
                print(f"ngrok exited with code {ngrok_process.returncode}")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _terminate_process(ngrok_process)
        _terminate_process(api_process)
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())