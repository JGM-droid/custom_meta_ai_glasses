"""ngrok_demo_launcher.py — LEGACY — DO NOT RUN

LEGACY WARNING — NOT PART OF THE V16+ CANONICAL RUNTIME
========================================================
This file is a pre-V16 ngrok-based demo launcher. It is quarantined and
must not be run as part of normal development or hardware validation workflows.
The tunnel function it provided is now handled by Cloudflare (cloudflared).

RISKS IF RUN:
  - Starts uvicorn on :8001 using sys.executable (not the venv Python),
    bypassing all V16 single-instance guards.
  - Starts ngrok, which conflicts with the active Cloudflare tunnel.
  - Runs glasses_demo.py --scenario normal, which writes resume_now.json
    and races against the canonical pipeline writer.
  - Creates duplicate runtime chains that break the V16 artifact-ownership model.

CANONICAL STARTUP COMMAND:
    .\\venv\\Scripts\\python.exe code\\prototype_v1\\start_assistant.py

CANONICAL TUNNEL COMMAND:
  cloudflared.exe tunnel --url http://127.0.0.1:8001

This file must not be used for new Investigation Session development. It
remains temporarily for backward compatibility and historical verification.

Do not run this file. If you must run it for historical reference only,
pass --allow-legacy-run as the first argument.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
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
LOCAL_BASE = "http://127.0.0.1:8001"
DESKTOP_DEBUG_URL = f"{LOCAL_BASE}/glasses_display_mock.html"


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


def _token_suffix() -> str:
    token = os.getenv("GLASSES_API_TOKEN", "").strip()
    if not token:
        return ""
    return f"&token={quote_plus(token)}"


def _build_glasses_hud_url(base_host: str) -> str:
    host = base_host.rstrip("/")
    return f"{host}/glasses?api={host}/glasses/latest{_token_suffix()}"


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

        local_glasses_url = _build_glasses_hud_url(LOCAL_BASE)
        public_glasses_url = _build_glasses_hud_url(display_tunnel_url)
        demo_result = subprocess.run(DEMO_NORMAL_COMMAND, cwd=str(BASE_DIR), check=False)

        print("NGROK DEMO LAUNCHER")
        print()
        print(f"Desktop debug HUD: {DESKTOP_DEBUG_URL}")
        print(f"Local glasses HUD: {local_glasses_url}")
        print(f"Public glasses HUD: {public_glasses_url}")
        print(f"Mock display HUD: {DESKTOP_DEBUG_URL}")
        print()
        print(f"API tunnel URL: {api_tunnel_url}")
        print(f"Display tunnel URL: {display_tunnel_url}")
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
    import sys as _sys

    if "--allow-legacy-run" not in _sys.argv:
        print(
            "\n"
            "LEGACY FILE — BLOCKED\n"
            "=====================\n"
            "Support tier: DEPRECATED\n"
            "ngrok_demo_launcher.py is not part of the V16+ canonical runtime.\n"
            "\n"
            "Running it would:\n"
            "  - Start a duplicate uvicorn on :8001 using the wrong Python interpreter\n"
            "  - Start ngrok, conflicting with the active Cloudflare tunnel\n"
            "  - Write resume_now.json, racing against the canonical pipeline\n"
            "  - Bypass all V16 single-instance guards\n"
            "\n"
            "Canonical startup command:\n"
            "  .\\\\venv\\\\Scripts\\\\python.exe code\\\\prototype_v1\\\\start_assistant.py\n"
            "\n"
            "Canonical tunnel command:\n"
            "  cloudflared.exe tunnel --url http://127.0.0.1:8001\n"
            "\n"
            "To override (not recommended):\n"
            "  python ngrok_demo_launcher.py --allow-legacy-run\n",
            file=_sys.stderr,
        )
        raise SystemExit(1)

    raise SystemExit(main())