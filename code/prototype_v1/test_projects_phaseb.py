from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import api
from projects import Project, ProjectStore


@pytest.fixture
def project_test_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    results_root = tmp_path / "results"
    projects_root = results_root / "projects"
    session_root = results_root / "investigation_sessions"

    project_store = ProjectStore(projects_root)
    session_store = api.InvestigationSessionStore(session_root)

    monkeypatch.setattr(api, "RESULTS_DIR", results_root)
    monkeypatch.setattr(api, "PROJECTS_ROOT", projects_root)
    monkeypatch.setattr(api, "PROJECT_STORE", project_store)
    monkeypatch.setattr(api, "INVESTIGATION_SESSIONS_ROOT", session_root)
    monkeypatch.setattr(api, "SESSION_STORE", session_store)
    monkeypatch.setattr(api, "EVIDENCE_STORE", api.InvestigationEvidenceStore(session_store))
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", results_root / "investigation_latest.json")
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")

    client = TestClient(api.app)
    return client, project_store, projects_root


def _create_project(client: TestClient, *, name: str, goal: str, checkpoint: dict[str, str] | None = None):
    payload: dict[str, object] = {"name": name, "goal": goal}
    if checkpoint is not None:
        payload["checkpoint"] = checkpoint
    response = client.post("/projects", json=payload)
    assert response.status_code == 201
    return response.json()


def test_create_project_persists_atomic_file_and_defaults(project_test_context):
    client, _store, projects_root = project_test_context

    payload = _create_project(client, name="Upstairs AC Repair", goal="Restore reliable cooling upstairs.")

    assert payload["schema_version"] == "1.0"
    assert payload["project_id"]
    assert payload["revision"] == 0
    assert payload["created_at_utc"].endswith("Z") or "+00:00" in payload["created_at_utc"]
    assert payload["updated_at_utc"].endswith("Z") or "+00:00" in payload["updated_at_utc"]

    project_file = projects_root / "projects" / f"{payload['project_id']}.json"
    assert project_file.exists()

    parsed = json.loads(project_file.read_text(encoding="utf-8"))
    assert parsed["name"] == "Upstairs AC Repair"
    assert parsed["checkpoint"]["next_action"] is None


def test_multiple_projects_have_unique_ids_and_independent_records(project_test_context):
    client, _store, _projects_root = project_test_context

    a = _create_project(client, name="Project A", goal="Goal A")
    b = _create_project(client, name="Project B", goal="Goal B")

    assert a["project_id"] != b["project_id"]

    get_a = client.get(f"/projects/{a['project_id']}")
    get_b = client.get(f"/projects/{b['project_id']}")

    assert get_a.status_code == 200
    assert get_b.status_code == 200
    assert get_a.json()["name"] == "Project A"
    assert get_b.json()["name"] == "Project B"


def test_checkpoint_partial_update_preserves_unspecified_fields(project_test_context):
    client, _store, _projects_root = project_test_context

    created = _create_project(
        client,
        name="Upstairs AC Repair",
        goal="Restore reliable cooling upstairs.",
        checkpoint={
            "completed_summary": "Thermostat and breaker checked",
            "next_action": "Inspect capacitor",
        },
    )

    patched = client.patch(
        f"/projects/{created['project_id']}/checkpoint",
        json={
            "expected_revision": created["revision"],
            "discoveries_summary": "Capacitor appears swollen",
            "next_action": "Identify capacitor rating",
        },
    )
    assert patched.status_code == 200

    body = patched.json()
    assert body["checkpoint"]["completed_summary"] == "Thermostat and breaker checked"
    assert body["checkpoint"]["discoveries_summary"] == "Capacitor appears swollen"
    assert body["checkpoint"]["next_action"] == "Identify capacitor rating"


def test_revision_conflict_returns_deterministic_error(project_test_context):
    client, _store, _projects_root = project_test_context

    created = _create_project(client, name="Project A", goal="Goal A")

    ok = client.patch(
        f"/projects/{created['project_id']}/checkpoint",
        json={"expected_revision": created["revision"], "next_action": "Do thing"},
    )
    assert ok.status_code == 200

    conflict = client.patch(
        f"/projects/{created['project_id']}/checkpoint",
        json={"expected_revision": created["revision"], "next_action": "Do stale thing"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["category"] == "revision_conflict"


def test_invalid_and_unknown_ids_do_not_fallback(project_test_context):
    client, _store, _projects_root = project_test_context

    _create_project(client, name="Project A", goal="Goal A")

    invalid = client.get("/projects/not-a-uuid")
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["category"] == "invalid_project_id"

    unknown = client.get(f"/projects/{uuid4()}")
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["category"] == "project_not_found"


def test_active_project_selection_is_persistent_and_does_not_mutate_records(project_test_context):
    client, store, projects_root = project_test_context

    a = _create_project(client, name="Project A", goal="Goal A")
    b = _create_project(client, name="Project B", goal="Goal B")

    a_before = deepcopy(client.get(f"/projects/{a['project_id']}").json())
    b_before = deepcopy(client.get(f"/projects/{b['project_id']}").json())

    set_a = client.put(f"/projects/active/{a['project_id']}")
    assert set_a.status_code == 200
    active_a = client.get("/projects/active")
    assert active_a.status_code == 200
    assert active_a.json()["project_id"] == a["project_id"]

    set_b = client.put(f"/projects/active/{b['project_id']}")
    assert set_b.status_code == 200
    active_b = client.get("/projects/active")
    assert active_b.status_code == 200
    assert active_b.json()["project_id"] == b["project_id"]

    a_after = client.get(f"/projects/{a['project_id']}").json()
    b_after = client.get(f"/projects/{b['project_id']}").json()

    assert a_before == a_after
    assert b_before == b_after

    pointer = projects_root / "active_project.json"
    assert pointer.exists()
    parsed_pointer = json.loads(pointer.read_text(encoding="utf-8"))
    assert parsed_pointer["active_project_id"] == b["project_id"]

    unknown_set = client.put(f"/projects/active/{uuid4()}")
    assert unknown_set.status_code == 404
    assert unknown_set.json()["detail"]["category"] == "project_not_found"

    invalid_set = client.put("/projects/active/not-a-uuid")
    assert invalid_set.status_code == 422
    assert invalid_set.json()["detail"]["category"] == "invalid_project_id"

    restarted_store = ProjectStore(projects_root)
    assert restarted_store.get_active_project_id() == b["project_id"]


def test_restart_persistence_for_multiple_projects_and_active_pointer(project_test_context):
    client, _store, projects_root = project_test_context

    a = _create_project(
        client,
        name="Upstairs AC Repair",
        goal="Restore reliable cooling upstairs.",
        checkpoint={
            "current_objective": "Determine likely AC failure.",
            "completed_summary": "Thermostat, breaker, and filter checked.",
            "discoveries_summary": "Capacitor appears swollen.",
            "current_work": "Inspecting capacitor specifications.",
            "stopped_at": "Before identifying capacitor rating.",
            "blockers": "Need capacitor label/specification.",
            "next_action": "Identify capacitor rating.",
        },
    )

    b = _create_project(
        client,
        name="Custom Meta AI Glasses",
        goal="Build a persistent project-aware AI assistant.",
        checkpoint={
            "current_objective": "Implement persistent Project foundation.",
            "completed_summary": "Investigation workflow operational and architecture pivot documented.",
            "discoveries_summary": "Investigation persistence patterns can be reused conceptually.",
            "current_work": "Building Phase B Project foundation.",
            "stopped_at": "Before ProjectStore implementation.",
            "blockers": "None.",
            "next_action": "Implement Project Memory foundation.",
        },
    )

    set_a = client.put(f"/projects/active/{a['project_id']}")
    assert set_a.status_code == 200

    active_a = client.get("/projects/active")
    assert active_a.status_code == 200
    assert active_a.json()["checkpoint"]["next_action"] == "Identify capacitor rating."

    set_b = client.put(f"/projects/active/{b['project_id']}")
    assert set_b.status_code == 200
    active_b = client.get("/projects/active")
    assert active_b.status_code == 200
    assert active_b.json()["checkpoint"]["next_action"] == "Implement Project Memory foundation."

    mutate_b = client.patch(
        f"/projects/{b['project_id']}/checkpoint",
        json={
            "expected_revision": active_b.json()["revision"],
            "discoveries_summary": "Confirmed deterministic project persistence design.",
        },
    )
    assert mutate_b.status_code == 200

    a_before_back_switch = client.get(f"/projects/{a['project_id']}").json()

    set_a_again = client.put(f"/projects/active/{a['project_id']}")
    assert set_a_again.status_code == 200
    active_a_again = client.get("/projects/active")
    assert active_a_again.status_code == 200
    assert active_a_again.json()["project_id"] == a["project_id"]
    assert active_a_again.json()["checkpoint"]["next_action"] == "Identify capacitor rating."

    restarted_store = ProjectStore(projects_root)
    restarted_active = restarted_store.get_active_project()
    restarted_a = restarted_store.load_project(a["project_id"])
    restarted_b = restarted_store.load_project(b["project_id"])

    assert restarted_active.project_id == a["project_id"]
    assert restarted_a.model_dump(mode="json") == a_before_back_switch
    assert restarted_b.checkpoint.discoveries_summary == "Confirmed deterministic project persistence design."


def test_project_corruption_is_quarantined_without_fallback(project_test_context):
    client, _store, projects_root = project_test_context

    created = _create_project(client, name="Project A", goal="Goal A")
    project_path = projects_root / "projects" / f"{created['project_id']}.json"
    project_path.write_text("{ bad json", encoding="utf-8")

    response = client.get(f"/projects/{created['project_id']}")
    assert response.status_code == 500
    assert response.json()["detail"]["category"] == "project_storage_error"

    assert not project_path.exists()
    quarantined = list((projects_root / "corrupt").glob("project_corrupt_*.json"))
    assert quarantined


def test_active_project_not_set_behavior(project_test_context):
    client, _store, _projects_root = project_test_context

    response = client.get("/projects/active")
    assert response.status_code == 404
    assert response.json()["detail"]["category"] == "active_project_not_set"


def test_project_operations_do_not_call_openai(monkeypatch: pytest.MonkeyPatch, project_test_context):
    client, _store, _projects_root = project_test_context

    called = {"value": False}

    def _fail_openai(*args, **kwargs):
        called["value"] = True
        raise AssertionError("OpenAI should not be called for project operations")

    monkeypatch.setattr(api, "OpenAI", _fail_openai)

    created = _create_project(client, name="Project A", goal="Goal A")

    assert client.get("/projects").status_code == 200
    assert client.get(f"/projects/{created['project_id']}").status_code == 200
    assert client.patch(
        f"/projects/{created['project_id']}/checkpoint",
        json={"expected_revision": 0, "next_action": "Next"},
    ).status_code == 200
    assert client.put(f"/projects/active/{created['project_id']}").status_code == 200
    assert client.get("/projects/active").status_code == 200

    assert called["value"] is False


def test_project_a_b_isolation_on_mutations(project_test_context):
    client, _store, _projects_root = project_test_context

    project_a = _create_project(client, name="Project A", goal="Goal A")
    project_b = _create_project(client, name="Project B", goal="Goal B")

    mutate_a = client.patch(
        f"/projects/{project_a['project_id']}/checkpoint",
        json={"expected_revision": 0, "current_objective": "A objective", "next_action": "A next"},
    )
    assert mutate_a.status_code == 200

    b_after_a = client.get(f"/projects/{project_b['project_id']}")
    assert b_after_a.status_code == 200
    assert b_after_a.json()["checkpoint"]["current_objective"] is None
    assert b_after_a.json()["checkpoint"]["next_action"] is None

    mutate_b = client.patch(
        f"/projects/{project_b['project_id']}/checkpoint",
        json={"expected_revision": 0, "current_objective": "B objective", "next_action": "B next"},
    )
    assert mutate_b.status_code == 200

    a_after_b = client.get(f"/projects/{project_a['project_id']}")
    assert a_after_b.status_code == 200
    assert a_after_b.json()["checkpoint"]["current_objective"] == "A objective"
    assert a_after_b.json()["checkpoint"]["next_action"] == "A next"
