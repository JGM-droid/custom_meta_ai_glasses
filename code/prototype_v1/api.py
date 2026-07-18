from __future__ import annotations

import atexit
import base64
from datetime import datetime, timezone
import io
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from uuid import UUID

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi import Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from investigations import (
    InvestigationAnalyzeResponse,
    InvestigationDesktopProjection,
    InvestigationEvidence,
    InvestigationEvidenceCreateRequest,
    InvestigationEvidenceInvalidContentType,
    InvestigationEvidenceInvalidId,
    InvestigationEvidenceNotFound,
    InvestigationEvidenceStateError,
    InvestigationEvidenceStore,
    InvestigationEvidenceStoreError,
    InvestigationEvidenceType,
    InvestigationGlassesProjection,
    InvestigationSession,
    InvestigationSessionCreateRequest,
    InvestigationSessionInvalidId,
    InvestigationSessionLifecycleError,
    InvestigationSessionMutationRequest,
    InvestigationSessionNotFound,
    InvestigationSessionStore,
    InvestigationSessionStoreError,
    InvestigationStoreError,
    InvestigationStoreNotFound,
    MAX_AUDIO_UPLOAD_BYTES,
    MAX_IMAGE_UPLOAD_BYTES,
    UPLOAD_CHUNK_SIZE,
    analyze_investigation_request_with_retained,
    apply_cancel_transition,
    apply_pause_transition,
    apply_resume_transition,
    build_desktop_projection,
    build_glasses_projection,
    investigation_stale_seconds,
    load_latest_investigation_result,
    save_latest_investigation_result,
)

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional import fallback
    OpenAI = None  # type: ignore[assignment]

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional import fallback
    Image = None  # type: ignore[assignment]


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
VISION_CONTEXT_JSON = RESULTS_DIR / "vision_context.json"
INVESTIGATION_LATEST_JSON = RESULTS_DIR / "investigation_latest.json"
INVESTIGATION_SESSIONS_ROOT = RESULTS_DIR / "investigation_sessions"
CONTEXT_FUSION_JSON = RESULTS_DIR / "context_fusion.json"
DISPLAY_HTML = BASE_DIR / "glasses_display_mock.html"
GLASSES_WEBAPP_DIR = BASE_DIR / "glasses_webapp"
GLASSES_WEBAPP_INDEX = GLASSES_WEBAPP_DIR / "index.html"
GLASSES_API_TOKEN = (os.environ.get("GLASSES_API_TOKEN") or "").strip()
REPO_DOTENV_PATH = REPO_ROOT / ".env"
LOCAL_DOTENV_PATH = BASE_DIR / ".env"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/results", StaticFiles(directory=str(RESULTS_DIR)), name="results")
if GLASSES_WEBAPP_DIR.exists() and GLASSES_WEBAPP_DIR.is_dir():
    app.mount("/glasses/static", StaticFiles(directory=str(GLASSES_WEBAPP_DIR)), name="glasses_static")


def _build_session_store() -> InvestigationSessionStore:
    return InvestigationSessionStore(INVESTIGATION_SESSIONS_ROOT)


SESSION_STORE = _build_session_store()


def _build_evidence_store() -> InvestigationEvidenceStore:
    return InvestigationEvidenceStore(SESSION_STORE)


EVIDENCE_STORE = _build_evidence_store()


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
_VISION_ALLOWED_MIME = {"image/jpeg", "image/png"}
_VISION_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
_VISION_MAX_EDGE = 1024
_EVIDENCE_IMAGE_ALLOWED_MIME = {"image/jpeg", "image/png"}
_EVIDENCE_IMAGE_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
_EVIDENCE_AUDIO_ALLOWED_MIME = {"audio/mpeg", "audio/mp4", "audio/aac", "audio/ogg", "audio/wav", "audio/x-wav"}
_EVIDENCE_AUDIO_ALLOWED_EXTENSIONS = {".mp3", ".m4a", ".aac", ".ogg", ".wav"}


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


def _read_dotenv_value(path: Path, key: str) -> str:
    if not path.exists() or not path.is_file():
        return ""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""

    prefix = f"{key}="
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith(prefix):
            continue

        value = line[len(prefix):].strip()
        if len(value) >= 2 and ((value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'"))):
            value = value[1:-1]
        return value.strip()
    return ""


def _load_openai_api_key() -> str:
    env_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if env_key:
        return env_key

    repo_key = _read_dotenv_value(REPO_DOTENV_PATH, "OPENAI_API_KEY")
    if repo_key:
        return repo_key

    return _read_dotenv_value(LOCAL_DOTENV_PATH, "OPENAI_API_KEY")


def _vision_model_name() -> str:
    configured = (
        os.environ.get("OPENAI_VISION_MODEL")
        or _read_dotenv_value(REPO_DOTENV_PATH, "OPENAI_VISION_MODEL")
        or _read_dotenv_value(LOCAL_DOTENV_PATH, "OPENAI_VISION_MODEL")
        or ""
    ).strip()
    if configured:
        return configured
    return "gpt-4o-mini"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _vision_empty_state() -> dict[str, object]:
    return {
        "summary": "No visual analysis available yet.",
        "observations": [],
        "recommended_next_step": "Upload a PNG or JPEG image to start manual visual analysis.",
        "copilot_prompt": "",
        "copilot_prompt_contextual": "",
        "clarification_request": "",
        "development_relevance": "UNKNOWN",
        "evidence_strength": 0.0,
        "context_fusion_allowed": False,
        "confidence": 0.0,
        "generated_at": _utc_now_iso(),
        "analysis_timestamp": "",
        "last_screenshot_processed": "",
        "auto_analysis_status": "idle",
        "source": "manual_upload",
        "has_data": False,
    }


def _vision_size_bucket(size_bytes: int) -> str:
    if size_bytes < 200_000:
        return "small"
    if size_bytes < 1_000_000:
        return "medium"
    return "large"


def _vision_filename_hint(filename: str) -> str:
    lower_name = filename.lower()
    if any(token in lower_name for token in ["error", "trace", "exception", "fail"]):
        return "error_focus"
    if any(token in lower_name for token in ["api", "backend", "server"]):
        return "backend_focus"
    if any(token in lower_name for token in ["ui", "screen", "hud", "display"]):
        return "ui_focus"
    return "general_focus"


def _build_mock_vision_payload(filename: str, content_type: str, size_bytes: int) -> dict[str, object]:
    size_bucket = _vision_size_bucket(size_bytes)
    hint = _vision_filename_hint(filename)

    summary_map = {
        "error_focus": "Captured screen appears focused on an error or failure state.",
        "backend_focus": "Captured screen appears focused on backend/API activity.",
        "ui_focus": "Captured screen appears focused on UI and display behavior.",
        "general_focus": "Captured screen appears focused on an active development task.",
    }
    next_step_map = {
        "error_focus": "Ask Copilot to identify the likely root cause and propose the smallest safe fix.",
        "backend_focus": "Ask Copilot to verify endpoint contracts and response schema consistency.",
        "ui_focus": "Ask Copilot to validate UI state transitions and data bindings.",
        "general_focus": "Ask Copilot to summarize current context and propose the next concrete step.",
    }

    confidence = 0.74 if size_bucket == "medium" else 0.67
    if hint == "error_focus":
        confidence = 0.79

    observations = [
        f"filename={filename}",
        f"content_type={content_type}",
        f"size_bytes={size_bytes}",
        f"size_bucket={size_bucket}",
        f"focus_hint={hint}",
    ]

    recommended_next_step = next_step_map[hint]
    summary = summary_map[hint]
    copilot_prompt = (
        "You are helping with a coding workflow based on a captured screen image.\n"
        f"Image metadata: filename={filename}, content_type={content_type}, size_bytes={size_bytes}, "
        f"size_bucket={size_bucket}, focus_hint={hint}.\n"
        f"Summary: {summary}\n"
        f"Recommended next step: {recommended_next_step}\n"
        "Please provide:\n"
        "1) A concise diagnosis of what is likely happening.\n"
        "2) The smallest safe next code or config change.\n"
        "3) A quick validation checklist to confirm success."
    )

    return {
        "summary": summary,
        "observations": observations,
        "recommended_next_step": recommended_next_step,
        "copilot_prompt": copilot_prompt,
        "confidence": confidence,
        "generated_at": _utc_now_iso(),
        "source": "manual_upload",
        "has_data": True,
    }


def _build_mock_fallback_payload(filename: str, content_type: str, size_bytes: int, source: str, reason: str = "") -> dict[str, object]:
    payload = _build_mock_vision_payload(filename, content_type, size_bytes)
    payload["source"] = source
    if reason:
        observations_raw = payload.get("observations")
        observations = list(observations_raw) if isinstance(observations_raw, list) else []
        observations.append(f"fallback_reason={reason}")
        payload["observations"] = observations
    return payload


def _prepare_image_for_openai(image_bytes: bytes) -> tuple[str, dict[str, object]]:
    if Image is None:
        raise RuntimeError("Pillow is not available for image preprocessing.")

    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except Exception as exc:
        raise RuntimeError(f"Could not decode image bytes: {exc}") from exc

    original_width, original_height = image.size
    max_edge = max(original_width, original_height)
    if max_edge > _VISION_MAX_EDGE:
        scale = _VISION_MAX_EDGE / float(max_edge)
        new_width = max(1, int(original_width * scale))
        new_height = max(1, int(original_height * scale))
        image = image.resize((new_width, new_height))

    if image.mode != "RGB":
        image = image.convert("RGB")

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=85, optimize=True)
    processed_bytes = output.getvalue()
    encoded = base64.b64encode(processed_bytes).decode("ascii")

    return encoded, {
        "original_size": [original_width, original_height],
        "processed_size": [image.size[0], image.size[1]],
        "processed_format": "jpeg",
        "processed_bytes": len(processed_bytes),
    }


def _extract_json_object(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)

    if raw.startswith("{") and raw.endswith("}"):
        return raw

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start : end + 1]
    return ""


def _normalized_confidence(value: object, fallback: float = 0.5) -> float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        parsed = fallback
    return max(0.0, min(1.0, parsed))


def _normalize_vision_model_payload(payload: dict[str, object], generated_at: str) -> dict[str, object]:
    summary = str(payload.get("summary") or "").strip()
    recommended_next_step = str(payload.get("recommended_next_step") or "").strip()
    copilot_prompt = str(payload.get("copilot_prompt") or "").strip()

    observations_raw = payload.get("observations")
    observations: list[str]
    if isinstance(observations_raw, list):
        observations = [str(item).strip() for item in observations_raw if str(item).strip()]
    else:
        observations = []

    if not summary:
        summary = "Unable to confidently summarize screenshot contents."
    if not recommended_next_step:
        recommended_next_step = "Ask Copilot to inspect the visible errors and propose the smallest safe fix."
    if not copilot_prompt:
        copilot_prompt = (
            "Analyze the screenshot context and propose a minimal safe fix. "
            "Include likely root cause, exact next step, and a validation checklist."
        )

    return {
        "summary": summary,
        "observations": observations,
        "recommended_next_step": recommended_next_step,
        "copilot_prompt": copilot_prompt,
        "confidence": _normalized_confidence(payload.get("confidence"), fallback=0.5),
        "generated_at": generated_at,
        "source": "openai_vision",
        "has_data": True,
    }


def _workflow_context_for_vision_fusion() -> dict[str, str]:
    resume_payload = _safe_load_json(RESUME_NOW_JSON)
    fusion_payload = _safe_load_json(CONTEXT_FUSION_JSON)

    active_file_payload_raw = resume_payload.get("active_file")
    active_file_payload = active_file_payload_raw if isinstance(active_file_payload_raw, dict) else {}
    resume_dev_raw = resume_payload.get("development_context")
    resume_dev = resume_dev_raw if isinstance(resume_dev_raw, dict) else {}
    fusion_dev_raw = fusion_payload.get("development_context")
    fusion_dev = fusion_dev_raw if isinstance(fusion_dev_raw, dict) else {}

    active_file = (
        _basename_only(active_file_payload.get("active_file_name") or active_file_payload.get("active_file_path"))
        or _basename_only(resume_dev.get("active_file"))
        or _basename_only(fusion_dev.get("active_file"))
        or "unknown_file"
    )

    task_tracking_raw = resume_payload.get("task_tracking")
    task_tracking = task_tracking_raw if isinstance(task_tracking_raw, dict) else {}
    current_task = (
        str(task_tracking.get("current_task") or "").strip()
        or str(resume_payload.get("current_focus") or "").strip()
        or str(fusion_payload.get("selected_source") or "").strip()
        or "unknown_task"
    )

    has_terminal_error = False
    resume_terminal_raw = resume_payload.get("has_terminal_error")
    fusion_terminal_raw = fusion_payload.get("has_terminal_error")
    if isinstance(resume_terminal_raw, bool):
        has_terminal_error = resume_terminal_raw
    elif isinstance(fusion_terminal_raw, bool):
        has_terminal_error = fusion_terminal_raw
    terminal_state = "terminal_error_detected" if has_terminal_error else "no_terminal_error_detected"

    git_risk = ""
    git_risk_context_raw = resume_payload.get("git_risk_context")
    git_risk_context = git_risk_context_raw if isinstance(git_risk_context_raw, dict) else {}
    if isinstance(git_risk_context.get("risk_level"), str):
        git_risk = str(git_risk_context.get("risk_level") or "").strip().lower()

    modified_files = resume_payload.get("modified_files")
    staged_files = resume_payload.get("staged_files")
    if not isinstance(modified_files, int):
        modified_files = fusion_payload.get("modified_files") if isinstance(fusion_payload.get("modified_files"), int) else 0
    if not isinstance(staged_files, int):
        staged_files = fusion_payload.get("staged_files") if isinstance(fusion_payload.get("staged_files"), int) else 0

    branch = str(resume_payload.get("active_branch") or fusion_payload.get("active_branch") or "unknown_branch").strip() or "unknown_branch"
    git_status = f"modified_files={modified_files}, staged_files={staged_files}, risk_level={git_risk or 'unknown'}"

    primary_guidance_raw = resume_payload.get("primary_guidance")
    primary_guidance = primary_guidance_raw if isinstance(primary_guidance_raw, dict) else {}
    guidance_priority_raw = resume_payload.get("guidance_priority")
    guidance_priority = guidance_priority_raw if isinstance(guidance_priority_raw, dict) else {}
    last_guidance = (
        str(primary_guidance.get("headline") or guidance_priority.get("headline") or "").strip()
        or str(guidance_priority.get("message") or "").strip()
        or "No guidance available"
    )

    project_progress_raw = resume_payload.get("project_progress")
    project_progress = project_progress_raw if isinstance(project_progress_raw, dict) else {}
    architecture_context_raw = resume_payload.get("architecture_context")
    architecture_context = architecture_context_raw if isinstance(architecture_context_raw, dict) else {}
    project_context = "; ".join(
        item
        for item in [
            f"milestone={str(project_progress.get('current_milestone') or 'unknown').strip()}",
            f"component={str(architecture_context.get('current_component') or active_file).strip()}",
            f"source={str(fusion_payload.get('selected_source') or 'unknown').strip()}",
        ]
        if item
    )

    return {
        "active_file": active_file,
        "current_task": current_task,
        "terminal_state": terminal_state,
        "git_status": git_status,
        "branch": branch,
        "last_guidance": last_guidance,
        "project_context": project_context,
    }


def _build_contextual_copilot_prompt(vision_payload: dict[str, object]) -> str:
    relevance = str(vision_payload.get("development_relevance") or "").strip().upper()
    if relevance == "LOW_RELEVANCE":
        return str(vision_payload.get("clarification_request") or "").strip()
    if relevance == "MEDIUM_RELEVANCE":
        return _build_contextual_copilot_prompt_limited(vision_payload)

    return _build_contextual_copilot_prompt_full(vision_payload)


def _build_contextual_copilot_prompt_full(vision_payload: dict[str, object]) -> str:
    context = _workflow_context_for_vision_fusion()

    summary = str(vision_payload.get("summary") or "No visual summary available.").strip()
    observations_raw = vision_payload.get("observations")
    observations = [str(item).strip() for item in observations_raw if str(item).strip()] if isinstance(observations_raw, list) else []
    recommended_next_step = str(vision_payload.get("recommended_next_step") or "Investigate likely root cause and apply minimal safe fix.").strip()
    confidence = _normalized_confidence(vision_payload.get("confidence"), fallback=0.5)

    problem_statement = (
        f"Visual analysis suggests: {summary}. "
        f"Workflow context indicates {context.get('terminal_state')} while working on {context.get('active_file')}."
    )

    observations_text = "; ".join(observations[:6]) if observations else "No structured observations"

    return (
        "You are helping with the Custom Meta AI Glasses project.\n\n"
        f"The screenshot shows: {summary}\n"
        f"The user is currently editing: {context.get('active_file')}\n"
        f"Current active task: {context.get('current_task')}\n"
        f"Terminal state: {context.get('terminal_state')}\n"
        f"Git status: {context.get('git_status')}\n"
        f"Current branch: {context.get('branch')}\n"
        f"Last guidance: {context.get('last_guidance')}\n"
        f"Project context: {context.get('project_context')}\n"
        f"Observed screenshot evidence: {observations_text}\n"
        f"Problem appears to exist: {problem_statement}\n"
        f"Vision confidence: {confidence:.2f}\n\n"
        "Instructions for Copilot:\n"
        f"1. Review {context.get('active_file')} first and identify the most likely root cause that matches the screenshot evidence.\n"
        "2. Provide exact code changes (minimal safe diff) and explain why they solve the issue.\n"
        "3. Include validation commands/checks that confirm the fix.\n"
        f"4. Align the fix with this next step recommendation: {recommended_next_step}"
    )


def _build_contextual_copilot_prompt_limited(vision_payload: dict[str, object]) -> str:
    context = _workflow_context_for_vision_fusion()

    summary = str(vision_payload.get("summary") or "No visual summary available.").strip()
    observations_raw = vision_payload.get("observations")
    observations = [str(item).strip() for item in observations_raw if str(item).strip()] if isinstance(observations_raw, list) else []
    recommended_next_step = str(vision_payload.get("recommended_next_step") or "Request clearer screenshot evidence.").strip()
    confidence = _normalized_confidence(vision_payload.get("confidence"), fallback=0.5)

    observations_text = "; ".join(observations[:5]) if observations else "No structured observations"

    return (
        "You are helping with the Custom Meta AI Glasses project.\n\n"
        "Evidence relevance: MEDIUM. Some project-related content may be present, but screenshot-to-task linkage is uncertain.\n"
        f"The screenshot appears to show: {summary}\n"
        f"Observed evidence: {observations_text}\n"
        f"Current branch context (may be unrelated): {context.get('branch')}\n"
        f"Current task context (may be unrelated): {context.get('current_task')}\n"
        f"Vision confidence: {confidence:.2f}\n\n"
        "Instructions for Copilot:\n"
        "1. Ask for one clarifying detail before proposing risky code edits.\n"
        "2. Provide conservative, low-risk guidance only, tied strictly to visible evidence.\n"
        "3. If evidence is insufficient, request a clearer dev screenshot (editor/terminal/error).\n"
        f"4. Use this as a tentative next step: {recommended_next_step}"
    )


def _development_relevance_payload(vision_payload: dict[str, object], filename: str) -> dict[str, object]:
    summary = str(vision_payload.get("summary") or "").strip().lower()
    next_step = str(vision_payload.get("recommended_next_step") or "").strip().lower()
    observations_raw = vision_payload.get("observations")
    observations = [str(item).strip().lower() for item in observations_raw if str(item).strip()] if isinstance(observations_raw, list) else []
    combined = " ".join([summary, next_step, " ".join(observations), filename.lower()])

    high_tokens = [
        "vscode", "cursor", "terminal", "traceback", "exception", "error", "fastapi", "api", "http",
        "cloudflare", "tunnel", "git", "conflict", "merge", "stack", "module", "warning", "code",
        "python", "json", "endpoint", "response", "docs", "documentation", "architecture",
    ]
    medium_tokens = [
        "project", "milestone", "workflow", "design", "diagram", "readme", "research", "analysis", "session",
    ]
    low_tokens = [
        "landscape", "mountain", "lake", "bird", "ferris", "mouse", "razer", "selfie", "pet", "photo",
    ]

    high_score = sum(1 for token in high_tokens if token in combined)
    medium_score = sum(1 for token in medium_tokens if token in combined)
    low_score = sum(1 for token in low_tokens if token in combined)
    base_conf = _normalized_confidence(vision_payload.get("confidence"), fallback=0.5)

    if low_score >= 1 and high_score == 0 and medium_score <= 1:
        evidence_strength = max(0.0, min(1.0, 0.15 + (base_conf * 0.2)))
        return {
            "development_relevance": "LOW_RELEVANCE",
            "evidence_strength": round(evidence_strength, 2),
            "context_fusion_allowed": False,
            "clarification_request": (
                "This image does not appear to contain software-development content.\n\n"
                "Upload a screenshot showing:\n"
                "- VS Code or Cursor\n"
                "- terminal output\n"
                "- browser/API/Cloudflare error\n"
                "- git issue\n"
                "- architecture diagram\n\n"
                "to receive coding assistance."
            ),
        }

    if high_score >= 2:
        evidence_strength = max(0.0, min(1.0, 0.55 + (high_score * 0.07) + (base_conf * 0.25) - (low_score * 0.08)))
        return {
            "development_relevance": "HIGH_RELEVANCE",
            "evidence_strength": round(evidence_strength, 2),
            "context_fusion_allowed": True,
            "clarification_request": "",
        }

    evidence_strength = max(0.0, min(1.0, 0.35 + (medium_score * 0.06) + (base_conf * 0.2) - (low_score * 0.05)))
    return {
        "development_relevance": "MEDIUM_RELEVANCE",
        "evidence_strength": round(evidence_strength, 2),
        "context_fusion_allowed": True,
        "clarification_request": "Screenshot may be partially related to development context; provide a clearer editor/terminal/error capture if available.",
    }


def _apply_evidence_gating(vision_payload: dict[str, object], filename: str) -> dict[str, object]:
    gated = dict(vision_payload)
    classification = _development_relevance_payload(gated, filename)
    gated.update(classification)

    relevance = str(gated.get("development_relevance") or "").strip().upper()
    if relevance == "LOW_RELEVANCE":
        summary = str(gated.get("summary") or "").strip() or "Screenshot appears unrelated to software-development workflow."
        gated["summary"] = summary

        observations_raw = gated.get("observations")
        observations = [str(item).strip() for item in observations_raw if str(item).strip()] if isinstance(observations_raw, list) else []
        if not observations:
            observations = ["No software-development evidence detected in screenshot."]
        gated["observations"] = observations[:8]

        gated["recommended_next_step"] = "Upload a development-focused screenshot to receive coding guidance."
        gated["copilot_prompt"] = str(gated.get("clarification_request") or "").strip()
        gated["copilot_prompt_contextual"] = str(gated.get("clarification_request") or "").strip()

    return gated


def _call_openai_vision(filename: str, content_type: str, image_bytes: bytes) -> dict[str, object]:
    api_key = _load_openai_api_key()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    if OpenAI is None:
        raise RuntimeError("OpenAI SDK is not available")

    encoded_image, image_meta = _prepare_image_for_openai(image_bytes)
    model_name = _vision_model_name()

    system_prompt = (
        "You are an expert software engineering assistant analyzing screenshots from development workflows. "
        "Identify concrete evidence from the image: IDE/editor details, file names, terminal errors, stack traces, "
        "browser/API/Cloudflare errors, git state, test failures, JSON payloads, and UI state. "
        "Return ONLY valid JSON with keys: summary, observations, recommended_next_step, copilot_prompt, confidence. "
        "observations must be a JSON array of short strings. confidence must be 0.0 to 1.0. "
        "copilot_prompt must be directly pasteable into GitHub Copilot Chat and include visible error details."
    )
    user_prompt = (
        "Analyze this screenshot and return only JSON. "
        f"File metadata: filename={filename}, content_type={content_type}, "
        f"processed_size={image_meta.get('processed_size')}."
    )

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model_name,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encoded_image}",
                            "detail": "low",
                        },
                    },
                ],
            },
        ],
    )

    content = str(response.choices[0].message.content or "")
    json_text = _extract_json_object(content)
    if not json_text:
        raise ValueError("Model response did not contain a JSON object.")

    parsed = json.loads(json_text)
    if not isinstance(parsed, dict):
        raise ValueError("Model JSON response must be an object.")

    normalized = _normalize_vision_model_payload(parsed, generated_at=_utc_now_iso())
    observations_raw = normalized.get("observations")
    observations = list(observations_raw) if isinstance(observations_raw, list) else []
    observations.extend(
        [
            f"model={model_name}",
            f"processed_size={image_meta.get('processed_size')}",
            f"processed_bytes={image_meta.get('processed_bytes')}",
        ]
    )
    normalized["observations"] = observations
    return normalized


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


def _raise_session_http_error(status_code: int, category: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail={"category": category, "message": message})


def _ensure_optional_glasses_token_auth(request: Request, token: str, *, unauthorized_message: str) -> None:
    if GLASSES_API_TOKEN:
        candidate = token.strip() or _extract_bearer_token(request)
        if candidate != GLASSES_API_TOKEN:
            _raise_session_http_error(status_code=401, category="unauthorized", message=unauthorized_message)


def _parse_session_create_payload(payload: dict[str, object] | None) -> InvestigationSessionCreateRequest:
    raw = payload or {}
    try:
        return InvestigationSessionCreateRequest.model_validate(raw)
    except ValidationError as exc:
        _raise_session_http_error(status_code=422, category="validation_error", message=str(exc.errors()[0].get("msg", "Invalid request payload.")))


def _parse_session_mutation_payload(payload: dict[str, object] | None) -> InvestigationSessionMutationRequest:
    raw = payload or {}
    try:
        return InvestigationSessionMutationRequest.model_validate(raw)
    except ValidationError as exc:
        _raise_session_http_error(status_code=422, category="validation_error", message=str(exc.errors()[0].get("msg", "Invalid request payload.")))


def _validate_session_id_or_422(session_id: str) -> str:
    try:
        return str(UUID(str(session_id).strip()))
    except ValueError:
        _raise_session_http_error(status_code=422, category="invalid_session_id", message="session_id must be a valid UUID.")


def _parse_optional_utc_datetime(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError("captured_at_utc must be a valid UTC timestamp.") from exc

    if parsed.tzinfo is None:
        raise ValueError("captured_at_utc must be timezone-aware UTC.")

    return parsed.astimezone(timezone.utc)


async def _read_bounded_upload(file: UploadFile, *, max_bytes: int) -> tuple[bytes, str, str]:
    filename = Path(file.filename or "upload.bin").name
    content_type = str(file.content_type or "").strip().lower()
    buffer = bytearray()
    try:
        while True:
            chunk = await file.read(UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > max_bytes:
                raise HTTPException(status_code=413, detail={"category": "upload_too_large", "message": "Evidence upload is too large."})
        return bytes(buffer), content_type, filename
    finally:
        await file.close()


def _parse_evidence_create_request(
    *,
    source: str,
    client_timestamp_utc: str | None,
    normalized_text: str | None,
    metadata: str | None,
    filename: str | None,
    mime_type: str | None,
    width: int | None,
    height: int | None,
    duration_seconds: float | None,
) -> InvestigationEvidenceCreateRequest:
    metadata_payload: dict[str, object] | None = None
    normalized_source = str(source or "").strip() or "backend"
    normalized_text = str(normalized_text or "").strip() or None
    normalized_filename = str(filename or "").strip() or None
    normalized_mime_type = str(mime_type or "").strip() or None
    metadata_text = str(metadata or "").strip()
    if metadata_text:
        try:
            parsed = json.loads(metadata_text)
        except json.JSONDecodeError as exc:
            raise ValueError("metadata must be valid JSON.") from exc
        if not isinstance(parsed, dict):
            raise ValueError("metadata must be a JSON object.")
        metadata_payload = parsed

    return InvestigationEvidenceCreateRequest.model_validate(
        {
            "source": normalized_source,
            "client_timestamp_utc": _parse_optional_utc_datetime(client_timestamp_utc),
            "normalized_text": normalized_text,
            "metadata": metadata_payload,
            "filename": normalized_filename,
            "mime_type": normalized_mime_type,
            "width": width,
            "height": height,
            "duration_seconds": duration_seconds,
        }
    )


def _validate_evidence_media_type(*, evidence_type: InvestigationEvidenceType, content_type: str, filename: str) -> None:
    suffix = Path(filename or "").suffix.lower()
    normalized_content_type = str(content_type or "").strip().lower()

    if evidence_type == InvestigationEvidenceType.IMAGE:
        if normalized_content_type not in _EVIDENCE_IMAGE_ALLOWED_MIME:
            raise HTTPException(status_code=415, detail={"category": "unsupported_media_type", "message": "Use image/jpeg or image/png for image evidence."})
        if suffix and suffix not in _EVIDENCE_IMAGE_ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=415, detail={"category": "unsupported_media_type", "message": "Use .jpg, .jpeg, or .png for image evidence."})
        return

    if evidence_type == InvestigationEvidenceType.AUDIO:
        if normalized_content_type not in _EVIDENCE_AUDIO_ALLOWED_MIME:
            raise HTTPException(status_code=415, detail={"category": "unsupported_media_type", "message": "Use a supported audio content type for audio evidence."})
        if suffix and suffix not in _EVIDENCE_AUDIO_ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=415, detail={"category": "unsupported_media_type", "message": "Use .mp3, .m4a, .aac, .ogg, or .wav for audio evidence."})
        return

    raise HTTPException(status_code=415, detail={"category": "unsupported_media_type", "message": "Unsupported evidence type."})


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


def _load_investigation_context_snapshot_from_context_fusion() -> dict[str, object] | None:
    # Phase 1B integration debt: context_fusion._build_payload is the currently
    # canonical available context snapshot producer, but it is private.
    # Keep this adapter isolated and fail-open so context issues never block
    # investigation analysis.
    try:
        from context_fusion import _build_payload as build_context_payload
    except Exception:
        return None

    if not callable(build_context_payload):
        return None

    try:
        payload = build_context_payload()
    except Exception:
        return None

    return payload if isinstance(payload, dict) else None


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


@app.get("/investigations", response_class=FileResponse)
async def investigations_page_alias():
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


@app.get("/vision/latest")
async def vision_latest():
    payload = _safe_load_json(VISION_CONTEXT_JSON)
    if payload:
        payload.setdefault("has_data", True)
        return payload
    return _vision_empty_state()


@app.post("/vision/analyze")
async def vision_analyze(request: Request, file: UploadFile = File(...)):
    content_type = str(file.content_type or "").strip().lower()
    filename = Path(file.filename or "upload.jpg").name
    suffix = Path(filename).suffix.lower()

    if content_type not in _VISION_ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="Unsupported content type. Use image/jpeg or image/png.")

    if suffix and suffix not in _VISION_ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file extension. Use .jpg, .jpeg, or .png.")

    image_bytes = await file.read()
    size_bytes = len(image_bytes)
    await file.close()

    if size_bytes <= 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        payload = _call_openai_vision(filename=filename, content_type=content_type, image_bytes=image_bytes)
    except ValueError as exc:
        payload = _build_mock_fallback_payload(
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            source="mock_fallback_parse_error",
            reason=str(exc),
        )
    except Exception as exc:
        payload = _build_mock_fallback_payload(
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            source="mock_fallback",
            reason=type(exc).__name__,
        )

    trigger = str(request.headers.get("X-Vision-Trigger", "")).strip().lower()
    is_auto = trigger in {"watcher", "auto", "auto_watcher", "screenshot_watcher"}
    payload = _apply_evidence_gating(payload, filename=filename)
    analysis_timestamp = str(payload.get("generated_at") or _utc_now_iso())

    if str(payload.get("development_relevance") or "").strip().upper() != "LOW_RELEVANCE":
        payload["copilot_prompt_contextual"] = _build_contextual_copilot_prompt(payload)
    payload["analysis_timestamp"] = analysis_timestamp
    payload["last_screenshot_processed"] = filename
    payload["auto_analysis_status"] = "auto_analyzed" if is_auto else "manual_upload"
    _safe_write_json(VISION_CONTEXT_JSON, payload)
    return payload


@app.post("/investigations/analyze", response_model=InvestigationAnalyzeResponse)
async def investigations_analyze(
    schema_version: str = Form(...),
    session_id: str = Form(...),
    idempotency_key: str = Form(...),
    user_explanation: str = Form(""),
    images: list[UploadFile] = File(...),
):
    public_response, retained_result = await analyze_investigation_request_with_retained(
        schema_version=schema_version,
        session_id=session_id,
        idempotency_key=idempotency_key,
        user_explanation=user_explanation,
        images=images,
        openai_client_factory=OpenAI,
        load_openai_api_key=_load_openai_api_key,
        load_model_name=_vision_model_name,
        prepare_image_for_openai=_prepare_image_for_openai,
        extract_json_object=_extract_json_object,
        load_context_snapshot=_load_investigation_context_snapshot_from_context_fusion,
    )

    try:
        save_latest_investigation_result(INVESTIGATION_LATEST_JSON, retained_result)
    except InvestigationStoreError as exc:
        raise HTTPException(status_code=500, detail="Investigation result persistence failed.") from exc

    return public_response


@app.get("/investigations/latest", response_model=InvestigationDesktopProjection)
async def investigations_latest() -> InvestigationDesktopProjection:
    try:
        retained_result = load_latest_investigation_result(INVESTIGATION_LATEST_JSON)
    except InvestigationStoreNotFound as exc:
        raise HTTPException(status_code=404, detail="No retained investigation result exists.") from exc
    except InvestigationStoreError as exc:
        raise HTTPException(status_code=500, detail="Retained investigation result is unavailable.") from exc

    stale_seconds = investigation_stale_seconds()
    return build_desktop_projection(retained_result, stale_seconds=stale_seconds)


@app.get("/investigations/latest/glasses", response_model=InvestigationGlassesProjection)
async def investigations_latest_glasses(request: Request, token: str = Query(default="")) -> InvestigationGlassesProjection:
    if GLASSES_API_TOKEN:
        candidate = token.strip() or _extract_bearer_token(request)
        if candidate != GLASSES_API_TOKEN:
            raise HTTPException(status_code=401, detail="Unauthorized token for glasses endpoint.")

    try:
        retained_result = load_latest_investigation_result(INVESTIGATION_LATEST_JSON)
    except InvestigationStoreNotFound as exc:
        raise HTTPException(status_code=404, detail="No retained investigation result exists.") from exc
    except InvestigationStoreError as exc:
        raise HTTPException(status_code=500, detail="Retained investigation result is unavailable.") from exc

    stale_seconds = investigation_stale_seconds()
    return build_glasses_projection(retained_result, stale_seconds=stale_seconds)


@app.post("/investigation-sessions", response_model=InvestigationSession, status_code=201)
async def create_investigation_session(
    request: Request,
    token: str = Query(default=""),
    payload: dict[str, object] | None = None,
) -> InvestigationSession:
    _ensure_optional_glasses_token_auth(
        request,
        token,
        unauthorized_message="Unauthorized token for session endpoint.",
    )
    create_request = _parse_session_create_payload(payload)

    try:
        return SESSION_STORE.create_session(client_metadata=create_request.client_metadata)
    except InvestigationSessionStoreError:
        _raise_session_http_error(status_code=500, category="session_storage_error", message="Session storage is unavailable.")


@app.get("/investigation-sessions/{session_id}", response_model=InvestigationSession)
async def get_investigation_session(
    session_id: str,
    request: Request,
    token: str = Query(default=""),
) -> InvestigationSession:
    _ensure_optional_glasses_token_auth(
        request,
        token,
        unauthorized_message="Unauthorized token for session endpoint.",
    )
    normalized_session_id = _validate_session_id_or_422(session_id)
    try:
        return SESSION_STORE.load_session(normalized_session_id)
    except InvestigationSessionNotFound:
        _raise_session_http_error(status_code=404, category="session_not_found", message="Session does not exist.")
    except InvestigationSessionInvalidId:
        _raise_session_http_error(status_code=422, category="invalid_session_id", message="session_id must be a valid UUID.")
    except InvestigationSessionStoreError:
        _raise_session_http_error(status_code=500, category="session_storage_error", message="Session storage is unavailable.")


@app.post("/investigation-sessions/{session_id}/pause", response_model=InvestigationSession)
async def pause_investigation_session(
    session_id: str,
    request: Request,
    token: str = Query(default=""),
    payload: dict[str, object] | None = None,
) -> InvestigationSession:
    _ensure_optional_glasses_token_auth(
        request,
        token,
        unauthorized_message="Unauthorized token for session endpoint.",
    )
    normalized_session_id = _validate_session_id_or_422(session_id)
    mutation = _parse_session_mutation_payload(payload)

    try:
        return SESSION_STORE.mutate_session(
            normalized_session_id,
            lambda session: apply_pause_transition(session, expected_revision=mutation.expected_revision),
        )
    except InvestigationSessionNotFound:
        _raise_session_http_error(status_code=404, category="session_not_found", message="Session does not exist.")
    except InvestigationSessionLifecycleError as exc:
        _raise_session_http_error(status_code=409, category=exc.category, message=exc.message)
    except InvestigationSessionInvalidId:
        _raise_session_http_error(status_code=422, category="invalid_session_id", message="session_id must be a valid UUID.")
    except InvestigationSessionStoreError:
        _raise_session_http_error(status_code=500, category="session_storage_error", message="Session storage is unavailable.")


@app.post("/investigation-sessions/{session_id}/resume", response_model=InvestigationSession)
async def resume_investigation_session(
    session_id: str,
    request: Request,
    token: str = Query(default=""),
    payload: dict[str, object] | None = None,
) -> InvestigationSession:
    _ensure_optional_glasses_token_auth(
        request,
        token,
        unauthorized_message="Unauthorized token for session endpoint.",
    )
    normalized_session_id = _validate_session_id_or_422(session_id)
    mutation = _parse_session_mutation_payload(payload)

    try:
        return SESSION_STORE.mutate_session(
            normalized_session_id,
            lambda session: apply_resume_transition(session, expected_revision=mutation.expected_revision),
        )
    except InvestigationSessionNotFound:
        _raise_session_http_error(status_code=404, category="session_not_found", message="Session does not exist.")
    except InvestigationSessionLifecycleError as exc:
        _raise_session_http_error(status_code=409, category=exc.category, message=exc.message)
    except InvestigationSessionInvalidId:
        _raise_session_http_error(status_code=422, category="invalid_session_id", message="session_id must be a valid UUID.")
    except InvestigationSessionStoreError:
        _raise_session_http_error(status_code=500, category="session_storage_error", message="Session storage is unavailable.")


@app.post("/investigation-sessions/{session_id}/cancel", response_model=InvestigationSession)
async def cancel_investigation_session(
    session_id: str,
    request: Request,
    token: str = Query(default=""),
    payload: dict[str, object] | None = None,
) -> InvestigationSession:
    _ensure_optional_glasses_token_auth(
        request,
        token,
        unauthorized_message="Unauthorized token for session endpoint.",
    )
    normalized_session_id = _validate_session_id_or_422(session_id)
    mutation = _parse_session_mutation_payload(payload)

    try:
        return SESSION_STORE.mutate_session(
            normalized_session_id,
            lambda session: apply_cancel_transition(session, expected_revision=mutation.expected_revision),
        )
    except InvestigationSessionNotFound:
        _raise_session_http_error(status_code=404, category="session_not_found", message="Session does not exist.")
    except InvestigationSessionLifecycleError as exc:
        _raise_session_http_error(status_code=409, category=exc.category, message=exc.message)
    except InvestigationSessionInvalidId:
        _raise_session_http_error(status_code=422, category="invalid_session_id", message="session_id must be a valid UUID.")
    except InvestigationSessionStoreError:
        _raise_session_http_error(status_code=500, category="session_storage_error", message="Session storage is unavailable.")


async def _upload_investigation_session_evidence(
    *,
    response: Response,
    session_id: str,
    request: Request,
    token: str,
    file: UploadFile,
    evidence_type: InvestigationEvidenceType,
    source: str,
    client_timestamp_utc: str | None,
    normalized_text: str | None,
    metadata: str | None,
    width: int | None,
    height: int | None,
    duration_seconds: float | None,
) -> InvestigationEvidence:
    _ensure_optional_glasses_token_auth(
        request,
        token,
        unauthorized_message="Unauthorized token for session endpoint.",
    )
    normalized_session_id = _validate_session_id_or_422(session_id)
    try:
        max_bytes = MAX_IMAGE_UPLOAD_BYTES if evidence_type == InvestigationEvidenceType.IMAGE else MAX_AUDIO_UPLOAD_BYTES
        raw_bytes, content_type, filename = await _read_bounded_upload(file, max_bytes=max_bytes)
    except HTTPException:
        raise

    if not raw_bytes:
        raise HTTPException(status_code=422, detail={"category": "invalid_upload", "message": "Uploaded evidence file is empty."})

    _validate_evidence_media_type(evidence_type=evidence_type, content_type=content_type, filename=filename)

    try:
        create_request = _parse_evidence_create_request(
            source=source,
            client_timestamp_utc=client_timestamp_utc,
            normalized_text=normalized_text,
            metadata=metadata,
            filename=filename,
            mime_type=content_type,
            width=width,
            height=height,
            duration_seconds=duration_seconds,
        )
    except ValueError as exc:
        category = "invalid_upload" if "metadata must" in str(exc).lower() else "validation_error"
        raise HTTPException(status_code=422, detail={"category": category, "message": str(exc)}) from exc

    try:
        evidence, created = EVIDENCE_STORE.upload_evidence(
            session_id=normalized_session_id,
            evidence_type=evidence_type,
            raw_bytes=raw_bytes,
            original_filename=filename,
            request=create_request,
            mime_type=content_type,
        )
    except InvestigationSessionNotFound:
        _raise_session_http_error(status_code=404, category="session_not_found", message="Session does not exist.")
    except InvestigationSessionInvalidId:
        _raise_session_http_error(status_code=422, category="invalid_session_id", message="session_id must be a valid UUID.")
    except InvestigationEvidenceStateError as exc:
        _raise_session_http_error(status_code=409, category="invalid_state_transition", message=str(exc))
    except InvestigationEvidenceStoreError:
        _raise_session_http_error(status_code=500, category="evidence_storage_error", message="Evidence storage is unavailable.")

    response.status_code = 201 if created else 200
    return evidence


@app.post("/investigation-sessions/{session_id}/evidence/image", response_model=InvestigationEvidence, status_code=201)
async def upload_investigation_session_image_evidence(
    session_id: str,
    request: Request,
    response: Response,
    token: str = Query(default=""),
    file: UploadFile = File(...),
    source: str = Form(default="backend"),
    client_timestamp_utc: str | None = Form(default=""),
    normalized_text: str | None = Form(default=""),
    metadata: str | None = Form(default=""),
    width: int | None = Form(default=None),
    height: int | None = Form(default=None),
) -> InvestigationEvidence:
    return await _upload_investigation_session_evidence(
        response=response,
        session_id=session_id,
        request=request,
        token=token,
        file=file,
        evidence_type=InvestigationEvidenceType.IMAGE,
        source=source,
        client_timestamp_utc=client_timestamp_utc,
        normalized_text=normalized_text,
        metadata=metadata,
        width=width,
        height=height,
        duration_seconds=None,
    )


@app.post("/investigation-sessions/{session_id}/evidence/audio", response_model=InvestigationEvidence, status_code=201)
async def upload_investigation_session_audio_evidence(
    session_id: str,
    request: Request,
    response: Response,
    token: str = Query(default=""),
    file: UploadFile = File(...),
    source: str = Form(default="backend"),
    client_timestamp_utc: str | None = Form(default=""),
    normalized_text: str | None = Form(default=""),
    metadata: str | None = Form(default=""),
    duration_seconds: float | None = Form(default=None),
) -> InvestigationEvidence:
    return await _upload_investigation_session_evidence(
        response=response,
        session_id=session_id,
        request=request,
        token=token,
        file=file,
        evidence_type=InvestigationEvidenceType.AUDIO,
        source=source,
        client_timestamp_utc=client_timestamp_utc,
        normalized_text=normalized_text,
        metadata=metadata,
        width=None,
        height=None,
        duration_seconds=duration_seconds,
    )


@app.get("/investigation-sessions/{session_id}/evidence", response_model=list[InvestigationEvidence])
async def list_investigation_session_evidence(
    session_id: str,
    request: Request,
    token: str = Query(default=""),
) -> list[InvestigationEvidence]:
    _ensure_optional_glasses_token_auth(
        request,
        token,
        unauthorized_message="Unauthorized token for session endpoint.",
    )
    normalized_session_id = _validate_session_id_or_422(session_id)

    try:
        return EVIDENCE_STORE.list_evidence(normalized_session_id)
    except InvestigationSessionNotFound:
        _raise_session_http_error(status_code=404, category="session_not_found", message="Session does not exist.")
    except InvestigationSessionInvalidId:
        _raise_session_http_error(status_code=422, category="invalid_session_id", message="session_id must be a valid UUID.")
    except InvestigationEvidenceStoreError:
        _raise_session_http_error(status_code=500, category="evidence_storage_error", message="Evidence storage is unavailable.")


@app.delete("/investigation-sessions/{session_id}/evidence/{evidence_id}", response_model=InvestigationEvidence)
async def delete_investigation_session_evidence(
    session_id: str,
    evidence_id: str,
    request: Request,
    token: str = Query(default=""),
) -> InvestigationEvidence:
    _ensure_optional_glasses_token_auth(
        request,
        token,
        unauthorized_message="Unauthorized token for session endpoint.",
    )
    normalized_session_id = _validate_session_id_or_422(session_id)

    try:
        return EVIDENCE_STORE.delete_evidence(normalized_session_id, evidence_id)
    except InvestigationSessionNotFound:
        _raise_session_http_error(status_code=404, category="session_not_found", message="Session does not exist.")
    except InvestigationSessionInvalidId:
        _raise_session_http_error(status_code=422, category="invalid_session_id", message="session_id must be a valid UUID.")
    except InvestigationEvidenceNotFound:
        _raise_session_http_error(status_code=404, category="evidence_not_found", message="Evidence does not exist.")
    except InvestigationEvidenceInvalidId:
        _raise_session_http_error(status_code=422, category="invalid_evidence_id", message="evidence_id must be a valid UUID.")
    except InvestigationEvidenceStateError as exc:
        _raise_session_http_error(status_code=409, category="invalid_state_transition", message=str(exc))
    except InvestigationEvidenceStoreError:
        _raise_session_http_error(status_code=500, category="evidence_storage_error", message="Evidence storage is unavailable.")
