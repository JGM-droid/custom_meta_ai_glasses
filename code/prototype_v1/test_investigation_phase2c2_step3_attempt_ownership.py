from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

import investigations.analysis_attempt_store as attempt_module
from investigations.analysis_attempt_store import (
    InvestigationAnalysisAttemptConflict,
    InvestigationAnalysisAttemptOwnershipError,
    InvestigationAnalysisAttemptStore,
    InvestigationAnalysisAttemptStoreError,
)
from investigations.models import InvestigationSessionStatus, create_new_investigation_session
from investigations.session_store import InvestigationSessionStore


def _hash(seed: str) -> str:
    return (seed * 64)[:64]


def _finalizing_session(session_store: InvestigationSessionStore):
    created = create_new_investigation_session()
    finalizing = created.model_copy(
        update={
            "status": InvestigationSessionStatus.FINALIZING,
            "revision": 3,
            "updated_at_utc": datetime.now(timezone.utc),
        }
    )
    session_store.save_session(finalizing)
    return finalizing


def _prepared_attempt(
    store: InvestigationAnalysisAttemptStore,
    *,
    session_id: str,
    analysis_attempt_id: str | None = None,
    attempt_number: int = 1,
    seed: str = "a",
):
    return store.build_prepared_attempt(
        session_id=session_id,
        analysis_attempt_id=analysis_attempt_id,
        attempt_number=attempt_number,
        frozen_manifest_hash=_hash(seed),
        context_snapshot_hash=_hash("b"),
        request_fingerprint=_hash("c"),
    )


def test_attempt_save_and_load_round_trip(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)

    attempt = _prepared_attempt(attempt_store, session_id=session.session_id)
    created = attempt_store.save_attempt(attempt)
    loaded = attempt_store.load_attempt(session_id=session.session_id, analysis_attempt_id=attempt.analysis_attempt_id)

    assert created is True
    assert loaded.model_dump(mode="json") == attempt.model_dump(mode="json")


def test_attempt_list_behavior_is_deterministic_and_sorted(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)

    a3 = _prepared_attempt(attempt_store, session_id=session.session_id, attempt_number=3)
    a1 = _prepared_attempt(attempt_store, session_id=session.session_id, attempt_number=1)
    a2 = _prepared_attempt(attempt_store, session_id=session.session_id, attempt_number=2)
    attempt_store.save_attempt(a3)
    attempt_store.save_attempt(a1)
    attempt_store.save_attempt(a2)

    listed = attempt_store.list_attempts(session_id=session.session_id)
    assert [item.attempt_number for item in listed] == [1, 2, 3]


def test_attempt_save_uses_atomic_replace_behavior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    attempt = _prepared_attempt(attempt_store, session_id=session.session_id)

    calls: list[tuple[str, str]] = []
    real_replace = attempt_module.os.replace

    def _tracking_replace(src: str, dst: str) -> None:
        calls.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr(attempt_module.os, "replace", _tracking_replace)
    attempt_store.save_attempt(attempt)
    assert len(calls) == 1


def test_existing_identical_attempt_save_is_idempotent(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    attempt = _prepared_attempt(attempt_store, session_id=session.session_id)

    assert attempt_store.save_attempt(attempt) is True
    assert attempt_store.save_attempt(attempt) is False


def test_existing_conflicting_attempt_save_is_rejected(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    attempt = _prepared_attempt(attempt_store, session_id=session.session_id)
    attempt_store.save_attempt(attempt)

    conflicting = attempt.model_copy(update={"request_fingerprint": _hash("d")})
    with pytest.raises(InvestigationAnalysisAttemptConflict):
        attempt_store.save_attempt(conflicting)


def test_ownership_sets_active_latest_and_legacy_current_pointers(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    attempt = _prepared_attempt(attempt_store, session_id=session.session_id)

    result = attempt_store.establish_attempt_ownership(
        session_id=session.session_id,
        proposed_attempt=attempt,
        expected_revision=session.revision,
    )

    assert result.session.active_analysis_attempt_id == attempt.analysis_attempt_id
    assert result.session.latest_analysis_attempt_id == attempt.analysis_attempt_id
    assert result.session.current_analysis_attempt_id == attempt.analysis_attempt_id


def test_ownership_revision_increments_once(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    attempt = _prepared_attempt(attempt_store, session_id=session.session_id)

    result = attempt_store.establish_attempt_ownership(
        session_id=session.session_id,
        proposed_attempt=attempt,
        expected_revision=session.revision,
    )

    assert result.session.revision == session.revision + 1


def test_active_attempt_conflict_is_rejected(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    first = _prepared_attempt(attempt_store, session_id=session.session_id)
    second = _prepared_attempt(attempt_store, session_id=session.session_id)

    first_result = attempt_store.establish_attempt_ownership(
        session_id=session.session_id,
        proposed_attempt=first,
        expected_revision=session.revision,
    )

    with pytest.raises(InvestigationAnalysisAttemptConflict):
        attempt_store.establish_attempt_ownership(
            session_id=session.session_id,
            proposed_attempt=second,
            expected_revision=first_result.session.revision,
        )


def test_expected_revision_conflict_is_rejected(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    attempt = _prepared_attempt(attempt_store, session_id=session.session_id)

    with pytest.raises(InvestigationAnalysisAttemptOwnershipError):
        attempt_store.establish_attempt_ownership(
            session_id=session.session_id,
            proposed_attempt=attempt,
            expected_revision=session.revision + 10,
        )


def test_concurrent_ownership_requests_cannot_create_two_active_attempts(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    first = _prepared_attempt(attempt_store, session_id=session.session_id)
    second = _prepared_attempt(attempt_store, session_id=session.session_id)

    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def _runner(candidate):
        barrier.wait()
        try:
            attempt_store.establish_attempt_ownership(
                session_id=session.session_id,
                proposed_attempt=candidate,
                expected_revision=session.revision,
            )
            outcomes.append("ok")
        except (InvestigationAnalysisAttemptOwnershipError, InvestigationAnalysisAttemptConflict):
            outcomes.append("conflict")

    t1 = threading.Thread(target=_runner, args=(first,))
    t2 = threading.Thread(target=_runner, args=(second,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert outcomes.count("ok") == 1
    assert outcomes.count("conflict") == 1

    reloaded = session_store.load_session(session.session_id)
    assert reloaded.active_analysis_attempt_id is not None
    attempts = attempt_store.list_attempts(session_id=session.session_id)
    assert len(attempts) >= 1
    active = [item for item in attempts if item.analysis_attempt_id == reloaded.active_analysis_attempt_id]
    assert len(active) == 1


def test_attempt_number_allocation_is_deterministic(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)

    existing_1 = _prepared_attempt(attempt_store, session_id=session.session_id, attempt_number=1)
    existing_3 = _prepared_attempt(attempt_store, session_id=session.session_id, attempt_number=3)
    attempt_store.save_attempt(existing_1)
    attempt_store.save_attempt(existing_3)

    session_without_active = session.model_copy(update={"revision": session.revision + 1})
    session_store.save_session(session_without_active)

    next_attempt = _prepared_attempt(attempt_store, session_id=session.session_id, attempt_number=1)
    result = attempt_store.establish_attempt_ownership(
        session_id=session.session_id,
        proposed_attempt=next_attempt,
        expected_revision=session_without_active.revision,
    )

    assert result.attempt.attempt_number == 4


def test_reconcile_when_attempt_exists_but_session_linkage_missing(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    attempt = _prepared_attempt(attempt_store, session_id=session.session_id)
    attempt_store.save_attempt(attempt)

    result = attempt_store.establish_attempt_ownership(
        session_id=session.session_id,
        proposed_attempt=attempt,
        expected_revision=session.revision,
    )

    assert result.reconciliation_action in {"link_existing_attempt", "reconcile_from_frozen_manifest_state"}
    assert result.session.active_analysis_attempt_id == attempt.analysis_attempt_id


def test_reconcile_when_session_linkage_exists_but_attempt_missing(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    missing_attempt_id = str(uuid4())

    linked_session = session.model_copy(
        update={
            "active_analysis_attempt_id": missing_attempt_id,
            "latest_analysis_attempt_id": missing_attempt_id,
            "current_analysis_attempt_id": missing_attempt_id,
            "revision": session.revision + 1,
            "updated_at_utc": datetime.now(timezone.utc),
        }
    )
    session_store.save_session(linked_session)

    proposed = _prepared_attempt(
        attempt_store,
        session_id=session.session_id,
        analysis_attempt_id=missing_attempt_id,
        attempt_number=1,
    )
    result = attempt_store.establish_attempt_ownership(
        session_id=session.session_id,
        proposed_attempt=proposed,
        expected_revision=linked_session.revision,
    )

    loaded = attempt_store.load_attempt(session_id=session.session_id, analysis_attempt_id=missing_attempt_id)
    assert loaded.analysis_attempt_id == missing_attempt_id
    assert result.reconciliation_action == "attempt_rehydrated_without_session_mutation"


def test_duplicate_reconciliation_request_is_idempotent(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    attempt = _prepared_attempt(attempt_store, session_id=session.session_id)

    first = attempt_store.establish_attempt_ownership(
        session_id=session.session_id,
        proposed_attempt=attempt,
        expected_revision=session.revision,
    )
    second = attempt_store.establish_attempt_ownership(
        session_id=session.session_id,
        proposed_attempt=attempt,
        expected_revision=None,
    )

    assert second.session.revision == first.session.revision
    assert len(attempt_store.list_attempts(session_id=session.session_id)) == 1


def test_reconcile_from_frozen_manifest_only_partial_state(tmp_path: Path):
    root = tmp_path / "investigation_sessions"
    session_store = InvestigationSessionStore(root)
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)

    finalization_dir = root / session.session_id / "finalization"
    finalization_dir.mkdir(parents=True, exist_ok=True)
    (finalization_dir / "frozen_manifest.json").write_text("{}", encoding="utf-8")

    attempt = _prepared_attempt(attempt_store, session_id=session.session_id)
    result = attempt_store.establish_attempt_ownership(
        session_id=session.session_id,
        proposed_attempt=attempt,
        expected_revision=session.revision,
    )

    assert result.reconciliation_action == "reconcile_from_frozen_manifest_state"
    assert result.session.active_analysis_attempt_id == attempt.analysis_attempt_id


def test_cross_session_attempt_mismatch_is_rejected(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)

    session_a = _finalizing_session(session_store)
    session_b = _finalizing_session(session_store)

    attempt_a = _prepared_attempt(attempt_store, session_id=session_a.session_id)
    attempt_store.save_attempt(attempt_a)

    proposed_for_b = _prepared_attempt(
        attempt_store,
        session_id=session_b.session_id,
        analysis_attempt_id=attempt_a.analysis_attempt_id,
    )

    with pytest.raises(InvestigationAnalysisAttemptConflict):
        attempt_store.establish_attempt_ownership(
            session_id=session_b.session_id,
            proposed_attempt=proposed_for_b,
            expected_revision=session_b.revision,
        )


def test_step3_scope_no_provider_result_or_api_side_effects(tmp_path: Path):
    root = tmp_path / "investigation_sessions"
    session_store = InvestigationSessionStore(root)
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    attempt = _prepared_attempt(attempt_store, session_id=session.session_id)

    attempt_store.establish_attempt_ownership(
        session_id=session.session_id,
        proposed_attempt=attempt,
        expected_revision=session.revision,
    )

    assert not (root / "results").exists()
    assert not (root / "latest.json").exists()
    assert len(list((root / session.session_id / "finalization" / "analysis_attempts").glob("*.json"))) == 1


def test_atomic_write_failure_translates_to_store_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    attempt = _prepared_attempt(attempt_store, session_id=session.session_id)

    def _fail_replace(_src: str, _dst: str) -> None:
        raise OSError("forced failure")

    monkeypatch.setattr(attempt_module.os, "replace", _fail_replace)
    with pytest.raises(InvestigationAnalysisAttemptStoreError):
        attempt_store.save_attempt(attempt)


def test_stage2_revision_conflict_leaves_durable_attempt_intact(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    attempt = _prepared_attempt(attempt_store, session_id=session.session_id)

    with pytest.raises(InvestigationAnalysisAttemptOwnershipError):
        attempt_store.establish_attempt_ownership(
            session_id=session.session_id,
            proposed_attempt=attempt,
            expected_revision=session.revision + 99,
        )

    loaded = attempt_store.load_attempt(session_id=session.session_id, analysis_attempt_id=attempt.analysis_attempt_id)
    assert loaded.analysis_attempt_id == attempt.analysis_attempt_id

    reloaded_session = session_store.load_session(session.session_id)
    assert reloaded_session.active_analysis_attempt_id is None


def test_no_attempt_file_work_runs_inside_session_mutator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    attempt = _prepared_attempt(attempt_store, session_id=session.session_id)

    in_mutator = {"value": False}

    real_mutate_session = session_store.mutate_session

    def _wrapped_mutate(session_id, mutator):
        def _wrapped(current):
            in_mutator["value"] = True
            try:
                return mutator(current)
            finally:
                in_mutator["value"] = False

        return real_mutate_session(session_id, _wrapped)

    monkeypatch.setattr(session_store, "mutate_session", _wrapped_mutate)

    real_save_attempt = attempt_store.save_attempt
    real_list_attempts = attempt_store.list_attempts
    real_foreign_scan = attempt_store._find_foreign_attempt_session

    def _guarded_save(attempt_record):
        if in_mutator["value"]:
            raise AssertionError("save_attempt executed inside mutator")
        return real_save_attempt(attempt_record)

    def _guarded_list(*, session_id: str):
        if in_mutator["value"]:
            raise AssertionError("list_attempts executed inside mutator")
        return real_list_attempts(session_id=session_id)

    def _guarded_foreign_scan(*, analysis_attempt_id: str, excluded_session_id: str):
        if in_mutator["value"]:
            raise AssertionError("foreign-session scan executed inside mutator")
        return real_foreign_scan(analysis_attempt_id=analysis_attempt_id, excluded_session_id=excluded_session_id)

    monkeypatch.setattr(attempt_store, "save_attempt", _guarded_save)
    monkeypatch.setattr(attempt_store, "list_attempts", _guarded_list)
    monkeypatch.setattr(attempt_store, "_find_foreign_attempt_session", _guarded_foreign_scan)

    result = attempt_store.establish_attempt_ownership(
        session_id=session.session_id,
        proposed_attempt=attempt,
        expected_revision=session.revision,
    )

    assert result.session.active_analysis_attempt_id == attempt.analysis_attempt_id


def test_attempt_persistence_happens_before_session_pointer_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    attempt = _prepared_attempt(attempt_store, session_id=session.session_id)

    state = {"save_called": False, "save_completed": False}
    observed = {"session_active_when_mutator_runs": None}

    real_save_attempt = attempt_store.save_attempt

    def _tracking_save(attempt_record):
        state["save_called"] = True
        result = real_save_attempt(attempt_record)
        state["save_completed"] = True
        return result

    real_mutate_session = session_store.mutate_session

    def _tracking_mutate(session_id, mutator):
        assert state["save_called"] is True
        assert state["save_completed"] is True

        def _wrapped(current):
            observed["session_active_when_mutator_runs"] = current.active_analysis_attempt_id
            return mutator(current)

        return real_mutate_session(session_id, _wrapped)

    monkeypatch.setattr(attempt_store, "save_attempt", _tracking_save)
    monkeypatch.setattr(session_store, "mutate_session", _tracking_mutate)

    result = attempt_store.establish_attempt_ownership(
        session_id=session.session_id,
        proposed_attempt=attempt,
        expected_revision=session.revision,
    )

    assert result.session.active_analysis_attempt_id == attempt.analysis_attempt_id
    assert observed["session_active_when_mutator_runs"] is None


def test_malformed_attempt_json_load_is_rejected_safely(tmp_path: Path):
    root = tmp_path / "investigation_sessions"
    session_store = InvestigationSessionStore(root)
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)
    attempt_id = str(uuid4())

    attempt_path = root / session.session_id / "finalization" / "analysis_attempts" / f"{attempt_id}.json"
    attempt_path.parent.mkdir(parents=True, exist_ok=True)
    attempt_path.write_text("{ bad-json", encoding="utf-8")

    with pytest.raises(InvestigationAnalysisAttemptStoreError):
        attempt_store.load_attempt(session_id=session.session_id, analysis_attempt_id=attempt_id)


def test_malformed_attempt_json_list_is_rejected_safely(tmp_path: Path):
    root = tmp_path / "investigation_sessions"
    session_store = InvestigationSessionStore(root)
    attempt_store = InvestigationAnalysisAttemptStore(session_store)
    session = _finalizing_session(session_store)

    attempt_path = root / session.session_id / "finalization" / "analysis_attempts" / f"{uuid4()}.json"
    attempt_path.parent.mkdir(parents=True, exist_ok=True)
    attempt_path.write_text("{ malformed", encoding="utf-8")

    with pytest.raises(InvestigationAnalysisAttemptStoreError):
        attempt_store.list_attempts(session_id=session.session_id)
