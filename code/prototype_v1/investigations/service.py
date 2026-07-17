from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException, UploadFile
from pydantic import ValidationError

from .models import (
    InvestigationDesktopProjection,
    SUPPORTED_SCHEMA_VERSION,
    InvestigationAnalyzeResponse,
    InvestigationGlassesProjection,
    InvestigationImagePayload,
    InvestigationModelResult,
    InvestigationNormalizedRequest,
    InvestigationRetainedResult,
)


_ALLOWED_MIME_TYPES = {"image/jpeg", "image/png"}
_CONTEXT_KEYS = (
    "active_branch",
    "modified_files",
    "staged_files",
    "has_terminal_error",
    "selected_source",
    "active_file",
    "development_context",
    "primary_guidance",
    "guidance_priority",
    "git_risk_context",
    "validation_evidence_available",
    "signal_freshness",
)

OpenAIClientFactory = Callable[..., Any]
ApiKeyLoader = Callable[[], str]
ModelLoader = Callable[[], str]
ImagePreparer = Callable[[bytes], tuple[str, dict[str, object]]]
ResponseJsonExtractor = Callable[[str], str]
ContextLoader = Callable[[], dict[str, object] | None]


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _require_non_empty(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if normalized:
        return normalized
    raise HTTPException(status_code=400, detail=f"{field_name} is required.")


def _validate_schema_version(schema_version: str) -> str:
    normalized = str(schema_version or "").strip()
    if normalized == SUPPORTED_SCHEMA_VERSION:
        return normalized
    raise HTTPException(status_code=400, detail="Unsupported schema_version. Use 1.0.")


async def _normalize_images(images: list[UploadFile]) -> list[InvestigationImagePayload]:
    image_count = len(images)
    if image_count < 2:
        raise HTTPException(status_code=400, detail="At least 2 images are required.")
    if image_count > 3:
        raise HTTPException(status_code=400, detail="At most 3 images are allowed.")

    normalized_images: list[InvestigationImagePayload] = []
    for order_index, upload in enumerate(images):
        content_type = str(upload.content_type or "").strip().lower()
        if content_type not in _ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=400, detail="Unsupported content type. Use image/jpeg or image/png.")

        filename = Path(upload.filename or f"image_{order_index + 1}").name or f"image_{order_index + 1}"
        image_bytes = await upload.read()
        try:
            size_bytes = len(image_bytes)
            if size_bytes <= 0:
                raise HTTPException(status_code=400, detail="Uploaded image file is empty.")

            normalized_images.append(
                InvestigationImagePayload(
                    order_index=order_index,
                    filename=filename,
                    content_type=content_type,
                    size_bytes=size_bytes,
                    image_bytes=image_bytes,
                )
            )
        finally:
            await upload.close()

    return normalized_images


def _build_investigation_id(session_id: str, idempotency_key: str) -> str:
    deterministic = uuid5(NAMESPACE_URL, f"{session_id}|{idempotency_key}")
    return f"inv_{deterministic.hex[:16]}"


async def normalize_investigation_request(
    schema_version: str,
    session_id: str,
    idempotency_key: str,
    user_explanation: str,
    images: list[UploadFile],
) -> InvestigationNormalizedRequest:
    return InvestigationNormalizedRequest(
        schema_version=_validate_schema_version(schema_version),
        session_id=_require_non_empty(session_id, "session_id"),
        idempotency_key=_require_non_empty(idempotency_key, "idempotency_key"),
        user_explanation=_normalize_text(user_explanation),
        images=await _normalize_images(images),
    )


def _context_staleness(signal_freshness: object) -> str:
    if not isinstance(signal_freshness, dict):
        return "unknown"

    max_seconds = 0
    found = False
    for value in signal_freshness.values():
        if not isinstance(value, (int, float)):
            continue
        found = True
        max_seconds = max(max_seconds, int(value))

    if not found:
        return "unknown"
    if max_seconds >= 300:
        return "stale"
    return "fresh"


def _compact_context_snapshot(payload: dict[str, object] | None) -> dict[str, object] | None:
    if not isinstance(payload, dict) or not payload:
        return None

    compact: dict[str, object] = {}
    for key in _CONTEXT_KEYS:
        value = payload.get(key)
        if value is None:
            continue
        compact[key] = value

    if not compact:
        return None

    compact["context_staleness"] = _context_staleness(compact.get("signal_freshness"))
    return compact


def _context_signal_age_seconds(signal_freshness: object) -> int | None:
    if not isinstance(signal_freshness, dict):
        return None

    max_seconds = 0
    found = False
    for value in signal_freshness.values():
        if not isinstance(value, (int, float)):
            continue
        found = True
        max_seconds = max(max_seconds, int(value))

    if not found:
        return None
    return max(0, max_seconds)


def _build_system_prompt() -> str:
    return (
        "You are an investigation assistant for software and device workflow debugging. "
        "Analyze all provided images together as one investigation and treat their order as a meaningful capture sequence. "
        "Use the spoken user explanation as supporting context. "
        "Use optional Context Engine data only when relevant and avoid assuming it is fresh unless indicated by signal freshness. "
        "Do not invent unsupported facts. If evidence is weak, state uncertainty in the diagnosis. "
        "Return exactly one concrete required_next_action and never return competing alternatives or multiple actions. "
        "Do not claim code changes are already completed. "
        "Return valid JSON only with exactly two fields: diagnosis and required_next_action."
    )


def _build_user_prompt(normalized_request: InvestigationNormalizedRequest, context_snapshot: dict[str, object] | None) -> str:
    sequence_lines = []
    for image in normalized_request.images:
        sequence_role = "initial or earliest captured context"
        if image.order_index == 1:
            sequence_role = "additional or progression context"
        elif image.order_index >= 2:
            sequence_role = "latest or final context"

        sequence_lines.append(
            f"Image {image.order_index + 1}: filename={image.filename}; content_type={image.content_type}; size_bytes={image.size_bytes}; sequence_role={sequence_role}"
        )

    context_text = "none"
    if context_snapshot is not None:
        context_text = json.dumps(context_snapshot, ensure_ascii=False)

    return (
        "Investigation session input:\n"
        f"session_id: {normalized_request.session_id}\n"
        f"idempotency_key: {normalized_request.idempotency_key}\n"
        f"user_explanation: {normalized_request.user_explanation or '[none provided]'}\n"
        "image_sequence_instructions:\n"
        "- Image 1 is the initial or earliest captured context.\n"
        "- Image 2 is additional or progression context.\n"
        "- Image 3 is the latest or final context when present.\n"
        "- Capture order is meaningful sequence context, but do not assume causal progression unless visual evidence supports it.\n"
        f"images:\n- " + "\n- ".join(sequence_lines) + "\n"
        f"context_engine_snapshot: {context_text}"
    )


def _build_public_response(
    normalized_request: InvestigationNormalizedRequest,
    model_result: InvestigationModelResult,
) -> InvestigationAnalyzeResponse:
    return InvestigationAnalyzeResponse(
        schema_version=normalized_request.schema_version,
        investigation_id=_build_investigation_id(
            normalized_request.session_id,
            normalized_request.idempotency_key,
        ),
        session_id=normalized_request.session_id,
        status="analyzed",
        diagnosis=model_result.diagnosis,
        required_next_action=model_result.required_next_action,
        image_count=len(normalized_request.images),
        image_order=[f"{item.order_index + 1}:{item.filename}" for item in normalized_request.images],
        used_user_explanation=normalized_request.user_explanation,
    )


def build_copilot_prompt(retained_result: InvestigationRetainedResult) -> str:
    image_order_text = ", ".join(retained_result.image_order)
    explanation_used = "yes" if bool(retained_result.used_user_explanation.strip()) else "no"
    context_used = "yes" if retained_result.context_used else "no"

    return (
        "Context:\n"
        f"Investigation ID: {retained_result.investigation_id}\n"
        f"Status: {retained_result.status}\n"
        f"Completed At: {retained_result.completed_at_utc.isoformat()}\n"
        f"Images Analyzed: {retained_result.image_count}\n"
        f"Image Order: {image_order_text}\n"
        f"User Explanation Used: {explanation_used}\n"
        f"Context Used: {context_used}\n"
        f"Context Freshness: {retained_result.context_staleness}\n\n"
        "Diagnosis:\n"
        f"{retained_result.diagnosis}\n\n"
        "Required Next Action:\n"
        f"{retained_result.required_next_action}\n\n"
        "Instructions for GitHub Copilot:\n"
        "1. Inspect the relevant files and available evidence before editing.\n"
        "2. Do not assume the proposed fix has already been applied.\n"
        "3. Preserve the existing architecture and avoid unrelated refactoring.\n"
        "4. If evidence is insufficient, identify the single most useful additional observation.\n"
        "5. Propose the smallest safe change and the exact validation steps.\n"
        "6. Do not commit or push unless explicitly requested."
    )


def _build_retained_result(
    public_response: InvestigationAnalyzeResponse,
    compact_context: dict[str, object] | None,
    completed_at_utc: datetime,
) -> InvestigationRetainedResult:
    context_used = compact_context is not None
    context_staleness = "unknown"
    context_signal_age_seconds = None
    if compact_context is not None:
        context_staleness = str(compact_context.get("context_staleness") or "unknown").strip().lower()
        if context_staleness not in {"fresh", "stale", "unknown"}:
            context_staleness = "unknown"
        context_signal_age_seconds = _context_signal_age_seconds(compact_context.get("signal_freshness"))

    retained = InvestigationRetainedResult(
        schema_version=public_response.schema_version,
        projection_version="1.0",
        investigation_id=public_response.investigation_id,
        session_id=public_response.session_id,
        status=public_response.status,
        diagnosis=public_response.diagnosis,
        required_next_action=public_response.required_next_action,
        image_count=public_response.image_count,
        image_order=public_response.image_order,
        used_user_explanation=public_response.used_user_explanation,
        completed_at_utc=completed_at_utc,
        context_used=context_used,
        context_staleness=context_staleness,
        context_signal_age_seconds=context_signal_age_seconds,
        copilot_prompt="placeholder",
    )
    retained.copilot_prompt = build_copilot_prompt(retained)
    return retained


def investigation_stale_seconds() -> int:
    raw = str(os.environ.get("INVESTIGATION_RESULT_STALE_SECONDS") or "").strip()
    if not raw:
        return 900
    try:
        parsed = int(raw)
    except ValueError:
        return 900
    if parsed <= 0:
        return 900
    return parsed


def retained_result_age_seconds(retained_result: InvestigationRetainedResult, now_utc: datetime | None = None) -> int | None:
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    completed = retained_result.completed_at_utc
    if completed.tzinfo is None:
        return None
    completed_utc = completed.astimezone(timezone.utc)
    delta = (now.astimezone(timezone.utc) - completed_utc).total_seconds()
    if delta < 0:
        return None
    return int(delta)


def retained_freshness_state(retained_result: InvestigationRetainedResult, stale_seconds: int, now_utc: datetime | None = None) -> tuple[str, int | None]:
    age_seconds = retained_result_age_seconds(retained_result, now_utc=now_utc)
    if age_seconds is None:
        return "unknown", None
    if age_seconds > stale_seconds:
        return "stale", age_seconds
    return "fresh", age_seconds


def _truncate_projection_text(value: str, max_chars: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    candidate = text[: max(0, max_chars - 1)].rstrip()
    last_space = candidate.rfind(" ")
    if last_space >= max_chars // 2:
        candidate = candidate[:last_space].rstrip()
    if not candidate:
        candidate = text[: max(0, max_chars - 1)].rstrip()
    return f"{candidate}..."


def _uncertainty_flag(diagnosis: str) -> bool:
    lowered = str(diagnosis or "").lower()
    markers = [
        "uncertain",
        "not sure",
        "insufficient",
        "likely",
        "possibly",
        "may",
        "might",
    ]
    return any(marker in lowered for marker in markers)


def build_desktop_projection(retained_result: InvestigationRetainedResult, stale_seconds: int, now_utc: datetime | None = None) -> InvestigationDesktopProjection:
    freshness_state, age_seconds = retained_freshness_state(retained_result, stale_seconds=stale_seconds, now_utc=now_utc)
    return InvestigationDesktopProjection(
        schema_version=retained_result.schema_version,
        projection_version=retained_result.projection_version,
        investigation_id=retained_result.investigation_id,
        session_id=retained_result.session_id,
        status=retained_result.status,
        diagnosis=retained_result.diagnosis,
        required_next_action=retained_result.required_next_action,
        copilot_prompt=retained_result.copilot_prompt,
        image_count=retained_result.image_count,
        image_order=retained_result.image_order,
        used_user_explanation=bool(retained_result.used_user_explanation.strip()),
        completed_at_utc=retained_result.completed_at_utc,
        context_used=retained_result.context_used,
        context_staleness=retained_result.context_staleness,
        context_signal_age_seconds=retained_result.context_signal_age_seconds,
        freshness_state=freshness_state,
        age_seconds=age_seconds,
    )


def build_glasses_projection(retained_result: InvestigationRetainedResult, stale_seconds: int, now_utc: datetime | None = None) -> InvestigationGlassesProjection:
    freshness_state, age_seconds = retained_freshness_state(retained_result, stale_seconds=stale_seconds, now_utc=now_utc)
    return InvestigationGlassesProjection(
        schema_version=retained_result.schema_version,
        projection_version=retained_result.projection_version,
        investigation_id=retained_result.investigation_id,
        status=retained_result.status,
        diagnosis_short=_truncate_projection_text(retained_result.diagnosis, 120),
        required_next_action_short=_truncate_projection_text(retained_result.required_next_action, 140),
        uncertainty_flag=_uncertainty_flag(retained_result.diagnosis),
        freshness_state=freshness_state,
        completed_at_utc=retained_result.completed_at_utc,
        age_seconds=age_seconds,
    )


def _is_timeout_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return True

    message = str(exc).lower()
    return "timed out" in message or "timeout" in message


def _extract_response_content(response: object) -> str:
    try:
        content = response.choices[0].message.content  # type: ignore[attr-defined]
    except Exception:
        return ""

    return str(content or "")


async def analyze_investigation_request(
    schema_version: str,
    session_id: str,
    idempotency_key: str,
    user_explanation: str,
    images: list[UploadFile],
    openai_client_factory: OpenAIClientFactory,
    load_openai_api_key: ApiKeyLoader,
    load_model_name: ModelLoader,
    prepare_image_for_openai: ImagePreparer,
    extract_json_object: ResponseJsonExtractor,
    load_context_snapshot: ContextLoader | None = None,
) -> InvestigationAnalyzeResponse:
    public_response, _retained_result = await analyze_investigation_request_with_retained(
        schema_version=schema_version,
        session_id=session_id,
        idempotency_key=idempotency_key,
        user_explanation=user_explanation,
        images=images,
        openai_client_factory=openai_client_factory,
        load_openai_api_key=load_openai_api_key,
        load_model_name=load_model_name,
        prepare_image_for_openai=prepare_image_for_openai,
        extract_json_object=extract_json_object,
        load_context_snapshot=load_context_snapshot,
    )
    return public_response


async def analyze_investigation_request_with_retained(
    schema_version: str,
    session_id: str,
    idempotency_key: str,
    user_explanation: str,
    images: list[UploadFile],
    openai_client_factory: OpenAIClientFactory,
    load_openai_api_key: ApiKeyLoader,
    load_model_name: ModelLoader,
    prepare_image_for_openai: ImagePreparer,
    extract_json_object: ResponseJsonExtractor,
    load_context_snapshot: ContextLoader | None = None,
) -> tuple[InvestigationAnalyzeResponse, InvestigationRetainedResult]:
    normalized_request = await normalize_investigation_request(
        schema_version=schema_version,
        session_id=session_id,
        idempotency_key=idempotency_key,
        user_explanation=user_explanation,
        images=images,
    )

    if openai_client_factory is None:
        raise HTTPException(status_code=503, detail="OpenAI runtime configuration unavailable.")
    if not callable(load_openai_api_key) or not callable(load_model_name):
        raise HTTPException(status_code=503, detail="OpenAI runtime configuration unavailable.")
    if not callable(prepare_image_for_openai) or not callable(extract_json_object):
        raise HTTPException(status_code=503, detail="OpenAI runtime configuration unavailable.")

    api_key = str(load_openai_api_key() or "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is unavailable.")

    model_name = str(load_model_name() or "").strip()
    if not model_name:
        raise HTTPException(status_code=503, detail="OpenAI model configuration is unavailable.")

    context_payload: dict[str, object] | None = None
    if callable(load_context_snapshot):
        try:
            loaded = load_context_snapshot()
            if isinstance(loaded, dict):
                context_payload = loaded
        except Exception:
            context_payload = None

    compact_context = _compact_context_snapshot(context_payload)

    user_content: list[dict[str, object]] = [
        {
            "type": "text",
            "text": _build_user_prompt(normalized_request, compact_context),
        }
    ]
    for image in normalized_request.images:
        encoded, _meta = prepare_image_for_openai(image.image_bytes)
        user_content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{encoded}",
                    "detail": "low",
                },
            }
        )

    client = openai_client_factory(api_key=api_key)
    try:
        response = client.chat.completions.create(
            model=model_name,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": user_content},
            ],
            timeout=45,
        )
    except Exception as exc:
        if _is_timeout_error(exc):
            raise HTTPException(status_code=504, detail="OpenAI investigation request timed out.") from exc
        raise HTTPException(status_code=500, detail="Investigation analysis failed.") from exc

    content = _extract_response_content(response)
    if not content.strip():
        raise HTTPException(status_code=502, detail="OpenAI returned an empty response.")

    json_text = str(extract_json_object(content) or "").strip()
    if not json_text:
        raise HTTPException(status_code=502, detail="OpenAI returned malformed JSON.")

    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="OpenAI returned malformed JSON.") from exc

    try:
        model_result = InvestigationModelResult.model_validate(parsed)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="OpenAI returned an invalid investigation result schema.") from exc

    public_response = _build_public_response(normalized_request, model_result)
    completed_at_utc = datetime.now(timezone.utc)
    retained_result = _build_retained_result(public_response, compact_context, completed_at_utc=completed_at_utc)
    return public_response, retained_result


async def validate_investigation_request(
    schema_version: str,
    session_id: str,
    idempotency_key: str,
    user_explanation: str,
    images: list[UploadFile],
) -> InvestigationAnalyzeResponse:
    normalized_request = await normalize_investigation_request(
        schema_version=schema_version,
        session_id=session_id,
        idempotency_key=idempotency_key,
        user_explanation=user_explanation,
        images=images,
    )

    return InvestigationAnalyzeResponse(
        schema_version=normalized_request.schema_version,
        investigation_id=_build_investigation_id(
            normalized_request.session_id,
            normalized_request.idempotency_key,
        ),
        session_id=normalized_request.session_id,
        status="validated",
        diagnosis="Investigation session received and validated.",
        required_next_action="Proceed to combined multimodal analysis integration.",
        image_count=len(normalized_request.images),
        image_order=[f"{item.order_index + 1}:{item.filename}" for item in normalized_request.images],
        used_user_explanation=normalized_request.user_explanation,
    )