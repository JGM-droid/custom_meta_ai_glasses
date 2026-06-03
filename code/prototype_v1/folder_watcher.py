from pathlib import Path
import time
import subprocess
import sys
import hashlib

BASE_DIR = Path(__file__).resolve().parent
WATCH_FOLDER = BASE_DIR / "test_images"
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PIPELINE_SCRIPT = BASE_DIR / "watch_latest_image.py"

seen_files = {image.name for image in WATCH_FOLDER.iterdir() if image.is_file()}
seen_hashes = set()


def wait_for_file_stability(file_path, check_interval=0.5, stable_checks=2, timeout=15):
    """Return True once file size remains unchanged across consecutive checks."""
    deadline = time.time() + timeout
    last_size = None
    stable_count = 0

    while time.time() < deadline:
        if not file_path.exists() or not file_path.is_file():
            return False

        current_size = file_path.stat().st_size
        if current_size == last_size:
            stable_count += 1
            if stable_count >= stable_checks:
                return True
        else:
            stable_count = 0
            last_size = current_size

        time.sleep(check_interval)

    return False


def compute_file_hash(file_path):
    hasher = hashlib.sha256()
    with open(file_path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

print(f"Watcher started: monitoring {WATCH_FOLDER}")

while True:
    for image in WATCH_FOLDER.iterdir():
        if image.is_file() and image.suffix.lower() in SUPPORTED_EXTENSIONS:
            if image.name not in seen_files:
                print(f"\nImage detected: {image.name}")

                if not wait_for_file_stability(image):
                    print(f"Skipped unstable image: {image.name} (file did not stabilize before timeout)")
                    seen_files.add(image.name)
                    continue

                image_hash = compute_file_hash(image)
                if image_hash in seen_hashes:
                    print(f"Skipped duplicate image: {image.name} (content hash already processed)")
                    seen_files.add(image.name)
                    continue

                result = subprocess.run(
                    [sys.executable, str(PIPELINE_SCRIPT), str(image)],
                    cwd=str(BASE_DIR),
                    check=False,
                )

                if result.returncode == 0:
                    print(f"Analysis completed: {image.name}")
                    seen_hashes.add(image_hash)
                else:
                    print(f"Analysis failed: {image.name} (exit code {result.returncode})")

                seen_files.add(image.name)

    time.sleep(2)