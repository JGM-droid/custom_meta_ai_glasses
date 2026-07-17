from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException, UploadFile
from pydantic import ValidationError

from .models import (
    SUPPORTED_SCHEMA_VERSION,
    InvestigationAnalyzeResponse,
    InvestigationImagePayload,
    InvestigationModelResult,
    InvestigationNormalizedRequest,
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

    return _build_public_response(normalized_request, model_result)


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