from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SUPPORTED_SCHEMA_VERSION = "1.0"


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