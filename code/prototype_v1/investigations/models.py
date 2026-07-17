from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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