from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys


BASE_DIR = Path(__file__).resolve().parent
TEST_IMAGES_DIR = BASE_DIR / "test_images"
PIPELINE_SCRIPT = BASE_DIR / "watch_latest_image.py"
LATEST_RESPONSE_PATH = BASE_DIR / "results" / "latest_response.json"


def pick_first_existing(candidates: list[str]) -> Path | None:
    for name in candidates:
        path = TEST_IMAGES_DIR / name
        if path.exists() and path.is_file():
            return path
    return None


def run_case(image_path: Path, expected_continuity: str | tuple[str, ...]) -> bool:
    result = subprocess.run(
        [sys.executable, str(PIPELINE_SCRIPT), str(image_path)],
        cwd=str(BASE_DIR),
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"image filename: {image_path.name}")
        print("task_continuity: Unknown")
        print("pass/fail: FAIL (pipeline execution failed)")
        stderr = (result.stderr or result.stdout or "").strip()
        if stderr:
            print(f"details: {stderr}")
        print()
        return False

    if not LATEST_RESPONSE_PATH.exists():
        print(f"image filename: {image_path.name}")
        print("task_continuity: Unknown")
        print("pass/fail: FAIL (latest_response.json missing)")
        print()
        return False

    try:
        payload = json.loads(LATEST_RESPONSE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"image filename: {image_path.name}")
        print("task_continuity: Unknown")
        print(f"pass/fail: FAIL (invalid latest_response.json: {exc})")
        print()
        return False

    task_continuity = str(payload.get("task_continuity", "Unknown") or "Unknown")
    expected_values = (expected_continuity,) if isinstance(expected_continuity, str) else expected_continuity
    passed = task_continuity.lower() in {value.lower() for value in expected_values}

    print(f"image filename: {image_path.name}")
    print(f"task_continuity: {task_continuity}")
    print(f"pass/fail: {'PASS' if passed else 'FAIL'}")
    print()

    return passed


def run_optional_case(image_path: Path | None, expected_continuity: str | tuple[str, ...], missing_message: str) -> bool | None:
    if image_path is None:
        print(missing_message)
        return None

    return run_case(image_path, expected_continuity)


def main() -> None:
    continuation_image = pick_first_existing(
        [
            "test_image.png",
            "watcher_test_01.png",
            "watcher_test_02.png",
            "watcher_test_03.png",
        ]
    )

    scenic_image = pick_first_existing(
        [
            "133959575898717423.jpg",
            "133959575898717423 - Copy.jpg",
            "133973540999428167.jpg",
            "134026336827829474.jpg",
            "134075326443157143.jpg",
        ]
    )

    task_switch_image = pick_first_existing(
        [
            "Screenshot 2026-05-26 112414.png",
        ]
    )

    missing = []
    if continuation_image is None:
        missing.append("Razer/task-related image (e.g., test_image.png)")
    if scenic_image is None:
        missing.append("unrelated scenic image (e.g., 133959575898717423.jpg)")

    if missing:
        print("Missing expected test images. Cannot run continuity smoke test.")
        for item in missing:
            print(f"- {item}")
        return

    print("Running task continuity smoke test...")
    print(f"Continuation case image: {continuation_image.name}")
    print(f"New task case image: {scenic_image.name}")
    if task_switch_image is not None:
        print(f"Different workflow case image: {task_switch_image.name}")
    else:
            print("Different workflow case image: not available (case will be skipped)")
    print()

    results = [
        run_case(continuation_image, "Continuation"),
        run_case(scenic_image, "New task"),
    ]

    task_switch_result = run_optional_case(
        task_switch_image,
        ("Task switch", "New task"),
        "Different workflow case skipped: no suitable workflow screenshot found.",
    )

    if task_switch_result is not None:
        results.append(task_switch_result)

    if all(results):
        print("Overall result: PASS")
    else:
        print("Overall result: FAIL")


if __name__ == "__main__":
    main()
