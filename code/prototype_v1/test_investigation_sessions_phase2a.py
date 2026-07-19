from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api
import investigations.session_store as session_store_module
from investigations.models import (
    INVESTIGATION_SESSION_SCHEMA_VERSION,
    InvestigationEvidenceCreateRequest,
    InvestigationEvidenceType,
    InvestigationRetainedResult,
    InvestigationSessionErrorMetadata,
    InvestigationSession,
    InvestigationSessionStatus,
    create_new_investigation_session,
)
from investigations.result_store import save_canonical_investigation_result
from investigations.result_store import load_canonical_investigation_result, load_latest_investigation_result
from investigations.session_lifecycle import (
    InvestigationSessionLifecycleError,
    apply_cancel_transition,
    apply_pause_transition,
    apply_resume_transition,
)
from investigations.session_store import (
    InvestigationSessionInvalidId,
    InvestigationSessionNotFound,
    InvestigationSessionStore,
    InvestigationSessionStoreError,
)
from investigations.evidence_store import InvestigationEvidenceStoreError


@pytest.fixture
def session_test_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "investigation_sessions"
    store = InvestigationSessionStore(root)
    monkeypatch.setattr(api, "INVESTIGATION_SESSIONS_ROOT", root)
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", tmp_path / "investigation_latest.json")
    monkeypatch.setattr(api, "SESSION_STORE", store)
    monkeypatch.setattr(api, "EVIDENCE_STORE", api.InvestigationEvidenceStore(store))
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")
    client = TestClient(api.app)
    return client, store, root


def _session_file_path(root: Path, session_id: str) -> Path:
    return root / "sessions" / f"{session_id}.json"


def _collecting_copy(session: InvestigationSession) -> InvestigationSession:
    now = datetime.now(timezone.utc)
    return session.model_copy(
        update={
            "status": InvestigationSessionStatus.COLLECTING,
            "revision": session.revision + 1,
            "updated_at_utc": now,
        }
    )


def _paused_copy(session: InvestigationSession) -> InvestigationSession:
    now = datetime.now(timezone.utc)
    return session.model_copy(
        update={
            "status": InvestigationSessionStatus.PAUSED,
            "revision": session.revision + 1,
            "updated_at_utc": now,
            "paused_at_utc": now,
        }
    )


def _cancelled_copy(session: InvestigationSession) -> InvestigationSession:
    now = datetime.now(timezone.utc)
    return session.model_copy(
        update={
            "status": InvestigationSessionStatus.CANCELLED,
            "revision": session.revision + 1,
            "updated_at_utc": now,
            "cancelled_at_utc": now,
        }
    )


def _create_collecting_session(client: TestClient) -> str:
    created = client.post("/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    session = api.SESSION_STORE.load_session(session_id)
    collecting = session.model_copy(
        update={
            "status": InvestigationSessionStatus.COLLECTING,
            "revision": session.revision + 1,
            "updated_at_utc": datetime.now(timezone.utc),
        }
    )
    api.SESSION_STORE.save_session(collecting)
    return session_id


def _upload_image(client: TestClient, session_id: str, *, name: str, content: bytes, normalized_text: str = "") -> str:
    response = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        data={"normalized_text": normalized_text},
        files={"file": (name, content, "image/png")},
    )
    assert response.status_code == 201
    return response.json()["evidence_id"]


def _upload_audio(client: TestClient, session_id: str, *, name: str, content: bytes, normalized_text: str) -> str:
    response = client.post(
        f"/investigation-sessions/{session_id}/evidence/audio",
        data={"normalized_text": normalized_text, "duration_seconds": 1.2},
        files={"file": (name, content, "audio/wav")},
    )
    assert response.status_code == 201
    return response.json()["evidence_id"]


class _StaticProvider:
    def analyze(self, _request_package):
        return api.InvestigationAnalysisResponse(
            schema_version=api.INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
            concise_diagnosis="Session analysis completed.",
            immediate_recommended_action="Capture one follow-up image if uncertainty remains.",
            supporting_observations=["Evidence ordered and parsed."],
            confidence_or_uncertainty="Moderate confidence.",
            warning_or_blocker=None,
            follow_up_capture_request=None,
        )


class _FailingProvider:
    def analyze(self, _request_package):
        raise api.InvestigationAnalysisProviderError("provider failure")


class _RaisingPersistence:
    def load_completed_result(self, *, session_id: str):
        return None

    def persist_result(self, *, session, request_package, response):
        raise RuntimeError("simulated persistence failure")


def _real_orchestrator_with_provider(provider):
    return api.InvestigationOrchestrator(
        session_store=api.SESSION_STORE,
        evidence_store=api.EVIDENCE_STORE,
        attempt_store=api.InvestigationAnalysisAttemptStore(api.SESSION_STORE),
        analysis_provider=provider,
        result_persistence=api._SessionRouteResultPersistence(),
    )


def test_model_valid_session_creation_defaults():
    session = create_new_investigation_session(client_metadata={"source": "desktop", "attempt": 1})

    assert session.schema_version == INVESTIGATION_SESSION_SCHEMA_VERSION
    assert session.status == InvestigationSessionStatus.CREATED
    assert session.revision == 0
    assert session.created_at_utc.tzinfo is not None
    assert session.updated_at_utc.tzinfo is not None


def test_model_uuid_validation_rejects_invalid_id():
    with pytest.raises(ValidationError):
        InvestigationSession.model_validate(
            {
                "schema_version": INVESTIGATION_SESSION_SCHEMA_VERSION,
                "session_id": "not-a-uuid",
                "status": "created",
                "revision": 0,
                "created_at_utc": datetime.now(timezone.utc),
                "updated_at_utc": datetime.now(timezone.utc),
            }
        )


def test_model_timezone_aware_timestamps_required():
    with pytest.raises(ValidationError):
        InvestigationSession.model_validate(
            {
                "schema_version": INVESTIGATION_SESSION_SCHEMA_VERSION,
                "session_id": str(create_new_investigation_session().session_id),
                "status": "created",
                "revision": 0,
                "created_at_utc": datetime.now(),
                "updated_at_utc": datetime.now(timezone.utc),
            }
        )


def test_model_invalid_status_rejected():
    with pytest.raises(ValidationError):
        InvestigationSession.model_validate(
            {
                "schema_version": INVESTIGATION_SESSION_SCHEMA_VERSION,
                "session_id": str(create_new_investigation_session().session_id),
                "status": "ready",
                "revision": 0,
                "created_at_utc": datetime.now(timezone.utc),
                "updated_at_utc": datetime.now(timezone.utc),
            }
        )


def test_model_client_metadata_bounds_enforced():
    too_many = {f"k{i}": "v" for i in range(17)}
    with pytest.raises(ValidationError):
        create_new_investigation_session(client_metadata=too_many)


@pytest.mark.parametrize(
    "payload",
    [
        {"error_category": "x" * 65, "retryable": True, "occurred_at_utc": datetime.now(timezone.utc), "safe_message": "ok"},
        {"error_category": "category", "retryable": True, "occurred_at_utc": datetime.now(timezone.utc), "safe_message": "x" * 301},
            {"error_category": "category", "retryable": [], "occurred_at_utc": datetime.now(timezone.utc), "safe_message": "ok"},
        {"error_category": "category", "retryable": True, "occurred_at_utc": datetime.now(), "safe_message": "ok"},
        {"error_category": "category", "retryable": True, "safe_message": "ok"},
        {"error_category": "category", "retryable": True, "occurred_at_utc": datetime.now(timezone.utc), "safe_message": "ok", "extra": "nope"},
    ],
)
def test_model_last_error_invalid_values_rejected(payload):
    with pytest.raises(ValidationError):
        InvestigationSessionErrorMetadata.model_validate(payload)


def test_store_save_load_round_trip_and_one_file(tmp_path: Path):
    store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    session = create_new_investigation_session(client_metadata={"source": "desktop"})
    store.save_session(session)

    loaded = store.load_session(session.session_id)
    assert loaded.session_id == session.session_id
    assert loaded.status == InvestigationSessionStatus.CREATED

    files = list((tmp_path / "investigation_sessions" / "sessions").glob("*.json"))
    assert len(files) == 1


def test_store_atomic_replace_failure_preserves_prior_file_and_cleans_temp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "investigation_sessions"
    store = InvestigationSessionStore(root)
    session = create_new_investigation_session()
    store.save_session(session)

    session_path = _session_file_path(root, session.session_id)
    before = session_path.read_text(encoding="utf-8")

    updated = session.model_copy(
        update={
            "status": InvestigationSessionStatus.PAUSED,
            "revision": session.revision + 1,
            "updated_at_utc": datetime.now(timezone.utc),
            "paused_at_utc": datetime.now(timezone.utc),
        }
    )

    def _raise_replace(_src: str, _dst: str) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(session_store_module.os, "replace", _raise_replace)

    with pytest.raises(InvestigationSessionStoreError):
        store.save_session(updated)

    assert session_path.read_text(encoding="utf-8") == before
    temp_files = list((root / "temp").glob("*.tmp"))
    assert temp_files == []


def test_store_malformed_json_is_quarantined(tmp_path: Path):
    root = tmp_path / "investigation_sessions"
    store = InvestigationSessionStore(root)
    session = create_new_investigation_session()
    session_path = _session_file_path(root, session.session_id)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text("{ malformed", encoding="utf-8")

    with pytest.raises(InvestigationSessionStoreError):
        store.load_session(session.session_id)

    assert not session_path.exists()
    assert list((root / "corrupt").glob("*.json"))


def test_store_path_traversal_rejected(tmp_path: Path):
    store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    with pytest.raises(InvestigationSessionInvalidId):
        store.load_session("..\\..\\evil")


def test_store_uses_isolated_root_and_supports_reload(tmp_path: Path):
    root = tmp_path / "isolated_root"
    store_a = InvestigationSessionStore(root)
    session = create_new_investigation_session()
    store_a.save_session(session)

    store_b = InvestigationSessionStore(root)
    loaded = store_b.load_session(session.session_id)
    assert loaded.session_id == session.session_id


def test_lifecycle_created_to_paused_and_collecting_to_paused():
    created = create_new_investigation_session()
    paused_from_created, changed_created = apply_pause_transition(created, expected_revision=0)
    assert changed_created is True
    assert paused_from_created.status == InvestigationSessionStatus.PAUSED
    assert paused_from_created.revision == 1

    collecting = _collecting_copy(created)
    paused_from_collecting, changed_collecting = apply_pause_transition(collecting, expected_revision=1)
    assert changed_collecting is True
    assert paused_from_collecting.status == InvestigationSessionStatus.PAUSED


def test_lifecycle_paused_to_collecting():
    created = create_new_investigation_session()
    paused, _ = apply_pause_transition(created, expected_revision=0)
    resumed, changed = apply_resume_transition(paused, expected_revision=1)
    assert changed is True
    assert resumed.status == InvestigationSessionStatus.COLLECTING


def test_lifecycle_cancel_from_created_collecting_paused():
    created = create_new_investigation_session()
    cancelled_created, changed_created = apply_cancel_transition(created, expected_revision=0)
    assert changed_created is True
    assert cancelled_created.status == InvestigationSessionStatus.CANCELLED

    collecting = _collecting_copy(created)
    cancelled_collecting, changed_collecting = apply_cancel_transition(collecting, expected_revision=1)
    assert changed_collecting is True
    assert cancelled_collecting.status == InvestigationSessionStatus.CANCELLED

    paused, _ = apply_pause_transition(created, expected_revision=0)
    cancelled_paused, changed_paused = apply_cancel_transition(paused, expected_revision=1)
    assert changed_paused is True
    assert cancelled_paused.status == InvestigationSessionStatus.CANCELLED


def test_lifecycle_idempotent_noop_rules_and_revision_behavior():
    created = create_new_investigation_session()
    paused, _ = apply_pause_transition(created, expected_revision=0)
    paused_before = paused.model_dump(mode="json")

    paused_again, changed_pause = apply_pause_transition(paused, expected_revision=1)
    assert changed_pause is False
    assert paused_again.revision == paused.revision
    assert paused_again.updated_at_utc == paused.updated_at_utc
    assert paused_again.model_dump(mode="json") == paused_before

    collecting = _collecting_copy(created)
    collecting_before = collecting.model_dump(mode="json")
    collecting_again, changed_resume = apply_resume_transition(collecting, expected_revision=1)
    assert changed_resume is False
    assert collecting_again.revision == collecting.revision
    assert collecting_again.updated_at_utc == collecting.updated_at_utc
    assert collecting_again.model_dump(mode="json") == collecting_before

    cancelled, _ = apply_cancel_transition(created, expected_revision=0)
    cancelled_before = cancelled.model_dump(mode="json")
    cancelled_again, changed_cancel = apply_cancel_transition(cancelled, expected_revision=1)
    assert changed_cancel is False
    assert cancelled_again.revision == cancelled.revision
    assert cancelled_again.updated_at_utc == cancelled.updated_at_utc
    assert cancelled_again.model_dump(mode="json") == cancelled_before


def test_lifecycle_invalid_transitions_and_revision_conflict():
    created = create_new_investigation_session()
    with pytest.raises(InvestigationSessionLifecycleError):
        apply_resume_transition(created, expected_revision=0)

    cancelled, _ = apply_cancel_transition(created, expected_revision=0)
    with pytest.raises(InvestigationSessionLifecycleError):
        apply_resume_transition(cancelled, expected_revision=1)

    with pytest.raises(InvestigationSessionLifecycleError) as exc_info:
        apply_pause_transition(created, expected_revision=99)
    assert exc_info.value.category == "revision_conflict"


def test_api_create_and_get_success(session_test_context):
    client, _, _ = session_test_context

    created = client.post("/investigation-sessions", json={"client_metadata": {"source": "desktop"}})
    assert created.status_code == 201
    payload = created.json()
    assert payload["status"] == "created"
    assert payload["revision"] == 0

    fetched = client.get(f"/investigation-sessions/{payload['session_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["session_id"] == payload["session_id"]


def test_api_get_missing_session_returns_404(session_test_context):
    client, _, _ = session_test_context
    missing_id = create_new_investigation_session().session_id

    response = client.get(f"/investigation-sessions/{missing_id}")
    assert response.status_code == 404
    assert response.json()["detail"]["category"] == "session_not_found"


def test_api_poll_session_missing_returns_404(session_test_context):
    client, _, _ = session_test_context
    missing_id = create_new_investigation_session().session_id

    response = client.get(f"/investigation-sessions/{missing_id}/poll")
    assert response.status_code == 404
    assert response.json()["detail"]["category"] == "session_not_found"


def test_api_invalid_session_id_returns_422(session_test_context):
    client, _, _ = session_test_context
    response = client.get("/investigation-sessions/not-a-uuid")
    assert response.status_code == 422
    assert response.json()["detail"]["category"] == "invalid_session_id"


def test_api_poll_invalid_session_id_returns_422(session_test_context):
    client, _, _ = session_test_context
    response = client.get("/investigation-sessions/not-a-uuid/poll")
    assert response.status_code == 422
    assert response.json()["detail"]["category"] == "invalid_session_id"


def test_api_first_image_upload_from_created_auto_starts_collecting(session_test_context):
    client, store, _ = session_test_context
    created = client.post("/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    response = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        data={"normalized_text": "initial explanation"},
        files={"file": ("first.png", b"image-bytes", "image/png")},
    )
    assert response.status_code == 201

    updated = store.load_session(session_id)
    assert updated.status == InvestigationSessionStatus.COLLECTING
    assert updated.revision == 1


def test_api_image_upload_rejects_cancelled_session_even_with_auto_start_logic(session_test_context):
    client, store, _ = session_test_context
    created = client.post("/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    cancelled = client.post(f"/investigation-sessions/{session_id}/cancel", json={"expected_revision": 0})
    assert cancelled.status_code == 200
    cancelled_revision = cancelled.json()["revision"]

    response = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        data={"normalized_text": "should fail"},
        files={"file": ("cancelled.png", b"image-bytes", "image/png")},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["category"] == "invalid_state_transition"

    unchanged = store.load_session(session_id)
    assert unchanged.status == InvestigationSessionStatus.CANCELLED
    assert unchanged.revision == cancelled_revision


def test_api_analyze_missing_session_returns_404(session_test_context):
    client, _, _ = session_test_context
    missing_id = create_new_investigation_session().session_id

    response = client.post(f"/investigation-sessions/{missing_id}/analyze", json={})
    assert response.status_code == 404
    assert response.json()["detail"]["category"] == "session_not_found"


def test_api_analyze_requires_at_least_one_image(session_test_context):
    client, _, _ = session_test_context
    session_id = _create_collecting_session(client)
    _upload_audio(client, session_id, name="voice.wav", content=b"voice", normalized_text="spoken explanation")

    response = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert response.status_code == 422
    assert response.json()["detail"]["category"] == "insufficient_evidence"


def test_api_analyze_rejects_more_than_three_images(session_test_context):
    client, _, _ = session_test_context
    session_id = _create_collecting_session(client)

    _upload_image(client, session_id, name="a.png", content=b"a", normalized_text="explanation")
    _upload_image(client, session_id, name="b.png", content=b"b")
    _upload_image(client, session_id, name="c.png", content=b"c")
    _upload_image(client, session_id, name="d.png", content=b"d")

    response = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert response.status_code == 422
    assert response.json()["detail"]["category"] == "too_many_images"


def test_api_analyze_rejects_cancelled_session(session_test_context):
    client, _, _ = session_test_context
    created = client.post("/investigation-sessions", json={})
    session_id = created.json()["session_id"]
    cancelled = client.post(f"/investigation-sessions/{session_id}/cancel", json={"expected_revision": 0})
    assert cancelled.status_code == 200

    response = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert response.status_code == 409
    assert response.json()["detail"]["category"] == "invalid_state_transition"


def test_api_analyze_conflicts_while_already_analyzing(session_test_context):
    client, store, _ = session_test_context
    session_id = _create_collecting_session(client)
    session = store.load_session(session_id)
    store.save_session(
        session.model_copy(
            update={
                "status": InvestigationSessionStatus.ANALYZING,
                "revision": session.revision + 1,
                "updated_at_utc": datetime.now(timezone.utc),
            }
        )
    )

    response = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert response.status_code == 409
    assert response.json()["detail"]["category"] == "analysis_attempt_conflict"


def test_api_analyze_completed_session_does_not_invoke_orchestrator_again(session_test_context, monkeypatch: pytest.MonkeyPatch):
    client, store, _ = session_test_context
    session_id = _create_collecting_session(client)
    result_id = str(uuid4())
    session = store.load_session(session_id)
    store.save_session(
        session.model_copy(
            update={
                "status": InvestigationSessionStatus.COMPLETED,
                "revision": session.revision + 1,
                "updated_at_utc": datetime.now(timezone.utc),
                "completed_result_id": result_id,
            }
        )
    )

    retained = InvestigationRetainedResult(
        schema_version="1.0",
        projection_version="1.0",
        investigation_id="inv-completed",
        session_id=session_id,
        status="analyzed",
        diagnosis="Done",
        required_next_action="No-op",
        image_count=2,
        image_order=["1:a.png", "2:b.png"],
        used_user_explanation="explanation",
        completed_at_utc=datetime.now(timezone.utc),
        context_used=False,
        context_staleness="unknown",
        context_signal_age_seconds=None,
        copilot_prompt="Prompt",
    )
    save_canonical_investigation_result(api.INVESTIGATION_LATEST_JSON.parent / "investigations", result_id=result_id, retained_result=retained)

    class _ForbiddenOrchestrator:
        def run_confirmed_investigation(self, **_kwargs):
            raise AssertionError("orchestrator should not run for completed sessions")

    monkeypatch.setattr(api, "_create_session_orchestrator", lambda: _ForbiddenOrchestrator())

    response = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_api_analyze_order_and_explanation_reach_orchestrator_context(session_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _, _ = session_test_context
    session_id = _create_collecting_session(client)

    first_id = _upload_image(client, session_id, name="one.png", content=b"1")
    second_id = _upload_image(client, session_id, name="two.png", content=b"2")
    _upload_audio(client, session_id, name="voice.wav", content=b"v", normalized_text="spoken explanation")

    captured: dict[str, object] = {"calls": 0, "context": None}

    class _RecordingOrchestrator:
        def run_confirmed_investigation(self, **kwargs):
            captured["calls"] += 1
            captured["context"] = kwargs["interaction_context"]
            session = api.SESSION_STORE.load_session(session_id)
            completed = session.model_copy(
                update={
                    "status": InvestigationSessionStatus.COMPLETED,
                    "revision": session.revision + 1,
                    "updated_at_utc": datetime.now(timezone.utc),
                    "completed_result_id": str(uuid4()),
                }
            )
            api.SESSION_STORE.save_session(completed)
            return api.InvestigationOrchestrationOutcome(
                session_id=session_id,
                analysis_attempt_id=None,
                result_id=completed.completed_result_id,
                response=None,
                persistence_deferred=False,
                provider_invoked=False,
                completed=True,
                progress_events=[],
            )

    monkeypatch.setattr(api, "_create_session_orchestrator", lambda: _RecordingOrchestrator())

    response = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert response.status_code == 200
    assert captured["calls"] == 1
    context = captured["context"]
    assert context.selected_capture_evidence_ids == [first_id, second_id]
    assert context.normalized_explanation_text == "spoken explanation"


def test_api_analyze_success_persists_result_and_poll_returns_compact(session_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _, _ = session_test_context
    session_id = _create_collecting_session(client)

    _upload_image(client, session_id, name="a.png", content=b"a", normalized_text="typed explanation")
    _upload_image(client, session_id, name="b.png", content=b"b")

    monkeypatch.setattr(api, "_create_session_orchestrator", lambda: _real_orchestrator_with_provider(_StaticProvider()))

    trigger = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert trigger.status_code == 200
    assert trigger.json()["accepted"] is True
    assert trigger.json()["status"] == "completed"
    assert trigger.json()["result_available"] is True

    poll = client.get(f"/investigation-sessions/{session_id}/poll")
    assert poll.status_code == 200
    assert poll.json()["status"] == "completed"
    assert poll.json()["result_available"] is True
    assert poll.json()["compact_result"] is not None


def test_api_analyze_single_image_success_persists_result_and_poll_returns_compact(session_test_context, monkeypatch: pytest.MonkeyPatch):
    client, store, _ = session_test_context
    session_id = _create_collecting_session(client)

    _upload_image(
        client,
        session_id,
        name="single.png",
        content=b"single",
        normalized_text="Analyze what is shown in this image and give me the single most useful next action.",
    )

    monkeypatch.setattr(api, "_create_session_orchestrator", lambda: _real_orchestrator_with_provider(_StaticProvider()))

    trigger = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert trigger.status_code == 200
    trigger_payload = trigger.json()
    assert trigger_payload["accepted"] is True
    assert trigger_payload["status"] == "completed"
    assert trigger_payload["result_available"] is True

    completed_session = store.load_session(session_id)
    assert completed_session.status == InvestigationSessionStatus.COMPLETED
    assert completed_session.completed_result_id is not None

    canonical = load_canonical_investigation_result(
        api.INVESTIGATION_LATEST_JSON.parent / "investigations",
        completed_session.completed_result_id,
    )
    assert canonical.session_id == session_id
    assert canonical.retained_result.image_count == 1
    assert canonical.retained_result.image_order == ["1:single.png"]

    latest = load_latest_investigation_result(api.INVESTIGATION_LATEST_JSON)
    assert latest.session_id == session_id
    assert latest.investigation_id == canonical.retained_result.investigation_id

    poll = client.get(f"/investigation-sessions/{session_id}/poll")
    assert poll.status_code == 200
    poll_payload = poll.json()
    assert poll_payload["status"] == "completed"
    assert poll_payload["result_available"] is True
    assert poll_payload["compact_result"] is not None


def test_api_analyze_failure_transitions_to_failed_and_poll_reports_error(session_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _, _ = session_test_context
    session_id = _create_collecting_session(client)

    _upload_image(client, session_id, name="a.png", content=b"a", normalized_text="typed explanation")

    monkeypatch.setattr(api, "_create_session_orchestrator", lambda: _real_orchestrator_with_provider(_FailingProvider()))

    trigger = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert trigger.status_code == 500
    assert trigger.json()["detail"]["category"] == "provider_failure"

    poll = client.get(f"/investigation-sessions/{session_id}/poll")
    assert poll.status_code == 200
    assert poll.json()["status"] == "failed"
    assert poll.json()["error"] is not None
    assert poll.json()["error"]["category"] == "provider_failure"


def test_api_analyze_persistence_failure_transitions_to_failed_and_poll_reports_safe_error(
    session_test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    client, _, _ = session_test_context
    session_id = _create_collecting_session(client)

    _upload_image(client, session_id, name="single.png", content=b"single", normalized_text="typed explanation")

    monkeypatch.setattr(
        api,
        "_create_session_orchestrator",
        lambda: api.InvestigationOrchestrator(
            session_store=api.SESSION_STORE,
            evidence_store=api.EVIDENCE_STORE,
            attempt_store=api.InvestigationAnalysisAttemptStore(api.SESSION_STORE),
            analysis_provider=_StaticProvider(),
            result_persistence=_RaisingPersistence(),
        ),
    )

    trigger = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert trigger.status_code == 500
    trigger_payload = trigger.json()
    assert trigger_payload["detail"]["category"] == "result_persistence_failure"
    assert "simulated persistence failure" not in json.dumps(trigger_payload).lower()

    poll = client.get(f"/investigation-sessions/{session_id}/poll")
    assert poll.status_code == 200
    poll_payload = poll.json()
    assert poll_payload["status"] == "failed"
    assert poll_payload["result_available"] is False
    assert poll_payload["compact_result"] is None
    assert poll_payload["error"] is not None
    assert poll_payload["error"]["category"] == "result_persistence_failure"


def test_api_analyze_route_does_not_call_openai_directly(session_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _, _ = session_test_context
    session_id = _create_collecting_session(client)

    _upload_image(client, session_id, name="a.png", content=b"a", normalized_text="typed explanation")

    calls = {"openai": 0}

    class _ForbiddenOpenAI:
        def __init__(self, *_args, **_kwargs):
            calls["openai"] += 1

    monkeypatch.setattr(api, "OpenAI", _ForbiddenOpenAI)
    monkeypatch.setattr(api, "_create_session_orchestrator", lambda: _real_orchestrator_with_provider(_StaticProvider()))

    trigger = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert trigger.status_code in {200, 500}
    assert calls["openai"] == 0


def test_api_poll_processing_has_no_compact_result(session_test_context):
    client, store, _ = session_test_context

    created = client.post("/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    session = store.load_session(session_id)
    analyzing = session.model_copy(
        update={
            "status": InvestigationSessionStatus.ANALYZING,
            "revision": session.revision + 1,
            "updated_at_utc": datetime.now(timezone.utc),
        }
    )
    store.save_session(analyzing)

    response = client.get(f"/investigation-sessions/{session_id}/poll")
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["status"] == "analyzing"
    assert payload["compact_result"] is None
    assert payload["result_available"] is False
    assert payload["investigation_id"] is None
    assert payload["poll_after_ms"] == api.POLL_HINT_MS_PROCESSING


def test_api_poll_completed_has_compact_result_and_is_idempotent(session_test_context):
    client, store, _ = session_test_context

    created = client.post("/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    result_id = str(uuid4())
    session = store.load_session(session_id)
    completed = session.model_copy(
        update={
            "status": InvestigationSessionStatus.COMPLETED,
            "revision": session.revision + 1,
            "updated_at_utc": datetime.now(timezone.utc),
            "completed_result_id": result_id,
        }
    )
    store.save_session(completed)

    retained = InvestigationRetainedResult(
        schema_version="1.0",
        projection_version="1.0",
        investigation_id="inv-mobile-1",
        session_id=session_id,
        status="validated",
        diagnosis="Diagnosis",
        required_next_action="Capture one clearer screenshot.",
        image_count=2,
        image_order=["1:first.png", "2:second.png"],
        used_user_explanation="explanation",
        completed_at_utc=datetime.now(timezone.utc),
        context_used=False,
        context_staleness="unknown",
        context_signal_age_seconds=None,
        copilot_prompt="Prompt",
    )
    save_canonical_investigation_result(api.INVESTIGATION_LATEST_JSON.parent / "investigations", result_id=result_id, retained_result=retained)

    first = client.get(f"/investigation-sessions/{session_id}/poll")
    second = client.get(f"/investigation-sessions/{session_id}/poll")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    payload = first.json()
    assert payload["session_id"] == session_id
    assert payload["status"] == "completed"
    assert payload["investigation_id"] == "inv-mobile-1"
    assert payload["result_available"] is True
    assert payload["compact_result"] is not None
    assert payload["poll_after_ms"] == api.POLL_HINT_MS_COMPLETED


def test_api_poll_includes_session_scoped_image_and_explanation_signals(session_test_context):
    client, store, _ = session_test_context

    created = client.post("/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    collecting = store.load_session(session_id).model_copy(
        update={
            "status": InvestigationSessionStatus.COLLECTING,
            "revision": 1,
            "updated_at_utc": datetime.now(timezone.utc),
        }
    )
    store.save_session(collecting)

    request = InvestigationEvidenceCreateRequest(
        source="android",
        normalized_text="Terminal shows a 401 error on the latest call.",
    )
    api.EVIDENCE_STORE.upload_evidence(
        session_id=session_id,
        evidence_type=InvestigationEvidenceType.IMAGE,
        raw_bytes=b"fake-image-content",
        mime_type="image/png",
        original_filename="capture.png",
        request=request,
    )

    response = client.get(f"/investigation-sessions/{session_id}/poll")
    assert response.status_code == 200
    payload = response.json()
    assert payload["image_count"] == 1
    assert payload["explanation_present"] is True


def test_api_poll_repeated_requests_do_not_mutate_session_state(session_test_context):
    client, store, _ = session_test_context

    created = client.post("/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    before = store.load_session(session_id)

    first = client.get(f"/investigation-sessions/{session_id}/poll")
    second = client.get(f"/investigation-sessions/{session_id}/poll")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["created_at"] == second.json()["created_at"]
    assert first.json()["updated_at"] == second.json()["updated_at"]

    after = store.load_session(session_id)
    assert after.model_dump(mode="json") == before.model_dump(mode="json")


def test_api_poll_storage_error_is_structured(session_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _, _ = session_test_context

    created = client.post("/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    monkeypatch.setattr(
        api.EVIDENCE_STORE,
        "list_evidence_for_analysis",
        lambda _session_id: (_ for _ in ()).throw(InvestigationEvidenceStoreError("disk failed")),
    )
    response = client.get(f"/investigation-sessions/{session_id}/poll")
    assert response.status_code == 500
    assert response.json()["detail"]["category"] == "evidence_storage_error"
    assert "disk failed" not in json.dumps(response.json()).lower()


def test_api_poll_does_not_invoke_analysis_or_result_persistence(session_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _, _ = session_test_context

    counters = {"analyze": 0, "save": 0}

    async def _forbidden_analyze(*_args, **_kwargs):
        counters["analyze"] += 1
        raise AssertionError("poll route must not analyze")

    def _forbidden_save(*_args, **_kwargs):
        counters["save"] += 1
        raise AssertionError("poll route must not persist latest results")

    monkeypatch.setattr(api, "analyze_investigation_request_with_retained", _forbidden_analyze)
    monkeypatch.setattr(api, "save_latest_investigation_result", _forbidden_save)

    created = client.post("/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    response = client.get(f"/investigation-sessions/{session_id}/poll")
    assert response.status_code == 200
    assert counters["analyze"] == 0
    assert counters["save"] == 0


def test_api_pause_resume_cancel_behaviors(session_test_context):
    client, store, _ = session_test_context

    created = client.post("/investigation-sessions", json={})
    session_id = created.json()["session_id"]

    pause_from_created = client.post(f"/investigation-sessions/{session_id}/pause", json={"expected_revision": 0})
    assert pause_from_created.status_code == 200
    assert pause_from_created.json()["status"] == "paused"
    assert pause_from_created.json()["revision"] == 1
    pause_updated_at = pause_from_created.json()["updated_at_utc"]

    resume_from_paused = client.post(f"/investigation-sessions/{session_id}/resume", json={"expected_revision": 1})
    assert resume_from_paused.status_code == 200
    assert resume_from_paused.json()["status"] == "collecting"
    assert resume_from_paused.json()["revision"] == 2
    resume_updated_at = resume_from_paused.json()["updated_at_utc"]

    resume_idempotent = client.post(f"/investigation-sessions/{session_id}/resume", json={"expected_revision": 2})
    assert resume_idempotent.status_code == 200
    assert resume_idempotent.json()["status"] == "collecting"
    assert resume_idempotent.json()["revision"] == 2
    assert resume_idempotent.json()["updated_at_utc"] == resume_updated_at

    cancel = client.post(f"/investigation-sessions/{session_id}/cancel", json={"expected_revision": 2})
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"
    assert cancel.json()["revision"] == 3
    cancel_updated_at = cancel.json()["updated_at_utc"]

    cancel_idempotent = client.post(f"/investigation-sessions/{session_id}/cancel", json={"expected_revision": 3})
    assert cancel_idempotent.status_code == 200
    assert cancel_idempotent.json()["status"] == "cancelled"
    assert cancel_idempotent.json()["revision"] == 3
    assert cancel_idempotent.json()["updated_at_utc"] == cancel_updated_at

    created_two = client.post("/investigation-sessions", json={"client_metadata": {"source": "seed"}})
    session_two = created_two.json()["session_id"]
    resume_from_created = client.post(f"/investigation-sessions/{session_two}/resume", json={"expected_revision": 0})
    assert resume_from_created.status_code == 409
    assert resume_from_created.json()["detail"]["category"] == "invalid_state_transition"

    session_model = store.load_session(session_two)
    collecting = _collecting_copy(session_model)
    store.save_session(collecting)

    pause_from_collecting = client.post(f"/investigation-sessions/{session_two}/pause", json={"expected_revision": collecting.revision})
    assert pause_from_collecting.status_code == 200
    assert pause_from_collecting.json()["status"] == "paused"
    assert pause_from_collecting.json()["updated_at_utc"] != created.json()["updated_at_utc"]


def test_api_cancelled_state_pause_and_resume_are_rejected_and_preserve_state(session_test_context):
    client, store, _ = session_test_context
    created = client.post("/investigation-sessions", json={})
    session_id = created.json()["session_id"]

    cancelled = client.post(f"/investigation-sessions/{session_id}/cancel", json={"expected_revision": 0})
    assert cancelled.status_code == 200
    cancelled_payload = cancelled.json()
    cancelled_revision = cancelled_payload["revision"]
    cancelled_updated_at = cancelled_payload["updated_at_utc"]

    pause_again = client.post(f"/investigation-sessions/{session_id}/pause", json={"expected_revision": cancelled_revision})
    assert pause_again.status_code == 409
    assert pause_again.json()["detail"]["category"] == "invalid_state_transition"

    resume_again = client.post(f"/investigation-sessions/{session_id}/resume", json={"expected_revision": cancelled_revision})
    assert resume_again.status_code == 409
    assert resume_again.json()["detail"]["category"] == "invalid_state_transition"

    persisted = store.load_session(session_id)
    assert persisted.status == InvestigationSessionStatus.CANCELLED
    assert persisted.revision == cancelled_revision
    assert persisted.updated_at_utc == datetime.fromisoformat(cancelled_updated_at.replace("Z", "+00:00"))


def test_api_storage_error_mapping_for_read_and_mutation_paths(session_test_context, monkeypatch: pytest.MonkeyPatch):
    client, store, _ = session_test_context
    created = client.post("/investigation-sessions", json={})
    session_id = created.json()["session_id"]

    monkeypatch.setattr(store, "load_session", lambda _session_id: (_ for _ in ()).throw(InvestigationSessionStoreError("disk full /tmp/secret")))
    response = client.get(f"/investigation-sessions/{session_id}")
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["category"] == "session_storage_error"
    assert "tmp" not in json.dumps(detail).lower()
    assert "disk full" not in json.dumps(detail).lower()
    assert "traceback" not in json.dumps(detail).lower()


def test_api_storage_error_preserves_prior_state_on_mutation_failure(session_test_context, monkeypatch: pytest.MonkeyPatch):
    client, store, _ = session_test_context
    created = client.post("/investigation-sessions", json={})
    session_id = created.json()["session_id"]
    before = store.load_session(session_id)

    def _raise_after_transition(*_args, **_kwargs):
        raise InvestigationSessionStoreError("unable to persist to /var/secret")

    monkeypatch.setattr(store, "_save_session_no_lock", _raise_after_transition)
    response = client.post(f"/investigation-sessions/{session_id}/pause", json={"expected_revision": 0})
    assert response.status_code == 500
    assert response.json()["detail"]["category"] == "session_storage_error"

    persisted = store.load_session(session_id)
    assert persisted.status == before.status
    assert persisted.revision == before.revision
    assert persisted.updated_at_utc == before.updated_at_utc


def test_api_revision_conflict_preserves_state(session_test_context):
    client, store, _ = session_test_context
    created = client.post("/investigation-sessions", json={})
    session_id = created.json()["session_id"]

    response = client.post(f"/investigation-sessions/{session_id}/pause", json={"expected_revision": 99})
    assert response.status_code == 409
    assert response.json()["detail"]["category"] == "revision_conflict"

    persisted = store.load_session(session_id)
    assert persisted.status == InvestigationSessionStatus.CREATED
    assert persisted.revision == 0


def test_api_validation_error_category_for_bad_payload(session_test_context):
    client, _, _ = session_test_context

    response = client.post("/investigation-sessions", json={"client_metadata": {"nested": {"bad": True}}})
    assert response.status_code == 422
    assert response.json()["detail"]["category"] == "validation_error"


def test_api_optional_token_behavior(session_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _, _ = session_test_context
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "phase2-token")

    unauthorized = client.post("/investigation-sessions", json={})
    assert unauthorized.status_code == 401
    assert unauthorized.json()["detail"]["category"] == "unauthorized"

    by_query = client.post("/investigation-sessions", params={"token": "phase2-token"}, json={})
    assert by_query.status_code == 201

    by_bearer = client.post(
        "/investigation-sessions",
        headers={"Authorization": "Bearer phase2-token"},
        json={},
    )
    assert by_bearer.status_code == 201


def test_api_phase2a_endpoints_never_call_openai_or_context(session_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _, _ = session_test_context
    counters = {"openai": 0, "context": 0}

    class _ForbiddenOpenAI:
        def __init__(self, *_args, **_kwargs):
            counters["openai"] += 1

    def _forbidden_context_loader():
        counters["context"] += 1
        return None

    monkeypatch.setattr(api, "OpenAI", _ForbiddenOpenAI)
    monkeypatch.setattr(api, "_load_investigation_context_snapshot_from_context_fusion", _forbidden_context_loader)

    created = client.post("/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    got = client.get(f"/investigation-sessions/{session_id}")
    assert got.status_code == 200

    paused = client.post(f"/investigation-sessions/{session_id}/pause", json={"expected_revision": 0})
    assert paused.status_code == 200

    resumed = client.post(f"/investigation-sessions/{session_id}/resume", json={"expected_revision": 1})
    assert resumed.status_code == 200

    cancelled = client.post(f"/investigation-sessions/{session_id}/cancel", json={"expected_revision": 2})
    assert cancelled.status_code == 200

    poll = client.get(f"/investigation-sessions/{session_id}/poll")
    assert poll.status_code == 200

    assert counters["openai"] == 0
    assert counters["context"] == 0


def test_api_routes_registered_for_phase2a():
    route_paths = {route.path for route in api.app.routes}
    assert "/investigation-sessions" in route_paths
    assert "/investigation-sessions/{session_id}" in route_paths
    assert "/investigation-sessions/{session_id}/poll" in route_paths
    assert "/investigation-sessions/{session_id}/analyze" in route_paths
    assert "/investigation-sessions/{session_id}/pause" in route_paths
    assert "/investigation-sessions/{session_id}/resume" in route_paths
    assert "/investigation-sessions/{session_id}/cancel" in route_paths


def test_store_no_global_index_file_created(tmp_path: Path):
    root = tmp_path / "investigation_sessions"
    store = InvestigationSessionStore(root)
    session = create_new_investigation_session()
    store.save_session(session)

    index_candidates = list(root.glob("*index*"))
    assert index_candidates == []


def test_store_prior_file_preserved_when_existing_file_is_malformed_on_write(tmp_path: Path):
    root = tmp_path / "investigation_sessions"
    store = InvestigationSessionStore(root)
    session = create_new_investigation_session()

    session_path = _session_file_path(root, session.session_id)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text("{ bad-json", encoding="utf-8")

    with pytest.raises(InvestigationSessionStoreError):
        store.save_session(session)

    assert not session_path.exists()
    assert list((root / "corrupt").glob("*.json"))


def test_store_load_nonexistent_raises_not_found(tmp_path: Path):
    store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    session_id = create_new_investigation_session().session_id
    with pytest.raises(InvestigationSessionNotFound):
        store.load_session(session_id)


def test_store_session_json_filename_is_uuid_json(tmp_path: Path):
    root = tmp_path / "investigation_sessions"
    store = InvestigationSessionStore(root)
    session = create_new_investigation_session()
    store.save_session(session)

    files = list((root / "sessions").glob("*.json"))
    assert len(files) == 1
    assert files[0].name == f"{session.session_id}.json"


def test_store_serialized_payload_is_valid_json(tmp_path: Path):
    root = tmp_path / "investigation_sessions"
    store = InvestigationSessionStore(root)
    session = create_new_investigation_session(client_metadata={"source": "desktop"})
    store.save_session(session)

    content = _session_file_path(root, session.session_id).read_text(encoding="utf-8")
    parsed = json.loads(content)
    assert parsed["session_id"] == session.session_id
    assert parsed["status"] == "created"
