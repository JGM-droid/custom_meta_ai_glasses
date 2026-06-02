from pathlib import Path
import time
import subprocess
import sys

BASE_DIR = Path(__file__).resolve().parent
WATCH_FOLDER = BASE_DIR / "test_images"
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PIPELINE_SCRIPT = BASE_DIR / "watch_latest_image.py"

seen_files = {image.name for image in WATCH_FOLDER.iterdir() if image.is_file()}

print(f"Watcher started: monitoring {WATCH_FOLDER}")

while True:
    for image in WATCH_FOLDER.iterdir():
        if image.is_file() and image.suffix.lower() in SUPPORTED_EXTENSIONS:
            if image.name not in seen_files:
                print(f"\nImage detected: {image.name}")

                result = subprocess.run(
                    [sys.executable, str(PIPELINE_SCRIPT), str(image)],
                    cwd=str(BASE_DIR),
                    check=False,
                )

                if result.returncode == 0:
                    print(f"Analysis completed: {image.name}")
                else:
                    print(f"Analysis failed: {image.name} (exit code {result.returncode})")

                seen_files.add(image.name)

    time.sleep(2)