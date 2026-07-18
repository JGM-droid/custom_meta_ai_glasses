from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from investigations.analysis_attempt_store import InvestigationAnalysisAttemptConflict, InvestigationAnalysisAttemptStore
from investigations.analysis_contract_errors import (
    InvestigationAnalysisRequestBuildError,
    InvestigationAnalysisResponseValidationError,
)
from investigations.analysis_request_builder import build_deterministic_analysis_request_package
from investigations.analysis_response_validator import validate_structured_analysis_response
from investigations.evidence_store import InvestigationEvidenceStore
from investigations.frozen_manifest_service import build_frozen_evidence_manifest_for_session
from investigations.investigation_orchestrator import (
    InvestigationOrchestrationAttemptConflictError,
    InvestigationOrchestrationInvalidInteractionError,
    InvestigationOrchestrationOutcome,
    InvestigationOrchestrationProviderError,
    InvestigationOrchestrationRequestBuildError,
    InvestigationOrchestrationResponseValidationError,
    InvestigationOrchestrationResultPersistenceError,
    InvestigationOrchestrationRevisionConflictError,
    InvestigationOrchestrationStage,
    InvestigationOrchestrationStoredResult,
    InvestigationOrchestrator,
)
from investigations.interaction_state_machine import InvestigationInteractionContext, InvestigationInteractionState
from investigations.models import (
    INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
    InvestigationAnalysisRequestPackage,
    InvestigationAnalysisResponse,
    InvestigationEvidenceCreateRequest,
    InvestigationEvidenceType,
    InvestigationSessionStatus,
)
from investigations.session_store import InvestigationSessionStore


class _FakeProvider:
    def __init__(self, *, response: InvestigationAnalysisResponse | None = None, error: Exception | None = None):
        self.calls: list[InvestigationAnalysisRequestPackage] = []
        self.response = response
        self.error = error

    def analyze(self, request_package: InvestigationAnalysisRequestPackage) -> InvestigationAnalysisResponse:
        self.calls.append(request_package)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class _FakeResultPersistence:
    def __init__(
        self,
        *,
        stored: InvestigationOrchestrationStoredResult | None = None,
        persist_error: Exception | None = None,
    ):
        self.stored = stored
        self.persist_error = persist_error
        self.persist_calls = 0

    def load_completed_result(self, *, session_id: str) -> InvestigationOrchestrationStoredResult | None:
        return self.stored

    def persist_result(self, *, session, request_package, response) -> str:
        self.persist_calls += 1
        if self.persist_error is not None:
            raise self.persist_error
        return str(uuid4())


class _OrderRecorder:
    def __init__(self):
        self.steps: list[str] = []


def _response() -> InvestigationAnalysisResponse:
    return InvestigationAnalysisResponse(
        schema_version=INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
        concise_diagnosis="Likely stale dependency lock mismatch.",
        immediate_recommended_action="Regenerate lockfile and run focused tests.",
        supporting_observations=["Capture one shows import error."],
        confidence_or_uncertainty="Likely, verify with one clean run.",
        warning_or_blocker=None,
        follow_up_capture_request=None,
    )


def _create_collecting_session(tmp_path: Path) -> tuple[InvestigationSessionStore, InvestigationEvidenceStore, InvestigationAnalysisAttemptStore, str]:
    root = tmp_path / "investigation_sessions"
    session_store = InvestigationSessionStore(root)
    evidence_store = InvestigationEvidenceStore(session_store)
    attempt_store = InvestigationAnalysisAttemptStore(session_store)

    session = session_store.create_session(client_metadata=None)
    collecting = session.model_copy(
        update={
            "status": InvestigationSessionStatus.COLLECTING,
            "revision": 1,
            "updated_at_utc": datetime.now(timezone.utc),
        }
    )
    session_store.save_session(collecting)
    return session_store, evidence_store, attempt_store, collecting.session_id


def _upload_image(evidence_store: InvestigationEvidenceStore, *, session_id: str, index: int) -> str:
    record, created = evidence_store.upload_evidence(
        session_id=session_id,
        evidence_type=InvestigationEvidenceType.IMAGE,
        raw_bytes=f"img-{index}".encode("utf-8"),
        mime_type="image/png",
        original_filename=f"img_{index}.png",
        request=InvestigationEvidenceCreateRequest(
            source="desktop",
            client_timestamp_utc=datetime.now(timezone.utc),
            normalized_text=None,
            metadata=None,
            filename=f"img_{index}.png",
            mime_type="image/png",
            width=1280,
            height=720,
            duration_seconds=None,
        ),
    )
    assert created is True
    return record.evidence_id


def _interaction_context(
    *,
    session_id: str,
    evidence_ids: list[str],
    confirmed: bool = True,
    explanation: str | None = "Need root cause",
):
    return InvestigationInteractionContext(
        schema_version="1.0",
        session_id=session_id,
        interaction_state=InvestigationInteractionState.READY_FOR_CONFIRMATION,
        selected_capture_evidence_ids=evidence_ids,
        normalized_explanation_text=explanation,
        analysis_confirmed=confirmed,
    )


def _orchestrator(
    *,
    session_store: InvestigationSessionStore,
    evidence_store: InvestigationEvidenceStore,
    attempt_store: InvestigationAnalysisAttemptStore,
    provider: _FakeProvider,
    persistence: _FakeResultPersistence | None = None,
    progress_sink=None,
    request_builder=build_deterministic_analysis_request_package,
    manifest_builder=build_frozen_evidence_manifest_for_session,
    response_validator=validate_structured_analysis_response,
):
    return InvestigationOrchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        analysis_provider=provider,
        result_persistence=persistence,
        progress_sink=progress_sink,
        request_builder=request_builder,
        manifest_builder=manifest_builder,
        response_validator=response_validator,
    )


def test_confirmed_interaction_begins_orchestration(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())
    persistence = _FakeResultPersistence()
    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=persistence,
    )

    outcome = orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )

    assert isinstance(outcome, InvestigationOrchestrationOutcome)
    assert outcome.provider_invoked is True


def test_unconfirmed_interaction_is_rejected_before_durable_or_provider_work(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())
    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
    )

    with pytest.raises(InvestigationOrchestrationInvalidInteractionError):
        orchestrator.run_confirmed_investigation(
            session_id=session_id,
            expected_revision=1,
            interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id], confirmed=False),
        )

    assert len(provider.calls) == 0


def test_zero_captures_is_rejected(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    provider = _FakeProvider(response=_response())
    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
    )

    with pytest.raises(InvestigationOrchestrationInvalidInteractionError):
        orchestrator.run_confirmed_investigation(
            session_id=session_id,
            expected_revision=1,
            interaction_context=_interaction_context(session_id=session_id, evidence_ids=[]),
        )


def test_blank_explanation_is_rejected(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())
    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
    )

    with pytest.raises(InvestigationOrchestrationInvalidInteractionError):
        orchestrator.run_confirmed_investigation(
            session_id=session_id,
            expected_revision=1,
            interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id], explanation=None),
        )


def test_progress_events_occur_in_deterministic_order(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())
    persistence = _FakeResultPersistence()
    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=persistence,
    )

    outcome = orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )

    assert [item.stage for item in outcome.progress_events] == [
        InvestigationOrchestrationStage.VALIDATING,
        InvestigationOrchestrationStage.FREEZING_EVIDENCE,
        InvestigationOrchestrationStage.ESTABLISHING_ATTEMPT,
        InvestigationOrchestrationStage.BUILDING_REQUEST,
        InvestigationOrchestrationStage.ANALYZING,
        InvestigationOrchestrationStage.VALIDATING_RESPONSE,
        InvestigationOrchestrationStage.PERSISTING_RESULT,
        InvestigationOrchestrationStage.COMPLETING,
        InvestigationOrchestrationStage.COMPLETED,
    ]


def test_progress_sequence_numbers_increase_monotonically(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())
    persistence = _FakeResultPersistence()
    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=persistence,
    )

    outcome = orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )
    seq = [event.sequence_number for event in outcome.progress_events]
    assert seq == sorted(seq)
    assert seq[0] == 1


def test_manifest_service_is_invoked_before_attempt_ownership(tmp_path: Path):
    recorder = _OrderRecorder()
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())

    def _manifest_builder(**kwargs):
        recorder.steps.append("manifest")
        return build_frozen_evidence_manifest_for_session(**kwargs)

    original = attempt_store.establish_attempt_ownership

    def _attempt_wrapper(*, session_id, proposed_attempt, expected_revision):
        recorder.steps.append("attempt")
        return original(session_id=session_id, proposed_attempt=proposed_attempt, expected_revision=expected_revision)

    attempt_store.establish_attempt_ownership = _attempt_wrapper  # type: ignore[method-assign]

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=_FakeResultPersistence(),
        manifest_builder=_manifest_builder,
    )

    orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )

    assert recorder.steps.index("manifest") < recorder.steps.index("attempt")


def test_attempt_ownership_occurs_before_request_construction(tmp_path: Path):
    recorder = _OrderRecorder()
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())

    original = attempt_store.establish_attempt_ownership

    def _attempt_wrapper(*, session_id, proposed_attempt, expected_revision):
        recorder.steps.append("attempt")
        return original(session_id=session_id, proposed_attempt=proposed_attempt, expected_revision=expected_revision)

    def _request_builder(**kwargs):
        recorder.steps.append("request")
        return provider.calls[0] if False else __import__("investigations.analysis_request_builder", fromlist=["build_deterministic_analysis_request_package"]).build_deterministic_analysis_request_package(**kwargs)

    attempt_store.establish_attempt_ownership = _attempt_wrapper  # type: ignore[method-assign]

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=_FakeResultPersistence(),
        request_builder=_request_builder,
    )

    orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )

    assert recorder.steps.index("attempt") < recorder.steps.index("request")


def test_request_construction_occurs_before_provider_invocation(tmp_path: Path):
    recorder = _OrderRecorder()
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)

    class _RecordingProvider(_FakeProvider):
        def analyze(self, request_package):
            recorder.steps.append("provider")
            return super().analyze(request_package)

    provider = _RecordingProvider(response=_response())

    def _request_builder(**kwargs):
        recorder.steps.append("request")
        from investigations.analysis_request_builder import build_deterministic_analysis_request_package

        return build_deterministic_analysis_request_package(**kwargs)

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=_FakeResultPersistence(),
        request_builder=_request_builder,
    )

    orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )

    assert recorder.steps.index("request") < recorder.steps.index("provider")


def test_provider_invoked_exactly_once_on_success(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=_FakeResultPersistence(),
    )

    orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )

    assert len(provider.calls) == 1


def test_provider_receives_production_request_package(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=_FakeResultPersistence(),
    )

    orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )

    assert isinstance(provider.calls[0], InvestigationAnalysisRequestPackage)


def test_canonical_structured_response_is_returned(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=_FakeResultPersistence(),
    )

    outcome = orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )

    assert isinstance(outcome.response, InvestigationAnalysisResponse)


def test_session_transitions_applied_in_correct_order(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=_FakeResultPersistence(),
    )

    outcome = orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )

    session = session_store.load_session(session_id)
    assert outcome.completed is True
    assert session.status == InvestigationSessionStatus.COMPLETED


def test_successful_completion_emits_terminal_completed_event(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=_FakeResultPersistence(),
    )

    outcome = orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )

    terminal = outcome.progress_events[-1]
    assert terminal.stage == InvestigationOrchestrationStage.COMPLETED
    assert terminal.terminal is True


def test_provider_failure_emits_terminal_failed_event(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(error=RuntimeError("provider failed"))

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
    )

    with pytest.raises(InvestigationOrchestrationProviderError):
        orchestrator.run_confirmed_investigation(
            session_id=session_id,
            expected_revision=1,
            interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
        )


def test_provider_failure_does_not_mark_session_completed(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(error=RuntimeError("provider failed"))

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
    )

    with pytest.raises(InvestigationOrchestrationProviderError):
        orchestrator.run_confirmed_investigation(
            session_id=session_id,
            expected_revision=1,
            interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
        )

    session = session_store.load_session(session_id)
    assert session.status != InvestigationSessionStatus.COMPLETED


def test_request_builder_failure_prevents_provider_invocation(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())

    def _fail_builder(**_kwargs):
        raise InvestigationAnalysisRequestBuildError("request failed")

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        request_builder=_fail_builder,
    )

    with pytest.raises(InvestigationOrchestrationRequestBuildError):
        orchestrator.run_confirmed_investigation(
            session_id=session_id,
            expected_revision=1,
            interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
        )

    assert len(provider.calls) == 0


def test_attempt_conflict_prevents_provider_invocation(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())

    def _attempt_conflict(*, session_id, proposed_attempt, expected_revision):
        raise InvestigationAnalysisAttemptConflict("conflict")

    attempt_store.establish_attempt_ownership = _attempt_conflict  # type: ignore[method-assign]

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
    )

    with pytest.raises(InvestigationOrchestrationAttemptConflictError):
        orchestrator.run_confirmed_investigation(
            session_id=session_id,
            expected_revision=1,
            interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
        )

    assert len(provider.calls) == 0


def test_revision_conflict_prevents_provider_invocation(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
    )

    with pytest.raises(InvestigationOrchestrationRevisionConflictError):
        orchestrator.run_confirmed_investigation(
            session_id=session_id,
            expected_revision=999,
            interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
        )

    assert len(provider.calls) == 0


def test_validation_failure_prevents_completion(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())

    def _bad_validator(_value):
        raise InvestigationAnalysisResponseValidationError("invalid")

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        response_validator=_bad_validator,
    )

    with pytest.raises(InvestigationOrchestrationResponseValidationError):
        orchestrator.run_confirmed_investigation(
            session_id=session_id,
            expected_revision=1,
            interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
        )

    session = session_store.load_session(session_id)
    assert session.status != InvestigationSessionStatus.COMPLETED


def test_result_store_failure_prevents_successful_completion_when_enabled(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())
    persistence = _FakeResultPersistence(persist_error=RuntimeError("persist failed"))

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=persistence,
    )

    with pytest.raises(InvestigationOrchestrationResultPersistenceError):
        orchestrator.run_confirmed_investigation(
            session_id=session_id,
            expected_revision=1,
            interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
        )


def test_duplicate_completed_request_does_not_call_provider_when_prior_result_available(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    completed = session_store.load_session(session_id).model_copy(
        update={
            "status": InvestigationSessionStatus.COMPLETED,
            "revision": 2,
            "completed_result_id": str(uuid4()),
            "updated_at_utc": datetime.now(timezone.utc),
        }
    )
    session_store.save_session(completed)

    provider = _FakeProvider(response=_response())
    persistence = _FakeResultPersistence(
        stored=InvestigationOrchestrationStoredResult(
            result_id=str(uuid4()),
            response=_response(),
        )
    )

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=persistence,
    )

    outcome = orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=2,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[str(uuid4())]),
    )

    assert outcome.provider_invoked is False
    assert len(provider.calls) == 0


def test_no_automatic_retry_occurs(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(error=RuntimeError("provider failed"))

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
    )

    with pytest.raises(InvestigationOrchestrationProviderError):
        orchestrator.run_confirmed_investigation(
            session_id=session_id,
            expected_revision=1,
            interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
        )

    assert len(provider.calls) == 1


def test_no_second_attempt_becomes_active(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=_FakeResultPersistence(),
    )

    orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )

    attempts = attempt_store.list_attempts(session_id=session_id)
    assert len(attempts) == 1


def test_callback_progress_sink_behavior_is_deterministic(tmp_path: Path):
    captured = []

    def _sink(event):
        captured.append((event.sequence_number, event.stage.value))

    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=_FakeResultPersistence(),
        progress_sink=_sink,
    )

    outcome = orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )

    expected = [(item.sequence_number, item.stage.value) for item in outcome.progress_events]
    assert captured == expected


def test_no_raw_image_base64_or_api_key_in_progress_events(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=_FakeResultPersistence(),
    )

    outcome = orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )

    dump = "\n".join(item.model_dump_json() for item in outcome.progress_events)
    assert "base64" not in dump
    assert "OPENAI_API_KEY" not in dump


def test_no_fastapi_ui_device_behavior_is_added(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    provider = _FakeProvider(response=_response())

    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=_FakeResultPersistence(),
    )

    orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )

    session_root = session_store.session_workspace_dir(session_id)
    assert not (session_root / "dashboard").exists()
    assert not (session_root / "android").exists()
    assert not (session_root / "glasses").exists()


def test_no_live_openai_request_occurs_during_pytest(tmp_path: Path):
    session_store, evidence_store, attempt_store, session_id = _create_collecting_session(tmp_path)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)

    class _NoLiveProvider(_FakeProvider):
        pass

    provider = _NoLiveProvider(response=_response())
    orchestrator = _orchestrator(
        session_store=session_store,
        evidence_store=evidence_store,
        attempt_store=attempt_store,
        provider=provider,
        persistence=_FakeResultPersistence(),
    )

    outcome = orchestrator.run_confirmed_investigation(
        session_id=session_id,
        expected_revision=1,
        interaction_context=_interaction_context(session_id=session_id, evidence_ids=[evidence_id]),
    )

    assert outcome.provider_invoked is True
    assert len(provider.calls) == 1
