from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import api
from projects import ProjectActivityStore, ProjectStore


@pytest.fixture
def project_activity_test_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    results_root = tmp_path / "results"
    projects_root = results_root / "projects"
    session_root = results_root / "investigation_sessions"

    project_store = ProjectStore(projects_root)
    activity_store = ProjectActivityStore(projects_root, project_store)
    session_store = api.InvestigationSessionStore(session_root)

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
    return client, project_store, activity_store, projects_root


def _create_project(client: TestClient, *, name: str, goal: str):
    response = client.post("/projects", json={"name": name, "goal": goal})
    assert response.status_code == 201
    return response.json()


def _create_activity(
    client: TestClient,
    project_id: str,
    *,
    activity_type: str = "note",
    source_type: str = "user",
    confirmation_status: str = "reported",
    summary: str = "Captured new finding",
    details: str | None = None,
    occurred_at_utc: str | None = None,
):
    payload: dict[str, object] = {
        "activity_type": activity_type,
        "source_type": source_type,
        "confirmation_status": confirmation_status,
        "summary": summary,
    }
    if details is not None:
        payload["details"] = details
    if occurred_at_utc is not None:
        payload["occurred_at_utc"] = occurred_at_utc

    response = client.post(f"/projects/{project_id}/activities", json=payload)
    return response


def test_create_activity_persists_under_project_namespace(project_activity_test_context):
    client, _project_store, _activity_store, projects_root = project_activity_test_context
    project = _create_project(client, name="Project A", goal="Goal A")

    response = _create_activity(
        client,
        project["project_id"],
        activity_type="observation",
        source_type="system",
        confirmation_status="observed",
        summary="Capacitor visibly swollen",
        details="Visual inspection from latest image.",
    )
    assert response.status_code == 201

    activity = response.json()
    assert activity["project_id"] == project["project_id"]
    assert activity["activity_id"]
    assert activity["schema_version"] == "1.0"

    activity_file = projects_root / "activities" / project["project_id"] / f"{activity['activity_id']}.json"
    assert activity_file.exists()


def test_activity_routes_reject_invalid_or_unknown_project(project_activity_test_context):
    client, _project_store, _activity_store, _projects_root = project_activity_test_context

    invalid_create = _create_activity(client, "not-a-uuid")
    assert invalid_create.status_code == 422
    assert invalid_create.json()["detail"]["category"] == "invalid_project_id"

    unknown_project_id = str(uuid4())
    unknown_create = _create_activity(client, unknown_project_id)
    assert unknown_create.status_code == 404
    assert unknown_create.json()["detail"]["category"] == "project_not_found"

    unknown_list = client.get(f"/projects/{unknown_project_id}/activities")
    assert unknown_list.status_code == 404
    assert unknown_list.json()["detail"]["category"] == "project_not_found"


def test_project_a_b_activity_isolation(project_activity_test_context):
    client, _project_store, _activity_store, _projects_root = project_activity_test_context

    project_a = _create_project(client, name="Project A", goal="Goal A")
    project_b = _create_project(client, name="Project B", goal="Goal B")

    create_a = _create_activity(client, project_a["project_id"], summary="A activity")
    assert create_a.status_code == 201
    create_b = _create_activity(client, project_b["project_id"], summary="B activity")
    assert create_b.status_code == 201

    list_a = client.get(f"/projects/{project_a['project_id']}/activities")
    list_b = client.get(f"/projects/{project_b['project_id']}/activities")
    assert list_a.status_code == 200
    assert list_b.status_code == 200

    assert len(list_a.json()) == 1
    assert len(list_b.json()) == 1
    assert list_a.json()[0]["summary"] == "A activity"
    assert list_b.json()[0]["summary"] == "B activity"


def test_cross_project_activity_access_denied_as_not_found(project_activity_test_context):
    client, _project_store, _activity_store, _projects_root = project_activity_test_context

    project_a = _create_project(client, name="Project A", goal="Goal A")
    project_b = _create_project(client, name="Project B", goal="Goal B")

    created = _create_activity(client, project_a["project_id"], summary="A private activity")
    assert created.status_code == 201
    activity_id = created.json()["activity_id"]

    wrong_owner_get = client.get(f"/projects/{project_b['project_id']}/activities/{activity_id}")
    assert wrong_owner_get.status_code == 404
    assert wrong_owner_get.json()["detail"]["category"] == "activity_not_found"


def test_activity_ordering_is_deterministic_by_occurred_then_created_then_id(project_activity_test_context):
    client, _project_store, _activity_store, _projects_root = project_activity_test_context
    project = _create_project(client, name="Project A", goal="Goal A")
    project_id = project["project_id"]

    _create_activity(
        client,
        project_id,
        summary="third",
        occurred_at_utc="2026-01-01T10:00:02Z",
    )
    _create_activity(
        client,
        project_id,
        summary="first",
        occurred_at_utc="2026-01-01T10:00:00Z",
    )
    _create_activity(
        client,
        project_id,
        summary="second",
        occurred_at_utc="2026-01-01T10:00:01Z",
    )

    listed = client.get(f"/projects/{project_id}/activities")
    assert listed.status_code == 200
    body = listed.json()
    assert [item["summary"] for item in body] == ["first", "second", "third"]

    sorted_copy = sorted(
        body,
        key=lambda item: (
            item["occurred_at_utc"],
            item["created_at_utc"],
            item["activity_id"],
        ),
    )
    assert body == sorted_copy


def test_activity_enums_are_enforced(project_activity_test_context):
    client, _project_store, _activity_store, _projects_root = project_activity_test_context
    project = _create_project(client, name="Project A", goal="Goal A")

    valid = _create_activity(
        client,
        project["project_id"],
        activity_type="decision",
        source_type="ai",
        confirmation_status="inferred",
        summary="Suggested replacing capacitor",
    )
    assert valid.status_code == 201

    invalid = _create_activity(
        client,
        project["project_id"],
        activity_type="unknown",
        source_type="user",
        confirmation_status="reported",
        summary="bad enum",
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["category"] == "validation_error"


def test_activity_append_does_not_mutate_checkpoint_or_project_revision(project_activity_test_context):
    client, _project_store, _activity_store, _projects_root = project_activity_test_context
    project = _create_project(client, name="Project A", goal="Goal A")

    project_before = deepcopy(client.get(f"/projects/{project['project_id']}").json())

    create_resp = _create_activity(client, project["project_id"], summary="Non-authoritative note")
    assert create_resp.status_code == 201

    project_after = client.get(f"/projects/{project['project_id']}").json()

    assert project_after["checkpoint"] == project_before["checkpoint"]
    assert project_after["revision"] == project_before["revision"]
    assert project_after["updated_at_utc"] == project_before["updated_at_utc"]


def test_activity_persists_across_store_restart(project_activity_test_context):
    client, _project_store, _activity_store, projects_root = project_activity_test_context
    project = _create_project(client, name="Project A", goal="Goal A")

    first = _create_activity(client, project["project_id"], summary="First")
    second = _create_activity(client, project["project_id"], summary="Second")
    assert first.status_code == 201
    assert second.status_code == 201

    restarted_project_store = ProjectStore(projects_root)
    restarted_activity_store = ProjectActivityStore(projects_root, restarted_project_store)

    loaded = restarted_activity_store.list_activities(project["project_id"])
    assert len(loaded) == 2
    assert {item.summary for item in loaded} == {"First", "Second"}


def test_activity_corruption_is_quarantined(project_activity_test_context):
    client, _project_store, _activity_store, projects_root = project_activity_test_context
    project = _create_project(client, name="Project A", goal="Goal A")

    created = _create_activity(client, project["project_id"], summary="Will corrupt")
    assert created.status_code == 201
    activity_id = created.json()["activity_id"]

    activity_path = projects_root / "activities" / project["project_id"] / f"{activity_id}.json"
    activity_path.write_text("{ bad json", encoding="utf-8")

    response = client.get(f"/projects/{project['project_id']}/activities/{activity_id}")
    assert response.status_code == 500
    assert response.json()["detail"]["category"] == "project_activity_storage_error"

    assert not activity_path.exists()
    quarantined = list((projects_root / "corrupt").glob("activity_corrupt_*.json"))
    assert quarantined


def test_activity_operations_do_not_call_openai(monkeypatch: pytest.MonkeyPatch, project_activity_test_context):
    client, _project_store, _activity_store, _projects_root = project_activity_test_context

    called = {"value": False}

    def _fail_openai(*args, **kwargs):
        called["value"] = True
        raise AssertionError("OpenAI should not be called for project activity operations")

    monkeypatch.setattr(api, "OpenAI", _fail_openai)

    project = _create_project(client, name="Project A", goal="Goal A")
    create_resp = _create_activity(client, project["project_id"], summary="No AI call")
    assert create_resp.status_code == 201

    activity_id = create_resp.json()["activity_id"]
    assert client.get(f"/projects/{project['project_id']}/activities").status_code == 200
    assert client.get(f"/projects/{project['project_id']}/activities/{activity_id}").status_code == 200

    assert called["value"] is False


def test_invalid_activity_id_returns_422(project_activity_test_context):
    client, _project_store, _activity_store, _projects_root = project_activity_test_context
    project = _create_project(client, name="Project A", goal="Goal A")

    response = client.get(f"/projects/{project['project_id']}/activities/not-a-uuid")
    assert response.status_code == 422
    assert response.json()["detail"]["category"] == "invalid_activity_id"
