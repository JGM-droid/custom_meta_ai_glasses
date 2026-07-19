from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SUPPORTED_SCHEMA_VERSION = "1.0"
INVESTIGATION_SESSION_SCHEMA_VERSION = "2.0"
INVESTIGATION_ANALYSIS_ATTEMPT_SCHEMA_VERSION = "2.0"
INVESTIGATION_RESULT_LINK_SCHEMA_VERSION = "2.0"
INVESTIGATION_CANONICAL_RESULT_SCHEMA_VERSION = "1.0"
INVESTIGATION_FROZEN_EVIDENCE_MANIFEST_SCHEMA_VERSION = "1.0"
INVESTIGATION_STRUCTURED_ANALYSIS_SCHEMA_VERSION = "1.0"
INVESTIGATION_LATENCY_METADATA_SCHEMA_VERSION = "1.0"
INVESTIGATION_ANALYSIS_REQUEST_PACKAGE_SCHEMA_VERSION = "1.0"
INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION = "1.0"

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
_MAX_SAFE_FAILURE_TEXT_LENGTH = 300
_MAX_PROVIDER_REQUEST_ID_LENGTH = 128
_MAX_PROMPT_LENGTH = 12000
_MAX_SELECTION_POLICY_VERSION_LENGTH = 32
_MAX_RENDERER_VERSION_LENGTH = 32
_MAX_STRUCTURED_LIST_ITEMS = 12
_MAX_STRUCTURED_TEXT_LENGTH = 1000
_MAX_SELECTED_IMAGE_COUNT = 3
_MAX_REQUEST_INSTRUCTION_LENGTH = 6000
_MAX_EXPLANATION_TEXT_LENGTH = 1000
_MAX_ATTACHMENT_METADATA_ENTRIES = 8
_MAX_ATTACHMENT_METADATA_KEY_LENGTH = 64
_MAX_ATTACHMENT_METADATA_VALUE_LENGTH = 160
_MAX_RESPONSE_DIAGNOSIS_LENGTH = 500
_MAX_RESPONSE_ACTION_LENGTH = 280
_MAX_RESPONSE_WARNING_LENGTH = 300
_MAX_RESPONSE_FOLLOW_UP_LENGTH = 280

SUPPORTED_ANALYSIS_REQUEST_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
}


class InvestigationSessionStatus(str, Enum):
    CREATED = "created"
    COLLECTING = "collecting"
    PAUSED = "paused"
    FINALIZING = "finalizing"
    ANALYZING = "analyzing"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class InvestigationAnalysisStatus(str, Enum):
    VALIDATED = "validated"
    ANALYZED = "analyzed"


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
    current_analysis_attempt_id: str | None = None
    active_analysis_attempt_id: str | None = None
    latest_analysis_attempt_id: str | None = None
    completed_result_id: str | None = None
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

    @field_validator(
        "current_analysis_attempt_id",
        "active_analysis_attempt_id",
        "latest_analysis_attempt_id",
        "completed_result_id",
    )
    @classmethod
    def _validate_optional_uuid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("Optional UUID fields must be non-empty when provided.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ValueError("Optional UUID fields must be valid UUIDs.") from exc
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
        current_analysis_attempt_id=None,
        active_analysis_attempt_id=None,
        latest_analysis_attempt_id=None,
        completed_result_id=None,
        last_error=None,
    )


class InvestigationAnalysisAttemptStatus(str, Enum):
    PREPARED = "prepared"
    PROVIDER_CALL_STARTED = "provider_call_started"
    COMPLETED = "completed"
    FAILED_PRE_CALL = "failed_pre_call"
    FAILED_PROVIDER_CONFIRMED = "failed_provider_confirmed"
    FAILED_RESULT_PERSISTENCE = "failed_result_persistence"
    AMBIGUOUS_COMPLETION = "ambiguous_completion"


class InvestigationAttemptFailureMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    category: str = Field(..., min_length=1, max_length=64)
    safe_message: str = Field(..., min_length=1, max_length=_MAX_SAFE_FAILURE_TEXT_LENGTH)
    retryable: bool


class InvestigationFrozenEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_id: str
    session_id: str
    storage_ref: str = Field(..., min_length=1, max_length=_MAX_EVIDENCE_STORAGE_REF_LENGTH)
    evidence_type: InvestigationEvidenceType
    mime_type: str = Field(..., min_length=1, max_length=_MAX_EVIDENCE_MIME_TYPE_LENGTH)
    captured_at_utc: datetime | None = None
    content_hash: str = Field(..., min_length=64, max_length=64)
    size_bytes: int = Field(..., gt=0)
    selection_index: int = Field(..., ge=0)

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

    @field_validator("storage_ref")
    @classmethod
    def _validate_storage_ref(cls, value: str) -> str:
        storage_ref = value.strip().replace("\\", "/")
        if not storage_ref:
            raise ValueError("storage_ref is required.")
        if storage_ref.startswith("/") or re.match(r"^[a-zA-Z]:", storage_ref):
            raise ValueError("storage_ref must be relative.")
        parts = storage_ref.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("storage_ref must be normalized and non-traversing.")
        return storage_ref

    @field_validator("mime_type")
    @classmethod
    def _validate_mime_type(cls, value: str) -> str:
        mime_type = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", mime_type):
            raise ValueError("mime_type is invalid.")
        return mime_type

    @field_validator("captured_at_utc")
    @classmethod
    def _validate_captured_at_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("captured_at_utc must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, value: str) -> str:
        text = value.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", text):
            raise ValueError("content_hash must be a 64-character hex digest.")
        return text


class InvestigationFrozenEvidenceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    manifest_id: str
    session_id: str
    analysis_attempt_id: str
    created_at_utc: datetime
    selection_policy_version: str = Field(default="1.0", min_length=1, max_length=_MAX_SELECTION_POLICY_VERSION_LENGTH)
    selected_evidence: list[InvestigationFrozenEvidenceItem] = Field(
        ...,
        min_length=1,
        max_length=_MAX_SELECTED_IMAGE_COUNT,
    )
    selected_evidence_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=_MAX_SELECTED_IMAGE_COUNT,
    )
    evidence_count: int = Field(..., ge=1, le=_MAX_SELECTED_IMAGE_COUNT)
    manifest_hash: str = Field(..., min_length=64, max_length=64)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != INVESTIGATION_FROZEN_EVIDENCE_MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema_version. Use {INVESTIGATION_FROZEN_EVIDENCE_MANIFEST_SCHEMA_VERSION}."
            )
        return value

    @field_validator("manifest_id", "session_id", "analysis_attempt_id")
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

    @field_validator("created_at_utc")
    @classmethod
    def _validate_created_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at_utc must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)

    @field_validator("selected_evidence_ids")
    @classmethod
    def _validate_selected_evidence_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = item.strip()
            if not text:
                raise ValueError("selected_evidence_ids must contain non-empty UUIDs.")
            try:
                parsed = str(UUID(text))
            except ValueError as exc:
                raise ValueError("selected_evidence_ids must contain valid UUIDs.") from exc
            if parsed in seen:
                raise ValueError("selected_evidence_ids must be unique.")
            seen.add(parsed)
            normalized.append(parsed)
        return normalized

    @field_validator("manifest_hash")
    @classmethod
    def _validate_manifest_hash(cls, value: str) -> str:
        text = value.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", text):
            raise ValueError("manifest_hash must be a 64-character hex digest.")
        return text

    @model_validator(mode="after")
    def _validate_manifest_consistency(self) -> "InvestigationFrozenEvidenceManifest":
        if self.evidence_count != len(self.selected_evidence):
            raise ValueError("evidence_count must match selected_evidence length.")
        if len(self.selected_evidence_ids) != len(self.selected_evidence):
            raise ValueError("selected_evidence_ids must match selected_evidence length.")

        ids_from_items = [item.evidence_id for item in self.selected_evidence]
        if ids_from_items != self.selected_evidence_ids:
            raise ValueError("selected_evidence_ids must exactly match selected_evidence order.")

        if any(item.evidence_type != InvestigationEvidenceType.IMAGE for item in self.selected_evidence):
            raise ValueError("selected_evidence must contain only image evidence items.")

        if any(item.session_id != self.session_id for item in self.selected_evidence):
            raise ValueError("selected_evidence session_id must match manifest session_id.")

        if any(item.selection_index != index for index, item in enumerate(self.selected_evidence)):
            raise ValueError("selected_evidence selection_index values must be zero-based and ordered.")

        return self


class InvestigationAnalysisEvidenceAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_id: str
    capture_timestamp_utc: datetime | None = None
    media_type: str = Field(..., min_length=1, max_length=_MAX_EVIDENCE_MIME_TYPE_LENGTH)
    storage_ref: str = Field(..., min_length=1, max_length=_MAX_EVIDENCE_STORAGE_REF_LENGTH)
    evidence_metadata: dict[str, str] | None = None

    @field_validator("evidence_id")
    @classmethod
    def _validate_evidence_id(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("evidence_id is required.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ValueError("evidence_id must be a valid UUID.") from exc
        return str(parsed)

    @field_validator("capture_timestamp_utc")
    @classmethod
    def _validate_capture_timestamp_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("capture_timestamp_utc must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)

    @field_validator("media_type")
    @classmethod
    def _validate_media_type(cls, value: str) -> str:
        media_type = value.strip().lower()
        if media_type not in SUPPORTED_ANALYSIS_REQUEST_IMAGE_MIME_TYPES:
            raise ValueError("media_type is unsupported for analysis packaging.")
        return media_type

    @field_validator("storage_ref")
    @classmethod
    def _validate_storage_ref(cls, value: str) -> str:
        storage_ref = value.strip().replace("\\", "/")
        if not storage_ref:
            raise ValueError("storage_ref is required.")
        if storage_ref.startswith("/") or re.match(r"^[a-zA-Z]:", storage_ref):
            raise ValueError("storage_ref must be relative.")
        parts = storage_ref.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("storage_ref must be normalized and non-traversing.")
        return storage_ref

    @field_validator("evidence_metadata")
    @classmethod
    def _validate_evidence_metadata(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        if len(value) > _MAX_ATTACHMENT_METADATA_ENTRIES:
            raise ValueError("evidence_metadata contains too many entries.")

        normalized: dict[str, str] = {}
        for key, item in value.items():
            cleaned_key = str(key).strip()
            cleaned_value = str(item).strip()
            if not cleaned_key:
                raise ValueError("evidence_metadata keys must be non-empty.")
            if not cleaned_value:
                raise ValueError("evidence_metadata values must be non-empty.")
            if len(cleaned_key) > _MAX_ATTACHMENT_METADATA_KEY_LENGTH:
                raise ValueError("evidence_metadata key is too long.")
            if len(cleaned_value) > _MAX_ATTACHMENT_METADATA_VALUE_LENGTH:
                raise ValueError("evidence_metadata value is too long.")
            normalized[cleaned_key] = cleaned_value
        return normalized


class InvestigationAnalysisRequestPackage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    session_id: str
    analysis_attempt_id: str
    attempt_number: int = Field(..., gt=0)
    frozen_manifest_id: str | None = None
    frozen_manifest_hash: str = Field(..., min_length=64, max_length=64)
    normalized_explanation_text: str | None = Field(default=None, min_length=1, max_length=_MAX_EXPLANATION_TEXT_LENGTH)
    deterministic_system_instructions: str = Field(..., min_length=1, max_length=_MAX_REQUEST_INSTRUCTION_LENGTH)
    deterministic_context_instructions: str = Field(..., min_length=1, max_length=_MAX_REQUEST_INSTRUCTION_LENGTH)
    ordered_evidence_inputs: list[InvestigationAnalysisEvidenceAttachment] = Field(
        ...,
        min_length=1,
        max_length=_MAX_SELECTED_IMAGE_COUNT,
    )

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != INVESTIGATION_ANALYSIS_REQUEST_PACKAGE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema_version. Use {INVESTIGATION_ANALYSIS_REQUEST_PACKAGE_SCHEMA_VERSION}."
            )
        return value

    @field_validator("session_id", "analysis_attempt_id", "frozen_manifest_id")
    @classmethod
    def _validate_uuid_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("UUID fields must be non-empty when provided.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ValueError("UUID fields must be valid UUIDs.") from exc
        return str(parsed)

    @field_validator("frozen_manifest_hash")
    @classmethod
    def _validate_manifest_hash(cls, value: str) -> str:
        text = value.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", text):
            raise ValueError("frozen_manifest_hash must be a 64-character hex digest.")
        return text

    @field_validator("normalized_explanation_text")
    @classmethod
    def _validate_optional_explanation_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("normalized_explanation_text must be non-empty when provided.")
        return text


class InvestigationAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    concise_diagnosis: str = Field(..., min_length=1, max_length=_MAX_RESPONSE_DIAGNOSIS_LENGTH)
    immediate_recommended_action: str = Field(..., min_length=1, max_length=_MAX_RESPONSE_ACTION_LENGTH)
    supporting_observations: list[str] = Field(..., min_length=1, max_length=_MAX_STRUCTURED_LIST_ITEMS)
    confidence_or_uncertainty: str = Field(..., min_length=1, max_length=_MAX_STRUCTURED_TEXT_LENGTH)
    warning_or_blocker: str | None = Field(default=None, min_length=1, max_length=_MAX_RESPONSE_WARNING_LENGTH)
    follow_up_capture_request: str | None = Field(default=None, min_length=1, max_length=_MAX_RESPONSE_FOLLOW_UP_LENGTH)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema_version. Use {INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION}."
            )
        return value

    @field_validator(
        "concise_diagnosis",
        "immediate_recommended_action",
        "confidence_or_uncertainty",
        "warning_or_blocker",
        "follow_up_capture_request",
    )
    @classmethod
    def _validate_trimmed_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("Text fields must be non-empty when provided.")
        return text

    @field_validator("supporting_observations", mode="after")
    @classmethod
    def _validate_supporting_observations(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if not text:
                raise ValueError("supporting_observations items must be non-empty.")
            if len(text) > _MAX_STRUCTURED_TEXT_LENGTH:
                raise ValueError("supporting_observations item is too long.")
            normalized.append(text)
        return normalized


class InvestigationStructuredAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    observed_evidence: list[str] = Field(..., min_length=1, max_length=_MAX_STRUCTURED_LIST_ITEMS)
    likely_issue: str = Field(..., min_length=1, max_length=_MAX_STRUCTURED_TEXT_LENGTH)
    confidence_or_uncertainty: str = Field(..., min_length=1, max_length=_MAX_STRUCTURED_TEXT_LENGTH)
    recommended_checks: list[str] = Field(..., min_length=1, max_length=_MAX_STRUCTURED_LIST_ITEMS)
    recommended_changes: list[str] = Field(default_factory=list, max_length=_MAX_STRUCTURED_LIST_ITEMS)
    relevant_safe_filenames: list[str] = Field(default_factory=list, max_length=_MAX_STRUCTURED_LIST_ITEMS)
    limitations: list[str] = Field(default_factory=list, max_length=_MAX_STRUCTURED_LIST_ITEMS)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != INVESTIGATION_STRUCTURED_ANALYSIS_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema_version. Use {INVESTIGATION_STRUCTURED_ANALYSIS_SCHEMA_VERSION}."
            )
        return value

    @field_validator(
        "observed_evidence",
        "recommended_checks",
        "recommended_changes",
        "limitations",
        mode="after",
    )
    @classmethod
    def _validate_text_lists(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if not text:
                raise ValueError("Structured analysis text list items must be non-empty.")
            if len(text) > _MAX_STRUCTURED_TEXT_LENGTH:
                raise ValueError("Structured analysis text list item is too long.")
            normalized.append(text)
        return normalized

    @field_validator("relevant_safe_filenames", mode="after")
    @classmethod
    def _validate_safe_filenames(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            text = str(item).strip().replace("\\", "/")
            if not text:
                raise ValueError("relevant_safe_filenames items must be non-empty.")
            if text.startswith("/") or re.match(r"^[a-zA-Z]:", text):
                raise ValueError("relevant_safe_filenames must use relative paths.")
            parts = text.split("/")
            if any(part in {"", ".", ".."} for part in parts):
                raise ValueError("relevant_safe_filenames must be normalized and non-traversing.")
            normalized.append(text)
        if len(normalized) != len(set(normalized)):
            raise ValueError("relevant_safe_filenames must be unique.")
        return normalized


class InvestigationLatencyMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    device_picture_to_prompt_ms: int | None = Field(default=None, ge=0)
    backend_picture_to_prompt_ms: int | None = Field(default=None, ge=0)
    capture_acknowledged_utc: datetime | None = None
    evidence_ready_utc: datetime | None = None
    context_collection_started_utc: datetime | None = None
    context_collection_completed_utc: datetime | None = None
    provider_request_started_utc: datetime | None = None
    provider_response_completed_utc: datetime | None = None
    result_persisted_utc: datetime | None = None
    prompt_available_utc: datetime | None = None
    backend_request_accepted_utc: datetime | None = None
    client_capture_acknowledged_utc: datetime | None = None
    client_request_started_utc: datetime | None = None
    evidence_preparation_ms: int | None = Field(default=None, ge=0)
    context_collection_ms: int | None = Field(default=None, ge=0)
    provider_round_trip_ms: int | None = Field(default=None, ge=0)
    result_processing_ms: int | None = Field(default=None, ge=0)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != INVESTIGATION_LATENCY_METADATA_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema_version. Use {INVESTIGATION_LATENCY_METADATA_SCHEMA_VERSION}."
            )
        return value

    @field_validator(
        "capture_acknowledged_utc",
        "evidence_ready_utc",
        "context_collection_started_utc",
        "context_collection_completed_utc",
        "provider_request_started_utc",
        "provider_response_completed_utc",
        "result_persisted_utc",
        "prompt_available_utc",
        "backend_request_accepted_utc",
        "client_capture_acknowledged_utc",
        "client_request_started_utc",
    )
    @classmethod
    def _validate_optional_utc_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Latency timestamp fields must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)


class InvestigationAnalysisAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    analysis_attempt_id: str
    session_id: str
    attempt_number: int = Field(..., gt=0)
    status: InvestigationAnalysisAttemptStatus
    frozen_manifest_hash: str = Field(..., min_length=64, max_length=64)
    context_snapshot_hash: str = Field(..., min_length=64, max_length=64)
    request_fingerprint: str = Field(..., min_length=64, max_length=64)
    created_at_utc: datetime
    started_at_utc: datetime | None = None
    completed_at_utc: datetime | None = None
    failed_at_utc: datetime | None = None
    failure_metadata: InvestigationAttemptFailureMetadata | None = None
    safe_error_category: str | None = Field(default=None, min_length=1, max_length=64)
    safe_error_message: str | None = Field(default=None, min_length=1, max_length=_MAX_SAFE_FAILURE_TEXT_LENGTH)
    frozen_manifest_id: str | None = None
    structured_analysis: InvestigationStructuredAnalysis | None = None
    rendered_prompt: str | None = Field(default=None, min_length=1, max_length=_MAX_PROMPT_LENGTH)
    prompt_renderer_version: str | None = Field(default=None, min_length=1, max_length=_MAX_RENDERER_VERSION_LENGTH)
    latency_metadata: InvestigationLatencyMetadata | None = None
    canonical_result_id: str | None = None
    provider_request_id: str | None = Field(default=None, max_length=_MAX_PROVIDER_REQUEST_ID_LENGTH)
    recovery_state: str | None = Field(default=None, max_length=64)
    retryable: bool

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != INVESTIGATION_ANALYSIS_ATTEMPT_SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version. Use {INVESTIGATION_ANALYSIS_ATTEMPT_SCHEMA_VERSION}.")
        return value

    @field_validator("analysis_attempt_id", "session_id", "canonical_result_id", "frozen_manifest_id")
    @classmethod
    def _validate_uuid_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("UUID fields must be non-empty when provided.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ValueError("UUID fields must be valid UUIDs.") from exc
        return str(parsed)

    @field_validator("frozen_manifest_hash", "context_snapshot_hash", "request_fingerprint")
    @classmethod
    def _validate_hash_fields(cls, value: str) -> str:
        text = value.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", text):
            raise ValueError("Hash fields must be 64-character hex digests.")
        return text

    @field_validator("created_at_utc", "started_at_utc", "completed_at_utc", "failed_at_utc")
    @classmethod
    def _validate_utc_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)

    @field_validator("provider_request_id", "recovery_state", "prompt_renderer_version")
    @classmethod
    def _validate_optional_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("Optional text fields must be non-empty when provided.")
        return text

    @field_validator("safe_error_category", "safe_error_message")
    @classmethod
    def _validate_optional_safe_error_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("Optional safe error fields must be non-empty when provided.")
        return text

    @model_validator(mode="after")
    def _validate_status_specific_fields(self) -> "InvestigationAnalysisAttempt":
        if self.status == InvestigationAnalysisAttemptStatus.COMPLETED:
            if self.completed_at_utc is None:
                raise ValueError("completed_at_utc is required for completed attempts.")
            if self.canonical_result_id is None:
                raise ValueError("canonical_result_id is required for completed attempts.")

        failure_states = {
            InvestigationAnalysisAttemptStatus.FAILED_PRE_CALL,
            InvestigationAnalysisAttemptStatus.FAILED_PROVIDER_CONFIRMED,
            InvestigationAnalysisAttemptStatus.FAILED_RESULT_PERSISTENCE,
            InvestigationAnalysisAttemptStatus.AMBIGUOUS_COMPLETION,
        }
        if self.status in failure_states and self.failure_metadata is None:
            raise ValueError("failure_metadata is required for failed attempts.")

        if self.failed_at_utc is not None and self.status not in failure_states:
            raise ValueError("failed_at_utc is only allowed for failed attempt statuses.")

        return self


class InvestigationResultLink(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    result_id: str
    session_id: str
    analysis_attempt_id: str
    canonical_storage_ref: str = Field(..., min_length=1, max_length=_MAX_EVIDENCE_STORAGE_REF_LENGTH)
    completed_at_utc: datetime
    result_hash: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != INVESTIGATION_RESULT_LINK_SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version. Use {INVESTIGATION_RESULT_LINK_SCHEMA_VERSION}.")
        return value

    @field_validator("result_id", "session_id", "analysis_attempt_id")
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

    @field_validator("completed_at_utc")
    @classmethod
    def _validate_completed_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("completed_at_utc must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)

    @field_validator("canonical_storage_ref")
    @classmethod
    def _validate_canonical_storage_ref(cls, value: str) -> str:
        ref = value.strip()
        if "\\" in ref:
            raise ValueError("canonical_storage_ref must use '/' separators.")
        if not ref:
            raise ValueError("canonical_storage_ref is required.")
        if ref.startswith("/") or re.match(r"^[a-zA-Z]:", ref):
            raise ValueError("canonical_storage_ref must be relative.")
        parts = ref.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("canonical_storage_ref must be normalized and non-traversing.")
        return ref

    @field_validator("result_hash")
    @classmethod
    def _validate_result_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", text):
            raise ValueError("result_hash must be a 64-character hex digest.")
        return text


class InvestigationCanonicalResultEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    result_id: str
    session_id: str | None = None
    analysis_attempt_id: str | None = None
    created_at_utc: datetime
    retained_result: InvestigationRetainedResult
    result_hash: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != INVESTIGATION_CANONICAL_RESULT_SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version. Use {INVESTIGATION_CANONICAL_RESULT_SCHEMA_VERSION}.")
        return value

    @field_validator("result_id", "session_id", "analysis_attempt_id")
    @classmethod
    def _validate_uuid_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("UUID fields must be non-empty when provided.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ValueError("UUID fields must be valid UUIDs.") from exc
        return str(parsed)

    @field_validator("created_at_utc")
    @classmethod
    def _validate_created_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at_utc must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)

    @field_validator("result_hash")
    @classmethod
    def _validate_result_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", text):
            raise ValueError("result_hash must be a 64-character hex digest.")
        return text


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
    status: InvestigationAnalysisStatus
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
    status: InvestigationAnalysisStatus
    diagnosis: str = Field(..., min_length=1)
    required_next_action: str = Field(..., min_length=1)
    image_count: int = Field(..., ge=1, le=3)
    image_order: list[str] = Field(..., min_length=1, max_length=3)
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
    status: InvestigationAnalysisStatus
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
    status: InvestigationAnalysisStatus
    diagnosis_short: str
    required_next_action_short: str
    uncertainty_flag: bool
    freshness_state: Literal["fresh", "stale", "unknown"]
    completed_at_utc: datetime
    age_seconds: int | None = Field(default=None, ge=0)


class InvestigationSessionPollingError(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    category: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=300)
    occurred_at_utc: datetime | None = None

    @field_validator("occurred_at_utc")
    @classmethod
    def _validate_occurred_at_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("occurred_at_utc must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)


class InvestigationSessionPollingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    investigation_id: str | None = None
    status: InvestigationSessionStatus
    created_at: datetime
    updated_at: datetime
    image_count: int = Field(..., ge=0)
    explanation_present: bool
    retryable: bool
    error: InvestigationSessionPollingError | None = None
    compact_result: InvestigationGlassesProjection | None = None
    result_available: bool
    poll_after_ms: int = Field(..., ge=250, le=60000)

    @field_validator("session_id")
    @classmethod
    def _validate_session_id(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("session_id is required.")
        try:
            return str(UUID(text))
        except ValueError as exc:
            raise ValueError("session_id must be a valid UUID.") from exc

    @field_validator("investigation_id")
    @classmethod
    def _validate_optional_investigation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("investigation_id must be non-empty when provided.")
        return text

    @field_validator("created_at", "updated_at")
    @classmethod
    def _validate_utc_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Polling timestamps must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)


class InvestigationSessionAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int | None = Field(default=None, ge=0)


class InvestigationSessionAnalyzeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    investigation_id: str | None = None
    status: InvestigationSessionStatus
    accepted: bool
    result_available: bool
    compact_result: InvestigationGlassesProjection | None = None
    retryable: bool
    error: InvestigationSessionPollingError | None = None
    poll_url: str

    @field_validator("session_id")
    @classmethod
    def _validate_session_id(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("session_id is required.")
        try:
            return str(UUID(text))
        except ValueError as exc:
            raise ValueError("session_id must be a valid UUID.") from exc

    @field_validator("investigation_id")
    @classmethod
    def _validate_optional_investigation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("investigation_id must be non-empty when provided.")
        return text

    @field_validator("poll_url")
    @classmethod
    def _validate_poll_url(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("poll_url is required.")
        if not text.startswith("/investigation-sessions/"):
            raise ValueError("poll_url must be a session polling path.")
        return text