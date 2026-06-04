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
API_PORT = 8001
API_LATEST_URL = f"http://127.0.0.1:{API_PORT}/latest"
DESKTOP_URL = f"http://127.0.0.1:{API_PORT}/glasses_display_mock.html"
NGROK_API_URL = "http://127.0.0.1:4040/api/tunnels"

API_COMMAND = [
    sys.executable,
    "-m",
    "uvicorn",
    "api:app",
    "--host",
    "127.0.0.1",
    "--port",
    str(API_PORT),
    "--app-dir",
    str(BASE_DIR),
]
REFRESH_WATCH_COMMAND = [
    sys.executable,
    str(BASE_DIR / "refresh_guidance.py"),
    "--watch",
]


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


def _fetch_processes() -> list[dict[str, Any]]:
    command = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,Name,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []

    raw = (result.stdout or "").strip()
    if not raw:
        return []

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _cmdline(proc: dict[str, Any]) -> str:
    return str(proc.get("CommandLine") or "").lower()


def _name(proc: dict[str, Any]) -> str:
    return str(proc.get("Name") or "").lower()


def _match_api_processes(processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for proc in processes:
        cmd = _cmdline(proc)
        if "uvicorn" in cmd and "8001" in cmd and "api" in cmd:
            matches.append(proc)
    return matches


def _match_refresh_watch_processes(processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for proc in processes:
        cmd = _cmdline(proc)
        if "refresh_guidance.py" in cmd and "--watch" in cmd:
            matches.append(proc)
    return matches


def _match_ngrok_processes(processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for proc in processes:
        cmd = _cmdline(proc)
        name = _name(proc)
        if "ngrok" in name or "ngrok" in cmd:
            matches.append(proc)
    return matches


def _warn_duplicates(label: str, matches: list[dict[str, Any]]) -> None:
    if len(matches) <= 1:
        return

    pids = [str(item.get("ProcessId", "?")) for item in matches]
    print(f"Warning: duplicate {label} processes detected: {', '.join(pids)}")


def _wait_for_api_ready(timeout_seconds: int = 12) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urlopen(API_LATEST_URL, timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _extract_ngrok_https_url(payload: dict[str, Any]) -> str:
    tunnels = payload.get("tunnels", []) if isinstance(payload, dict) else []
    for tunnel in tunnels:
        if not isinstance(tunnel, dict):
            continue

        public_url = str(tunnel.get("public_url", "")).strip()
        if not public_url.startswith("https://"):
            continue

        config = tunnel.get("config", {}) if isinstance(tunnel.get("config"), dict) else {}
        addr = str(config.get("addr", "")).strip().lower()
        if addr.endswith(":8001"):
            return public_url.rstrip("/")
    return ""


def _fetch_ngrok_public_url() -> str:
    try:
        with urlopen(NGROK_API_URL, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError):
        return ""
    return _extract_ngrok_https_url(payload)


def _ngrok_launcher_available() -> bool:
    if (BASE_DIR / "ngrok_demo_launcher.py").is_file():
        return True
    return bool(shutil.which("ngrok"))


def _print_urls(ngrok_url: str) -> None:
    print(f"Desktop URL: {DESKTOP_URL}")
    if ngrok_url:
        print(f"Phone/Glasses URL: {ngrok_url}/glasses_display_mock.html?api={ngrok_url}/latest")
    elif _ngrok_launcher_available():
        print("Phone/Glasses URL: unavailable (ngrok launcher is available, but no active tunnel was detected)")


def main() -> int:
    api_process: subprocess.Popen[str] | None = None
    refresh_process: subprocess.Popen[str] | None = None

    processes = _fetch_processes()
    api_matches = _match_api_processes(processes)
    refresh_matches = _match_refresh_watch_processes(processes)
    ngrok_matches = _match_ngrok_processes(processes)

    _warn_duplicates("uvicorn API", api_matches)
    _warn_duplicates("refresh watcher", refresh_matches)
    _warn_duplicates("ngrok", ngrok_matches)

    try:
        if api_matches:
            print("API: already running on port 8001")
        else:
            print("API: starting")
            api_process = _start_process(API_COMMAND)
            if _wait_for_api_ready(timeout_seconds=12):
                print("API: ready")
            else:
                print("Warning: API did not report ready within timeout")

        if refresh_matches:
            print("Refresh watcher: already running")
        else:
            print("Refresh watcher: starting")
            refresh_process = _start_process(REFRESH_WATCH_COMMAND)

        ngrok_url = _fetch_ngrok_public_url()
        _print_urls(ngrok_url)
        print("Press Ctrl+C to stop child processes started by this launcher.")

        if api_process is None and refresh_process is None:
            return 0

        while True:
            if api_process is not None and api_process.poll() is not None:
                print(f"API process exited with code {api_process.returncode}")
                break
            if refresh_process is not None and refresh_process.poll() is not None:
                print(f"Refresh watcher exited with code {refresh_process.returncode}")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping launcher...")
    finally:
        _terminate_process(refresh_process)
        _terminate_process(api_process)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
