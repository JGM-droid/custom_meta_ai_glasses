from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

import investigations.result_store as result_store_module
from investigations.models import (
    INVESTIGATION_ANALYSIS_ATTEMPT_SCHEMA_VERSION,
    INVESTIGATION_CANONICAL_RESULT_SCHEMA_VERSION,
    INVESTIGATION_RESULT_LINK_SCHEMA_VERSION,
    INVESTIGATION_SESSION_SCHEMA_VERSION,
    InvestigationAnalysisAttempt,
    InvestigationAttemptFailureMetadata,
    InvestigationAnalysisAttemptStatus,
    InvestigationCanonicalResultEnvelope,
    InvestigationResultLink,
    InvestigationRetainedResult,
    InvestigationSession,
    InvestigationSessionStatus,
    create_new_investigation_session,
)
from investigations.result_store import (
    InvestigationStoreConflict,
    InvestigationStoreError,
    InvestigationStoreNotFound,
    load_canonical_investigation_result,
    load_latest_investigation_result,
    save_canonical_investigation_result,
    save_investigation_result_by_id,
    save_latest_investigation_result,
)
from investigations.session_lifecycle import (
    InvestigationSessionLifecycleError,
    apply_analysis_started_transition,
    apply_complete_transition,
    apply_fail_transition,
    apply_finalize_transition,
)


def _retained_result(*, session_id: str = "session-legacy", investigation_id: str = "inv_seed") -> InvestigationRetainedResult:
    return InvestigationRetainedResult(
        schema_version="1.0",
        projection_version="1.0",
        investigation_id=investigation_id,
        session_id=session_id,
        status="analyzed",
        diagnosis="Diagnosis",
        required_next_action="Capture one more screenshot.",
        image_count=2,
        image_order=["1:first.png", "2:second.png"],
        used_user_explanation="explanation",
        completed_at_utc=datetime.now(timezone.utc),
        context_used=False,
        context_staleness="unknown",
        context_signal_age_seconds=None,
        copilot_prompt="Prompt",
    )


def _attempt_payload(status: InvestigationAnalysisAttemptStatus) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": INVESTIGATION_ANALYSIS_ATTEMPT_SCHEMA_VERSION,
        "analysis_attempt_id": str(uuid4()),
        "session_id": str(uuid4()),
        "attempt_number": 1,
        "status": status.value,
        "frozen_manifest_hash": "a" * 64,
        "context_snapshot_hash": "b" * 64,
        "request_fingerprint": "c" * 64,
        "created_at_utc": datetime.now(timezone.utc),
        "started_at_utc": datetime.now(timezone.utc),
        "completed_at_utc": None,
        "failure_metadata": None,
        "canonical_result_id": None,
        "provider_request_id": "provider-req-1",
        "recovery_state": "none",
        "retryable": False,
    }

    if status == InvestigationAnalysisAttemptStatus.COMPLETED:
        payload["completed_at_utc"] = datetime.now(timezone.utc)
        payload["canonical_result_id"] = str(uuid4())

    if status in {
        InvestigationAnalysisAttemptStatus.FAILED_PRE_CALL,
        InvestigationAnalysisAttemptStatus.FAILED_PROVIDER_CONFIRMED,
        InvestigationAnalysisAttemptStatus.FAILED_RESULT_PERSISTENCE,
        InvestigationAnalysisAttemptStatus.AMBIGUOUS_COMPLETION,
    }:
        payload["failure_metadata"] = {
            "category": "provider_error",
            "safe_message": "Provider failed safely.",
            "retryable": status != InvestigationAnalysisAttemptStatus.AMBIGUOUS_COMPLETION,
        }

    return payload


@pytest.mark.parametrize(
    "status",
    [
        "created",
        "collecting",
        "paused",
        "finalizing",
        "analyzing",
        "failed",
        "completed",
        "cancelled",
    ],
)
def test_session_model_accepts_all_phase2c_statuses(status: str):
    payload = {
        "schema_version": INVESTIGATION_SESSION_SCHEMA_VERSION,
        "session_id": str(uuid4()),
        "status": status,
        "revision": 0,
        "created_at_utc": datetime.now(timezone.utc),
        "updated_at_utc": datetime.now(timezone.utc),
    }
    session = InvestigationSession.model_validate(payload)
    assert session.status.value == status


def test_session_model_rejects_invalid_status():
    payload = {
        "schema_version": INVESTIGATION_SESSION_SCHEMA_VERSION,
        "session_id": str(uuid4()),
        "status": "ready_for_analysis",
        "revision": 0,
        "created_at_utc": datetime.now(timezone.utc),
        "updated_at_utc": datetime.now(timezone.utc),
    }
    with pytest.raises(ValidationError):
        InvestigationSession.model_validate(payload)


def test_old_session_json_loads_with_phase2c_defaults():
    payload = {
        "schema_version": INVESTIGATION_SESSION_SCHEMA_VERSION,
        "session_id": str(uuid4()),
        "status": "collecting",
        "revision": 2,
        "created_at_utc": datetime.now(timezone.utc),
        "updated_at_utc": datetime.now(timezone.utc),
        "client_metadata": {"source": "desktop"},
    }

    session = InvestigationSession.model_validate(payload)
    assert session.current_analysis_attempt_id is None
    assert session.completed_result_id is None
    assert session.last_error is None
    assert session.revision == 2


def test_session_optional_uuid_fields_validate():
    payload = {
        "schema_version": INVESTIGATION_SESSION_SCHEMA_VERSION,
        "session_id": str(uuid4()),
        "status": "finalizing",
        "revision": 1,
        "created_at_utc": datetime.now(timezone.utc),
        "updated_at_utc": datetime.now(timezone.utc),
        "current_analysis_attempt_id": str(uuid4()),
        "completed_result_id": str(uuid4()),
    }

    model = InvestigationSession.model_validate(payload)
    assert model.current_analysis_attempt_id is not None
    assert model.completed_result_id is not None

    payload["current_analysis_attempt_id"] = "not-a-uuid"
    with pytest.raises(ValidationError):
        InvestigationSession.model_validate(payload)


@pytest.mark.parametrize("status", list(InvestigationAnalysisAttemptStatus))
def test_attempt_model_accepts_all_approved_statuses(status: InvestigationAnalysisAttemptStatus):
    attempt = InvestigationAnalysisAttempt.model_validate(_attempt_payload(status))
    assert attempt.status == status


def test_attempt_model_rejects_invalid_status():
    payload = _attempt_payload(InvestigationAnalysisAttemptStatus.PREPARED)
    payload["status"] = "running"
    with pytest.raises(ValidationError):
        InvestigationAnalysisAttempt.model_validate(payload)


def test_attempt_model_rejects_unsafe_or_oversized_failure_data():
    payload = _attempt_payload(InvestigationAnalysisAttemptStatus.FAILED_PRE_CALL)
    payload["failure_metadata"] = {
        "category": "x" * 65,
        "safe_message": "ok",
        "retryable": True,
    }
    with pytest.raises(ValidationError):
        InvestigationAnalysisAttempt.model_validate(payload)

    payload = _attempt_payload(InvestigationAnalysisAttemptStatus.FAILED_PRE_CALL)
    payload["failure_metadata"] = {
        "category": "provider_error",
        "safe_message": "x" * 301,
        "retryable": True,
    }
    with pytest.raises(ValidationError):
        InvestigationAnalysisAttempt.model_validate(payload)


def test_attempt_model_provider_request_id_bounded():
    payload = _attempt_payload(InvestigationAnalysisAttemptStatus.PREPARED)
    payload["provider_request_id"] = "x" * 128
    InvestigationAnalysisAttempt.model_validate(payload)

    payload["provider_request_id"] = "x" * 129
    with pytest.raises(ValidationError):
        InvestigationAnalysisAttempt.model_validate(payload)


def test_result_link_model_path_and_uuid_validation():
    link = InvestigationResultLink.model_validate(
        {
            "schema_version": INVESTIGATION_RESULT_LINK_SCHEMA_VERSION,
            "result_id": str(uuid4()),
            "session_id": str(uuid4()),
            "analysis_attempt_id": str(uuid4()),
            "canonical_storage_ref": "results/11111111-1111-1111-1111-111111111111.json",
            "completed_at_utc": datetime.now(timezone.utc),
        }
    )
    assert link.canonical_storage_ref.startswith("results/")

    with pytest.raises(ValidationError):
        InvestigationResultLink.model_validate(
            {
                "schema_version": INVESTIGATION_RESULT_LINK_SCHEMA_VERSION,
                "result_id": str(uuid4()),
                "session_id": str(uuid4()),
                "analysis_attempt_id": str(uuid4()),
                "canonical_storage_ref": "/results/bad.json",
                "completed_at_utc": datetime.now(timezone.utc),
            }
        )

    with pytest.raises(ValidationError):
        InvestigationResultLink.model_validate(
            {
                "schema_version": INVESTIGATION_RESULT_LINK_SCHEMA_VERSION,
                "result_id": str(uuid4()),
                "session_id": str(uuid4()),
                "analysis_attempt_id": str(uuid4()),
                "canonical_storage_ref": "results/../bad.json",
                "completed_at_utc": datetime.now(timezone.utc),
            }
        )

    with pytest.raises(ValidationError):
        InvestigationResultLink.model_validate(
            {
                "schema_version": INVESTIGATION_RESULT_LINK_SCHEMA_VERSION,
                "result_id": str(uuid4()),
                "session_id": str(uuid4()),
                "analysis_attempt_id": str(uuid4()),
                "canonical_storage_ref": "results\\bad.json",
                "completed_at_utc": datetime.now(timezone.utc),
            }
        )

    with pytest.raises(ValidationError):
        InvestigationResultLink.model_validate(
            {
                "schema_version": INVESTIGATION_RESULT_LINK_SCHEMA_VERSION,
                "result_id": "not-a-uuid",
                "session_id": str(uuid4()),
                "analysis_attempt_id": str(uuid4()),
                "canonical_storage_ref": "results/good.json",
                "completed_at_utc": datetime.now(timezone.utc),
            }
        )


def test_lifecycle_phase2c_revision_transitions():
    created = create_new_investigation_session()
    collecting = created.model_copy(
        update={
            "status": InvestigationSessionStatus.COLLECTING,
            "revision": 1,
            "updated_at_utc": datetime.now(timezone.utc),
        }
    )

    finalizing, changed = apply_finalize_transition(collecting, expected_revision=1)
    assert changed is True
    assert finalizing.status == InvestigationSessionStatus.FINALIZING
    assert finalizing.revision == 2

    analyzing, changed = apply_analysis_started_transition(finalizing, expected_revision=2)
    assert changed is True
    assert analyzing.status == InvestigationSessionStatus.ANALYZING
    assert analyzing.revision == 3

    completed_result_id = str(uuid4())
    completed, changed = apply_complete_transition(
        analyzing,
        expected_revision=3,
        completed_result_id=completed_result_id,
    )
    assert changed is True
    assert completed.status == InvestigationSessionStatus.COMPLETED
    assert completed.completed_result_id == completed_result_id
    assert completed.revision == 4


def test_lifecycle_fail_transition_and_terminal_behavior():
    created = create_new_investigation_session()
    finalizing = created.model_copy(
        update={
            "status": InvestigationSessionStatus.FINALIZING,
            "revision": 1,
            "updated_at_utc": datetime.now(timezone.utc),
        }
    )

    failed, changed = apply_fail_transition(
        finalizing,
        expected_revision=1,
        error_category="provider_error",
        safe_message="Safe failure.",
        retryable=True,
    )
    assert changed is True
    assert failed.status == InvestigationSessionStatus.FAILED
    assert failed.revision == 2
    assert failed.last_error is not None
    assert failed.last_error.retryable is True

    failed_again, changed = apply_fail_transition(
        failed,
        expected_revision=2,
        error_category="provider_error",
        safe_message="Safe failure.",
        retryable=True,
    )
    assert changed is False
    assert failed_again.revision == failed.revision

    completed = failed.model_copy(
        update={
            "status": InvestigationSessionStatus.COMPLETED,
            "completed_result_id": str(uuid4()),
        }
    )
    with pytest.raises(InvestigationSessionLifecycleError):
        apply_fail_transition(
            completed,
            expected_revision=2,
            error_category="provider_error",
            safe_message="Safe failure.",
            retryable=False,
        )

    cancelled = failed.model_copy(update={"status": InvestigationSessionStatus.CANCELLED})
    with pytest.raises(InvestigationSessionLifecycleError):
        apply_fail_transition(
            cancelled,
            expected_revision=2,
            error_category="provider_error",
            safe_message="Safe failure.",
            retryable=False,
        )


def test_lifecycle_rejected_transition_and_expected_revision_do_not_mutate():
    created = create_new_investigation_session()
    collecting = created.model_copy(
        update={
            "status": InvestigationSessionStatus.COLLECTING,
            "revision": 3,
            "updated_at_utc": datetime.now(timezone.utc),
        }
    )

    with pytest.raises(InvestigationSessionLifecycleError) as exc_info:
        apply_finalize_transition(collecting, expected_revision=99)
    assert exc_info.value.category == "revision_conflict"

    with pytest.raises(InvestigationSessionLifecycleError):
        apply_complete_transition(
            collecting,
            expected_revision=3,
            completed_result_id=str(uuid4()),
        )

    assert collecting.status == InvestigationSessionStatus.COLLECTING
    assert collecting.revision == 3


def test_result_store_save_and_load_canonical_by_result_id(tmp_path: Path):
    store_root = tmp_path / "results" / "investigations"
    retained_a = _retained_result(session_id=str(uuid4()), investigation_id="inv-a")
    retained_b = _retained_result(session_id=str(uuid4()), investigation_id="inv-b")

    result_id_a = str(uuid4())
    result_id_b = str(uuid4())

    envelope_a = save_canonical_investigation_result(store_root, result_id=result_id_a, retained_result=retained_a)
    envelope_b = save_canonical_investigation_result(store_root, result_id=result_id_b, retained_result=retained_b)

    loaded_a = load_canonical_investigation_result(store_root, result_id_a)
    loaded_b = load_canonical_investigation_result(store_root, result_id_b)

    assert envelope_a.result_id == result_id_a
    assert envelope_b.result_id == result_id_b
    assert loaded_a.retained_result.investigation_id == "inv-a"
    assert loaded_b.retained_result.investigation_id == "inv-b"


def test_result_store_latest_compatibility_and_historical_ownership(tmp_path: Path):
    latest_path = tmp_path / "investigation_latest.json"
    retained_a = _retained_result(investigation_id="inv-a")
    retained_b = _retained_result(investigation_id="inv-b")

    save_latest_investigation_result(latest_path, retained_a)
    first_latest = load_latest_investigation_result(latest_path)
    assert first_latest.investigation_id == "inv-a"

    save_latest_investigation_result(latest_path, retained_b)
    second_latest = load_latest_investigation_result(latest_path)
    assert second_latest.investigation_id == "inv-b"

    canonical_results_dir = tmp_path / "investigations" / "results"
    files = sorted(canonical_results_dir.glob("*.json"))
    assert len(files) == 2

    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    ids = {item["retained_result"]["investigation_id"] for item in payloads}
    assert ids == {"inv-a", "inv-b"}


def test_result_store_atomic_write_and_temp_cleanup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store_root = tmp_path / "results" / "investigations"
    retained = _retained_result(session_id=str(uuid4()))
    result_id = str(uuid4())

    original_replace = result_store_module.os.replace

    def _raise_replace(_src: str, _dst: str) -> None:
        raise OSError("simulated failure")

    monkeypatch.setattr(result_store_module.os, "replace", _raise_replace)

    with pytest.raises(InvestigationStoreError):
        save_canonical_investigation_result(store_root, result_id=result_id, retained_result=retained)

    assert list((store_root / "results").glob("*.tmp")) == []
    monkeypatch.setattr(result_store_module.os, "replace", original_replace)


def test_result_store_idempotent_same_result_and_conflict_detection(tmp_path: Path):
    store_root = tmp_path / "results" / "investigations"
    retained = _retained_result(session_id=str(uuid4()), investigation_id="inv-same")
    result_id = str(uuid4())

    first = InvestigationCanonicalResultEnvelope(
        schema_version=INVESTIGATION_CANONICAL_RESULT_SCHEMA_VERSION,
        result_id=result_id,
        session_id=None,
        analysis_attempt_id=None,
        created_at_utc=retained.completed_at_utc,
        retained_result=retained,
        result_hash=None,
    )

    save_investigation_result_by_id(store_root, first)
    save_investigation_result_by_id(store_root, first)

    conflicting = first.model_copy(
        update={
            "retained_result": first.retained_result.model_copy(
                update={"diagnosis": "Different diagnosis"}
            )
        }
    )

    with pytest.raises(InvestigationStoreConflict):
        save_investigation_result_by_id(store_root, conflicting)


def test_result_store_latest_update_failure_does_not_destroy_canonical(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    latest_path = tmp_path / "investigation_latest.json"
    retained = _retained_result(session_id=str(uuid4()), investigation_id="inv-canonical")
    original_replace = result_store_module.os.replace

    def _replace_fail_latest(src: str, dst: str):
        if Path(dst) == latest_path:
            raise OSError("latest write failed")
        return original_replace(src, dst)

    monkeypatch.setattr(result_store_module.os, "replace", _replace_fail_latest)

    with pytest.raises(InvestigationStoreError):
        save_latest_investigation_result(latest_path, retained)

    canonical_results = list((tmp_path / "investigations" / "results").glob("*.json"))
    assert len(canonical_results) == 1
    payload = json.loads(canonical_results[0].read_text(encoding="utf-8"))
    assert payload["retained_result"]["investigation_id"] == "inv-canonical"


def test_result_store_not_found_corrupt_and_unsafe_result_id(tmp_path: Path):
    store_root = tmp_path / "results" / "investigations"

    with pytest.raises(InvestigationStoreNotFound):
        load_canonical_investigation_result(store_root, str(uuid4()))

    result_id = str(uuid4())
    path = store_root / "results" / f"{result_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ malformed", encoding="utf-8")
    with pytest.raises(InvestigationStoreError):
        load_canonical_investigation_result(store_root, result_id)

    with pytest.raises(InvestigationStoreError):
        load_canonical_investigation_result(store_root, "../escape")

    with pytest.raises(InvestigationStoreError):
        save_canonical_investigation_result(store_root, result_id="not-a-uuid", retained_result=_retained_result())


def test_result_store_canonical_optional_uuid_fields_accept_none_and_valid_uuid(tmp_path: Path):
    store_root = tmp_path / "results" / "investigations"
    retained_none = _retained_result(session_id="legacy-session")
    result_none = save_canonical_investigation_result(
        store_root,
        result_id=str(uuid4()),
        retained_result=retained_none,
        session_id=None,
        analysis_attempt_id=None,
    )
    assert result_none.session_id is None
    assert result_none.analysis_attempt_id is None

    valid_session_id = str(uuid4())
    valid_attempt_id = str(uuid4())
    retained_valid = _retained_result(session_id=valid_session_id)
    result_valid = save_canonical_investigation_result(
        store_root,
        result_id=str(uuid4()),
        retained_result=retained_valid,
        session_id=valid_session_id,
        analysis_attempt_id=valid_attempt_id,
    )
    assert result_valid.session_id == valid_session_id
    assert result_valid.analysis_attempt_id == valid_attempt_id


def test_result_store_canonical_optional_uuid_fields_reject_invalid_explicit_values(tmp_path: Path):
    store_root = tmp_path / "results" / "investigations"
    latest_path = tmp_path / "investigation_latest.json"
    previous = _retained_result(investigation_id="prev")
    save_latest_investigation_result(latest_path, previous)
    latest_before = latest_path.read_text(encoding="utf-8")

    retained = _retained_result(session_id=str(uuid4()), investigation_id="invalid-opt")
    canonical_dir = store_root / "results"

    with pytest.raises(InvestigationStoreError):
        save_canonical_investigation_result(
            store_root,
            result_id=str(uuid4()),
            retained_result=retained,
            session_id="not-a-uuid",
            analysis_attempt_id=None,
        )

    with pytest.raises(InvestigationStoreError):
        save_canonical_investigation_result(
            store_root,
            result_id=str(uuid4()),
            retained_result=retained,
            session_id=None,
            analysis_attempt_id="not-a-uuid",
        )

    with pytest.raises(InvestigationStoreError):
        save_canonical_investigation_result(
            store_root,
            result_id=str(uuid4()),
            retained_result=retained,
            session_id="   ",
            analysis_attempt_id=None,
        )

    with pytest.raises(InvestigationStoreError):
        save_canonical_investigation_result(
            store_root,
            result_id=str(uuid4()),
            retained_result=retained,
            session_id=None,
            analysis_attempt_id="   ",
        )

    assert not canonical_dir.exists() or list(canonical_dir.glob("*.json")) == []
    assert latest_path.read_text(encoding="utf-8") == latest_before
    if canonical_dir.exists():
        assert list(canonical_dir.glob("*.tmp")) == []
