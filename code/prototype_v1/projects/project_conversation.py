from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PROJECT_CONVERSATION_SCHEMA_VERSION = "1.0"
CONVERSATION_TURN_SCHEMA_VERSION = "1.0"
MAX_CONVERSATION_TEXT_LENGTH = 8000
MAX_CONVERSATION_IMAGE_REFERENCES = 5


class ConversationRole(str, Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class ConversationTurnStatus(str, Enum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ConversationTextPart(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["TEXT"] = "TEXT"
    text: str = Field(min_length=1, max_length=MAX_CONVERSATION_TEXT_LENGTH)


class ConversationEvidenceReferencePart(BaseModel):
    """Provider-neutral pointer to canonical Investigation Evidence; never contains bytes."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["PROJECT_RESOURCE_REFERENCE"] = "PROJECT_RESOURCE_REFERENCE"
    resource_kind: Literal["EVIDENCE"] = "EVIDENCE"
    resource_id: str
    relationship: Literal["ATTACHED"] = "ATTACHED"
    container_kind: Literal["INVESTIGATION_SESSION"] = "INVESTIGATION_SESSION"
    container_id: str

    @field_validator("resource_id", "container_id")
    @classmethod
    def _validate_uuid(cls, value: str) -> str:
        try:
            return str(UUID(str(value)))
        except ValueError as exc:
            raise ValueError("Evidence reference identity fields must be valid UUIDs.") from exc


ConversationContentPart = Annotated[
    Union[ConversationTextPart, ConversationEvidenceReferencePart],
    Field(discriminator="type"),
]


class ConversationProviderProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=200)
    request_id: str | None = Field(default=None, max_length=200)


class ConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str = CONVERSATION_TURN_SCHEMA_VERSION
    turn_id: str
    conversation_id: str
    project_id: str
    sequence_number: int = Field(ge=1)
    role: ConversationRole
    status: ConversationTurnStatus
    content_parts: list[ConversationContentPart] = Field(
        min_length=1, max_length=1 + MAX_CONVERSATION_IMAGE_REFERENCES)
    idempotency_key: str = Field(min_length=1, max_length=128)
    request_fingerprint: str = Field(min_length=64, max_length=64)
    created_at_utc: datetime
    completed_at_utc: datetime | None = None
    provider_provenance: ConversationProviderProvenance | None = None
    failure_category: str | None = Field(default=None, max_length=100)
    failure_message: str | None = Field(default=None, max_length=500)

    @field_validator("turn_id", "conversation_id", "project_id")
    @classmethod
    def _validate_uuid(cls, value: str) -> str:
        try:
            return str(UUID(str(value)))
        except ValueError as exc:
            raise ValueError("Identity fields must be valid UUIDs.") from exc

    @field_validator("created_at_utc", "completed_at_utc")
    @classmethod
    def _normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Turn timestamps must be timezone-aware.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_state(self) -> "ConversationTurn":
        if self.status == ConversationTurnStatus.COMPLETED and self.completed_at_utc is None:
            raise ValueError("Completed turns require completed_at_utc.")
        if self.status == ConversationTurnStatus.FAILED and not self.failure_category:
            raise ValueError("Failed turns require failure_category.")
        if self.role == ConversationRole.USER and self.provider_provenance is not None:
            raise ValueError("User turns cannot have provider provenance.")
        text_parts = [item for item in self.content_parts if isinstance(item, ConversationTextPart)]
        evidence_parts = [item for item in self.content_parts if isinstance(item, ConversationEvidenceReferencePart)]
        if len(text_parts) != 1:
            raise ValueError("Phase 1B conversation turns require exactly one text part.")
        if self.role == ConversationRole.ASSISTANT and evidence_parts:
            raise ValueError("Phase 1B assistant turns cannot attach Evidence.")
        if len(evidence_parts) > MAX_CONVERSATION_IMAGE_REFERENCES:
            raise ValueError("Too many Evidence references.")
        if len({(item.container_id, item.resource_id) for item in evidence_parts}) != len(evidence_parts):
            raise ValueError("Duplicate Evidence references are not allowed.")
        return self


class ProjectConversation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str = PROJECT_CONVERSATION_SCHEMA_VERSION
    conversation_id: str
    project_id: str
    created_at_utc: datetime
    updated_at_utc: datetime
    turns: list[ConversationTurn] = Field(default_factory=list)

    @field_validator("conversation_id", "project_id")
    @classmethod
    def _validate_uuid(cls, value: str) -> str:
        try:
            return str(UUID(str(value)))
        except ValueError as exc:
            raise ValueError("Identity fields must be valid UUIDs.") from exc

    @model_validator(mode="after")
    def _validate_turns(self) -> "ProjectConversation":
        expected = list(range(1, len(self.turns) + 1))
        actual = [item.sequence_number for item in self.turns]
        if actual != expected:
            raise ValueError("Conversation turns must have contiguous deterministic ordering.")
        if any(item.project_id != self.project_id or item.conversation_id != self.conversation_id for item in self.turns):
            raise ValueError("Conversation turn ownership mismatch.")
        if len({item.turn_id for item in self.turns}) != len(self.turns):
            raise ValueError("Conversation turn IDs must be unique.")
        return self


class ConversationSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=1, max_length=128)
    evidence_refs: list[ConversationEvidenceReferencePart] = Field(
        default_factory=list, max_length=MAX_CONVERSATION_IMAGE_REFERENCES)


class ConversationReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    project_id: str
    turns: list[ConversationTurn]


class ConversationSendResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    project_id: str
    turns: list[ConversationTurn] = Field(min_length=2, max_length=2)
    reconstructed: bool = False
