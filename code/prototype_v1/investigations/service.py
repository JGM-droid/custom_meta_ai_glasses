from __future__ import annotations

from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException, UploadFile

from .models import (
    SUPPORTED_SCHEMA_VERSION,
    InvestigationAnalyzeRequest,
    InvestigationAnalyzeResponse,
    InvestigationImageMetadata,
)


_ALLOWED_MIME_TYPES = {"image/jpeg", "image/png"}


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


async def _normalize_images(images: list[UploadFile]) -> list[InvestigationImageMetadata]:
    image_count = len(images)
    if image_count < 2:
        raise HTTPException(status_code=400, detail="At least 2 images are required.")
    if image_count > 3:
        raise HTTPException(status_code=400, detail="At most 3 images are allowed.")

    normalized_images: list[InvestigationImageMetadata] = []
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
                InvestigationImageMetadata(
                    order_index=order_index,
                    filename=filename,
                    content_type=content_type,
                    size_bytes=size_bytes,
                )
            )
        finally:
            await upload.close()

    return normalized_images


def _build_investigation_id(session_id: str, idempotency_key: str) -> str:
    deterministic = uuid5(NAMESPACE_URL, f"{session_id}|{idempotency_key}")
    return f"inv_{deterministic.hex[:16]}"


async def validate_investigation_request(
    schema_version: str,
    session_id: str,
    idempotency_key: str,
    user_explanation: str,
    images: list[UploadFile],
) -> InvestigationAnalyzeResponse:
    normalized_request = InvestigationAnalyzeRequest(
        schema_version=_validate_schema_version(schema_version),
        session_id=_require_non_empty(session_id, "session_id"),
        idempotency_key=_require_non_empty(idempotency_key, "idempotency_key"),
        user_explanation=_normalize_text(user_explanation),
        images=await _normalize_images(images),
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