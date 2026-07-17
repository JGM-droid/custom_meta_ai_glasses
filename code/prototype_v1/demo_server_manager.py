"""demo_server_manager.py — LEGACY — DO NOT RUN

LEGACY WARNING — NOT PART OF THE V16+ CANONICAL RUNTIME
========================================================
This file is a V5.2-era diagnostic tool. It is quarantined and must not be
run as part of normal development or hardware validation workflows.

RISKS IF RUN:
  - The --start flag spawns uvicorn on :8001 using bare 'python' (not the
    venv Python), bypassing all V16 single-instance guards.
  - Writes demo_server_status.json to results/, polluting the artifact store.
  - Start commands embedded in this file are not venv-pinned and will spawn
    unguarded runtime chains.

CANONICAL STARTUP COMMAND:
    .\\venv\\Scripts\\python.exe code\\prototype_v1\\start_assistant.py

This file must not be used for new Investigation Session development. It
remains temporarily for backward compatibility and historical verification.

Do not run this file. If you must run it for historical reference only,
pass --allow-legacy-run as the first argument.

------------------------------------------------------------------------
Original V5.2 docstring:

demo_server_manager.py — V5.2 Local Demo Server Manager

Checks whether the API server (port 8001) and the display web server (port 8002)
are running and network-reachable, then prints exact start commands for any that
are missing.

Usage:
    python code/prototype_v1/demo_server_manager.py           # status check only
    python code/prototype_v1/demo_server_manager.py --start   # start missing servers
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
OUTPUT_PATH = RESULTS_DIR / "demo_server_status.json"

API_PORT = 8001
DISPLAY_PORT = 8002

API_CMD = "python -m uvicorn api:app --host 0.0.0.0 --port 8001 --app-dir code/prototype_v1"
DISPLAY_CMD = "python -m http.server 8002 --directory code/prototype_v1"


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def _detect_local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No external traffic is sent; this only selects the outbound interface.
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        sock.close()
    return ip


def _port_in_use(port: int) -> bool:
    """Return True if anything is listening on port (any interface)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        result = sock.connect_ex(("127.0.0.1", port))
        return result == 0
    finally:
        sock.close()


def _netstat_bind_address(port: int) -> str:
    """
    Parse `netstat -ano` to find the bind address of a TCP listener on *port*.
    Returns: "0.0.0.0", "127.0.0.1", a LAN IP string, or "unknown".
    """
    try:
        output = subprocess.check_output(
            ["netstat", "-ano"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unknown"

    target = f":{port}"
    for line in output.splitlines():
        parts = line.split()
        # Typical netstat line: Proto  Local  Foreign  State  PID
        if len(parts) < 4:
            continue
        if parts[0].upper() not in ("TCP", "TCP4", "TCP6"):
            continue
        local = parts[1]
        state = parts[3].upper() if len(parts) >= 4 else ""
        # Only LISTENING rows tell us the bound address
        if state != "LISTENING":
            continue
        # local may be "0.0.0.0:8001" or "[::]:8001"
        if not local.endswith(target):
            continue
        addr = local.rsplit(":", 1)[0].strip("[]")
        return addr  # e.g. "0.0.0.0" or "127.0.0.1" or a LAN IP
    return "unknown"


def _is_network_reachable(bind_addr: str, local_ip: str) -> str:
    """
    Given a bind address and the machine's LAN IP, return a reachability label.
    "yes"     — accessible from other devices on the LAN
    "no"      — loopback only, not accessible from other devices
    "unknown" — could not determine
    """
    if bind_addr == "0.0.0.0":
        return "yes"
    if bind_addr == "127.0.0.1":
        return "no"
    if bind_addr == local_ip:
        return "yes"
    if bind_addr == "unknown":
        return "unknown"
    # Any other non-loopback address is a LAN or external interface
    return "yes"


# ---------------------------------------------------------------------------
# Status gathering
# ---------------------------------------------------------------------------

def _check_port(port: int, local_ip: str, name: str, start_cmd: str) -> dict[str, Any]:
    running = _port_in_use(port)
    if running:
        bind_addr = _netstat_bind_address(port)
        net_reachable = _is_network_reachable(bind_addr, local_ip)
    else:
        bind_addr = "n/a"
        net_reachable = "no"

    return {
        "name": name,
        "port": port,
        "running": running,
        "bind_address": bind_addr,
        "network_reachable": net_reachable,
        "start_command": start_cmd,
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

_TICK = "✓"
_CROSS = "✗"
_WARN = "!"


def _print_divider() -> None:
    print("-" * 60)


def _status_icon(value: bool | str) -> str:
    if value is True or value == "yes":
        return _TICK
    if value is False or value == "no":
        return _CROSS
    return _WARN


def _print_status(api: dict, display: dict, local_ip: str) -> None:
    _print_divider()
    print("  Demo Server Status")
    _print_divider()
    print(f"  LAN IP detected : {local_ip}")
    print()

    for info in (api, display):
        run_icon = _status_icon(info["running"])
        net_icon = _status_icon(info["network_reachable"])
        print(f"  [{run_icon}] {info['name']} (port {info['port']})")
        print(f"       Running           : {'Yes' if info['running'] else 'No'}")
        if info["running"]:
            print(f"       Bound to          : {info['bind_address']}")
            reachable = info["network_reachable"]
            if reachable == "yes":
                label = "Yes — accessible from phone/glasses"
            elif reachable == "no":
                label = "No  — loopback only, phone cannot reach this"
            else:
                label = "Unknown"
            print(f"       [{net_icon}] Network reachable : {label}")
        print()

    _print_divider()
    print("  Next Steps")
    _print_divider()

    needs_action = False
    for info in (api, display):
        if not info["running"]:
            needs_action = True
            print(f"  Start {info['name']}:")
            print(f"    {info['start_command']}")
            print()
        elif info["network_reachable"] == "no":
            needs_action = True
            print(f"  [{_WARN}] {info['name']} is running but only on loopback (127.0.0.1).")
            print(f"       Stop it and restart with the network-accessible command:")
            print(f"    {info['start_command']}")
            print()
        else:
            print(f"  [{_TICK}] {info['name']} — Already running and network reachable.")
            print()

    if not needs_action:
        print("  Both servers are running and network reachable.")
        print(f"  Open on phone: http://{local_ip}:{DISPLAY_PORT}/glasses_display_mock.html")
        print()

    _print_divider()


# ---------------------------------------------------------------------------
# Server launch
# ---------------------------------------------------------------------------

def _start_in_new_window(cmd: str, title: str) -> None:
    """Launch *cmd* in a new PowerShell window (Windows only)."""
    ps_cmd = (
        f'Start-Process powershell -ArgumentList '
        f'"-NoExit", "-Command", "{cmd}" '
        f'-WindowStyle Normal'
    )
    subprocess.Popen(
        ["powershell", "-Command", ps_cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"  [+] Started: {title}")
    print(f"       Command: {cmd}")


def _start_missing(api: dict, display: dict) -> None:
    _print_divider()
    print("  Starting missing servers...")
    _print_divider()
    started_any = False

    for info in (api, display):
        if not info["running"]:
            _start_in_new_window(info["start_command"], info["name"])
            started_any = True
        elif info["network_reachable"] == "no":
            print(
                f"  [{_WARN}] {info['name']} is already running but on loopback only.\n"
                f"       Stop it manually, then re-run with --start to relaunch on 0.0.0.0."
            )
        else:
            print(f"  [{_TICK}] {info['name']} — Already running, skipping.")

    if not started_any:
        print("  Nothing to start.")
    print()


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def _write_json(api: dict, display: dict, local_ip: str) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "local_ip": local_ip,
        "api_server": api,
        "display_server": display,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"  Status written to: {OUTPUT_PATH.relative_to(BASE_DIR.parent.parent)}")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Demo server status checker and launcher.")
    parser.add_argument("--start", action="store_true", help="Start missing servers in new windows.")
    args = parser.parse_args()

    local_ip = _detect_local_ip()

    api = _check_port(API_PORT, local_ip, "API server (uvicorn)", API_CMD)
    display = _check_port(DISPLAY_PORT, local_ip, "Display server (http.server)", DISPLAY_CMD)

    _print_status(api, display, local_ip)
    _write_json(api, display, local_ip)

    if args.start:
        _start_missing(api, display)


if __name__ == "__main__":
    import sys as _sys

    if "--allow-legacy-run" not in _sys.argv:
        print(
            "\n"
            "LEGACY FILE — BLOCKED\n"
            "=====================\n"
            "demo_server_manager.py is not part of the V16+ canonical runtime.\n"
            "\n"
            "Running it would:\n"
            "  - With --start: spawn a duplicate uvicorn on :8001 using unvenv-pinned 'python'\n"
            "  - Bypass all V16 single-instance guards\n"
            "  - Write demo_server_status.json to the results/ artifact store\n"
            "\n"
            "Canonical startup command:\n"
            "  venv\\\\Scripts\\\\python.exe code\\\\prototype_v1\\\\start_assistant.py\n"
            "\n"
            "To override (not recommended):\n"
            "  python demo_server_manager.py --allow-legacy-run\n",
            file=_sys.stderr,
        )
        raise SystemExit(1)

    main()
