from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


SUPPORTED_SCHEMA_VERSION = "1.0"
INVESTIGATION_SESSION_SCHEMA_VERSION = "2.0"

_MAX_CLIENT_METADATA_ENTRIES = 16
_MAX_CLIENT_METADATA_KEY_LENGTH = 64
_MAX_CLIENT_METADATA_STRING_LENGTH = 256
_MAX_CLIENT_METADATA_TOTAL_TEXT = 2048

_MAX_EVIDENCE_METADATA_ENTRIES = 16
_MAX_EVIDENCE_METADATA_KEY_LENGTH = 64
_MAX_EVIDENCE_METADATA_STRING_LENGTH = 256
_MAX_EVIDENCE_METADATA_TOTAL_TEXT = 2048

_MAX_EVIDENCE_FILENAME_LENGTH = 255
_MAX_EVIDENCE_MIME_TYPE_LENGTH = 100
_MAX_EVIDENCE_STORAGE_REF_LENGTH = 512
_MAX_EVIDENCE_DIMENSION = 100000
_MAX_EVIDENCE_DURATION_SECONDS = 86400


class InvestigationSessionStatus(str, Enum):
    CREATED = "created"
    COLLECTING = "collecting"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class InvestigationSessionErrorMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    error_category: str = Field(..., min_length=1, max_length=64)
    retryable: bool
    occurred_at_utc: datetime
    safe_message: str = Field(..., min_length=1, max_length=300)

    @field_validator("occurred_at_utc")
    @classmethod
    def _validate_occurred_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at_utc must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)


class InvestigationEvidenceType(str, Enum):
    IMAGE = "image"
    AUDIO = "audio"


class InvestigationEvidenceValidationStatus(str, Enum):
    ACCEPTED = "accepted"
    DUPLICATE_ACCEPTED = "duplicate_accepted"


class InvestigationEvidenceType(str, Enum):
    IMAGE = "image"
    AUDIO = "audio"


InvestigationEvidenceKind = InvestigationEvidenceType


class InvestigationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    evidence_id: str
    session_id: str
    evidence_type: InvestigationEvidenceType
    source: str = Field(..., min_length=1, max_length=32)
    created_at_utc: datetime
    validation_status: InvestigationEvidenceValidationStatus
    sequence_number: int = Field(..., gt=0)
    client_timestamp_utc: datetime | None = None
    filename: str = Field(..., min_length=1, max_length=_MAX_EVIDENCE_FILENAME_LENGTH)
    mime_type: str = Field(..., min_length=1, max_length=_MAX_EVIDENCE_MIME_TYPE_LENGTH)
    storage_ref: str = Field(..., min_length=1, max_length=_MAX_EVIDENCE_STORAGE_REF_LENGTH)
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)
    width: int | None = Field(default=None, gt=0, le=_MAX_EVIDENCE_DIMENSION)
    height: int | None = Field(default=None, gt=0, le=_MAX_EVIDENCE_DIMENSION)
    duration_seconds: float | None = Field(default=None, gt=0, le=float(_MAX_EVIDENCE_DURATION_SECONDS))
    normalized_text: str | None = None
    metadata: dict[str, str | int | float | bool | None] | None = None

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("schema_version is required.")
        return value

    @field_validator("evidence_id", "session_id")
    @classmethod
    def _validate_uuid_fields(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("UUID fields are required.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ValueError("UUID fields must be valid UUIDs.") from exc
        return str(parsed)

    @field_validator("created_at_utc", "client_timestamp_utc")
    @classmethod
    def _validate_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", text):
            raise ValueError("content_hash must be a 64-character hex digest.")
        return text

    @field_validator("source", "filename", "mime_type", "storage_ref", "normalized_text")
    @classmethod
    def _validate_trimmed_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("Field must be non-empty.")
        return text

    @field_validator("filename")
    @classmethod
    def _validate_filename(cls, value: str) -> str:
        filename = value.strip()
        if Path(filename).name != filename:
            raise ValueError("filename must be a safe basename.")
        if len(filename) > _MAX_EVIDENCE_FILENAME_LENGTH:
            raise ValueError("filename is too long.")
        if filename in {".", ".."}:
            raise ValueError("filename is invalid.")
        if ":" in filename:
            raise ValueError("filename is invalid.")
        return filename

    @field_validator("storage_ref")
    @classmethod
    def _validate_storage_ref(cls, value: str) -> str:
        storage_ref = value.strip().replace("\\", "/")
        if not storage_ref:
            raise ValueError("storage_ref is required.")
        if storage_ref.startswith("/") or re.match(r"^[a-zA-Z]:", storage_ref):
            raise ValueError("storage_ref must be relative.")
        parts = [part for part in storage_ref.split("/") if part]
        if len(parts) != len(storage_ref.split("/")):
            raise ValueError("storage_ref must not contain empty segments.")
        if any(part == ".." for part in parts):
            raise ValueError("storage_ref must not escape the workspace.")
        if Path(storage_ref).is_absolute():
            raise ValueError("storage_ref must be relative.")
        return storage_ref

    @field_validator("mime_type")
    @classmethod
    def _validate_mime_type(cls, value: str) -> str:
        mime_type = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", mime_type):
            raise ValueError("mime_type is invalid.")
        return mime_type

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(
        cls,
        value: dict[str, str | int | float | bool | None] | None,
    ) -> dict[str, str | int | float | bool | None] | None:
        if value is None:
            return None

        if len(value) > _MAX_EVIDENCE_METADATA_ENTRIES:
            raise ValueError("metadata contains too many entries.")

        total_text = 0
        normalized: dict[str, str | int | float | bool | None] = {}
        for key, item in value.items():
            cleaned_key = str(key).strip()
            if not cleaned_key:
                raise ValueError("metadata keys must be non-empty.")
            if len(cleaned_key) > _MAX_EVIDENCE_METADATA_KEY_LENGTH:
                raise ValueError("metadata key is too long.")

            if isinstance(item, str):
                cleaned_value = item.strip()
                if len(cleaned_value) > _MAX_EVIDENCE_METADATA_STRING_LENGTH:
                    raise ValueError("metadata string value is too long.")
                total_text += len(cleaned_key) + len(cleaned_value)
                normalized[cleaned_key] = cleaned_value
                continue

            if isinstance(item, (int, float, bool)) or item is None:
                total_text += len(cleaned_key) + len(str(item))
                normalized[cleaned_key] = item
                continue

            raise ValueError("metadata values must be scalar types.")

        if total_text > _MAX_EVIDENCE_METADATA_TOTAL_TEXT:
            raise ValueError("metadata total content is too large.")

        return normalized


class InvestigationEvidenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(default="backend", min_length=1, max_length=32)
    client_timestamp_utc: datetime | None = None
    normalized_text: str | None = None
    metadata: dict[str, str | int | float | bool | None] | None = None
    filename: str | None = Field(default=None, max_length=_MAX_EVIDENCE_FILENAME_LENGTH)
    mime_type: str | None = Field(default=None, max_length=_MAX_EVIDENCE_MIME_TYPE_LENGTH)
    width: int | None = Field(default=None, gt=0, le=_MAX_EVIDENCE_DIMENSION)
    height: int | None = Field(default=None, gt=0, le=_MAX_EVIDENCE_DIMENSION)
    duration_seconds: float | None = Field(default=None, gt=0, le=float(_MAX_EVIDENCE_DURATION_SECONDS))


class InvestigationSession(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    session_id: str
    status: InvestigationSessionStatus
    revision: int = Field(..., ge=0)
    created_at_utc: datetime
    updated_at_utc: datetime
    paused_at_utc: datetime | None = None
    cancelled_at_utc: datetime | None = None
    client_metadata: dict[str, str | int | float | bool | None] | None = None
    last_error: InvestigationSessionErrorMetadata | None = None

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != INVESTIGATION_SESSION_SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version. Use {INVESTIGATION_SESSION_SCHEMA_VERSION}.")
        return value

    @field_validator("session_id")
    @classmethod
    def _validate_session_id(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("session_id is required.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ValueError("session_id must be a valid UUID.") from exc
        return str(parsed)

    @field_validator("created_at_utc", "updated_at_utc", "paused_at_utc", "cancelled_at_utc")
    @classmethod
    def _validate_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)

    @field_validator("client_metadata")
    @classmethod
    def _validate_client_metadata(
        cls,
        value: dict[str, str | int | float | bool | None] | None,
    ) -> dict[str, str | int | float | bool | None] | None:
        if value is None:
            return None

        if len(value) > _MAX_CLIENT_METADATA_ENTRIES:
            raise ValueError("client_metadata contains too many entries.")

        total_text = 0
        normalized: dict[str, str | int | float | bool | None] = {}
        for key, item in value.items():
            cleaned_key = str(key).strip()
            if not cleaned_key:
                raise ValueError("client_metadata keys must be non-empty.")
            if len(cleaned_key) > _MAX_CLIENT_METADATA_KEY_LENGTH:
                raise ValueError("client_metadata key is too long.")

            if isinstance(item, str):
                cleaned_value = item.strip()
                if len(cleaned_value) > _MAX_CLIENT_METADATA_STRING_LENGTH:
                    raise ValueError("client_metadata string value is too long.")
                total_text += len(cleaned_key) + len(cleaned_value)
                normalized[cleaned_key] = cleaned_value
                continue

            if isinstance(item, (int, float, bool)) or item is None:
                total_text += len(cleaned_key) + len(str(item))
                normalized[cleaned_key] = item
                continue

            raise ValueError("client_metadata values must be scalar types.")

        if total_text > _MAX_CLIENT_METADATA_TOTAL_TEXT:
            raise ValueError("client_metadata total content is too large.")

        return normalized


class InvestigationSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_metadata: dict[str, str | int | float | bool | None] | None = None


class InvestigationSessionMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int | None = Field(default=None, ge=0)


def create_new_investigation_session(
    *,
    client_metadata: dict[str, str | int | float | bool | None] | None = None,
) -> InvestigationSession:
    now = datetime.now(timezone.utc)
    return InvestigationSession(
        schema_version=INVESTIGATION_SESSION_SCHEMA_VERSION,
        session_id=str(uuid4()),
        status=InvestigationSessionStatus.CREATED,
        revision=0,
        created_at_utc=now,
        updated_at_utc=now,
        paused_at_utc=None,
        cancelled_at_utc=None,
        client_metadata=client_metadata,
        last_error=None,
    )


class InvestigationImageMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_index: int = Field(..., ge=0)
    filename: str
    content_type: str
    size_bytes: int = Field(..., gt=0)


class InvestigationAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    session_id: str
    idempotency_key: str
    user_explanation: str
    images: list[InvestigationImageMetadata]


class InvestigationAnalyzeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    investigation_id: str
    session_id: str
    status: str
    diagnosis: str
    required_next_action: str
    image_count: int
    image_order: list[str]
    used_user_explanation: str


class InvestigationImagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_index: int = Field(..., ge=0)
    filename: str
    content_type: str
    size_bytes: int = Field(..., gt=0)
    image_bytes: bytes = Field(..., min_length=1)


class InvestigationNormalizedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    session_id: str
    idempotency_key: str
    user_explanation: str
    images: list[InvestigationImagePayload]


class InvestigationModelResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    diagnosis: str = Field(..., min_length=1)
    required_next_action: str = Field(..., min_length=1)

    @field_validator("diagnosis", "required_next_action")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Field must be non-empty.")
        return normalized

    @field_validator("required_next_action")
    @classmethod
    def _validate_single_action(cls, value: str) -> str:
        lowered = value.lower()
        if re.search(r"\beither\b[\s\S]{0,240}\bor\b", lowered):
            raise ValueError("required_next_action must contain exactly one action.")
        if re.search(r"\boption\s*1\b", lowered) and re.search(r"\boption\s*2\b", lowered):
            raise ValueError("required_next_action must contain exactly one action.")
        if re.search(r"\b(option\s*\d+\s*:)", lowered):
            raise ValueError("required_next_action must contain exactly one action.")
        if re.search(r"\balternatively\b", lowered):
            raise ValueError("required_next_action must contain exactly one action.")
        if re.search(r"\byou can either\b", lowered):
            raise ValueError("required_next_action must contain exactly one action.")
        if re.search(r"\bone alternative\b", lowered) or re.search(r"\banother alternative\b", lowered):
            raise ValueError("required_next_action must contain exactly one action.")

        if re.search(r"\bor\s+ignore\b", lowered):
            raise ValueError("required_next_action must contain exactly one action.")

        return value.strip()


class InvestigationRetainedResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    projection_version: str = "1.0"
    investigation_id: str
    session_id: str
    status: str
    diagnosis: str = Field(..., min_length=1)
    required_next_action: str = Field(..., min_length=1)
    image_count: int = Field(..., ge=2, le=3)
    image_order: list[str] = Field(..., min_length=2, max_length=3)
    used_user_explanation: str
    completed_at_utc: datetime
    context_used: bool
    context_staleness: Literal["fresh", "stale", "unknown"]
    context_signal_age_seconds: int | None = Field(default=None, ge=0)
    copilot_prompt: str = Field(..., min_length=1)

    @field_validator("completed_at_utc")
    @classmethod
    def _validate_completed_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("completed_at_utc must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)

    @field_validator("diagnosis", "required_next_action", "copilot_prompt")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Field must be non-empty.")
        return text


class InvestigationDesktopProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    projection_version: str
    investigation_id: str
    session_id: str
    status: str
    diagnosis: str
    required_next_action: str
    copilot_prompt: str
    image_count: int
    image_order: list[str]
    used_user_explanation: bool
    completed_at_utc: datetime
    context_used: bool
    context_staleness: Literal["fresh", "stale", "unknown"]
    context_signal_age_seconds: int | None = Field(default=None, ge=0)
    freshness_state: Literal["fresh", "stale", "unknown"]
    age_seconds: int | None = Field(default=None, ge=0)


class InvestigationGlassesProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    projection_version: str
    investigation_id: str
    status: str
    diagnosis_short: str
    required_next_action_short: str
    uncertainty_flag: bool
    freshness_state: Literal["fresh", "stale", "unknown"]
    completed_at_utc: datetime
    age_seconds: int | None = Field(default=None, ge=0)