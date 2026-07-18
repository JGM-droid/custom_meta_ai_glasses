from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .evidence_store import InvestigationEvidenceStore
from .models import InvestigationEvidenceType, InvestigationSession, InvestigationSessionStatus
from .session_lifecycle import (
    InvestigationSessionLifecycleError,
    apply_analysis_started_transition,
    apply_cancel_transition,
    apply_complete_transition,
    apply_fail_transition,
    apply_finalize_transition,
    apply_resume_transition,
    apply_start_transition,
)

INTERACTION_STATE_SCHEMA_VERSION = "1.0"
_INTERACTION_MAX_CAPTURES = 3
_INTERACTION_MAX_EXPLANATION_TEXT = 1000


class InvestigationInteractionState(str, Enum):
    IDLE = "idle"
    WAITING_FOR_CAPTURE = "waiting_for_capture"
    WAITING_FOR_MORE_OR_DONE = "waiting_for_more_or_done"
    WAITING_FOR_EXPLANATION = "waiting_for_explanation"
    READY_FOR_CONFIRMATION = "ready_for_confirmation"
    ANALYZING = "analyzing"
    RESULT_READY = "result_ready"
    CANCELLED = "cancelled"
    FAILED = "failed"


class InvestigationInteractionEvent(str, Enum):
    START_INVESTIGATION = "start_investigation"
    CAPTURE_REQUESTED = "capture_requested"
    CAPTURE_COMPLETED = "capture_completed"
    CAPTURE_FAILED = "capture_failed"
    DONE_CAPTURING = "done_capturing"
    EXPLANATION_STARTED = "explanation_started"
    EXPLANATION_COMPLETED = "explanation_completed"
    CONFIRM_ANALYSIS = "confirm_analysis"
    CANCEL = "cancel"
    RETAKE_LAST = "retake_last"
    REMOVE_LAST_CAPTURE = "remove_last_capture"
    START_OVER = "start_over"
    STATUS_REQUESTED = "status_requested"
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_SUCCEEDED = "analysis_succeeded"
    ANALYSIS_FAILED = "analysis_failed"


class InvestigationInteractionError(RuntimeError):
    pass


class InvestigationInteractionInvalidTransition(InvestigationInteractionError):
    pass


class InvestigationInteractionValidationError(InvestigationInteractionError):
    pass


class InvestigationInteractionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str
    session_id: str
    interaction_state: InvestigationInteractionState
    selected_capture_evidence_ids: list[str] = Field(default_factory=list, max_length=_INTERACTION_MAX_CAPTURES)
    normalized_explanation_text: str | None = Field(default=None, min_length=1, max_length=_INTERACTION_MAX_EXPLANATION_TEXT)
    analysis_confirmed: bool = False

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != INTERACTION_STATE_SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version. Use {INTERACTION_STATE_SCHEMA_VERSION}.")
        return value

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

    @field_validator("selected_capture_evidence_ids")
    @classmethod
    def _validate_capture_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item).strip()
            if not text:
                raise ValueError("selected_capture_evidence_ids must contain non-empty UUIDs.")
            try:
                parsed = str(UUID(text))
            except ValueError as exc:
                raise ValueError("selected_capture_evidence_ids must contain valid UUIDs.") from exc
            if parsed in seen:
                raise ValueError("selected_capture_evidence_ids must be unique.")
            seen.add(parsed)
            normalized.append(parsed)
        return normalized

    @field_validator("normalized_explanation_text")
    @classmethod
    def _validate_explanation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("normalized_explanation_text must be non-empty when provided.")
        return text


class InvestigationInteractionTransitionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    previous_state: InvestigationInteractionState
    new_state: InvestigationInteractionState
    accepted_event: InvestigationInteractionEvent
    user_confirmation: str = Field(..., min_length=1, max_length=240)
    capture_count: int = Field(..., ge=0, le=_INTERACTION_MAX_CAPTURES)
    explanation_present: bool
    analysis_may_begin: bool
    next_allowed_actions: list[InvestigationInteractionEvent] = Field(default_factory=list)


class InvestigationInteractionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interaction: InvestigationInteractionContext
    session: InvestigationSession
    lifecycle_changed: bool
    transition: InvestigationInteractionTransitionResult


def new_interaction_context(*, session_id: str) -> InvestigationInteractionContext:
    return InvestigationInteractionContext(
        schema_version=INTERACTION_STATE_SCHEMA_VERSION,
        session_id=session_id,
        interaction_state=InvestigationInteractionState.IDLE,
        selected_capture_evidence_ids=[],
        normalized_explanation_text=None,
        analysis_confirmed=False,
    )


def map_session_status_to_interaction_terminal_state(
    session_status: InvestigationSessionStatus,
) -> InvestigationInteractionState | None:
    if session_status == InvestigationSessionStatus.ANALYZING:
        return InvestigationInteractionState.ANALYZING
    if session_status == InvestigationSessionStatus.COMPLETED:
        return InvestigationInteractionState.RESULT_READY
    if session_status == InvestigationSessionStatus.CANCELLED:
        return InvestigationInteractionState.CANCELLED
    if session_status == InvestigationSessionStatus.FAILED:
        return InvestigationInteractionState.FAILED
    return None


class InvestigationInteractionStateMachine:
    def __init__(self, *, evidence_store: InvestigationEvidenceStore | None = None):
        self._evidence_store = evidence_store

    def apply(
        self,
        *,
        session: InvestigationSession,
        interaction: InvestigationInteractionContext,
        event: InvestigationInteractionEvent,
        expected_revision: int | None = None,
        evidence_id: str | None = None,
        explanation_text: str | None = None,
        completed_result_id: str | None = None,
        error_category: str | None = None,
        safe_error_message: str | None = None,
        retryable: bool = True,
    ) -> InvestigationInteractionOutcome:
        if interaction.session_id != session.session_id:
            raise InvestigationInteractionValidationError("interaction.session_id must match session.session_id.")

        previous_state = interaction.interaction_state
        session_out = session
        lifecycle_changed = False
        current = interaction

        if event == InvestigationInteractionEvent.STATUS_REQUESTED:
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=False,
                event=event,
                message=self._status_message(current),
            )

        if event == InvestigationInteractionEvent.START_INVESTIGATION:
            session_out, lifecycle_changed = self._apply_lifecycle(
                apply_start_transition,
                session=session_out,
                expected_revision=expected_revision,
            )
            current = current.model_copy(
                update={
                    "interaction_state": InvestigationInteractionState.WAITING_FOR_CAPTURE,
                    "selected_capture_evidence_ids": [],
                    "normalized_explanation_text": None,
                    "analysis_confirmed": False,
                }
            )
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=lifecycle_changed,
                event=event,
                message="Investigation started. Show me the first view and capture when ready.",
            )

        if event == InvestigationInteractionEvent.CAPTURE_REQUESTED:
            self._require_state(
                current,
                {
                    InvestigationInteractionState.WAITING_FOR_CAPTURE,
                    InvestigationInteractionState.WAITING_FOR_MORE_OR_DONE,
                },
                "Capture cannot be requested in the current interaction state.",
            )
            if self._capture_count(current) >= _INTERACTION_MAX_CAPTURES:
                raise InvestigationInteractionInvalidTransition("Maximum of three captures reached for this interaction.")
            current = current.model_copy(update={"interaction_state": InvestigationInteractionState.WAITING_FOR_CAPTURE})
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=False,
                event=event,
                message="Capture requested. Capture when ready.",
            )

        if event == InvestigationInteractionEvent.CAPTURE_COMPLETED:
            self._require_state(
                current,
                {
                    InvestigationInteractionState.WAITING_FOR_CAPTURE,
                    InvestigationInteractionState.WAITING_FOR_MORE_OR_DONE,
                },
                "Capture cannot complete before investigation start.",
            )
            if self._capture_count(current) >= _INTERACTION_MAX_CAPTURES:
                raise InvestigationInteractionInvalidTransition("A fourth capture is not allowed in this demo flow.")

            normalized_evidence_id = self._normalize_uuid(evidence_id, "evidence_id")
            self._validate_capture_evidence(session_id=session.session_id, evidence_id=normalized_evidence_id)

            if normalized_evidence_id in current.selected_capture_evidence_ids:
                raise InvestigationInteractionInvalidTransition("This capture is already part of the interaction selection.")

            updated_ids = [*current.selected_capture_evidence_ids, normalized_evidence_id]
            count = len(updated_ids)
            message = f"Image {count} captured. Capture another view or finish capturing."
            if count == _INTERACTION_MAX_CAPTURES:
                message = "Image 3 captured. Maximum captures reached. Finish capturing."

            current = current.model_copy(
                update={
                    "interaction_state": InvestigationInteractionState.WAITING_FOR_MORE_OR_DONE,
                    "selected_capture_evidence_ids": updated_ids,
                    "normalized_explanation_text": None,
                    "analysis_confirmed": False,
                }
            )
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=False,
                event=event,
                message=message,
            )

        if event == InvestigationInteractionEvent.CAPTURE_FAILED:
            self._require_state(
                current,
                {
                    InvestigationInteractionState.WAITING_FOR_CAPTURE,
                    InvestigationInteractionState.WAITING_FOR_MORE_OR_DONE,
                },
                "Capture failure cannot be recorded in the current interaction state.",
            )
            current = current.model_copy(update={"interaction_state": InvestigationInteractionState.WAITING_FOR_CAPTURE})
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=False,
                event=event,
                message="Capture failed. Try capturing again when ready.",
            )

        if event == InvestigationInteractionEvent.DONE_CAPTURING:
            self._require_state(
                current,
                {
                    InvestigationInteractionState.WAITING_FOR_CAPTURE,
                    InvestigationInteractionState.WAITING_FOR_MORE_OR_DONE,
                },
                "Capture completion cannot be requested in the current interaction state.",
            )
            if self._capture_count(current) <= 0:
                raise InvestigationInteractionInvalidTransition("At least one image is required before finishing capture.")
            current = current.model_copy(update={"interaction_state": InvestigationInteractionState.WAITING_FOR_EXPLANATION})
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=False,
                event=event,
                message="Briefly explain what you are trying to figure out.",
            )

        if event == InvestigationInteractionEvent.EXPLANATION_STARTED:
            self._require_state(
                current,
                {InvestigationInteractionState.WAITING_FOR_EXPLANATION},
                "Explanation can only start after capturing is complete.",
            )
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=False,
                event=event,
                message="Explanation started. Share one concise problem description.",
            )

        if event == InvestigationInteractionEvent.EXPLANATION_COMPLETED:
            self._require_state(
                current,
                {InvestigationInteractionState.WAITING_FOR_EXPLANATION},
                "Explanation can only be completed after finishing captures.",
            )
            normalized_explanation = self._normalize_explanation(explanation_text)
            current = current.model_copy(
                update={
                    "interaction_state": InvestigationInteractionState.READY_FOR_CONFIRMATION,
                    "normalized_explanation_text": normalized_explanation,
                    "analysis_confirmed": False,
                }
            )
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=False,
                event=event,
                message=self._ready_summary_message(current),
            )

        if event == InvestigationInteractionEvent.CONFIRM_ANALYSIS:
            self._require_state(
                current,
                {InvestigationInteractionState.READY_FOR_CONFIRMATION},
                "Analysis confirmation is only valid in ready_for_confirmation.",
            )
            if self._capture_count(current) <= 0:
                raise InvestigationInteractionInvalidTransition("Cannot confirm analysis without at least one capture.")
            if not self._explanation_present(current):
                raise InvestigationInteractionInvalidTransition("Cannot confirm analysis without an explanation.")

            session_out, lifecycle_changed = self._apply_lifecycle(
                apply_finalize_transition,
                session=session_out,
                expected_revision=expected_revision,
            )
            current = current.model_copy(update={"analysis_confirmed": True})
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=lifecycle_changed,
                event=event,
                message="Analysis confirmed. Ready to begin analysis.",
            )

        if event == InvestigationInteractionEvent.RETAKE_LAST:
            self._require_state(
                current,
                {
                    InvestigationInteractionState.WAITING_FOR_CAPTURE,
                    InvestigationInteractionState.WAITING_FOR_MORE_OR_DONE,
                    InvestigationInteractionState.WAITING_FOR_EXPLANATION,
                    InvestigationInteractionState.READY_FOR_CONFIRMATION,
                },
                "Retake is not allowed in the current interaction state.",
            )
            if self._capture_count(current) <= 0:
                raise InvestigationInteractionInvalidTransition("Cannot retake when no capture exists.")
            updated_ids = current.selected_capture_evidence_ids[:-1]
            current = current.model_copy(
                update={
                    "interaction_state": InvestigationInteractionState.WAITING_FOR_CAPTURE,
                    "selected_capture_evidence_ids": updated_ids,
                    "normalized_explanation_text": None,
                    "analysis_confirmed": False,
                }
            )
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=False,
                event=event,
                message="Last capture removed for retake. Capture the replacement view.",
            )

        if event == InvestigationInteractionEvent.REMOVE_LAST_CAPTURE:
            self._require_state(
                current,
                {
                    InvestigationInteractionState.WAITING_FOR_CAPTURE,
                    InvestigationInteractionState.WAITING_FOR_MORE_OR_DONE,
                    InvestigationInteractionState.WAITING_FOR_EXPLANATION,
                    InvestigationInteractionState.READY_FOR_CONFIRMATION,
                },
                "Capture removal is not allowed in the current interaction state.",
            )
            if self._capture_count(current) <= 0:
                raise InvestigationInteractionInvalidTransition("Cannot remove a capture when none exist.")
            updated_ids = current.selected_capture_evidence_ids[:-1]
            next_state = (
                InvestigationInteractionState.WAITING_FOR_CAPTURE
                if not updated_ids
                else InvestigationInteractionState.WAITING_FOR_MORE_OR_DONE
            )
            current = current.model_copy(
                update={
                    "interaction_state": next_state,
                    "selected_capture_evidence_ids": updated_ids,
                    "normalized_explanation_text": None,
                    "analysis_confirmed": False,
                }
            )
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=False,
                event=event,
                message="Last capture removed. Continue capturing or finish when ready.",
            )

        if event == InvestigationInteractionEvent.START_OVER:
            session_out, lifecycle_changed = self._restore_collecting_session(
                session=session_out,
                expected_revision=expected_revision,
            )
            current = current.model_copy(
                update={
                    "interaction_state": InvestigationInteractionState.WAITING_FOR_CAPTURE,
                    "selected_capture_evidence_ids": [],
                    "normalized_explanation_text": None,
                    "analysis_confirmed": False,
                }
            )
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=lifecycle_changed,
                event=event,
                message="Interaction reset. Prior evidence is preserved; capture again when ready.",
            )

        if event == InvestigationInteractionEvent.CANCEL:
            session_out, lifecycle_changed = self._apply_lifecycle(
                apply_cancel_transition,
                session=session_out,
                expected_revision=expected_revision,
            )
            current = current.model_copy(
                update={
                    "interaction_state": InvestigationInteractionState.CANCELLED,
                    "analysis_confirmed": False,
                }
            )
            message = "Investigation cancelled."
            if not lifecycle_changed:
                message = "Investigation already cancelled."
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=lifecycle_changed,
                event=event,
                message=message,
            )

        if event == InvestigationInteractionEvent.ANALYSIS_STARTED:
            if not current.analysis_confirmed:
                raise InvestigationInteractionInvalidTransition("Analysis cannot start before confirmation.")
            self._require_state(
                current,
                {InvestigationInteractionState.READY_FOR_CONFIRMATION},
                "Analysis can only start from ready_for_confirmation.",
            )
            session_out, lifecycle_changed = self._apply_lifecycle(
                apply_analysis_started_transition,
                session=session_out,
                expected_revision=expected_revision,
            )
            current = current.model_copy(update={"interaction_state": InvestigationInteractionState.ANALYZING})
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=lifecycle_changed,
                event=event,
                message="Analysis started.",
            )

        if event == InvestigationInteractionEvent.ANALYSIS_SUCCEEDED:
            self._require_state(
                current,
                {InvestigationInteractionState.ANALYZING},
                "analysis_succeeded is only valid while analyzing.",
            )
            normalized_result_id = self._normalize_uuid(completed_result_id, "completed_result_id")
            session_out, lifecycle_changed = self._apply_lifecycle(
                apply_complete_transition,
                session=session_out,
                expected_revision=expected_revision,
                completed_result_id=normalized_result_id,
            )
            current = current.model_copy(
                update={
                    "interaction_state": InvestigationInteractionState.RESULT_READY,
                    "analysis_confirmed": False,
                }
            )
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=lifecycle_changed,
                event=event,
                message="Analysis complete. Result is ready.",
            )

        if event == InvestigationInteractionEvent.ANALYSIS_FAILED:
            self._require_state(
                current,
                {InvestigationInteractionState.ANALYZING},
                "analysis_failed is only valid while analyzing.",
            )
            category = str(error_category or "analysis_failed").strip()
            safe_message = str(safe_error_message or "Analysis failed before a valid result was produced.").strip()
            if not category or not safe_message:
                raise InvestigationInteractionValidationError("analysis_failed requires non-empty error_category and safe_error_message.")

            session_out, lifecycle_changed = self._apply_lifecycle(
                apply_fail_transition,
                session=session_out,
                expected_revision=expected_revision,
                error_category=category,
                safe_message=safe_message,
                retryable=retryable,
            )
            current = current.model_copy(
                update={
                    "interaction_state": InvestigationInteractionState.FAILED,
                    "analysis_confirmed": False,
                }
            )
            return self._outcome(
                previous_state=previous_state,
                current=current,
                session=session_out,
                lifecycle_changed=lifecycle_changed,
                event=event,
                message="Analysis failed. You can retry after reviewing the session state.",
            )

        raise InvestigationInteractionValidationError("Unsupported interaction event.")

    def _validate_capture_evidence(self, *, session_id: str, evidence_id: str) -> None:
        if self._evidence_store is None:
            raise InvestigationInteractionValidationError("Evidence store is required for capture_completed validation.")
        evidence = self._evidence_store.load_evidence_for_analysis(session_id=session_id, evidence_id=evidence_id)
        if evidence.session_id != session_id:
            raise InvestigationInteractionValidationError("Capture evidence does not belong to the interaction session.")
        if evidence.evidence_type != InvestigationEvidenceType.IMAGE:
            raise InvestigationInteractionValidationError("Capture evidence must be image type.")

    @staticmethod
    def _normalize_uuid(value: str | None, field_name: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise InvestigationInteractionValidationError(f"{field_name} is required.")
        try:
            return str(UUID(text))
        except ValueError as exc:
            raise InvestigationInteractionValidationError(f"{field_name} must be a valid UUID.") from exc

    @staticmethod
    def _normalize_explanation(value: str | None) -> str:
        text = str(value or "").strip()
        if not text:
            raise InvestigationInteractionValidationError("Explanation must be non-empty.")
        if len(text) > _INTERACTION_MAX_EXPLANATION_TEXT:
            raise InvestigationInteractionValidationError("Explanation exceeds maximum length.")
        return text

    @staticmethod
    def _capture_count(interaction: InvestigationInteractionContext) -> int:
        return len(interaction.selected_capture_evidence_ids)

    @staticmethod
    def _explanation_present(interaction: InvestigationInteractionContext) -> bool:
        return bool((interaction.normalized_explanation_text or "").strip())

    @staticmethod
    def _require_state(
        interaction: InvestigationInteractionContext,
        allowed: set[InvestigationInteractionState],
        message: str,
    ) -> None:
        if interaction.interaction_state not in allowed:
            raise InvestigationInteractionInvalidTransition(message)

    def _restore_collecting_session(
        self,
        *,
        session: InvestigationSession,
        expected_revision: int | None,
    ) -> tuple[InvestigationSession, bool]:
        if session.status == InvestigationSessionStatus.CREATED:
            return self._apply_lifecycle(apply_start_transition, session=session, expected_revision=expected_revision)
        if session.status == InvestigationSessionStatus.PAUSED:
            return self._apply_lifecycle(apply_resume_transition, session=session, expected_revision=expected_revision)
        if session.status == InvestigationSessionStatus.COLLECTING:
            return session, False
        raise InvestigationInteractionInvalidTransition("start_over is not valid for the current durable session status.")

    def _apply_lifecycle(self, fn, *, session: InvestigationSession, expected_revision: int | None, **kwargs):
        try:
            return fn(session, expected_revision=expected_revision, **kwargs)
        except InvestigationSessionLifecycleError as exc:
            raise InvestigationInteractionInvalidTransition(exc.message) from exc

    def _status_message(self, interaction: InvestigationInteractionContext) -> str:
        return self._ready_summary_message(interaction)

    def _ready_summary_message(self, interaction: InvestigationInteractionContext) -> str:
        capture_count = self._capture_count(interaction)
        explanation_present = self._explanation_present(interaction)
        explanation_text = "present" if explanation_present else "missing"
        return (
            f"Ready summary: {capture_count} image(s), explanation {explanation_text}. "
            "You may analyze, retake, remove, cancel, or start over."
        )

    def _outcome(
        self,
        *,
        previous_state: InvestigationInteractionState,
        current: InvestigationInteractionContext,
        session: InvestigationSession,
        lifecycle_changed: bool,
        event: InvestigationInteractionEvent,
        message: str,
    ) -> InvestigationInteractionOutcome:
        terminal = map_session_status_to_interaction_terminal_state(session.status)
        effective_state = current.interaction_state
        if terminal is not None:
            effective_state = terminal
            current = current.model_copy(update={"interaction_state": effective_state})

        transition = InvestigationInteractionTransitionResult(
            previous_state=previous_state,
            new_state=effective_state,
            accepted_event=event,
            user_confirmation=message,
            capture_count=self._capture_count(current),
            explanation_present=self._explanation_present(current),
            analysis_may_begin=(
                effective_state == InvestigationInteractionState.READY_FOR_CONFIRMATION and current.analysis_confirmed
            ),
            next_allowed_actions=self._next_allowed_actions(current, session.status),
        )
        return InvestigationInteractionOutcome(
            interaction=current,
            session=session,
            lifecycle_changed=lifecycle_changed,
            transition=transition,
        )

    def _next_allowed_actions(
        self,
        interaction: InvestigationInteractionContext,
        session_status: InvestigationSessionStatus,
    ) -> list[InvestigationInteractionEvent]:
        if session_status == InvestigationSessionStatus.CANCELLED:
            return [InvestigationInteractionEvent.STATUS_REQUESTED, InvestigationInteractionEvent.CANCEL]
        if session_status == InvestigationSessionStatus.COMPLETED:
            return [InvestigationInteractionEvent.STATUS_REQUESTED]
        if session_status == InvestigationSessionStatus.ANALYZING:
            return [
                InvestigationInteractionEvent.STATUS_REQUESTED,
                InvestigationInteractionEvent.ANALYSIS_SUCCEEDED,
                InvestigationInteractionEvent.ANALYSIS_FAILED,
            ]

        state = interaction.interaction_state
        capture_count = self._capture_count(interaction)

        if state == InvestigationInteractionState.IDLE:
            return [InvestigationInteractionEvent.START_INVESTIGATION, InvestigationInteractionEvent.STATUS_REQUESTED]
        if state == InvestigationInteractionState.WAITING_FOR_CAPTURE:
            actions = [
                InvestigationInteractionEvent.CAPTURE_REQUESTED,
                InvestigationInteractionEvent.CAPTURE_COMPLETED,
                InvestigationInteractionEvent.CAPTURE_FAILED,
                InvestigationInteractionEvent.CANCEL,
                InvestigationInteractionEvent.START_OVER,
                InvestigationInteractionEvent.STATUS_REQUESTED,
            ]
            if capture_count > 0:
                actions.insert(3, InvestigationInteractionEvent.RETAKE_LAST)
            return actions
        if state == InvestigationInteractionState.WAITING_FOR_MORE_OR_DONE:
            actions = [
                InvestigationInteractionEvent.DONE_CAPTURING,
                InvestigationInteractionEvent.REMOVE_LAST_CAPTURE,
                InvestigationInteractionEvent.RETAKE_LAST,
                InvestigationInteractionEvent.CANCEL,
                InvestigationInteractionEvent.START_OVER,
                InvestigationInteractionEvent.STATUS_REQUESTED,
            ]
            if capture_count < _INTERACTION_MAX_CAPTURES:
                actions.insert(0, InvestigationInteractionEvent.CAPTURE_REQUESTED)
                actions.insert(1, InvestigationInteractionEvent.CAPTURE_COMPLETED)
                actions.insert(2, InvestigationInteractionEvent.CAPTURE_FAILED)
            return actions
        if state == InvestigationInteractionState.WAITING_FOR_EXPLANATION:
            return [
                InvestigationInteractionEvent.EXPLANATION_STARTED,
                InvestigationInteractionEvent.EXPLANATION_COMPLETED,
                InvestigationInteractionEvent.REMOVE_LAST_CAPTURE,
                InvestigationInteractionEvent.RETAKE_LAST,
                InvestigationInteractionEvent.CANCEL,
                InvestigationInteractionEvent.START_OVER,
                InvestigationInteractionEvent.STATUS_REQUESTED,
            ]
        if state == InvestigationInteractionState.READY_FOR_CONFIRMATION:
            actions = [
                InvestigationInteractionEvent.CONFIRM_ANALYSIS,
                InvestigationInteractionEvent.REMOVE_LAST_CAPTURE,
                InvestigationInteractionEvent.RETAKE_LAST,
                InvestigationInteractionEvent.CANCEL,
                InvestigationInteractionEvent.START_OVER,
                InvestigationInteractionEvent.STATUS_REQUESTED,
            ]
            if interaction.analysis_confirmed:
                actions.insert(1, InvestigationInteractionEvent.ANALYSIS_STARTED)
            return actions
        if state == InvestigationInteractionState.ANALYZING:
            return [
                InvestigationInteractionEvent.STATUS_REQUESTED,
                InvestigationInteractionEvent.ANALYSIS_SUCCEEDED,
                InvestigationInteractionEvent.ANALYSIS_FAILED,
            ]
        if state == InvestigationInteractionState.RESULT_READY:
            return [InvestigationInteractionEvent.STATUS_REQUESTED]
        if state == InvestigationInteractionState.FAILED:
            return [InvestigationInteractionEvent.STATUS_REQUESTED, InvestigationInteractionEvent.START_OVER]
        if state == InvestigationInteractionState.CANCELLED:
            return [InvestigationInteractionEvent.STATUS_REQUESTED, InvestigationInteractionEvent.CANCEL]
        return [InvestigationInteractionEvent.STATUS_REQUESTED]
