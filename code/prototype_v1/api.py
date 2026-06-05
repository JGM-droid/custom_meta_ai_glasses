from __future__ import annotations

import atexit
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
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
REPO_ROOT = BASE_DIR.parent.parent
VENV_PYTHON = (REPO_ROOT / "venv" / "Scripts" / "python.exe").resolve()
API_LOCK_PATH = BASE_DIR / "results" / "api_server.lock"
WATCH_SCRIPT = BASE_DIR / "watch_latest_image.py"
LATEST_RESPONSE_JSON = BASE_DIR / "results" / "latest_response.json"
RESUME_NOW_JSON = BASE_DIR / "results" / "resume_now.json"
HUD_CACHE_JSON = BASE_DIR / "results" / "last_known_hud_payload.json"
RESULTS_DIR = BASE_DIR / "results"
DISPLAY_HTML = BASE_DIR / "glasses_display_mock.html"
GLASSES_WEBAPP_DIR = BASE_DIR / "glasses_webapp"
GLASSES_WEBAPP_INDEX = GLASSES_WEBAPP_DIR / "index.html"
GLASSES_API_TOKEN = (os.environ.get("GLASSES_API_TOKEN") or "").strip()

RESULTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/results", StaticFiles(directory=str(RESULTS_DIR)), name="results")
if GLASSES_WEBAPP_DIR.exists() and GLASSES_WEBAPP_DIR.is_dir():
    app.mount("/glasses/static", StaticFiles(directory=str(GLASSES_WEBAPP_DIR)), name="glasses_static")


def _normalized_path(path: Path) -> str:
    return str(path.resolve()).casefold()


def _is_canonical_python() -> bool:
    try:
        return _normalized_path(Path(sys.executable)) == _normalized_path(VENV_PYTHON)
    except OSError:
        return False


def _process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_lock_pid(lock_path: Path) -> int | None:
    if not lock_path.exists() or not lock_path.is_file():
        return None

    try:
        raw = lock_path.read_text(encoding="utf-8").strip().splitlines()[0]
        return int(raw)
    except (OSError, ValueError, IndexError):
        return None


def _acquire_single_instance_lock(lock_path: Path, label: str) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            existing_pid = _read_lock_pid(lock_path)
            if existing_pid is not None and _process_is_running(existing_pid):
                print(f"{label}: already running as PID {existing_pid}; refusing to start a duplicate.")
                return False

            try:
                lock_path.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                print(f"{label}: could not clear stale lock {lock_path}: {exc}")
                return False
            continue

        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n")
            handle.write(f"{sys.executable}\n")
        return True


def _release_single_instance_lock(lock_path: Path) -> None:
    current_pid = _read_lock_pid(lock_path)
    if current_pid != os.getpid():
        return

    try:
        lock_path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


if not _is_canonical_python():
    print(f"api.py: refusing to start under {sys.executable}; use {VENV_PYTHON}")
    raise SystemExit(1)

if not _acquire_single_instance_lock(API_LOCK_PATH, "api.py"):
    raise SystemExit(1)

atexit.register(_release_single_instance_lock, API_LOCK_PATH)

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


def _newest_generated_at(candidates: list[str], fallback_source_path: Path) -> str:
    # Pick the newest valid timestamp so HUD freshness reflects the latest
    # producer update (for example refresh_guidance updating resume_now.json).
    newest: datetime | None = None
    for candidate in candidates:
        parsed = _parse_iso8601(candidate)
        if not parsed:
            continue
        if newest is None or parsed > newest:
            newest = parsed

    if newest is not None:
        return newest.isoformat(timespec="seconds")

    try:
        modified = datetime.fromtimestamp(fallback_source_path.stat().st_mtime, tz=timezone.utc)
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


def _extract_bearer_token(request: Request) -> str:
    auth = str(request.headers.get("Authorization", "")).strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _truncate_text(value: object, max_chars: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max(0, max_chars - 1)].rstrip()}..."


def _basename_only(path_text: object) -> str:
    raw = str(path_text or "").strip()
    if not raw:
        return ""
    return Path(raw).name


def _compact_active_context(payload: dict[str, object]) -> str:
    development = payload.get("development_context") if isinstance(payload.get("development_context"), dict) else {}
    file_name = _basename_only(development.get("active_file"))
    function_name = str(development.get("active_function") or "").strip()

    if not file_name:
        active_file = payload.get("active_file") if isinstance(payload.get("active_file"), dict) else {}
        file_name = _basename_only(active_file.get("active_file_name") or active_file.get("active_file_path"))

    if file_name and function_name:
        return _truncate_text(f"{file_name} :: {function_name}", 96)
    if file_name:
        return _truncate_text(file_name, 96)
    return "No active context"


def _confidence_percent(payload: dict[str, object]) -> int:
    decision_conf = payload.get("decision_confidence")
    if isinstance(decision_conf, (int, float)):
        value = float(decision_conf)
        if value <= 1:
            return int(max(0, min(100, round(value * 100))))
        return int(max(0, min(100, round(value))))

    task_tracking = payload.get("task_tracking") if isinstance(payload.get("task_tracking"), dict) else {}
    task_conf = task_tracking.get("task_confidence")
    if isinstance(task_conf, (int, float)):
        value = float(task_conf)
        if value <= 1:
            return int(max(0, min(100, round(value * 100))))
        return int(max(0, min(100, round(value))))

    return 0


def _build_glasses_payload(payload: dict[str, object]) -> dict[str, object]:
    guidance = payload.get("primary_guidance") if isinstance(payload.get("primary_guidance"), dict) else {}
    guidance_priority = payload.get("guidance_priority") if isinstance(payload.get("guidance_priority"), dict) else {}
    freshness = payload.get("payload_freshness") if isinstance(payload.get("payload_freshness"), dict) else {}

    headline = str(guidance.get("headline") or guidance_priority.get("headline") or "No headline").strip()
    next_action = str(
        guidance.get("recommended_action")
        or guidance_priority.get("recommended_action")
        or payload.get("recommended_next_action")
        or "No next action"
    ).strip()

    blocked = False
    if isinstance(guidance.get("blocking"), bool):
        blocked = bool(guidance.get("blocking"))
    elif isinstance(guidance_priority.get("blocking"), bool):
        blocked = bool(guidance_priority.get("blocking"))
    else:
        level = str(guidance.get("level") or guidance_priority.get("level") or "").strip().lower()
        blocked = level == "critical"

    short_reason = str(
        payload.get("decision_reason")
        or guidance.get("reason")
        or guidance_priority.get("message")
        or "No reason available"
    )

    freshness_state = str(
        freshness.get("state")
        or payload.get("hud_status")
        or "stale"
    ).strip().lower() or "stale"

    generated_at = str(payload.get("generated_at") or freshness.get("generated_at") or "")
    age_seconds_raw = freshness.get("age_seconds") if freshness else payload.get("age_seconds")
    try:
        age_seconds = int(age_seconds_raw) if age_seconds_raw is not None else 0
    except (TypeError, ValueError):
        age_seconds = 0

    return {
        "headline": _truncate_text(headline, 80) or "No headline",
        "next_action": _truncate_text(next_action, 140) or "No next action",
        "blocked": blocked,
        "confidence_percent": _confidence_percent(payload),
        "short_reason": _truncate_text(short_reason, 120) or "No reason available",
        "active_context": _compact_active_context(payload),
        "freshness_state": freshness_state,
        "generated_at": generated_at,
        "age_seconds": max(0, age_seconds),
    }


@app.get("/glasses_display_mock.html", response_class=FileResponse)
async def display_mock():
    if not DISPLAY_HTML.exists():
        raise HTTPException(status_code=404, detail="Display mock not found.")
    return FileResponse(str(DISPLAY_HTML), media_type="text/html")


@app.get("/glasses", response_class=FileResponse)
async def glasses_webapp():
    if not GLASSES_WEBAPP_INDEX.exists():
        raise HTTPException(status_code=404, detail="Glasses web app not found.")
    return FileResponse(str(GLASSES_WEBAPP_INDEX), media_type="text/html")


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

    # Keep latest_response.json support for vision-analysis payload fields, but
    # compute freshness from the newest available timestamp across both sources.
    freshness_candidates: list[str] = []
    if LATEST_RESPONSE_JSON.exists():
        latest_fresh_payload = _safe_load_json(LATEST_RESPONSE_JSON)
        freshness_candidates.append(_payload_generated_at(latest_fresh_payload, LATEST_RESPONSE_JSON))
    if RESUME_NOW_JSON.exists():
        resume_fresh_payload = _safe_load_json(RESUME_NOW_JSON)
        freshness_candidates.append(_payload_generated_at(resume_fresh_payload, RESUME_NOW_JSON))
    freshness_candidates.append(_payload_generated_at(payload, freshness_source))

    generated_at = _newest_generated_at(freshness_candidates, freshness_source)
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


@app.get("/glasses/latest")
async def glasses_latest(request: Request, token: str = Query(default="")):
    if GLASSES_API_TOKEN:
        candidate = token.strip() or _extract_bearer_token(request)
        if candidate != GLASSES_API_TOKEN:
            raise HTTPException(status_code=401, detail="Unauthorized token for glasses endpoint.")

    payload = await latest()
    return _build_glasses_payload(payload)


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
