from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

import start_assistant as sa


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent.parent
VENV_PYTHON = (REPO_ROOT / "venv" / "Scripts" / "python.exe").resolve()
ACTIVE_EDITOR_STATE_JSON = BASE_DIR / "results" / "active_editor_state.json"
NGROK_API_URL = "http://127.0.0.1:4040/api/tunnels"
CLOUDFLARED_FALLBACK = Path(r"C:\Program Files\cloudflared\cloudflared.exe")
NGROK_FALLBACK = Path(r"C:\Users\jesse\Downloads\ngrok-v3-stable-windows-amd64\ngrok.exe")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-click demo startup for Custom Meta AI Glasses")
    parser.add_argument("--no-tunnel", action="store_true", help="Skip tunnel detection/startup")
    parser.add_argument("--prefer-cloudflare", action="store_true", help="Prefer Cloudflare tunnel over ngrok")
    parser.add_argument("--prefer-ngrok", action="store_true", help="Prefer ngrok tunnel over Cloudflare")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser windows (default behavior)")
    args = parser.parse_args()

    if args.prefer_cloudflare and args.prefer_ngrok:
        parser.error("Use only one of --prefer-cloudflare or --prefer-ngrok")

    return args


def _is_canonical_python() -> bool:
    try:
        return str(Path(sa.sys.executable).resolve()).casefold() == str(VENV_PYTHON).casefold()
    except OSError:
        return False


def _find_cloudflared() -> str | None:
    on_path = shutil.which("cloudflared")
    if on_path:
        return on_path
    if CLOUDFLARED_FALLBACK.is_file():
        return str(CLOUDFLARED_FALLBACK)
    return None


def _find_ngrok() -> str | None:
    on_path = shutil.which("ngrok")
    if on_path:
        return on_path
    if NGROK_FALLBACK.is_file():
        return str(NGROK_FALLBACK)
    return None


def _match_cloudflared_processes(processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for proc in processes:
        cmd = str(proc.get("CommandLine") or "").lower()
        name = str(proc.get("Name") or "").lower()
        if "cloudflared" in name or "cloudflared" in cmd:
            matches.append(proc)
    return matches


def _warn_duplicates(label: str, matches: list[dict[str, Any]]) -> None:
    if len(matches) <= 1:
        return
    pids = [str(item.get("ProcessId", "?")) for item in matches]
    print(f"Warning: duplicate {label} processes detected: {', '.join(pids)}")


def _token_suffix() -> str:
    token = os.getenv("GLASSES_API_TOKEN", "").strip()
    if not token:
        return ""
    return f"&token={quote_plus(token)}"


def _build_glasses_hud_url(base_host: str) -> str:
    host = base_host.rstrip("/")
    return f"{host}/glasses?api={host}/glasses/latest{_token_suffix()}"


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


def _start_ngrok_tunnel(owned: list[subprocess.Popen[str]]) -> str:
    existing = _fetch_ngrok_public_url()
    if existing:
        return existing

    ngrok_exe = _find_ngrok()
    if not ngrok_exe:
        return ""

    print("Tunnel: starting ngrok...")
    process = subprocess.Popen([ngrok_exe, "http", "8001"], cwd=str(BASE_DIR))
    owned.append(process)

    deadline = time.time() + 18
    while time.time() < deadline:
        public_url = _fetch_ngrok_public_url()
        if public_url:
            return public_url
        if process.poll() is not None:
            break
        time.sleep(1)

    print("Warning: ngrok did not produce a usable HTTPS URL.")
    return ""


def _start_cloudflare_tunnel(owned: list[subprocess.Popen[str]], temp_files: list[tempfile.NamedTemporaryFile]) -> str:
    cloudflared_exe = _find_cloudflared()
    if not cloudflared_exe:
        return ""

    print("Tunnel: starting Cloudflare quick tunnel...")
    log_file = tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", delete=False)
    temp_files.append(log_file)

    process = subprocess.Popen(
        [cloudflared_exe, "tunnel", "--url", "http://127.0.0.1:8001", "--no-autoupdate"],
        cwd=str(BASE_DIR),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    owned.append(process)

    pattern = re.compile(r"https://[a-z0-9\-]+\.trycloudflare\.com", re.IGNORECASE)
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            log_text = Path(log_file.name).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            log_text = ""

        match = pattern.search(log_text)
        if match:
            return match.group(0).rstrip("/")

        if process.poll() is not None:
            break
        time.sleep(1)

    print("Warning: cloudflared did not produce a usable quick tunnel URL.")
    return ""


def _http_status(url: str, extra_headers: dict[str, str] | None = None) -> int:
    headers = extra_headers or {}
    request = Request(url, headers=headers)
    with urlopen(request, timeout=4) as response:
        return int(response.status)


def _validate_local_endpoints() -> tuple[bool, list[str]]:
    results: list[str] = []
    ok = True

    local_glasses = "http://127.0.0.1:8001/glasses"
    local_latest = "http://127.0.0.1:8001/glasses/latest"

    try:
        status = _http_status(local_glasses)
        results.append(f"Validation: {local_glasses} -> {status}")
        if status != 200:
            ok = False
    except (HTTPError, URLError, TimeoutError) as exc:
        results.append(f"Validation: {local_glasses} -> ERROR ({exc})")
        ok = False

    payload: dict[str, Any] = {}
    try:
        request = Request(local_latest)
        with urlopen(request, timeout=4) as response:
            status = int(response.status)
            payload = json.loads(response.read().decode("utf-8"))
        results.append(f"Validation: {local_latest} -> {status}")
        if status != 200:
            ok = False
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        results.append(f"Validation: {local_latest} -> ERROR ({exc})")
        ok = False

    has_freshness = isinstance(payload, dict) and ("freshness_state" in payload)
    has_context = isinstance(payload, dict) and ("active_context" in payload)
    results.append(f"Validation: /glasses/latest has freshness_state -> {has_freshness}")
    results.append(f"Validation: /glasses/latest has active_context -> {has_context}")
    if not has_freshness or not has_context:
        ok = False

    if ACTIVE_EDITOR_STATE_JSON.exists():
        results.append("Validation: active_editor_state.json exists")
    else:
        results.append("Warning: active_editor_state.json missing (extension may not be producing active editor state)")

    return ok, results


def _print_urls(public_base: str) -> None:
    local_base = "http://127.0.0.1:8001"
    desktop_url = f"{local_base}/glasses_display_mock.html"

    print(f"Desktop debug HUD: {desktop_url}")
    print(f"Local glasses HUD: {_build_glasses_hud_url(local_base)}")
    if public_base:
        print(f"Public glasses HUD: {_build_glasses_hud_url(public_base)}")
    else:
        print("Public glasses HUD: unavailable")


def _select_tunnel_order(args: argparse.Namespace) -> list[str]:
    if args.prefer_cloudflare:
        return ["cloudflare", "ngrok"]
    if args.prefer_ngrok:
        return ["ngrok", "cloudflare"]
    return ["ngrok", "cloudflare"]


def _cleanup_owned_processes(processes: list[subprocess.Popen[str]]) -> None:
    for process in processes:
        sa._terminate_process(process)


def main() -> int:
    args = _parse_args()

    if not _is_canonical_python():
        print(f"launch_demo.py: refusing to start under {sa.sys.executable}; use {VENV_PYTHON}")
        return 1

    owned_processes: list[subprocess.Popen[str]] = []
    temp_files: list[tempfile.NamedTemporaryFile] = []

    processes = sa._fetch_processes()
    api_matches = sa._match_api_processes(processes)
    refresh_matches = sa._match_refresh_watch_processes(processes)
    ngrok_matches = sa._match_ngrok_processes(processes)
    cloudflared_matches = _match_cloudflared_processes(processes)

    _warn_duplicates("uvicorn API", api_matches)
    _warn_duplicates("refresh watcher", refresh_matches)
    _warn_duplicates("ngrok", ngrok_matches)
    _warn_duplicates("cloudflared", cloudflared_matches)

    try:
        if api_matches:
            print("API: already running on port 8001")
        else:
            print("API: starting")
            process = sa._start_process(sa.API_COMMAND)
            owned_processes.append(process)
            if sa._wait_for_api_ready(timeout_seconds=12):
                print("API: ready")
            else:
                print("Warning: API did not report ready within timeout")

        if refresh_matches:
            print("Refresh watcher: already running")
        else:
            print("Refresh watcher: starting")
            process = sa._start_process(sa.REFRESH_WATCH_COMMAND)
            owned_processes.append(process)

        public_base = ""
        if args.no_tunnel:
            print("Tunnel: skipped (--no-tunnel)")
        else:
            for tunnel_kind in _select_tunnel_order(args):
                if tunnel_kind == "ngrok":
                    public_base = _start_ngrok_tunnel(owned_processes)
                else:
                    public_base = _start_cloudflare_tunnel(owned_processes, temp_files)

                if public_base:
                    print(f"Tunnel: active via {tunnel_kind}")
                    break

            if not public_base:
                print("Warning: no public tunnel URL available")

        if args.no_browser:
            print("Browser: suppressed (--no-browser)")

        _print_urls(public_base)

        ok, validation_lines = _validate_local_endpoints()
        for line in validation_lines:
            print(line)

        if not ok:
            print("Validation: FAILED")
        else:
            print("Validation: PASSED")

        if owned_processes:
            print("Press Ctrl+C to stop child processes started by this launcher.")
        else:
            print("All services were already running. Launcher staying alive as orchestrator — press Ctrl+C to exit.")

        while True:
            for process in owned_processes:
                if process.poll() is not None:
                    print(f"Child process exited with code {process.returncode}")
                    return 1
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping launcher...")
    finally:
        _cleanup_owned_processes(owned_processes)
        for temp_file in temp_files:
            try:
                Path(temp_file.name).unlink(missing_ok=True)
            except OSError:
                pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
