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


def print_missing_images_message() -> None:
    print("Missing required demo images. Cannot run demo scenario.")
    print("Required image groups:")
    print("- Razer task image (example: test_image.png)")
    print("- Scenic image (example: 133959575898717423.jpg)")


def run_pipeline(image_path: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(PIPELINE_SCRIPT), str(image_path)],
        cwd=str(BASE_DIR),
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        if not details:
            details = "Pipeline execution failed with no error details."
        return False, details

    return True, ""


def read_latest_response() -> tuple[dict, str]:
    if not LATEST_RESPONSE_PATH.exists():
        return {}, "latest_response.json was not created."

    try:
        payload = json.loads(LATEST_RESPONSE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, f"latest_response.json is invalid JSON: {exc}"

    if not isinstance(payload, dict):
        return {}, "latest_response.json root is not an object."

    return payload, ""


def summarize_run(image_name: str, payload: dict) -> None:
    task_continuity = str(payload.get("task_continuity", "Unknown") or "Unknown")

    progress = payload.get("task_progress", {})
    if not isinstance(progress, dict):
        progress = {}
    step_count = progress.get("step_count", 0)
    next_step = str(progress.get("next_step", "Unknown") or "Unknown")

    stuck_status = payload.get("stuck_status", {})
    if not isinstance(stuck_status, dict):
        stuck_status = {}
    is_stuck = bool(stuck_status.get("is_stuck", False))
    repeated_count = stuck_status.get("repeated_next_step_count", 0)
    stuck_reason = str(stuck_status.get("reason", "Unknown") or "Unknown")

    intervention = payload.get("intervention", {})
    if not isinstance(intervention, dict):
        intervention = {}
    intervention_message = str(intervention.get("message", "No intervention message") or "No intervention message")

    guidance = str(payload.get("glasses_guidance", "Unknown") or "Unknown")

    print("=" * 64)
    print(f"Image filename: {image_name}")
    print(f"Task continuity: {task_continuity}")
    print(f"Task progress: step_count={step_count}; next_step={next_step}")
    print(
        "Stuck status: "
        f"is_stuck={'Yes' if is_stuck else 'No'}; "
        f"repeated_next_step_count={repeated_count}; "
        f"reason={stuck_reason}"
    )
    print(f"Intervention message: {intervention_message}")
    print(f"Glasses guidance: {guidance}")


def main() -> None:
    razer_image = pick_first_existing(
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

    if razer_image is None or scenic_image is None:
        print_missing_images_message()
        return

    sequence: list[tuple[str, Path]] = [
        ("Razer task run", razer_image),
        ("Razer repeat run (stuck/intervention trigger)", razer_image),
        ("Scenic run (new task/no intervention showcase)", scenic_image),
    ]

    print("Starting Demo Scenario Runner")
    print(f"Pipeline script: {PIPELINE_SCRIPT.name}")
    print(f"Latest response path: {LATEST_RESPONSE_PATH}")

    for title, image_path in sequence:
        print()
        print(f"--- {title} ---")
        ok, error = run_pipeline(image_path)
        if not ok:
            print(f"Failed on image: {image_path.name}")
            print(error)
            print("Exiting demo scenario.")
            return

        payload, read_error = read_latest_response()
        if read_error:
            print(f"Failed after image: {image_path.name}")
            print(read_error)
            print("Exiting demo scenario.")
            return

        summarize_run(image_path.name, payload)

    print()
    print("Demo scenario complete.")


if __name__ == "__main__":
    main()
