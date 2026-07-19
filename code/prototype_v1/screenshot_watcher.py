"""screenshot_watcher.py — OPTIONAL SCREENSHOT WATCHER

Support tier: SUPPORTED DIAGNOSTIC

Optional diagnostic watcher that posts captures to vision analyze endpoints.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import urllib.error
import urllib.request
import uuid

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent.parent
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
POLL_SECONDS = float(os.environ.get("SCREENSHOT_WATCH_POLL_SECONDS", "1.5"))
VISION_ANALYZE_URL = os.environ.get("VISION_ANALYZE_URL", "http://127.0.0.1:8001/vision/analyze")


def _default_watch_dir() -> Path:
    configured = str(os.environ.get("SCREENSHOT_WATCH_DIR", "")).strip()
    if configured:
        return Path(configured).expanduser().resolve()

    pictures_dir = (Path.home() / "Pictures" / "Screenshots").resolve()
    if pictures_dir.exists() and pictures_dir.is_dir():
        return pictures_dir

    repo_screenshots = (REPO_ROOT / "screenshots").resolve()
    if repo_screenshots.exists() and repo_screenshots.is_dir():
        return repo_screenshots

    return (BASE_DIR / "test_images").resolve()


def _wait_for_stable_file(path: Path, timeout_seconds: float = 15.0) -> bool:
    deadline = time.time() + timeout_seconds
    previous_size = -1
    stable_checks = 0

    while time.time() < deadline:
        if not path.exists() or not path.is_file():
            return False

        size = path.stat().st_size
        if size <= 0:
            stable_checks = 0
        elif size == previous_size:
            stable_checks += 1
            if stable_checks >= 2:
                return True
        else:
            stable_checks = 0
            previous_size = size

        time.sleep(0.5)

    return False


def _compute_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _multipart_body(file_path: Path, boundary: str) -> bytes:
    mime = "image/png" if file_path.suffix.lower() == ".png" else "image/jpeg"
    file_bytes = file_path.read_bytes()

    chunks: list[bytes] = [
        f"--{boundary}\r\n".encode("utf-8"),
        (
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8"),
        file_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    return b"".join(chunks)


def _call_vision_analyze(file_path: Path) -> dict[str, object]:
    boundary = f"----copilotwatcher{uuid.uuid4().hex}"
    body = _multipart_body(file_path, boundary)

    request = urllib.request.Request(
        VISION_ANALYZE_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-Vision-Trigger": "watcher",
        },
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read().decode("utf-8", errors="replace")
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, dict) else {}


def main() -> None:
    watch_dir = _default_watch_dir()
    watch_dir.mkdir(parents=True, exist_ok=True)

    seen_names = {entry.name for entry in watch_dir.iterdir() if entry.is_file()}
    seen_hashes: set[str] = set()

    print(f"[WATCHER] Started screenshot watcher: {watch_dir}")
    print(f"[WATCHER] Vision endpoint: {VISION_ANALYZE_URL}")

    while True:
        for entry in watch_dir.iterdir():
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if entry.name in seen_names:
                continue

            print(f"[WATCHER] New screenshot detected: {entry.name}")

            if not _wait_for_stable_file(entry):
                print(f"[WATCHER] Skipped unstable screenshot: {entry.name}")
                seen_names.add(entry.name)
                continue

            try:
                digest = _compute_file_hash(entry)
            except OSError as exc:
                print(f"[WATCHER] Failed to read screenshot {entry.name}: {exc}")
                seen_names.add(entry.name)
                continue

            if digest in seen_hashes:
                print(f"[WATCHER] Skipped duplicate screenshot content: {entry.name}")
                seen_names.add(entry.name)
                continue

            try:
                vision_payload = _call_vision_analyze(entry)
                source = str(vision_payload.get("source") or "unknown")
                print(f"[VISION] Analysis completed: file={entry.name} source={source}")

                contextual_prompt = str(vision_payload.get("copilot_prompt_contextual") or "").strip()
                if contextual_prompt:
                    print(f"[FUSION] Contextual prompt generated ({len(contextual_prompt)} chars)")
                else:
                    print("[FUSION] Contextual prompt missing")

                status = str(vision_payload.get("auto_analysis_status") or "unknown")
                generated = str(vision_payload.get("analysis_timestamp") or vision_payload.get("generated_at") or "unknown")
                print(f"[UI] Prompt updated: status={status} timestamp={generated}")

                seen_hashes.add(digest)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
                print(f"[VISION] Analysis failed HTTP {exc.code}: {detail}")
            except Exception as exc:
                print(f"[VISION] Analysis failed: {type(exc).__name__}: {exc}")

            seen_names.add(entry.name)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
