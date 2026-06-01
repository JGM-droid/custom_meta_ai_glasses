from pathlib import Path
import time
import subprocess

watch_folder = Path("code/prototype_v1/test_images")
supported_extensions = {".png", ".jpg", ".jpeg", ".webp"}

seen_files = set(image.name for image in watch_folder.iterdir() if image.is_file())

print("Watching for new images...")

while True:
    for image in watch_folder.iterdir():
        if image.is_file() and image.suffix.lower() in supported_extensions:
            if image.name not in seen_files:
                print(f"\nNew image detected: {image.name}")

                subprocess.run(
                    ["python", "code/prototype_v1/watch_latest_image.py", str(image)]
                )

                seen_files.add(image.name)

    time.sleep(2)