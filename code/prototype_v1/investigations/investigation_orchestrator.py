from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .analysis_attempt_store import (
    InvestigationAnalysisAttemptConflict,
    InvestigationAnalysisAttemptOwnershipError,
    InvestigationAnalysisAttemptStore,
)
from .analysis_contract_errors import (
    InvestigationAnalysisProviderError,
    InvestigationAnalysisRequestBuildError,
    InvestigationAnalysisResponseValidationError,
)
from .analysis_request_builder import build_deterministic_analysis_request_package
from .analysis_response_validator import validate_structured_analysis_response
from .evidence_store import InvestigationEvidenceStore
from .frozen_manifest_service import (
    InvestigationFrozenManifestSelectionError,
    build_frozen_evidence_manifest_for_session,
)
from .interaction_state_machine import InvestigationInteractionContext, InvestigationInteractionState
from .models import InvestigationAnalysisRequestPackage, InvestigationAnalysisResponse, InvestigationSession
from .models import InvestigationSessionStatus
from .openai_analysis_provider import InvestigationAnalysisProvider
from .session_lifecycle import (
    InvestigationSessionLifecycleError,
    apply_analysis_started_transition,
    apply_complete_transition,
    apply_finalize_transition,
)
from .session_store import InvestigationSessionStore


class InvestigationOrchestrationStage(str, Enum):
    VALIDATING = "validating"
    FREEZING_EVIDENCE = "freezing_evidence"
    ESTABLISHING_ATTEMPT = "establishing_attempt"
    BUILDING_REQUEST = "building_request"
    ANALYZING = "analyzing"
    VALIDATING_RESPONSE = "validating_response"
    PERSISTING_RESULT = "persisting_result"
    COMPLETING = "completing"
    COMPLETED = "completed"
    FAILED = "failed"


class InvestigationOrchestrationProgressEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    session_id: str
    analysis_attempt_id: str | None = None
    stage: InvestigationOrchestrationStage
    status: str = Field(..., min_length=1, max_length=160)
    sequence_number: int = Field(..., ge=1)
    terminal: bool
    safe_failure_category: str | None = Field(default=None, min_length=1, max_length=64)


class InvestigationOrchestrationOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    analysis_attempt_id: str | None = None
    result_id: str | None = None
    response: InvestigationAnalysisResponse | None = None
    persistence_deferred: bool
    provider_invoked: bool
    completed: bool
    progress_events: list[InvestigationOrchestrationProgressEvent]


class InvestigationOrchestrationError(RuntimeError):
    pass


class InvestigationOrchestrationInvalidInteractionError(InvestigationOrchestrationError):
    pass


class InvestigationOrchestrationRevisionConflictError(InvestigationOrchestrationError):
    pass


class InvestigationOrchestrationManifestError(InvestigationOrchestrationError):
    pass


class InvestigationOrchestrationAttemptConflictError(InvestigationOrchestrationError):
    pass


class InvestigationOrchestrationRequestBuildError(InvestigationOrchestrationError):
    pass


class InvestigationOrchestrationProviderError(InvestigationOrchestrationError):
    pass


class InvestigationOrchestrationResponseValidationError(InvestigationOrchestrationError):
    pass


class InvestigationOrchestrationResultPersistenceError(InvestigationOrchestrationError):
    pass


class InvestigationOrchestrationLifecycleError(InvestigationOrchestrationError):
    pass


class InvestigationOrchestrationUnexpectedError(InvestigationOrchestrationError):
    pass


class InvestigationOrchestrationStoredResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: str
    response: InvestigationAnalysisResponse


class InvestigationResultPersistenceAdapter(Protocol):
    def load_completed_result(self, *, session_id: str) -> InvestigationOrchestrationStoredResult | None:
        ...

    def persist_result(
        self,
        *,
        session: InvestigationSession,
        request_package: InvestigationAnalysisRequestPackage,
        response: InvestigationAnalysisResponse,
    ) -> str:
        ...


ProgressSink = Callable[[InvestigationOrchestrationProgressEvent], None]


class InvestigationOrchestrator:
    def __init__(
        self,
        *,
        session_store: InvestigationSessionStore,
        evidence_store: InvestigationEvidenceStore,
        attempt_store: InvestigationAnalysisAttemptStore,
        analysis_provider: InvestigationAnalysisProvider,
        result_persistence: InvestigationResultPersistenceAdapter | None = None,
        progress_sink: ProgressSink | None = None,
        request_builder=build_deterministic_analysis_request_package,
        manifest_builder=build_frozen_evidence_manifest_for_session,
        response_validator=validate_structured_analysis_response,
    ):
        self._session_store = session_store
        self._evidence_store = evidence_store
        self._attempt_store = attempt_store
        self._analysis_provider = analysis_provider
        self._result_persistence = result_persistence
        self._progress_sink = progress_sink
        self._request_builder = request_builder
        self._manifest_builder = manifest_builder
        self._response_validator = response_validator

    def run_confirmed_investigation(
        self,
        *,
        session_id: str,
        expected_revision: int,
        interaction_context: InvestigationInteractionContext,
    ) -> InvestigationOrchestrationOutcome:
        progress: list[InvestigationOrchestrationProgressEvent] = []
        sequence = 0
        analysis_attempt_id: str | None = None
        provider_invoked = False

        def emit(stage: InvestigationOrchestrationStage, status: str, *, terminal: bool = False, failure: str | None = None) -> None:
            nonlocal sequence
            sequence += 1
            event = InvestigationOrchestrationProgressEvent(
                session_id=session_id,
                analysis_attempt_id=analysis_attempt_id,
                stage=stage,
                status=status,
                sequence_number=sequence,
                terminal=terminal,
                safe_failure_category=failure,
            )
            progress.append(event)
            if self._progress_sink is not None:
                try:
                    self._progress_sink(event)
                except Exception:
                    # Progress sink failures are ignored to avoid corrupting orchestration state.
                    pass

        try:
            emit(InvestigationOrchestrationStage.VALIDATING, "Preparing investigation.")
            self._validate_interaction_preconditions(session_id=session_id, interaction_context=interaction_context)

            session = self._session_store.load_session(session_id)
            if session.session_id != session_id:
                raise InvestigationOrchestrationInvalidInteractionError("Loaded session identity does not match request.")

            if session.status == InvestigationSessionStatus.COMPLETED:
                existing = self._load_existing_completed_result(session_id=session_id)
                if existing is None:
                    raise InvestigationOrchestrationResultPersistenceError(
                        "Session is completed but no compatible persisted structured result is available."
                    )
                emit(InvestigationOrchestrationStage.COMPLETED, "Investigation complete.", terminal=True)
                return InvestigationOrchestrationOutcome(
                    session_id=session_id,
                    analysis_attempt_id=session.latest_analysis_attempt_id,
                    result_id=existing.result_id,
                    response=existing.response,
                    persistence_deferred=False,
                    provider_invoked=False,
                    completed=True,
                    progress_events=progress,
                )

            if expected_revision != session.revision:
                raise InvestigationOrchestrationRevisionConflictError(
                    "expected_revision does not match current session revision."
                )

            provisional_attempt_id = str(uuid4())

            emit(InvestigationOrchestrationStage.FREEZING_EVIDENCE, "Freezing selected evidence.")
            try:
                manifest = self._manifest_builder(
                    evidence_store=self._evidence_store,
                    session_id=session_id,
                    analysis_attempt_id=provisional_attempt_id,
                )
            except InvestigationFrozenManifestSelectionError as exc:
                raise InvestigationOrchestrationManifestError("Unable to freeze evidence for analysis.") from exc

            emit(InvestigationOrchestrationStage.ESTABLISHING_ATTEMPT, "Establishing analysis attempt ownership.")
            prepared_attempt = self._attempt_store.build_prepared_attempt(
                session_id=session_id,
                analysis_attempt_id=provisional_attempt_id,
                attempt_number=1,
                frozen_manifest_hash=manifest.manifest_hash,
                context_snapshot_hash=_stable_hash(f"context_snapshot|{session_id}|{manifest.manifest_hash}"),
                request_fingerprint=_stable_hash(
                    f"request|{session_id}|{manifest.manifest_hash}|{interaction_context.normalized_explanation_text or ''}"
                ),
            ).model_copy(update={"frozen_manifest_id": manifest.manifest_id})

            try:
                ownership = self._attempt_store.establish_attempt_ownership(
                    session_id=session_id,
                    proposed_attempt=prepared_attempt,
                    expected_revision=expected_revision,
                )
            except (InvestigationAnalysisAttemptConflict, InvestigationAnalysisAttemptOwnershipError) as exc:
                raise InvestigationOrchestrationAttemptConflictError("Unable to establish analysis attempt ownership.") from exc

            analysis_attempt_id = ownership.attempt.analysis_attempt_id

            emit(InvestigationOrchestrationStage.BUILDING_REQUEST, "Preparing AI analysis.")
            try:
                request_package = self._request_builder(
                    session=ownership.session,
                    analysis_attempt=ownership.attempt,
                    frozen_manifest=manifest,
                    evidence_store=self._evidence_store,
                    normalized_explanation_text=interaction_context.normalized_explanation_text,
                )
            except InvestigationAnalysisRequestBuildError as exc:
                raise InvestigationOrchestrationRequestBuildError("Failed to build deterministic analysis request.") from exc

            emit(InvestigationOrchestrationStage.ANALYZING, "AI is analyzing the investigation.")
            finalizing_session = self._apply_session_transition(
                session_id=session_id,
                expected_revision=ownership.session.revision,
                transition=lambda current: apply_finalize_transition(current, expected_revision=ownership.session.revision),
            )
            analyzing_session = self._apply_session_transition(
                session_id=session_id,
                expected_revision=finalizing_session.revision,
                transition=lambda current: apply_analysis_started_transition(current, expected_revision=finalizing_session.revision),
            )

            provider_invoked = True
            try:
                provider_response = self._analysis_provider.analyze(request_package)
            except InvestigationAnalysisProviderError as exc:
                raise InvestigationOrchestrationProviderError("Provider analysis failed.") from exc
            except Exception as exc:
                raise InvestigationOrchestrationProviderError("Provider analysis failed.") from exc

            emit(InvestigationOrchestrationStage.VALIDATING_RESPONSE, "Validating the response.")
            try:
                validated_response = self._response_validator(provider_response)
            except InvestigationAnalysisResponseValidationError as exc:
                raise InvestigationOrchestrationResponseValidationError("Provider response validation failed.") from exc

            emit(InvestigationOrchestrationStage.PERSISTING_RESULT, "Persisting investigation result.")
            result_id: str | None = None
            persistence_deferred = self._result_persistence is None
            if self._result_persistence is not None:
                try:
                    result_id = self._result_persistence.persist_result(
                        session=analyzing_session,
                        request_package=request_package,
                        response=validated_response,
                    )
                except Exception as exc:
                    raise InvestigationOrchestrationResultPersistenceError("Result persistence failed.") from exc

            completed = False
            if result_id is not None:
                emit(InvestigationOrchestrationStage.COMPLETING, "Completing investigation lifecycle.")
                self._apply_session_transition(
                    session_id=session_id,
                    expected_revision=analyzing_session.revision,
                    transition=lambda current: apply_complete_transition(
                        current,
                        expected_revision=analyzing_session.revision,
                        completed_result_id=result_id,
                    ),
                )
                completed = True

            emit(
                InvestigationOrchestrationStage.COMPLETED,
                "Investigation complete." if completed else "Investigation response ready; result persistence deferred.",
                terminal=True,
            )
            return InvestigationOrchestrationOutcome(
                session_id=session_id,
                analysis_attempt_id=analysis_attempt_id,
                result_id=result_id,
                response=validated_response,
                persistence_deferred=persistence_deferred,
                provider_invoked=provider_invoked,
                completed=completed,
                progress_events=progress,
            )

        except InvestigationOrchestrationError as exc:
            emit(
                InvestigationOrchestrationStage.FAILED,
                "Investigation failed before completion.",
                terminal=True,
                failure=_safe_failure_category(exc),
            )
            raise
        except Exception as exc:
            emit(
                InvestigationOrchestrationStage.FAILED,
                "Investigation failed before completion.",
                terminal=True,
                failure="unexpected_orchestration_failure",
            )
            raise InvestigationOrchestrationUnexpectedError("Unexpected orchestration failure.") from exc

    def _apply_session_transition(
        self,
        *,
        session_id: str,
        expected_revision: int,
        transition,
    ) -> InvestigationSession:
        def _mutator(current: InvestigationSession) -> tuple[InvestigationSession, bool]:
            try:
                updated, changed = transition(current)
            except InvestigationSessionLifecycleError as exc:
                raise InvestigationOrchestrationLifecycleError(exc.message) from exc
            return updated, changed

        return self._session_store.mutate_session(session_id, _mutator)

    def _load_existing_completed_result(self, *, session_id: str) -> InvestigationOrchestrationStoredResult | None:
        if self._result_persistence is None:
            return None
        return self._result_persistence.load_completed_result(session_id=session_id)

    @staticmethod
    def _validate_interaction_preconditions(
        *,
        session_id: str,
        interaction_context: InvestigationInteractionContext,
    ) -> None:
        if interaction_context.session_id != session_id:
            raise InvestigationOrchestrationInvalidInteractionError("Interaction session_id mismatch.")
        if interaction_context.interaction_state != InvestigationInteractionState.READY_FOR_CONFIRMATION:
            raise InvestigationOrchestrationInvalidInteractionError(
                "Interaction state must be ready_for_confirmation."
            )
        if not interaction_context.analysis_confirmed:
            raise InvestigationOrchestrationInvalidInteractionError("Interaction must be analysis-confirmed.")
        if len(interaction_context.selected_capture_evidence_ids) <= 0:
            raise InvestigationOrchestrationInvalidInteractionError("At least one selected capture is required.")
        explanation = str(interaction_context.normalized_explanation_text or "").strip()
        if not explanation:
            raise InvestigationOrchestrationInvalidInteractionError("A non-empty explanation is required.")


def _safe_failure_category(exc: InvestigationOrchestrationError) -> str:
    if isinstance(exc, InvestigationOrchestrationInvalidInteractionError):
        return "invalid_interaction_state"
    if isinstance(exc, InvestigationOrchestrationRevisionConflictError):
        return "revision_conflict"
    if isinstance(exc, InvestigationOrchestrationManifestError):
        return "manifest_failure"
    if isinstance(exc, InvestigationOrchestrationAttemptConflictError):
        return "attempt_ownership_conflict"
    if isinstance(exc, InvestigationOrchestrationRequestBuildError):
        return "request_construction_failure"
    if isinstance(exc, InvestigationOrchestrationProviderError):
        return "provider_failure"
    if isinstance(exc, InvestigationOrchestrationResponseValidationError):
        return "response_validation_failure"
    if isinstance(exc, InvestigationOrchestrationResultPersistenceError):
        return "result_persistence_failure"
    if isinstance(exc, InvestigationOrchestrationLifecycleError):
        return "lifecycle_transition_failure"
    return "unexpected_orchestration_failure"


def _stable_hash(value: str) -> str:
    encoded = value.encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
