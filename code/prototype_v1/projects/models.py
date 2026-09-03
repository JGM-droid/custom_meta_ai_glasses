from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from investigations.models import InvestigationDesktopProjection


PROJECT_SCHEMA_VERSION = "1.0"
ACTIVE_PROJECT_POINTER_SCHEMA_VERSION = "1.0"
PROJECT_ACTIVITY_SCHEMA_VERSION = "1.0"
CHECKPOINT_PROPOSAL_SCHEMA_VERSION = "1.0"
PROJECT_CONTEXT_PACK_SCHEMA_VERSION = "1.0"
PROJECT_CONTEXT_QUERY_PACK_SCHEMA_VERSION = "1.0"
PROJECT_ORIENTATION_SCHEMA_VERSION = "1.0"
PROJECT_TRUST_STATE_SCHEMA_VERSION = "1.0"
PROJECT_KNOWLEDGE_SCHEMA_VERSION = "1.0"
PROJECT_IDEA_LIST_SCHEMA_VERSION = "1.0"
PROJECT_EXPLORE_SCHEMA_VERSION = "1.0"
PROJECT_EXPLORE_PROVIDER_RESULT_SCHEMA_VERSION = "1.1"
PROJECT_AI_RESULT_SCHEMA_VERSION = "1.0"

_MAX_ACTIVITY_SUMMARY_LENGTH = 500
_MAX_ACTIVITY_DETAILS_LENGTH = 3000
_MAX_ACTIVITY_METADATA_ENTRIES = 16
_MAX_ACTIVITY_METADATA_KEY_LENGTH = 64
_MAX_ACTIVITY_METADATA_STRING_LENGTH = 256
_MAX_ACTIVITY_METADATA_TOTAL_TEXT = 2048
_MAX_CHECKPOINT_PROPOSAL_REASON_LENGTH = 1000

_MAX_EXPLORE_CONCEPT_LENGTH = 800
_MAX_EXPLORE_PROPOSED_CHANGES_LENGTH = 800
_MAX_EXPLORE_ESTIMATED_COST_QUALIFIER_LENGTH = 120
_MAX_EXPLORE_RECOMMENDATION_REASON_LENGTH = 800
_MAX_EXPLORE_OBSERVATION_LENGTH = 200
_MAX_EXPLORE_OBSERVATIONS = 4
_MAX_EXPLORE_NEXT_STEP_LENGTH = 200
_MAX_EXPLORE_NEXT_STEPS = 5
_MAX_EXPLORE_FOLLOW_UP_QUESTION_LENGTH = 200
_MAX_EXPLORE_FOLLOW_UP_QUESTIONS = 4

# Must match project_explore.py's _FIELD_DELIMITER exactly - reserved for
# lossless Activity text encoding, never valid in provider-supplied text.
_RESERVED_FIELD_DELIMITER = chr(0xE000)


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
    IDEA = "idea"
    OPEN_QUESTION = "open_question"


class ProjectActivitySourceType(str, Enum):
    USER = "user"
    SYSTEM = "system"
    AI = "ai"


class ProjectActivityConfirmationStatus(str, Enum):
    REPORTED = "reported"
    OBSERVED = "observed"
    INFERRED = "inferred"
    CONFIRMED = "confirmed"


class ProjectTrustDecisionType(str, Enum):
    CONTINUE = "continue"
    DISAGREE = "disagree"
    MORE_EVIDENCE = "more_evidence"


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


class ProjectIdeaCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: str = Field(..., min_length=1, max_length=_MAX_ACTIVITY_SUMMARY_LENGTH)
    details: str | None = Field(default=None, max_length=_MAX_ACTIVITY_DETAILS_LENGTH)
    metadata: dict[str, str | int | float | bool | None] | None = None


class ProjectIdeaList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    project_id: str
    limit: int
    ideas: list[ProjectActivity] = Field(default_factory=list)


class ProjectIdeaPromotionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idea: ProjectActivity
    roadmap_activity: ProjectActivity
    created: bool


class ProjectExploreDisposition(str, Enum):
    KEEP = "keep"
    DISMISS = "dismiss"
    SELECT = "select"


class ProjectExploreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_intent: str = Field(..., min_length=1, max_length=1000)
    input_refs: list[str] = Field(default_factory=list, max_length=5)
    idempotency_key: str = Field(..., min_length=1, max_length=128)

    @field_validator("input_refs")
    @classmethod
    def _validate_input_refs(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            try:
                ref = str(UUID(str(item or "").strip()))
            except ValueError as exc:
                raise ValueError("input_refs must contain valid Activity UUIDs.") from exc
            if ref in seen:
                raise ValueError("input_refs must not contain duplicates.")
            seen.add(ref)
            normalized.append(ref)
        return normalized


class ExplorePlanEstimatedCost(BaseModel):
    """A small, optional, structured cost estimate for one Explore option.

    Encoded as one delimited scalar Activity metadata value (see
    project_explore.py's encode/decode helpers), never as nested JSON.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    currency: str = Field(..., min_length=3, max_length=3)
    min_amount: float | None = Field(default=None, ge=0)
    max_amount: float | None = Field(default=None, ge=0)
    qualifier: str | None = Field(default=None, max_length=_MAX_EXPLORE_ESTIMATED_COST_QUALIFIER_LENGTH)

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        text = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", text):
            raise ValueError("currency must be a 3-letter ISO 4217 code.")
        return text

    @field_validator("qualifier")
    @classmethod
    def _validate_qualifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        if _RESERVED_FIELD_DELIMITER in text:
            raise ValueError("qualifier must not contain the reserved delimiter character.")
        if "|" in text:
            raise ValueError("qualifier must not contain '|'.")
        return text

    @model_validator(mode="after")
    def _validate_range(self) -> "ExplorePlanEstimatedCost":
        if self.min_amount is not None and self.max_amount is not None and self.min_amount > self.max_amount:
            raise ValueError("min_amount must not exceed max_amount.")
        return self


def _validate_bounded_text_list(value: list[str], *, item_max_length: int, field_name: str) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or len(text) > item_max_length:
            raise ValueError(f"{field_name} entries must contain 1 to {item_max_length} characters.")
        if _RESERVED_FIELD_DELIMITER in text:
            raise ValueError(f"{field_name} entries must not contain the reserved delimiter character.")
        key = " ".join(text.lower().split())
        if key in seen:
            raise ValueError(f"{field_name} must not contain duplicates.")
        seen.add(key)
        normalized.append(text)
    return normalized


class ProjectExploreProviderOption(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ordinal: int = Field(..., ge=1, le=3)
    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1, max_length=1000)
    rationale: str | None = Field(default=None, max_length=800)
    tradeoffs: str | None = Field(default=None, max_length=800)
    source_refs: list[str] = Field(default_factory=list, max_length=5)
    concept: str | None = Field(default=None, max_length=_MAX_EXPLORE_CONCEPT_LENGTH)
    proposed_changes: str | None = Field(default=None, max_length=_MAX_EXPLORE_PROPOSED_CHANGES_LENGTH)
    estimated_cost: ExplorePlanEstimatedCost | None = None

    @field_validator("title", "summary", "rationale", "tradeoffs", "concept", "proposed_changes")
    @classmethod
    def _reject_reserved_delimiter(cls, value: str | None) -> str | None:
        if value is not None and _RESERVED_FIELD_DELIMITER in value:
            raise ValueError("Field must not contain the reserved delimiter character.")
        return value


class ProjectExploreOptionSet(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["1.1"]
    result_type: Literal["OPTION_SET"] = "OPTION_SET"
    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1, max_length=1000)
    source_refs: list[str] = Field(default_factory=list, max_length=5)
    options: list[ProjectExploreProviderOption] = Field(..., min_length=3, max_length=3)
    observations: list[str] = Field(..., min_length=1, max_length=_MAX_EXPLORE_OBSERVATIONS)
    recommended_ordinal: int = Field(..., ge=1, le=3)
    recommendation_reason: str = Field(..., min_length=1, max_length=_MAX_EXPLORE_RECOMMENDATION_REASON_LENGTH)
    next_steps: list[str] = Field(..., min_length=1, max_length=_MAX_EXPLORE_NEXT_STEPS)
    follow_up_questions: list[str] = Field(default_factory=list, max_length=_MAX_EXPLORE_FOLLOW_UP_QUESTIONS)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != PROJECT_EXPLORE_PROVIDER_RESULT_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {PROJECT_EXPLORE_PROVIDER_RESULT_SCHEMA_VERSION}.")
        return value

    @field_validator("observations", mode="after")
    @classmethod
    def _validate_observations(cls, value: list[str]) -> list[str]:
        return _validate_bounded_text_list(value, item_max_length=_MAX_EXPLORE_OBSERVATION_LENGTH, field_name="observations")

    @field_validator("next_steps", mode="after")
    @classmethod
    def _validate_next_steps(cls, value: list[str]) -> list[str]:
        return _validate_bounded_text_list(value, item_max_length=_MAX_EXPLORE_NEXT_STEP_LENGTH, field_name="next_steps")

    @field_validator("follow_up_questions", mode="after")
    @classmethod
    def _validate_follow_up_questions(cls, value: list[str]) -> list[str]:
        return _validate_bounded_text_list(value, item_max_length=_MAX_EXPLORE_FOLLOW_UP_QUESTION_LENGTH, field_name="follow_up_questions")

    @field_validator("title", "summary", "recommendation_reason")
    @classmethod
    def _reject_reserved_delimiter(cls, value: str) -> str:
        if _RESERVED_FIELD_DELIMITER in value:
            raise ValueError("Field must not contain the reserved delimiter character.")
        return value

    @model_validator(mode="after")
    def _validate_recommended_ordinal_references_an_option(self) -> "ProjectExploreOptionSet":
        if self.recommended_ordinal not in {option.ordinal for option in self.options}:
            raise ValueError("recommended_ordinal must reference one of the returned options.")
        return self


class ProjectExploreInformationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["1.1"]
    result_type: Literal["INFORMATION_REQUEST"] = "INFORMATION_REQUEST"
    title: str = Field(..., min_length=1, max_length=200)
    prompt: str = Field(..., min_length=1, max_length=1000)
    requested_inputs: list[str] = Field(..., min_length=1, max_length=5)
    source_refs: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != PROJECT_EXPLORE_PROVIDER_RESULT_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {PROJECT_EXPLORE_PROVIDER_RESULT_SCHEMA_VERSION}.")
        return value

    @field_validator("requested_inputs")
    @classmethod
    def _validate_requested_inputs(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip()
            if not text or len(text) > 300:
                raise ValueError("requested_inputs entries must contain 1 to 300 characters.")
            key = " ".join(text.lower().split())
            if key in seen:
                raise ValueError("requested_inputs must not contain duplicates.")
            seen.add(key)
            normalized.append(text)
        return normalized


class ProjectExploreDispositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    disposition: ProjectExploreDisposition
    idempotency_key: str = Field(..., min_length=1, max_length=128)


class ProjectExploreOptionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idea: ProjectActivity
    interaction_id: str
    result_item_id: str
    ordinal: int
    disposition: ProjectExploreDisposition | None = None
    disposition_activity: ProjectActivity | None = None
    disposition_history: list[ProjectActivity] = Field(default_factory=list)
    promoted: bool = False
    roadmap_activity: ProjectActivity | None = None
    related_proposals: list[CheckpointProposal] = Field(default_factory=list)
    concept: str | None = None
    proposed_changes: str | None = None
    estimated_cost: ExplorePlanEstimatedCost | None = None
    recommended: bool = False


class ProjectExploreGroupView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interaction_id: str
    idempotency_key: str
    complete: bool
    options: list[ProjectExploreOptionView] = Field(default_factory=list)
    title: str | None = None
    summary: str | None = None
    observations: list[str] = Field(default_factory=list)
    recommended_ordinal: int | None = None
    recommendation_reason: str | None = None
    next_steps: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    result_activity: ProjectActivity | None = None


class ProjectExploreReadProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PROJECT_EXPLORE_SCHEMA_VERSION
    project_id: str
    option_sets: list[ProjectExploreGroupView] = Field(default_factory=list)
    preferred_direction: ProjectExploreOptionView | None = None
    canonical_checkpoint: ProjectCheckpoint
    project_revision: int
    next_action: str


class ProjectExploreExecutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PROJECT_EXPLORE_SCHEMA_VERSION
    project_id: str
    interaction_id: str | None = None
    result_type: str
    suggestions_created: bool
    message: str
    option_set: ProjectExploreGroupView | None = None
    information_request: ProjectExploreInformationRequest | None = None


class ProjectExploreDispositionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idea: ProjectActivity
    decision_activity: ProjectActivity
    created: bool
    projection: ProjectExploreReadProjection


class ProjectRoadmap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed: list[ProjectActivity] = Field(default_factory=list)
    current: list[ProjectActivity] = Field(default_factory=list)
    upcoming: list[ProjectActivity] = Field(default_factory=list)
    deferred: list[ProjectActivity] = Field(default_factory=list)


class ProjectOrientation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    project_id: str
    name: str
    status: ProjectStatus
    objective: str
    where_we_are: str | None = None
    now: str | None = None
    next: str | None = None
    blockers: str | None = None
    roadmap: ProjectRoadmap = Field(default_factory=ProjectRoadmap)

    @field_validator("schema_version")
    @classmethod
    def _validate_orientation_schema_version(cls, value: str) -> str:
        if value != PROJECT_ORIENTATION_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema_version. Use {PROJECT_ORIENTATION_SCHEMA_VERSION}."
            )
        return value


class ProjectTrustDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: ProjectTrustDecisionType
    correction: str | None = Field(default=None, max_length=1000)

    @field_validator("correction")
    @classmethod
    def _normalize_correction(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ProjectInvestigationTrustState(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    project_id: str
    investigation_session_id: str
    investigation_result_id: str
    hypothesis: str
    recommended_next_action: str
    status: str
    user_decision: ProjectTrustDecisionType | None = None
    user_correction: str | None = None
    decision_activity_id: str | None = None
    decided_at_utc: datetime | None = None
    checkpoint_proposal_id: str | None = None
    checkpoint_proposal_status: CheckpointProposalStatus | None = None
    follow_up_investigation_session_id: str | None = None


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


class ProjectProgressCheckpointPatch(BaseModel):
    """The deliberately small checkpoint surface a user may suggest while recording progress."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    current_work: str | None = Field(default=None, max_length=2000)
    blockers: str | None = Field(default=None, max_length=2000)
    next_action: str | None = Field(default=None, max_length=1000)

    @field_validator("current_work", "blockers", "next_action")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    def to_update_fields(self) -> dict[str, str]:
        return {key: value for key, value in self.model_dump(mode="python").items() if value is not None}


class ProjectProgressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    idempotency_key: str = Field(..., min_length=1, max_length=128)
    summary: str = Field(..., min_length=1, max_length=_MAX_ACTIVITY_SUMMARY_LENGTH)
    details: str | None = Field(default=None, max_length=_MAX_ACTIVITY_DETAILS_LENGTH)
    expected_project_revision: int = Field(..., ge=0)
    checkpoint_patch: ProjectProgressCheckpointPatch | None = None

    @field_validator("idempotency_key", "summary", "details")
    @classmethod
    def _normalize_progress_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class ProjectProgressPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    idempotency_key: str
    summary: str
    details: str | None = None
    base_project_revision: int = Field(..., ge=0)
    effective_checkpoint_patch: ProjectProgressCheckpointPatch | None = None
    proposal_required: bool


class ProjectProgressResponse(ProjectProgressPreview):
    activity: ProjectActivity
    proposal: "CheckpointProposal | None" = None
    reconstructed: bool = False


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


class ProjectTrustDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trust_state: ProjectInvestigationTrustState
    decision_activity: ProjectActivity
    checkpoint_proposal: CheckpointProposal | None = None


class ProjectKnowledgeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: str
    occurred_at_utc: datetime
    summary: str
    source_type: str
    confirmation_status: str
    evidence_id: str | None = None
    activity_id: str | None = None
    investigation_session_id: str | None = None
    related_activity_ids: list[str] = Field(default_factory=list)
    reference: str | None = None


class ProjectKnowledgeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_kind: str
    occurred_at_utc: datetime
    summary: str
    source_type: str
    confirmation_status: str
    activity_id: str | None = None
    proposal_id: str | None = None
    metadata: dict[str, str | int | float | bool | None] | None = None


class ProjectKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    project_id: str
    evidence_limit: int
    decision_limit: int
    finding_limit: int
    history_limit: int
    recent_important_change_limit: int
    evidence: list[ProjectKnowledgeEvidence] = Field(default_factory=list)
    decisions: list[ProjectKnowledgeRecord] = Field(default_factory=list)
    findings: list[ProjectKnowledgeRecord] = Field(default_factory=list)
    history: list[ProjectActivity] = Field(default_factory=list)
    recent_important_changes: list[ProjectKnowledgeRecord] = Field(default_factory=list)


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
    detected_question_class: str = Field(..., min_length=1, max_length=64)
    retrieval_contract: str = Field(..., min_length=1, max_length=128)
    matched_terms: list[str] = Field(default_factory=list)
    required_categories: list[str] = Field(default_factory=list)
    optional_categories: list[str] = Field(default_factory=list)
    excluded_categories: list[str] = Field(default_factory=list)
    selected_categories: list[str] = Field(default_factory=list)
    category_inclusion_reasons: dict[str, str] = Field(default_factory=dict)
    recent_activity_limit: int = Field(..., ge=0)
    recent_investigation_limit: int = Field(..., ge=0)
    fallback_used: bool = False
    fallback_reason: str | None = None

    @field_validator("strategy")
    @classmethod
    def _normalize_strategy(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("strategy is required.")
        return text

    @field_validator("detected_question_class", "retrieval_contract")
    @classmethod
    def _normalize_required_text_fields(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Field is required.")
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

    @field_validator("required_categories", "optional_categories", "excluded_categories", "selected_categories")
    @classmethod
    def _normalize_categories(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip().lower()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    @field_validator("category_inclusion_reasons")
    @classmethod
    def _normalize_category_inclusion_reasons(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for category, reason in value.items():
            key = str(category or "").strip().lower()
            text = str(reason or "").strip()
            if not key or not text:
                continue
            normalized[key] = text
        return normalized

    @field_validator("fallback_reason")
    @classmethod
    def _normalize_fallback_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        return text


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


class ProjectAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(..., min_length=1, max_length=1000)

    @field_validator("question")
    @classmethod
    def _normalize_question(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("question is required.")
        return text


class ProjectGroundedAnswerReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_kind: str = Field(..., min_length=1, max_length=64)
    source_id: str | None = Field(default=None, max_length=64)
    summary: str = Field(..., min_length=1, max_length=500)
    evidence_status: str | None = Field(default=None, max_length=64)

    @field_validator("source_kind", "summary", "evidence_status")
    @classmethod
    def _normalize_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        return text


class ProjectGroundedAnswerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: str
    project_name: str
    question: str = Field(..., min_length=1, max_length=1000)
    question_class: str = Field(..., min_length=1, max_length=64)
    answer: str = Field(..., min_length=1, max_length=4000)
    grounding_status: str = Field(..., min_length=1, max_length=64)
    insufficient_context: bool = False
    uncertainty_note: str | None = Field(default=None, max_length=1000)
    fallback_used: bool = False
    selected_context_summary: list[str] = Field(default_factory=list)
    references: list[ProjectGroundedAnswerReference] = Field(default_factory=list)
    provider: str | None = Field(default=None, max_length=64)
    provider_model: str | None = Field(default=None, max_length=200)
    model_call_count: int = Field(default=1, ge=1)

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

    @field_validator(
        "project_name",
        "question",
        "question_class",
        "answer",
        "grounding_status",
        "uncertainty_note",
        "provider",
        "provider_model",
    )
    @classmethod
    def _normalize_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        return text

    @field_validator("selected_context_summary")
    @classmethod
    def _normalize_selected_context_summary(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(text)
        return normalized


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


# --- Rich Project Intelligence V1 (ADR-059): ProjectAIResult presentation envelope ---
#
# This is a read/presentation composition, never a persisted entity of its
# own. TROUBLESHOOT/EXPLORE_PLAN/GENERAL_GUIDANCE each keep their existing
# domain owner (Investigation, evolved Explore, Project Q&A); the payload
# fields below reuse those services' existing typed responses unchanged
# rather than duplicating their shape.

class ProjectAIResultType(str, Enum):
    TROUBLESHOOT = "TROUBLESHOOT"
    EXPLORE_PLAN = "EXPLORE_PLAN"
    GENERAL_GUIDANCE = "GENERAL_GUIDANCE"


_MAX_AI_RESULT_HEADLINE_LENGTH = 280
_MAX_AI_RESULT_NEXT_LENGTH = 280
_MAX_AI_RESULT_SUMMARY_LENGTH = 1000


class ProjectAIResultHudProjection(BaseModel):
    """The concise, bounded glasses projection - never the full rich result."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    headline: str = Field(..., min_length=1, max_length=_MAX_AI_RESULT_HEADLINE_LENGTH)
    next: str | None = Field(default=None, max_length=_MAX_AI_RESULT_NEXT_LENGTH)
    uncertainty_flag: bool = False


class ProjectAIResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str = PROJECT_AI_RESULT_SCHEMA_VERSION
    result_id: str
    project_id: str
    result_type: ProjectAIResultType
    summary: str = Field(..., min_length=1, max_length=_MAX_AI_RESULT_SUMMARY_LENGTH)
    hud_projection: ProjectAIResultHudProjection
    evidence_refs: list[str] = Field(default_factory=list)
    suggested_project_updates: bool = False
    # True only for GENERAL_GUIDANCE: this result is not persisted anywhere
    # and cannot be reconstructed after restart. Clients must not imply
    # durability (e.g. no "saved to your project" copy, no HUD reference
    # that survives a reconnect) when this is True.
    ephemeral: bool = False

    troubleshoot: InvestigationDesktopProjection | None = None
    explore_plan: ProjectExploreGroupView | None = None
    general_guidance: ProjectGroundedAnswerResponse | None = None

    @model_validator(mode="after")
    def _validate_exactly_one_payload_matches_result_type(self) -> "ProjectAIResult":
        payload_by_type = {
            ProjectAIResultType.TROUBLESHOOT: self.troubleshoot,
            ProjectAIResultType.EXPLORE_PLAN: self.explore_plan,
            ProjectAIResultType.GENERAL_GUIDANCE: self.general_guidance,
        }
        for result_type, payload in payload_by_type.items():
            present = payload is not None
            should_be_present = result_type == self.result_type
            if present != should_be_present:
                raise ValueError("Exactly one payload field must be set, matching result_type.")
        if self.result_type == ProjectAIResultType.GENERAL_GUIDANCE and not self.ephemeral:
            raise ValueError("GENERAL_GUIDANCE results must be marked ephemeral.")
        if self.result_type != ProjectAIResultType.GENERAL_GUIDANCE and self.ephemeral:
            raise ValueError("Only GENERAL_GUIDANCE results may be marked ephemeral.")
        return self
