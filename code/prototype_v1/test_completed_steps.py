from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys


BASE_DIR = Path(__file__).resolve().parent
TEST_IMAGE = BASE_DIR / "test_images" / "test_image.png"
PIPELINE_SCRIPT = BASE_DIR / "watch_latest_image.py"
LATEST_RESPONSE_PATH = BASE_DIR / "results" / "latest_response.json"


def main() -> None:
    if not TEST_IMAGE.exists() or not TEST_IMAGE.is_file():
        print(f"image filename: {TEST_IMAGE.name}")
        print("completed_steps: []")
        print("step count: 0")
        print("PASS/FAIL: FAIL")
        return

    result = subprocess.run(
        [sys.executable, str(PIPELINE_SCRIPT), str(TEST_IMAGE)],
        cwd=str(BASE_DIR),
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"image filename: {TEST_IMAGE.name}")
        print("completed_steps: []")
        print("step count: 0")
        print("PASS/FAIL: FAIL")
        return

    if not LATEST_RESPONSE_PATH.exists():
        print(f"image filename: {TEST_IMAGE.name}")
        print("completed_steps: []")
        print("step count: 0")
        print("PASS/FAIL: FAIL")
        return

    try:
        payload = json.loads(LATEST_RESPONSE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"image filename: {TEST_IMAGE.name}")
        print("completed_steps: []")
        print("step count: 0")
        print("PASS/FAIL: FAIL")
        return

    exists = "completed_steps" in payload
    completed_steps_value = payload.get("completed_steps", [])
    is_list = isinstance(completed_steps_value, list)
    completed_steps = completed_steps_value if is_list else []
    step_count = len(completed_steps)
    has_items = step_count >= 1

    passed = exists and is_list and has_items

    print(f"image filename: {TEST_IMAGE.name}")
    print(f"completed_steps: {completed_steps}")
    print(f"step count: {step_count}")
    print(f"PASS/FAIL: {'PASS' if passed else 'FAIL'}")


if __name__ == "__main__":
    main()
