from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PROJECT_SCHEMA_VERSION = "1.0"
ACTIVE_PROJECT_POINTER_SCHEMA_VERSION = "1.0"
PROJECT_ACTIVITY_SCHEMA_VERSION = "1.0"
CHECKPOINT_PROPOSAL_SCHEMA_VERSION = "1.0"
PROJECT_CONTEXT_PACK_SCHEMA_VERSION = "1.0"
PROJECT_CONTEXT_QUERY_PACK_SCHEMA_VERSION = "1.0"

_MAX_ACTIVITY_SUMMARY_LENGTH = 500
_MAX_ACTIVITY_DETAILS_LENGTH = 3000
_MAX_ACTIVITY_METADATA_ENTRIES = 16
_MAX_ACTIVITY_METADATA_KEY_LENGTH = 64
_MAX_ACTIVITY_METADATA_STRING_LENGTH = 256
_MAX_ACTIVITY_METADATA_TOTAL_TEXT = 2048
_MAX_CHECKPOINT_PROPOSAL_REASON_LENGTH = 1000


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ProjectActivityType(str, Enum):
    NOTE = "note"
    OBSERVATION = "observation"
    ACTION = "action"
    RESULT = "result"
    DECISION = "decision"
    BLOCKER = "blocker"
    MILESTONE = "milestone"


class ProjectActivitySourceType(str, Enum):
    USER = "user"
    SYSTEM = "system"
    AI = "ai"


class ProjectActivityConfirmationStatus(str, Enum):
    REPORTED = "reported"
    OBSERVED = "observed"
    INFERRED = "inferred"
    CONFIRMED = "confirmed"


class CheckpointProposalStatus(str, Enum):
    PENDING = "pending"
    APPLIED = "applied"
    REJECTED = "rejected"


class ProjectCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    current_objective: str | None = Field(default=None, max_length=400)
    completed_summary: str | None = Field(default=None, max_length=2000)
    discoveries_summary: str | None = Field(default=None, max_length=2000)
    current_work: str | None = Field(default=None, max_length=2000)
    stopped_at: str | None = Field(default=None, max_length=500)
    blockers: str | None = Field(default=None, max_length=2000)
    next_action: str | None = Field(default=None, max_length=1000)

    @field_validator(
        "current_objective",
        "completed_summary",
        "discoveries_summary",
        "current_work",
        "stopped_at",
        "blockers",
        "next_action",
    )
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        return text


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    project_id: str
    name: str = Field(..., min_length=1, max_length=200)
    goal: str = Field(..., min_length=1, max_length=1000)
    status: ProjectStatus
    checkpoint: ProjectCheckpoint = Field(default_factory=ProjectCheckpoint)
    revision: int = Field(..., ge=0)
    created_at_utc: datetime
    updated_at_utc: datetime

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != PROJECT_SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version. Use {PROJECT_SCHEMA_VERSION}.")
        return value

    @field_validator("project_id")
    @classmethod
    def _validate_project_id(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("project_id is required.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ValueError("project_id must be a valid UUID.") from exc
        return str(parsed)

    @field_validator("created_at_utc", "updated_at_utc")
    @classmethod
    def _validate_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=200)
    goal: str = Field(..., min_length=1, max_length=1000)
    status: ProjectStatus = ProjectStatus.ACTIVE
    checkpoint: ProjectCheckpoint | None = None


class ProjectCheckpointPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_revision: int | None = Field(default=None, ge=0)
    current_objective: str | None = Field(default=None, max_length=400)
    completed_summary: str | None = Field(default=None, max_length=2000)
    discoveries_summary: str | None = Field(default=None, max_length=2000)
    current_work: str | None = Field(default=None, max_length=2000)
    stopped_at: str | None = Field(default=None, max_length=500)
    blockers: str | None = Field(default=None, max_length=2000)
    next_action: str | None = Field(default=None, max_length=1000)

    @field_validator(
        "current_objective",
        "completed_summary",
        "discoveries_summary",
        "current_work",
        "stopped_at",
        "blockers",
        "next_action",
    )
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        return text


class ProjectSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: str
    name: str
    status: ProjectStatus
    updated_at_utc: datetime
    current_objective: str | None = None
    next_action: str | None = None


class ProjectActivity(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    activity_id: str
    project_id: str
    activity_type: ProjectActivityType
    source_type: ProjectActivitySourceType
    confirmation_status: ProjectActivityConfirmationStatus
    summary: str = Field(..., min_length=1, max_length=_MAX_ACTIVITY_SUMMARY_LENGTH)
    details: str | None = Field(default=None, max_length=_MAX_ACTIVITY_DETAILS_LENGTH)
    occurred_at_utc: datetime
    created_at_utc: datetime
    metadata: dict[str, str | int | float | bool | None] | None = None

    @field_validator("schema_version")
    @classmethod
    def _validate_activity_schema_version(cls, value: str) -> str:
        if value != PROJECT_ACTIVITY_SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version. Use {PROJECT_ACTIVITY_SCHEMA_VERSION}.")
        return value

    @field_validator("activity_id", "project_id")
    @classmethod
    def _validate_uuid_fields(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("UUID fields are required.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ValueError("UUID fields must be valid UUIDs.") from exc
        return str(parsed)

    @field_validator("summary", "details")
    @classmethod
    def _normalize_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        return text

    @field_validator("occurred_at_utc", "created_at_utc")
    @classmethod
    def _validate_utc_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(
        cls,
        value: dict[str, str | int | float | bool | None] | None,
    ) -> dict[str, str | int | float | bool | None] | None:
        if value is None:
            return None

        if len(value) > _MAX_ACTIVITY_METADATA_ENTRIES:
            raise ValueError("metadata contains too many entries.")

        total_text = 0
        normalized: dict[str, str | int | float | bool | None] = {}
        for key, item in value.items():
            cleaned_key = str(key).strip()
            if not cleaned_key:
                raise ValueError("metadata keys must be non-empty.")
            if len(cleaned_key) > _MAX_ACTIVITY_METADATA_KEY_LENGTH:
                raise ValueError("metadata key is too long.")

            if isinstance(item, str):
                cleaned_value = item.strip()
                if len(cleaned_value) > _MAX_ACTIVITY_METADATA_STRING_LENGTH:
                    raise ValueError("metadata string value is too long.")
                total_text += len(cleaned_key) + len(cleaned_value)
                normalized[cleaned_key] = cleaned_value
                continue

            if isinstance(item, (int, float, bool)) or item is None:
                total_text += len(cleaned_key) + len(str(item))
                normalized[cleaned_key] = item
                continue

            raise ValueError("metadata values must be scalar types.")

        if total_text > _MAX_ACTIVITY_METADATA_TOTAL_TEXT:
            raise ValueError("metadata total content is too large.")

        return normalized


class ProjectActivityCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    activity_type: ProjectActivityType
    source_type: ProjectActivitySourceType
    confirmation_status: ProjectActivityConfirmationStatus
    summary: str = Field(..., min_length=1, max_length=_MAX_ACTIVITY_SUMMARY_LENGTH)
    details: str | None = Field(default=None, max_length=_MAX_ACTIVITY_DETAILS_LENGTH)
    occurred_at_utc: datetime | None = None
    metadata: dict[str, str | int | float | bool | None] | None = None

    @field_validator("summary", "details")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        return text

    @field_validator("occurred_at_utc")
    @classmethod
    def _validate_optional_occurred_at_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("occurred_at_utc must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)


class CheckpointProposalPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    current_objective: str | None = Field(default=None, max_length=400)
    completed_summary: str | None = Field(default=None, max_length=2000)
    discoveries_summary: str | None = Field(default=None, max_length=2000)
    current_work: str | None = Field(default=None, max_length=2000)
    stopped_at: str | None = Field(default=None, max_length=500)
    blockers: str | None = Field(default=None, max_length=2000)
    next_action: str | None = Field(default=None, max_length=1000)

    @field_validator(
        "current_objective",
        "completed_summary",
        "discoveries_summary",
        "current_work",
        "stopped_at",
        "blockers",
        "next_action",
    )
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        return text

    def to_update_fields(self) -> dict[str, str]:
        raw = self.model_dump(mode="python")
        fields: dict[str, str] = {}
        for key, value in raw.items():
            if value is not None:
                fields[key] = value
        return fields


class CheckpointProposalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_project_revision: int = Field(..., ge=0)
    source_activity_ids: list[str] = Field(default_factory=list)
    proposed_checkpoint_patch: CheckpointProposalPatch
    reason: str = Field(..., min_length=1, max_length=_MAX_CHECKPOINT_PROPOSAL_REASON_LENGTH)

    @field_validator("source_activity_ids")
    @classmethod
    def _validate_source_activity_ids(cls, value: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip()
            if not text:
                raise ValueError("source_activity_ids must contain valid UUID values.")
            try:
                normalized = str(UUID(text))
            except ValueError as exc:
                raise ValueError("source_activity_ids must contain valid UUID values.") from exc
            if normalized in seen:
                continue
            seen.add(normalized)
            unique.append(normalized)
        return unique

    @field_validator("reason")
    @classmethod
    def _normalize_reason(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("reason is required.")
        return text

    @field_validator("proposed_checkpoint_patch")
    @classmethod
    def _validate_non_empty_patch(cls, value: CheckpointProposalPatch) -> CheckpointProposalPatch:
        if not value.to_update_fields():
            raise ValueError("proposed_checkpoint_patch must include at least one field.")
        return value


class CheckpointProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    proposal_id: str
    project_id: str
    base_project_revision: int = Field(..., ge=0)
    source_activity_ids: list[str] = Field(default_factory=list)
    proposed_checkpoint_patch: CheckpointProposalPatch
    reason: str = Field(..., min_length=1, max_length=_MAX_CHECKPOINT_PROPOSAL_REASON_LENGTH)
    status: CheckpointProposalStatus
    created_at_utc: datetime
    applied_at_utc: datetime | None = None
    rejected_at_utc: datetime | None = None

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != CHECKPOINT_PROPOSAL_SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version. Use {CHECKPOINT_PROPOSAL_SCHEMA_VERSION}.")
        return value

    @field_validator("proposal_id", "project_id")
    @classmethod
    def _validate_uuid_fields(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("UUID fields are required.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ValueError("UUID fields must be valid UUIDs.") from exc
        return str(parsed)

    @field_validator("source_activity_ids")
    @classmethod
    def _normalize_source_activity_ids(cls, value: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip()
            if not text:
                raise ValueError("source_activity_ids must contain valid UUID values.")
            try:
                normalized = str(UUID(text))
            except ValueError as exc:
                raise ValueError("source_activity_ids must contain valid UUID values.") from exc
            if normalized in seen:
                continue
            seen.add(normalized)
            unique.append(normalized)
        return unique

    @field_validator("reason")
    @classmethod
    def _normalize_reason(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("reason is required.")
        return text

    @field_validator("created_at_utc", "applied_at_utc", "rejected_at_utc")
    @classmethod
    def _validate_utc_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)

    @field_validator("proposed_checkpoint_patch")
    @classmethod
    def _validate_non_empty_patch(cls, value: CheckpointProposalPatch) -> CheckpointProposalPatch:
        if not value.to_update_fields():
            raise ValueError("proposed_checkpoint_patch must include at least one field.")
        return value

    @model_validator(mode="after")
    def _validate_status_timestamps(self) -> "CheckpointProposal":
        if self.status == CheckpointProposalStatus.PENDING:
            if self.applied_at_utc is not None or self.rejected_at_utc is not None:
                raise ValueError("pending proposals must not have terminal timestamps.")
        elif self.status == CheckpointProposalStatus.APPLIED:
            if self.applied_at_utc is None or self.rejected_at_utc is not None:
                raise ValueError("applied proposals must have applied_at_utc only.")
        elif self.status == CheckpointProposalStatus.REJECTED:
            if self.rejected_at_utc is None or self.applied_at_utc is not None:
                raise ValueError("rejected proposals must have rejected_at_utc only.")
        return self

    @classmethod
    def build_new(
        cls,
        *,
        proposal_id: str,
        project_id: str,
        base_project_revision: int,
        source_activity_ids: list[str],
        proposed_checkpoint_patch: CheckpointProposalPatch,
        reason: str,
        created_at_utc: datetime,
    ) -> "CheckpointProposal":
        return cls(
            schema_version=CHECKPOINT_PROPOSAL_SCHEMA_VERSION,
            proposal_id=proposal_id,
            project_id=project_id,
            base_project_revision=base_project_revision,
            source_activity_ids=source_activity_ids,
            proposed_checkpoint_patch=proposed_checkpoint_patch,
            reason=reason,
            status=CheckpointProposalStatus.PENDING,
            created_at_utc=created_at_utc,
            applied_at_utc=None,
            rejected_at_utc=None,
        )


class ActiveProjectPointer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    active_project_id: str
    updated_at_utc: datetime

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != ACTIVE_PROJECT_POINTER_SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version. Use {ACTIVE_PROJECT_POINTER_SCHEMA_VERSION}.")
        return value

    @field_validator("active_project_id")
    @classmethod
    def _validate_project_id(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("active_project_id is required.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ValueError("active_project_id must be a valid UUID.") from exc
        return str(parsed)

    @field_validator("updated_at_utc")
    @classmethod
    def _validate_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("updated_at_utc must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)


class ProjectInvestigationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str
    result_id: str
    investigation_id: str
    status: str
    diagnosis: str = Field(..., min_length=1, max_length=500)
    required_next_action: str = Field(..., min_length=1, max_length=280)
    completed_at_utc: datetime

    @field_validator("session_id", "result_id")
    @classmethod
    def _validate_uuid_fields(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("UUID fields are required.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ValueError("UUID fields must be valid UUIDs.") from exc
        return str(parsed)

    @field_validator("investigation_id", "status", "diagnosis", "required_next_action")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Field must be non-empty.")
        return text

    @field_validator("completed_at_utc")
    @classmethod
    def _validate_completed_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("completed_at_utc must be timezone-aware UTC.")
        return value.astimezone(timezone.utc)


class ProjectContextPack(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    project_id: str
    project_name: str
    project_goal: str
    project_status: ProjectStatus
    checkpoint: ProjectCheckpoint
    current_objective: str | None = None
    blockers: str | None = None
    next_action: str | None = None
    recent_activity_limit: int = Field(..., ge=1)
    recent_investigation_limit: int = Field(..., ge=1)
    recent_activities: list[ProjectActivity] = Field(default_factory=list)
    recent_investigations: list[ProjectInvestigationSummary] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _validate_context_pack_schema_version(cls, value: str) -> str:
        if value != PROJECT_CONTEXT_PACK_SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version. Use {PROJECT_CONTEXT_PACK_SCHEMA_VERSION}.")
        return value

    @field_validator("project_id")
    @classmethod
    def _validate_project_id(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("project_id is required.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ValueError("project_id must be a valid UUID.") from exc
        return str(parsed)

    @field_validator("project_name", "project_goal", "current_objective", "blockers", "next_action")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        return text


class ProjectContextQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(..., min_length=1, max_length=1000)

    @field_validator("question")
    @classmethod
    def _normalize_question(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("question is required.")
        return text


class ProjectContextSelectionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    strategy: str = Field(..., min_length=1, max_length=64)
    matched_terms: list[str] = Field(default_factory=list)
    recent_activity_limit: int = Field(..., ge=1)
    recent_investigation_limit: int = Field(..., ge=1)
    fallback_used: bool = False

    @field_validator("strategy")
    @classmethod
    def _normalize_strategy(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("strategy is required.")
        return text

    @field_validator("matched_terms")
    @classmethod
    def _normalize_matched_terms(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip().lower()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized


class ProjectContextQueryPack(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    project_id: str
    project_name: str
    project_goal: str
    project_status: ProjectStatus
    question: str = Field(..., min_length=1, max_length=1000)
    checkpoint: ProjectCheckpoint
    current_objective: str | None = None
    blockers: str | None = None
    next_action: str | None = None
    selection: ProjectContextSelectionMetadata
    selected_activities: list[ProjectActivity] = Field(default_factory=list)
    selected_investigations: list[ProjectInvestigationSummary] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _validate_context_query_pack_schema_version(cls, value: str) -> str:
        if value != PROJECT_CONTEXT_QUERY_PACK_SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version. Use {PROJECT_CONTEXT_QUERY_PACK_SCHEMA_VERSION}.")
        return value

    @field_validator("project_id")
    @classmethod
    def _validate_project_id(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("project_id is required.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ValueError("project_id must be a valid UUID.") from exc
        return str(parsed)

    @field_validator("project_name", "project_goal", "question", "current_objective", "blockers", "next_action")
    @classmethod
    def _normalize_optional_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        return text


def create_new_project(
    *,
    name: str,
    goal: str,
    status: ProjectStatus = ProjectStatus.ACTIVE,
    checkpoint: ProjectCheckpoint | None = None,
) -> Project:
    now = datetime.now(timezone.utc)
    return Project(
        schema_version=PROJECT_SCHEMA_VERSION,
        project_id=str(uuid4()),
        name=name,
        goal=goal,
        status=status,
        checkpoint=checkpoint or ProjectCheckpoint(),
        revision=0,
        created_at_utc=now,
        updated_at_utc=now,
    )


def to_project_summary(project: Project) -> ProjectSummary:
    return ProjectSummary(
        project_id=project.project_id,
        name=project.name,
        status=project.status,
        updated_at_utc=project.updated_at_utc,
        current_objective=project.checkpoint.current_objective,
        next_action=project.checkpoint.next_action,
    )
