from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from urllib.error import URLError
from urllib.request import urlopen

from artifact_ownership import warn_if_multiple_writers


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent.parent
PYTHON_EXECUTABLE = Path(sys.executable).resolve()
VENV_PYTHON = (
    REPO_ROOT / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
).resolve()
START_ASSISTANT_LOCK = BASE_DIR / "results" / "start_assistant.lock"
API_PORT = 8001
API_LATEST_URL = f"http://127.0.0.1:{API_PORT}/latest"
DESKTOP_URL = f"http://127.0.0.1:{API_PORT}/glasses_display_mock.html"
NGROK_API_URL = "http://127.0.0.1:4040/api/tunnels"

API_COMMAND = [
    str(PYTHON_EXECUTABLE),
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
    str(PYTHON_EXECUTABLE),
    str(BASE_DIR / "refresh_guidance.py"),
    "--watch",
]


def _normalized_path(path: Path) -> str:
    normalized = str(path.resolve())
    return normalized.casefold() if os.name == "nt" else normalized


def _is_canonical_python() -> bool:
    try:
        return _normalized_path(PYTHON_EXECUTABLE) == _normalized_path(VENV_PYTHON)
    except OSError:
        return False


def _process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_lock_pid(lock_path: Path) -> int | None:
    if not lock_path.exists() or not lock_path.is_file():
        return None

    try:
        raw = lock_path.read_text(encoding="utf-8").strip().splitlines()[0]
        return int(raw)
    except (OSError, ValueError, IndexError):
        return None


def _acquire_single_instance_lock(lock_path: Path, label: str) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            existing_pid = _read_lock_pid(lock_path)
            if existing_pid is not None and _process_is_running(existing_pid):
                print(f"{label}: already running as PID {existing_pid}; refusing to start a duplicate.")
                return False

            try:
                lock_path.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                print(f"{label}: could not clear stale lock {lock_path}: {exc}")
                return False
            continue

        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n")
            handle.write(f"{sys.executable}\n")
        return True


def _release_single_instance_lock(lock_path: Path) -> None:
    current_pid = _read_lock_pid(lock_path)
    if current_pid != os.getpid():
        return

    try:
        lock_path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


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


def _fetch_windows_processes() -> list[dict[str, Any]]:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if not powershell:
        return []

    command = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,Name,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-Command", command],
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


def _fetch_posix_processes() -> list[dict[str, Any]]:
    ps = shutil.which("ps")
    if not ps:
        return []

    result = subprocess.run(
        [ps, "-eo", "pid=,comm=,args="],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []

    processes: list[dict[str, Any]] = []
    for line in (result.stdout or "").splitlines():
        parts = line.strip().split(maxsplit=2)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        name = parts[1]
        command_line = parts[2] if len(parts) == 3 else name
        processes.append({"ProcessId": pid, "Name": name, "CommandLine": command_line})
    return processes


def _fetch_processes() -> list[dict[str, Any]]:
    if os.name == "nt":
        return _fetch_windows_processes()
    return _fetch_posix_processes()


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


def _refuse_duplicates(label: str, matches: list[dict[str, Any]]) -> bool:
    if not matches:
        return False

    pids = [str(item.get("ProcessId", "?")) for item in matches]
    noun = "process" if len(matches) == 1 else "processes"
    print(f"{label}: already running as {noun} {', '.join(pids)}; refusing to start a duplicate.")
    return True


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


def _token_suffix() -> str:
    token = os.getenv("GLASSES_API_TOKEN", "").strip()
    if not token:
        return ""
    return f"&token={quote_plus(token)}"


def _build_glasses_hud_url(base_host: str) -> str:
    host = base_host.rstrip("/")
    return f"{host}/glasses?api={host}/glasses/latest{_token_suffix()}"


def _print_urls(ngrok_url: str) -> None:
    local_glasses_url = _build_glasses_hud_url(f"http://127.0.0.1:{API_PORT}")

    print(f"Desktop debug HUD: {DESKTOP_URL}")
    # Preserve easy access to the original mock display endpoint.
    print(f"Mock display HUD: {DESKTOP_URL}")
    print(f"Local glasses HUD: {local_glasses_url}")

    if ngrok_url:
        print(f"Public glasses HUD: {_build_glasses_hud_url(ngrok_url)}")
    elif _ngrok_launcher_available():
        print("Public glasses HUD: unavailable (ngrok launcher is available, but no active tunnel was detected)")


def main() -> int:
    api_process: subprocess.Popen[str] | None = None
    refresh_process: subprocess.Popen[str] | None = None

    warn_if_multiple_writers()

    if not _is_canonical_python():
        print(f"start_assistant.py: refusing to start under {PYTHON_EXECUTABLE}; use {VENV_PYTHON}")
        return 1

    if not _acquire_single_instance_lock(START_ASSISTANT_LOCK, "start_assistant.py"):
        return 1

    atexit.register(_release_single_instance_lock, START_ASSISTANT_LOCK)

    processes = _fetch_processes()
    api_matches = _match_api_processes(processes)
    refresh_matches = _match_refresh_watch_processes(processes)
    ngrok_matches = _match_ngrok_processes(processes)

    if _refuse_duplicates("uvicorn API", api_matches) or _refuse_duplicates("refresh watcher", refresh_matches):
        return 1

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
        _release_single_instance_lock(START_ASSISTANT_LOCK)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
