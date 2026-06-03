from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path


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
DEMO_COMMAND = [
    sys.executable,
    str(BASE_DIR / "glasses_demo.py"),
    "--scenario",
    "normal",
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


def main() -> int:
    api_process: subprocess.Popen[str] | None = None
    display_process: subprocess.Popen[str] | None = None

    def _cleanup(*_args: object) -> None:
        _terminate_process(api_process)
        _terminate_process(display_process)

    previous_interrupt = signal.signal(signal.SIGINT, lambda *_args: (_cleanup(), sys.exit(0)))
    previous_terminate = signal.signal(signal.SIGTERM, lambda *_args: (_cleanup(), sys.exit(0)))

    try:
        api_process = _start_process(API_COMMAND)
        display_process = _start_process(DISPLAY_COMMAND)

        demo_result = subprocess.run(DEMO_COMMAND, cwd=str(BASE_DIR), check=False)

        print("LOCAL DEMO LAUNCHER")
        print()
        print("Local URLs:")
        print("- http://127.0.0.1:8001/latest")
        print("- http://127.0.0.1:8002/glasses_display_mock.html")
        print()
        print("Manual tunnel commands:")
        print("- ngrok http 8001")
        print("- ngrok http 8002")
        print()
        print(f"glasses_demo.py exited with code {demo_result.returncode}")
        print("Press Ctrl+C to stop the local servers.")

        while True:
            if api_process.poll() is not None:
                print(f"API server exited with code {api_process.returncode}")
                break
            if display_process.poll() is not None:
                print(f"Display server exited with code {display_process.returncode}")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _cleanup()
        signal.signal(signal.SIGINT, previous_interrupt)
        signal.signal(signal.SIGTERM, previous_terminate)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())