from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import api
from projects import ProjectActivityStore, ProjectStore


@pytest.fixture
def orientation_test_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
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
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")

    return TestClient(api.app), projects_root


def _create_project(client: TestClient, name: str, *, checkpoint: dict[str, str] | None = None):
    response = client.post(
        "/projects",
        json={"name": name, "goal": f"Goal for {name}", "checkpoint": checkpoint},
    )
    assert response.status_code == 201
    return response.json()


def _create_roadmap_activity(
    client: TestClient,
    project_id: str,
    summary: str,
    status: str,
    occurred_at_utc: str,
):
    response = client.post(
        f"/projects/{project_id}/activities",
        json={
            "activity_type": "milestone",
            "source_type": "user",
            "confirmation_status": "confirmed",
            "summary": summary,
            "occurred_at_utc": occurred_at_utc,
            "metadata": {"roadmap_status": status},
        },
    )
    assert response.status_code == 201
    return response.json()


def test_orientation_groups_roadmap_and_uses_checkpoint_precedence(orientation_test_context):
    client, _projects_root = orientation_test_context
    project = _create_project(
        client,
        "AC Repair",
        checkpoint={
            "current_objective": "Electrical diagnosis",
            "current_work": "Testing capacitor",
            "next_action": "Measure capacitance",
            "blockers": "Waiting for meter",
        },
    )
    project_id = project["project_id"]
    entries = [
        ("Verify cooling", "upcoming", "2026-08-23T10:00:05Z"),
        ("Inspect system", "completed", "2026-08-23T10:00:01Z"),
        ("Test capacitor", "current", "2026-08-23T10:00:03Z"),
        ("Test contactor", "completed", "2026-08-23T10:00:02Z"),
        ("Replace thermostat", "deferred", "2026-08-23T10:00:06Z"),
        ("Repair identified fault", "upcoming", "2026-08-23T10:00:04Z"),
    ]
    for entry in entries:
        _create_roadmap_activity(client, project_id, *entry)

    response = client.get(f"/projects/{project_id}/orientation")
    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == project_id
    assert body["name"] == "AC Repair"
    assert body["status"] == "active"
    assert body["objective"] == "Goal for AC Repair"
    assert body["where_we_are"] == "Electrical diagnosis"
    assert body["now"] == "Testing capacitor"
    assert body["next"] == "Measure capacitance"
    assert body["blockers"] == "Waiting for meter"
    assert [item["summary"] for item in body["roadmap"]["completed"]] == ["Inspect system", "Test contactor"]
    assert [item["summary"] for item in body["roadmap"]["current"]] == ["Test capacitor"]
    assert [item["summary"] for item in body["roadmap"]["upcoming"]] == ["Repair identified fault", "Verify cooling"]
    assert [item["summary"] for item in body["roadmap"]["deferred"]] == ["Replace thermostat"]


def test_orientation_is_project_scoped_stable_and_ignores_untagged_or_unknown_status(orientation_test_context):
    client, _projects_root = orientation_test_context
    project_a = _create_project(client, "A")
    project_b = _create_project(client, "B")
    _create_roadmap_activity(client, project_a["project_id"], "A only", "current", "2026-01-01T00:00:00Z")
    _create_roadmap_activity(client, project_b["project_id"], "B only", "deferred", "2026-01-01T00:00:00Z")
    _create_roadmap_activity(client, project_a["project_id"], "Unknown", "idea", "2026-01-01T00:00:01Z")

    first = client.get(f"/projects/{project_a['project_id']}/orientation")
    second = client.get(f"/projects/{project_a['project_id']}/orientation")
    assert first.status_code == 200
    assert first.json() == second.json()
    serialized = str(first.json())
    assert "A only" in serialized
    assert "B only" not in serialized
    assert "Unknown" not in serialized


def test_empty_orientation_is_valid_and_read_does_not_mutate_any_state(monkeypatch, orientation_test_context):
    client, projects_root = orientation_test_context
    project = _create_project(client, "Empty")
    other = _create_project(client, "Active")
    assert client.put(f"/projects/active/{other['project_id']}").status_code == 200

    before_project = deepcopy(client.get(f"/projects/{project['project_id']}").json())
    before_activities = deepcopy(client.get(f"/projects/{project['project_id']}/activities").json())
    pointer_path = projects_root / "active_project.json"
    before_pointer = pointer_path.read_bytes()
    called = {"value": False}

    def _fail_openai(*_args, **_kwargs):
        called["value"] = True
        raise AssertionError("Orientation must not call an AI provider")

    monkeypatch.setattr(api, "OpenAI", _fail_openai)
    response = client.get(f"/projects/{project['project_id']}/orientation")
    assert response.status_code == 200
    body = response.json()
    assert body["where_we_are"] is None
    assert body["now"] is None
    assert body["next"] is None
    assert body["blockers"] is None
    assert body["roadmap"] == {"completed": [], "current": [], "upcoming": [], "deferred": []}
    assert called["value"] is False
    assert client.get(f"/projects/{project['project_id']}").json() == before_project
    assert client.get(f"/projects/{project['project_id']}/activities").json() == before_activities
    assert pointer_path.read_bytes() == before_pointer
    assert client.get("/projects/active").json()["project_id"] == other["project_id"]


def test_orientation_errors_and_existing_project_apis_remain_available(orientation_test_context):
    client, _projects_root = orientation_test_context
    project = _create_project(client, "Compatibility")
    assert client.get("/projects/not-a-uuid/orientation").status_code == 422
    assert client.get(f"/projects/{uuid4()}/orientation").status_code == 404
    assert client.get(f"/projects/{project['project_id']}").status_code == 200
    assert client.get(f"/projects/{project['project_id']}/activities").status_code == 200
    assert client.get(f"/projects/{project['project_id']}/context").status_code == 200
