from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


app = FastAPI(title="Prototype V1 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
WATCH_SCRIPT = BASE_DIR / "watch_latest_image.py"
LATEST_RESPONSE_JSON = BASE_DIR / "results" / "latest_response.json"
RESUME_NOW_JSON = BASE_DIR / "results" / "resume_now.json"
HUD_CACHE_JSON = BASE_DIR / "results" / "last_known_hud_payload.json"
RESULTS_DIR = BASE_DIR / "results"
DISPLAY_HTML = BASE_DIR / "glasses_display_mock.html"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/results", StaticFiles(directory=str(RESULTS_DIR)), name="results")

_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _safe_load_json(path: Path) -> dict[str, object]:
    if not path.exists() or not path.is_file():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _safe_write_json(path: Path, payload: dict[str, object]) -> None:
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def _copy_hud_fields(source: dict[str, object], target: dict[str, object]) -> None:
    keys = [
        "guidance_priority",
        "recommended_next_action",
        "task_tracking",
        "next_step_decision",
        "decision_reason",
        "decision_confidence",
        "decision_factors",
        "primary_guidance",
        "advisory_guidance",
        "active_file_available",
        "active_file",
        "active_file_display",
    ]
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        if key not in target or not target.get(key):
            target[key] = value


def _parse_iso8601(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _payload_generated_at(payload: dict[str, object], source_path: Path) -> str:
    candidates = [
        payload.get("generated_at"),
        payload.get("timestamp"),
    ]

    signal_freshness = payload.get("signal_freshness") if isinstance(payload.get("signal_freshness"), dict) else {}
    if signal_freshness:
        candidates.append(signal_freshness.get("context_fusion_generated_at"))

    for candidate in candidates:
        parsed = _parse_iso8601(str(candidate or ""))
        if parsed:
            return parsed.isoformat(timespec="seconds")

    try:
        modified = datetime.fromtimestamp(source_path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        modified = datetime.now(timezone.utc)
    return modified.isoformat(timespec="seconds")


def _hud_status_from_age(age_seconds: int) -> str:
    if age_seconds > 60:
        return "stale"
    return "connected"


def _has_task_decision_fields(payload: dict[str, object]) -> bool:
    has_task = isinstance(payload.get("task_tracking"), dict) and bool(payload.get("task_tracking"))
    has_decision = bool(str(payload.get("next_step_decision", "")).strip()) and bool(str(payload.get("decision_reason", "")).strip())
    return has_task and has_decision


def _load_resume_guidance() -> dict[str, str | dict[str, object]]:
    if not RESUME_NOW_JSON.exists() or not RESUME_NOW_JSON.is_file():
        return {}

    try:
        payload = json.loads(RESUME_NOW_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    if not isinstance(payload, dict):
        return {}

    merged: dict[str, str | dict[str, object]] = {}
    guidance_priority = payload.get("guidance_priority")
    if isinstance(guidance_priority, dict):
        merged["guidance_priority"] = guidance_priority

    recommended_next_action = payload.get("recommended_next_action")
    if isinstance(recommended_next_action, str) and recommended_next_action.strip():
        merged["resume_recommended_action"] = recommended_next_action.strip()

    return merged


def _load_resume_payload() -> dict[str, object]:
    return _safe_load_json(RESUME_NOW_JSON)


@app.get("/glasses_display_mock.html", response_class=FileResponse)
async def display_mock():
    if not DISPLAY_HTML.exists():
        raise HTTPException(status_code=404, detail="Display mock not found.")
    return FileResponse(str(DISPLAY_HTML), media_type="text/html")


@app.get("/latest")
async def latest():
    source_path: Path | None = None
    if LATEST_RESPONSE_JSON.exists():
        source_path = LATEST_RESPONSE_JSON
    elif RESUME_NOW_JSON.exists():
        source_path = RESUME_NOW_JSON

    payload: dict[str, object] = {}
    if source_path is not None:
        payload = _safe_load_json(source_path)

    resume_payload = _load_resume_payload()
    if resume_payload:
        _copy_hud_fields(resume_payload, payload)
        guidance_only = _load_resume_guidance()
        for key, value in guidance_only.items():
            if key not in payload or not payload.get(key):
                payload[key] = value

    cache_payload = _safe_load_json(HUD_CACHE_JSON)
    if cache_payload:
        _copy_hud_fields(cache_payload, payload)

    if not payload:
        raise HTTPException(
            status_code=404,
            detail="No display data available. Run glasses_demo.py or analyze an image first.",
        )

    freshness_source = source_path or RESUME_NOW_JSON
    generated_at = _payload_generated_at(payload, freshness_source)
    parsed_generated = _parse_iso8601(generated_at) or datetime.now(timezone.utc)
    age_seconds = max(0, int((datetime.now(timezone.utc) - parsed_generated).total_seconds()))

    hud_status = _hud_status_from_age(age_seconds)
    if not _has_task_decision_fields(payload):
        hud_status = "stale" if cache_payload else "error"

    payload["generated_at"] = generated_at
    payload["age_seconds"] = age_seconds
    payload["hud_status"] = hud_status
    payload["payload_freshness"] = {
        "generated_at": generated_at,
        "age_seconds": age_seconds,
        "state": hud_status,
    }

    if _has_task_decision_fields(payload):
        cache_to_write = dict(payload)
        _safe_write_json(HUD_CACHE_JSON, cache_to_write)

    return payload


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    suffix = Path(file.filename or "upload.bin").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Use .png, .jpg, .jpeg, or .webp.",
        )

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_path = Path(tmp.name)
            file.file.seek(0)
            shutil.copyfileobj(file.file, tmp)

        command = [sys.executable, str(WATCH_SCRIPT), str(temp_path)]
        result = subprocess.run(
            command,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            check=False,
            env=os.environ.copy(),
        )

        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            raise HTTPException(
                status_code=500,
                detail=f"Image analysis pipeline failed: {stderr}",
            )

        if not LATEST_RESPONSE_JSON.exists():
            raise HTTPException(
                status_code=500,
                detail="latest_response.json was not generated by the pipeline.",
            )

        try:
            return json.loads(LATEST_RESPONSE_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"latest_response.json is not valid JSON: {exc}",
            ) from exc
    finally:
        try:
            await file.close()
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)
