from pathlib import Path

import requests


API_URL = "http://127.0.0.1:8001/analyze"
IMAGE_PATH = Path(__file__).resolve().parent / "test_images" / "test_image.png"


def main() -> None:
    if not IMAGE_PATH.exists():
        raise FileNotFoundError(f"Test image not found: {IMAGE_PATH}")

    with IMAGE_PATH.open("rb") as image_file:
        files = {"file": (IMAGE_PATH.name, image_file, "image/png")}
        response = requests.post(API_URL, files=files, timeout=120)

    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
