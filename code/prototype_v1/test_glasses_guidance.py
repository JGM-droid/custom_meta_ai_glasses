from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys


BASE_DIR = Path(__file__).resolve().parent
TEST_IMAGE = BASE_DIR / "test_images" / "test_image.png"
PIPELINE_SCRIPT = BASE_DIR / "watch_latest_image.py"
LATEST_RESPONSE_PATH = BASE_DIR / "results" / "latest_response.json"
MAX_GUIDANCE_LENGTH = 150


def main() -> None:
    if not TEST_IMAGE.exists() or not TEST_IMAGE.is_file():
        print(f"image filename: {TEST_IMAGE.name}")
        print("glasses_guidance: <missing test image>")
        print("character count: 0")
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
        print("glasses_guidance: <pipeline execution failed>")
        print("character count: 0")
        print("PASS/FAIL: FAIL")
        return

    if not LATEST_RESPONSE_PATH.exists():
        print(f"image filename: {TEST_IMAGE.name}")
        print("glasses_guidance: <latest_response.json missing>")
        print("character count: 0")
        print("PASS/FAIL: FAIL")
        return

    try:
        payload = json.loads(LATEST_RESPONSE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"image filename: {TEST_IMAGE.name}")
        print("glasses_guidance: <invalid latest_response.json>")
        print("character count: 0")
        print("PASS/FAIL: FAIL")
        return

    guidance_value = payload.get("glasses_guidance")
    guidance = str(guidance_value).strip() if guidance_value is not None else ""
    char_count = len(guidance)

    exists = "glasses_guidance" in payload
    not_empty = char_count > 0
    within_limit = char_count <= MAX_GUIDANCE_LENGTH
    passed = exists and not_empty and within_limit

    print(f"image filename: {TEST_IMAGE.name}")
    print(f"glasses_guidance: {guidance if guidance else '<empty>'}")
    print(f"character count: {char_count}")
    print(f"PASS/FAIL: {'PASS' if passed else 'FAIL'}")


if __name__ == "__main__":
    main()
