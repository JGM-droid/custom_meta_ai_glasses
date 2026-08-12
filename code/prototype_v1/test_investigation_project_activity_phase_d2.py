from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import api
from investigations.models import InvestigationSessionStatus
from investigations.session_store import InvestigationSessionStore
from projects import ProjectActivityStore, ProjectStore


class _StaticProvider:
    def analyze(self, _request_package):
        return api.InvestigationAnalysisResponse(
            schema_version=api.INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
            concise_diagnosis="Likely a UI rendering failure.",
            immediate_recommended_action="Rebuild the frontend bundle and recheck the viewport.",
            supporting_observations=["Evidence was ordered and normalized."],
            confidence_or_uncertainty="Moderate confidence.",
            warning_or_blocker=None,
            follow_up_capture_request=None,
        )


@pytest.fixture
def d2_test_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    results_root = tmp_path / "results"
    projects_root = results_root / "projects"
    session_root = results_root / "investigation_sessions"

    project_store = ProjectStore(projects_root)
    activity_store = ProjectActivityStore(projects_root, project_store)
    session_store = InvestigationSessionStore(session_root)

    monkeypatch.setattr(api, "RESULTS_DIR", results_root)
    monkeypatch.setattr(api, "PROJECTS_ROOT", projects_root)
    monkeypatch.setattr(api, "PROJECT_STORE", project_store)
    monkeypatch.setattr(api, "PROJECT_ACTIVITY_STORE", activity_store)
    monkeypatch.setattr(api, "INVESTIGATION_SESSIONS_ROOT", session_root)
    monkeypatch.setattr(api, "SESSION_STORE", session_store)
    monkeypatch.setattr(api, "EVIDENCE_STORE", api.InvestigationEvidenceStore(session_store))
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", results_root / "investigation_latest.json")
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")

    client = TestClient(api.app)
    return client, project_store, activity_store, session_store, projects_root


def _create_project(client: TestClient, *, name: str) -> dict[str, object]:
    response = client.post(
        "/projects",
        json={
            "name": name,
            "goal": f"Goal for {name}",
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_project_owned_session_with_image(client: TestClient, project_id: str) -> str:
    created = client.post(f"/projects/{project_id}/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    uploaded = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        data={"normalized_text": "The image shows a missing configuration file error."},
        files={"file": ("capture.png", b"image-bytes", "image/png")},
    )
    assert uploaded.status_code == 201
    return session_id


def _create_unowned_session_with_image(client: TestClient) -> str:
    created = client.post("/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    uploaded = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        data={"normalized_text": "Legacy session evidence."},
        files={"file": ("capture.png", b"image-bytes", "image/png")},
    )
    assert uploaded.status_code == 201
    return session_id


def _analyze_with_static_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(api, "_create_session_orchestrator", lambda: api.InvestigationOrchestrator(
        session_store=api.SESSION_STORE,
        evidence_store=api.EVIDENCE_STORE,
        attempt_store=api.InvestigationAnalysisAttemptStore(api.SESSION_STORE),
        analysis_provider=_StaticProvider(),
        result_persistence=api._SessionRouteResultPersistence(),
    ))


def test_completed_project_owned_investigation_creates_one_activity(d2_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, activity_store, _session_store, _projects_root = d2_test_context
    project = _create_project(client, name="Project A")
    session_id = _create_project_owned_session_with_image(client, project["project_id"])
    _analyze_with_static_provider(monkeypatch)

    before_project = deepcopy(client.get(f"/projects/{project['project_id']}").json())

    response = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"

    activities = client.get(f"/projects/{project['project_id']}/activities")
    assert activities.status_code == 200
    body = activities.json()
    assert len(body) == 1

    activity = body[0]
    assert activity["project_id"] == project["project_id"]
    assert activity["activity_type"] == "result"
    assert activity["source_type"] == "ai"
    assert activity["confirmation_status"] == "inferred"
    assert activity["metadata"]["investigation_session_id"] == session_id
    assert activity["metadata"]["investigation_result_id"]
    assert "Likely a UI rendering failure." in activity["summary"]
    assert "Rebuild the frontend bundle" in activity["details"]

    after_project = client.get(f"/projects/{project['project_id']}").json()
    assert after_project["checkpoint"] == before_project["checkpoint"]
    assert after_project["revision"] == before_project["revision"]
    assert after_project["updated_at_utc"] == before_project["updated_at_utc"]

    activity_id = activity["activity_id"]
    loaded = activity_store.load_activity(project["project_id"], activity_id)
    assert loaded.activity_id == activity_id


def test_completed_project_owned_investigation_rerun_does_not_duplicate_activity(d2_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, _activity_store, _session_store, _projects_root = d2_test_context
    project = _create_project(client, name="Project A")
    session_id = _create_project_owned_session_with_image(client, project["project_id"])
    _analyze_with_static_provider(monkeypatch)

    first = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert first.status_code == 200

    first_activities = client.get(f"/projects/{project['project_id']}/activities").json()
    assert len(first_activities) == 1
    first_activity_id = first_activities[0]["activity_id"]

    second = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert second.status_code == 200
    assert second.json()["status"] == "completed"

    second_activities = client.get(f"/projects/{project['project_id']}/activities").json()
    assert len(second_activities) == 1
    assert second_activities[0]["activity_id"] == first_activity_id


def test_project_b_cannot_see_project_a_investigation_activity(d2_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, _activity_store, _session_store, _projects_root = d2_test_context
    project_a = _create_project(client, name="Project A")
    project_b = _create_project(client, name="Project B")
    session_id = _create_project_owned_session_with_image(client, project_a["project_id"])
    _analyze_with_static_provider(monkeypatch)

    completed = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert completed.status_code == 200

    list_b = client.get(f"/projects/{project_b['project_id']}/activities")
    assert list_b.status_code == 200
    assert list_b.json() == []

    activity_id = client.get(f"/projects/{project_a['project_id']}/activities").json()[0]["activity_id"]
    wrong_owner_get = client.get(f"/projects/{project_b['project_id']}/activities/{activity_id}")
    assert wrong_owner_get.status_code == 404
    assert wrong_owner_get.json()["detail"]["category"] == "activity_not_found"


def test_legacy_unowned_investigation_creates_no_project_activity(d2_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, _activity_store, _session_store, _projects_root = d2_test_context
    project = _create_project(client, name="Project A")
    session_id = _create_unowned_session_with_image(client)
    _analyze_with_static_provider(monkeypatch)

    response = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert response.status_code == 200

    activities = client.get(f"/projects/{project['project_id']}/activities")
    assert activities.status_code == 200
    assert activities.json() == []


def test_cancelled_investigation_creates_no_activity(d2_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, _activity_store, _session_store, _projects_root = d2_test_context
    project = _create_project(client, name="Project A")
    session_id = _create_project_owned_session_with_image(client, project["project_id"])
    cancelled = client.post(f"/investigation-sessions/{session_id}/cancel", json={"expected_revision": 1})
    assert cancelled.status_code == 200

    _analyze_with_static_provider(monkeypatch)
    response = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert response.status_code == 409

    activities = client.get(f"/projects/{project['project_id']}/activities")
    assert activities.status_code == 200
    assert activities.json() == []


def test_failed_investigation_does_not_create_activity(d2_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, _activity_store, _session_store, _projects_root = d2_test_context
    project = _create_project(client, name="Project A")
    session_id = _create_project_owned_session_with_image(client, project["project_id"])

    class _FailingProvider:
        def analyze(self, _request_package):
            raise api.InvestigationAnalysisProviderError("provider failure")

    monkeypatch.setattr(api, "_create_session_orchestrator", lambda: api.InvestigationOrchestrator(
        session_store=api.SESSION_STORE,
        evidence_store=api.EVIDENCE_STORE,
        attempt_store=api.InvestigationAnalysisAttemptStore(api.SESSION_STORE),
        analysis_provider=_FailingProvider(),
        result_persistence=api._SessionRouteResultPersistence(),
    ))

    response = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert response.status_code == 500
    assert response.json()["detail"]["category"] == "provider_failure"

    activities = client.get(f"/projects/{project['project_id']}/activities")
    assert activities.status_code == 200
    assert activities.json() == []


def test_activity_projection_does_not_call_openai_and_is_restart_persistent(d2_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, activity_store, _session_store, projects_root = d2_test_context
    project = _create_project(client, name="Project A")
    session_id = _create_project_owned_session_with_image(client, project["project_id"])
    _analyze_with_static_provider(monkeypatch)

    calls = {"openai": 0}

    class _ForbiddenOpenAI:
        def __init__(self, *_args, **_kwargs):
            calls["openai"] += 1

    monkeypatch.setattr(api, "OpenAI", _ForbiddenOpenAI)

    response = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert response.status_code == 200
    assert calls["openai"] == 0

    project_before = deepcopy(client.get(f"/projects/{project['project_id']}").json())
    activity_before = client.get(f"/projects/{project['project_id']}/activities").json()[0]

    restarted_project_store = ProjectStore(projects_root)
    restarted_activity_store = ProjectActivityStore(projects_root, restarted_project_store)
    restarted_loaded = restarted_activity_store.load_activity(project["project_id"], activity_before["activity_id"])

    assert restarted_loaded.project_id == project["project_id"]
    assert restarted_loaded.metadata["investigation_session_id"] == session_id
    assert restarted_loaded.metadata["investigation_result_id"]
    assert client.get(f"/projects/{project['project_id']}").json()["checkpoint"] == project_before["checkpoint"]
