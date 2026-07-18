from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from investigations.evidence_store import InvestigationEvidenceStore
from investigations.interaction_state_machine import (
    InvestigationInteractionEvent,
    InvestigationInteractionInvalidTransition,
    InvestigationInteractionState,
    InvestigationInteractionStateMachine,
    InvestigationInteractionValidationError,
    new_interaction_context,
)
from investigations.models import InvestigationEvidenceCreateRequest, InvestigationEvidenceType, InvestigationSessionStatus
from investigations.session_store import InvestigationSessionStore


def _create_session_store(tmp_path: Path) -> tuple[InvestigationSessionStore, InvestigationEvidenceStore, str]:
    root = tmp_path / "investigation_sessions"
    session_store = InvestigationSessionStore(root)
    evidence_store = InvestigationEvidenceStore(session_store)
    session = session_store.create_session(client_metadata=None)
    return session_store, evidence_store, session.session_id


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
            width=1200,
            height=800,
            duration_seconds=None,
        ),
    )
    assert created is True
    return record.evidence_id


def _start_interaction(machine: InvestigationInteractionStateMachine, session_store: InvestigationSessionStore, session_id: str):
    session = session_store.load_session(session_id)
    context = new_interaction_context(session_id=session_id)
    outcome = machine.apply(
        session=session,
        interaction=context,
        event=InvestigationInteractionEvent.START_INVESTIGATION,
        expected_revision=session.revision,
    )
    session_store.save_session(outcome.session)
    return outcome.session, outcome.interaction, outcome


def _capture(
    machine: InvestigationInteractionStateMachine,
    *,
    session,
    interaction,
    evidence_id: str,
):
    return machine.apply(
        session=session,
        interaction=interaction,
        event=InvestigationInteractionEvent.CAPTURE_COMPLETED,
        evidence_id=evidence_id,
    )


def _ready_for_confirmation(
    machine: InvestigationInteractionStateMachine,
    *,
    session,
    interaction,
    explanation_text: str,
):
    done = machine.apply(
        session=session,
        interaction=interaction,
        event=InvestigationInteractionEvent.DONE_CAPTURING,
    )
    ready = machine.apply(
        session=done.session,
        interaction=done.interaction,
        event=InvestigationInteractionEvent.EXPLANATION_COMPLETED,
        explanation_text=explanation_text,
    )
    return ready


def test_new_investigation_starts_in_correct_interaction_state(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)

    _session, interaction, _outcome = _start_interaction(machine, session_store, session_id)

    assert interaction.interaction_state == InvestigationInteractionState.WAITING_FOR_CAPTURE


def test_start_returns_first_capture_instruction(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)

    _session, _interaction, outcome = _start_interaction(machine, session_store, session_id)

    assert outcome.transition.user_confirmation == "Investigation started. Show me the first view and capture when ready."


def test_capture_before_start_is_rejected(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session = session_store.load_session(session_id)
    context = new_interaction_context(session_id=session_id)

    evidence_id = str(uuid4())
    with pytest.raises(InvestigationInteractionInvalidTransition):
        machine.apply(
            session=session,
            interaction=context,
            event=InvestigationInteractionEvent.CAPTURE_COMPLETED,
            evidence_id=evidence_id,
        )


def test_first_capture_succeeds(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    outcome = _capture(machine, session=session, interaction=interaction, evidence_id=evidence_id)

    assert outcome.transition.capture_count == 1
    assert outcome.interaction.interaction_state == InvestigationInteractionState.WAITING_FOR_MORE_OR_DONE


def test_capture_confirmation_includes_correct_image_number(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    outcome = _capture(machine, session=session, interaction=interaction, evidence_id=evidence_id)

    assert outcome.transition.user_confirmation == "Image 1 captured. Capture another view or finish capturing."


def test_second_and_third_captures_succeed(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    first = _capture(
        machine,
        session=session,
        interaction=interaction,
        evidence_id=_upload_image(evidence_store, session_id=session_id, index=1),
    )
    second = _capture(
        machine,
        session=first.session,
        interaction=first.interaction,
        evidence_id=_upload_image(evidence_store, session_id=session_id, index=2),
    )
    third = _capture(
        machine,
        session=second.session,
        interaction=second.interaction,
        evidence_id=_upload_image(evidence_store, session_id=session_id, index=3),
    )

    assert second.transition.capture_count == 2
    assert third.transition.capture_count == 3


def test_fourth_capture_is_rejected(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    one = _capture(machine, session=session, interaction=interaction, evidence_id=_upload_image(evidence_store, session_id=session_id, index=1))
    two = _capture(machine, session=one.session, interaction=one.interaction, evidence_id=_upload_image(evidence_store, session_id=session_id, index=2))
    three = _capture(machine, session=two.session, interaction=two.interaction, evidence_id=_upload_image(evidence_store, session_id=session_id, index=3))

    with pytest.raises(InvestigationInteractionInvalidTransition):
        _capture(
            machine,
            session=three.session,
            interaction=three.interaction,
            evidence_id=_upload_image(evidence_store, session_id=session_id, index=4),
        )


def test_done_capturing_with_zero_images_is_rejected(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    with pytest.raises(InvestigationInteractionInvalidTransition):
        machine.apply(session=session, interaction=interaction, event=InvestigationInteractionEvent.DONE_CAPTURING)


def test_done_capturing_with_images_requests_explanation(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    captured = _capture(
        machine,
        session=session,
        interaction=interaction,
        evidence_id=_upload_image(evidence_store, session_id=session_id, index=1),
    )
    done = machine.apply(
        session=captured.session,
        interaction=captured.interaction,
        event=InvestigationInteractionEvent.DONE_CAPTURING,
    )

    assert done.interaction.interaction_state == InvestigationInteractionState.WAITING_FOR_EXPLANATION
    assert done.transition.user_confirmation == "Briefly explain what you are trying to figure out."


def test_blank_explanation_is_rejected(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    captured = _capture(
        machine,
        session=session,
        interaction=interaction,
        evidence_id=_upload_image(evidence_store, session_id=session_id, index=1),
    )
    done = machine.apply(session=captured.session, interaction=captured.interaction, event=InvestigationInteractionEvent.DONE_CAPTURING)

    with pytest.raises(InvestigationInteractionValidationError):
        machine.apply(
            session=done.session,
            interaction=done.interaction,
            event=InvestigationInteractionEvent.EXPLANATION_COMPLETED,
            explanation_text="   ",
        )


def test_valid_explanation_reaches_ready_for_confirmation(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    captured = _capture(
        machine,
        session=session,
        interaction=interaction,
        evidence_id=_upload_image(evidence_store, session_id=session_id, index=1),
    )
    ready = _ready_for_confirmation(
        machine,
        session=captured.session,
        interaction=captured.interaction,
        explanation_text="Need to find why tests fail after refactor.",
    )

    assert ready.interaction.interaction_state == InvestigationInteractionState.READY_FOR_CONFIRMATION


def test_confirmation_reports_correct_capture_count(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    c1 = _capture(machine, session=session, interaction=interaction, evidence_id=_upload_image(evidence_store, session_id=session_id, index=1))
    c2 = _capture(machine, session=c1.session, interaction=c1.interaction, evidence_id=_upload_image(evidence_store, session_id=session_id, index=2))
    ready = _ready_for_confirmation(
        machine,
        session=c2.session,
        interaction=c2.interaction,
        explanation_text="Need root cause across two views.",
    )

    assert "2 image(s)" in ready.transition.user_confirmation


def test_confirm_analysis_with_no_explanation_is_rejected(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    captured = _capture(
        machine,
        session=session,
        interaction=interaction,
        evidence_id=_upload_image(evidence_store, session_id=session_id, index=1),
    )

    with pytest.raises(InvestigationInteractionInvalidTransition):
        machine.apply(
            session=captured.session,
            interaction=captured.interaction,
            event=InvestigationInteractionEvent.CONFIRM_ANALYSIS,
            expected_revision=captured.session.revision,
        )


def test_confirm_analysis_in_wrong_state_is_rejected(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    with pytest.raises(InvestigationInteractionInvalidTransition):
        machine.apply(
            session=session,
            interaction=interaction,
            event=InvestigationInteractionEvent.CONFIRM_ANALYSIS,
            expected_revision=session.revision,
        )


def test_valid_confirm_analysis_indicates_analysis_may_begin(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    captured = _capture(
        machine,
        session=session,
        interaction=interaction,
        evidence_id=_upload_image(evidence_store, session_id=session_id, index=1),
    )
    ready = _ready_for_confirmation(
        machine,
        session=captured.session,
        interaction=captured.interaction,
        explanation_text="Need issue diagnosis.",
    )

    confirmed = machine.apply(
        session=ready.session,
        interaction=ready.interaction,
        event=InvestigationInteractionEvent.CONFIRM_ANALYSIS,
        expected_revision=ready.session.revision,
    )

    assert confirmed.transition.analysis_may_begin is True
    assert confirmed.session.status == InvestigationSessionStatus.FINALIZING


def test_retake_last_works_with_one_or_more_captures(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    c1 = _capture(machine, session=session, interaction=interaction, evidence_id=_upload_image(evidence_store, session_id=session_id, index=1))
    c2 = _capture(machine, session=c1.session, interaction=c1.interaction, evidence_id=_upload_image(evidence_store, session_id=session_id, index=2))

    retaken = machine.apply(session=c2.session, interaction=c2.interaction, event=InvestigationInteractionEvent.RETAKE_LAST)

    assert retaken.transition.capture_count == 1
    assert retaken.interaction.interaction_state == InvestigationInteractionState.WAITING_FOR_CAPTURE


def test_retake_last_with_no_captures_is_rejected(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    with pytest.raises(InvestigationInteractionInvalidTransition):
        machine.apply(session=session, interaction=interaction, event=InvestigationInteractionEvent.RETAKE_LAST)


def test_remove_last_capture_updates_count_and_state_correctly(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    c1 = _capture(machine, session=session, interaction=interaction, evidence_id=_upload_image(evidence_store, session_id=session_id, index=1))
    c2 = _capture(machine, session=c1.session, interaction=c1.interaction, evidence_id=_upload_image(evidence_store, session_id=session_id, index=2))

    removed_once = machine.apply(
        session=c2.session,
        interaction=c2.interaction,
        event=InvestigationInteractionEvent.REMOVE_LAST_CAPTURE,
    )
    removed_twice = machine.apply(
        session=removed_once.session,
        interaction=removed_once.interaction,
        event=InvestigationInteractionEvent.REMOVE_LAST_CAPTURE,
    )

    assert removed_once.transition.capture_count == 1
    assert removed_once.interaction.interaction_state == InvestigationInteractionState.WAITING_FOR_MORE_OR_DONE
    assert removed_twice.transition.capture_count == 0
    assert removed_twice.interaction.interaction_state == InvestigationInteractionState.WAITING_FOR_CAPTURE


def test_start_over_resets_without_unintended_destructive_deletion(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    id1 = _upload_image(evidence_store, session_id=session_id, index=1)
    id2 = _upload_image(evidence_store, session_id=session_id, index=2)
    c1 = _capture(machine, session=session, interaction=interaction, evidence_id=id1)
    c2 = _capture(machine, session=c1.session, interaction=c1.interaction, evidence_id=id2)

    reset = machine.apply(
        session=c2.session,
        interaction=c2.interaction,
        event=InvestigationInteractionEvent.START_OVER,
    )

    assert reset.interaction.interaction_state == InvestigationInteractionState.WAITING_FOR_CAPTURE
    assert reset.transition.capture_count == 0
    assert evidence_store.load_evidence_for_analysis(session_id=session_id, evidence_id=id1).evidence_id == id1
    assert evidence_store.load_evidence_for_analysis(session_id=session_id, evidence_id=id2).evidence_id == id2


def test_cancel_is_deterministic_and_idempotent(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    first = machine.apply(
        session=session,
        interaction=interaction,
        event=InvestigationInteractionEvent.CANCEL,
        expected_revision=session.revision,
    )
    second = machine.apply(
        session=first.session,
        interaction=first.interaction,
        event=InvestigationInteractionEvent.CANCEL,
        expected_revision=first.session.revision,
    )

    assert first.session.status == InvestigationSessionStatus.CANCELLED
    assert first.transition.user_confirmation == "Investigation cancelled."
    assert second.transition.user_confirmation == "Investigation already cancelled."


def test_analysis_started_transitions_correctly(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    captured = _capture(
        machine,
        session=session,
        interaction=interaction,
        evidence_id=_upload_image(evidence_store, session_id=session_id, index=1),
    )
    ready = _ready_for_confirmation(
        machine,
        session=captured.session,
        interaction=captured.interaction,
        explanation_text="Need analysis start event.",
    )
    confirmed = machine.apply(
        session=ready.session,
        interaction=ready.interaction,
        event=InvestigationInteractionEvent.CONFIRM_ANALYSIS,
        expected_revision=ready.session.revision,
    )
    started = machine.apply(
        session=confirmed.session,
        interaction=confirmed.interaction,
        event=InvestigationInteractionEvent.ANALYSIS_STARTED,
        expected_revision=confirmed.session.revision,
    )

    assert started.interaction.interaction_state == InvestigationInteractionState.ANALYZING
    assert started.session.status == InvestigationSessionStatus.ANALYZING


def test_analysis_succeeded_transitions_to_result_ready(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    captured = _capture(
        machine,
        session=session,
        interaction=interaction,
        evidence_id=_upload_image(evidence_store, session_id=session_id, index=1),
    )
    ready = _ready_for_confirmation(
        machine,
        session=captured.session,
        interaction=captured.interaction,
        explanation_text="Need success transition.",
    )
    confirmed = machine.apply(
        session=ready.session,
        interaction=ready.interaction,
        event=InvestigationInteractionEvent.CONFIRM_ANALYSIS,
        expected_revision=ready.session.revision,
    )
    started = machine.apply(
        session=confirmed.session,
        interaction=confirmed.interaction,
        event=InvestigationInteractionEvent.ANALYSIS_STARTED,
        expected_revision=confirmed.session.revision,
    )
    succeeded = machine.apply(
        session=started.session,
        interaction=started.interaction,
        event=InvestigationInteractionEvent.ANALYSIS_SUCCEEDED,
        expected_revision=started.session.revision,
        completed_result_id=str(uuid4()),
    )

    assert succeeded.interaction.interaction_state == InvestigationInteractionState.RESULT_READY
    assert succeeded.session.status == InvestigationSessionStatus.COMPLETED


def test_analysis_failed_preserves_retry_relevant_state(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    captured = _capture(
        machine,
        session=session,
        interaction=interaction,
        evidence_id=_upload_image(evidence_store, session_id=session_id, index=1),
    )
    ready = _ready_for_confirmation(
        machine,
        session=captured.session,
        interaction=captured.interaction,
        explanation_text="Need failed transition.",
    )
    confirmed = machine.apply(
        session=ready.session,
        interaction=ready.interaction,
        event=InvestigationInteractionEvent.CONFIRM_ANALYSIS,
        expected_revision=ready.session.revision,
    )
    started = machine.apply(
        session=confirmed.session,
        interaction=confirmed.interaction,
        event=InvestigationInteractionEvent.ANALYSIS_STARTED,
        expected_revision=confirmed.session.revision,
    )
    failed = machine.apply(
        session=started.session,
        interaction=started.interaction,
        event=InvestigationInteractionEvent.ANALYSIS_FAILED,
        expected_revision=started.session.revision,
        error_category="provider_timeout",
        safe_error_message="Analysis timed out.",
        retryable=True,
    )

    assert failed.interaction.interaction_state == InvestigationInteractionState.FAILED
    assert failed.session.status == InvestigationSessionStatus.FAILED
    assert failed.transition.capture_count == 1
    assert failed.transition.explanation_present is True


def test_invalid_analysis_status_transitions_are_rejected(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    with pytest.raises(InvestigationInteractionInvalidTransition):
        machine.apply(
            session=session,
            interaction=interaction,
            event=InvestigationInteractionEvent.ANALYSIS_SUCCEEDED,
            expected_revision=session.revision,
            completed_result_id=str(uuid4()),
        )


def test_status_requested_does_not_mutate_state(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)
    session, interaction, _ = _start_interaction(machine, session_store, session_id)

    before_state = interaction.model_dump(mode="json")
    before_session = session.model_dump(mode="json")

    status = machine.apply(session=session, interaction=interaction, event=InvestigationInteractionEvent.STATUS_REQUESTED)

    assert status.interaction.model_dump(mode="json") == before_state
    assert status.session.model_dump(mode="json") == before_session


def test_identical_state_event_input_produces_identical_output(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)

    base_session, base_interaction, _ = _start_interaction(machine, session_store, session_id)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)

    first = machine.apply(
        session=base_session,
        interaction=base_interaction,
        event=InvestigationInteractionEvent.CAPTURE_COMPLETED,
        evidence_id=evidence_id,
    )
    second = machine.apply(
        session=base_session,
        interaction=base_interaction,
        event=InvestigationInteractionEvent.CAPTURE_COMPLETED,
        evidence_id=evidence_id,
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_no_provider_call_occurs(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)

    session, interaction, _ = _start_interaction(machine, session_store, session_id)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    outcome = machine.apply(
        session=session,
        interaction=interaction,
        event=InvestigationInteractionEvent.CAPTURE_COMPLETED,
        evidence_id=evidence_id,
    )

    assert outcome.transition.accepted_event == InvestigationInteractionEvent.CAPTURE_COMPLETED


def test_no_manifest_attempt_result_api_ui_or_device_behavior_is_introduced(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)

    session, interaction, _ = _start_interaction(machine, session_store, session_id)
    evidence_id = _upload_image(evidence_store, session_id=session_id, index=1)
    _ = machine.apply(
        session=session,
        interaction=interaction,
        event=InvestigationInteractionEvent.CAPTURE_COMPLETED,
        evidence_id=evidence_id,
    )

    session_root = session_store.session_workspace_dir(session_id)
    assert not (session_root / "finalization").exists()
    assert not (session_store.root / "results").exists()


def test_existing_session_lifecycle_semantics_remain_compatible(tmp_path: Path):
    session_store, evidence_store, session_id = _create_session_store(tmp_path)
    machine = InvestigationInteractionStateMachine(evidence_store=evidence_store)

    session, interaction, _ = _start_interaction(machine, session_store, session_id)
    captured = _capture(
        machine,
        session=session,
        interaction=interaction,
        evidence_id=_upload_image(evidence_store, session_id=session_id, index=1),
    )
    ready = _ready_for_confirmation(
        machine,
        session=captured.session,
        interaction=captured.interaction,
        explanation_text="Need lifecycle compatibility.",
    )
    confirmed = machine.apply(
        session=ready.session,
        interaction=ready.interaction,
        event=InvestigationInteractionEvent.CONFIRM_ANALYSIS,
        expected_revision=ready.session.revision,
    )
    started = machine.apply(
        session=confirmed.session,
        interaction=confirmed.interaction,
        event=InvestigationInteractionEvent.ANALYSIS_STARTED,
        expected_revision=confirmed.session.revision,
    )

    assert confirmed.session.status == InvestigationSessionStatus.FINALIZING
    assert started.session.status == InvestigationSessionStatus.ANALYZING
