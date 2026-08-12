from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import api
from investigations.models import INVESTIGATION_SESSION_SCHEMA_VERSION
from investigations.session_store import InvestigationSessionStore
from projects import ProjectStore


@pytest.fixture
def ownership_test_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    results_root = tmp_path / "results"
    projects_root = results_root / "projects"
    session_root = results_root / "investigation_sessions"

    project_store = ProjectStore(projects_root)
    session_store = InvestigationSessionStore(session_root)

    monkeypatch.setattr(api, "RESULTS_DIR", results_root)
    monkeypatch.setattr(api, "PROJECTS_ROOT", projects_root)
    monkeypatch.setattr(api, "PROJECT_STORE", project_store)
    monkeypatch.setattr(api, "INVESTIGATION_SESSIONS_ROOT", session_root)
    monkeypatch.setattr(api, "SESSION_STORE", session_store)
    monkeypatch.setattr(api, "EVIDENCE_STORE", api.InvestigationEvidenceStore(session_store))
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", results_root / "investigation_latest.json")
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")

    client = TestClient(api.app)
    return client, project_store, session_store, session_root


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


def test_project_scoped_create_sets_session_project_id(ownership_test_context):
    client, _project_store, _session_store, _session_root = ownership_test_context
    project = _create_project(client, name="Owner Project")

    created = client.post(f"/projects/{project['project_id']}/investigation-sessions", json={})
    assert created.status_code == 201
    payload = created.json()

    assert payload["project_id"] == project["project_id"]
    fetched = client.get(f"/projects/{project['project_id']}/investigation-sessions/{payload['session_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["project_id"] == project["project_id"]


def test_global_create_accepts_project_id_and_validates_existence(ownership_test_context):
    client, _project_store, _session_store, _session_root = ownership_test_context
    project = _create_project(client, name="Pathless Create Project")

    created = client.post("/investigation-sessions", json={"project_id": project["project_id"]})
    assert created.status_code == 201
    assert created.json()["project_id"] == project["project_id"]

    missing = client.post("/investigation-sessions", json={"project_id": str(uuid4())})
    assert missing.status_code == 404
    assert missing.json()["detail"]["category"] == "project_not_found"


def test_project_scoped_create_rejects_payload_project_mismatch(ownership_test_context):
    client, _project_store, _session_store, _session_root = ownership_test_context
    project_a = _create_project(client, name="Project A")
    project_b = _create_project(client, name="Project B")

    response = client.post(
        f"/projects/{project_a['project_id']}/investigation-sessions",
        json={"project_id": project_b["project_id"]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["category"] == "project_mismatch"


def test_project_list_and_get_enforce_ownership_isolation(ownership_test_context):
    client, _project_store, _session_store, _session_root = ownership_test_context
    project_a = _create_project(client, name="Project A")
    project_b = _create_project(client, name="Project B")

    a_session = client.post(f"/projects/{project_a['project_id']}/investigation-sessions", json={})
    b_session = client.post(f"/projects/{project_b['project_id']}/investigation-sessions", json={})
    legacy_session = client.post("/investigation-sessions", json={})

    assert a_session.status_code == 201
    assert b_session.status_code == 201
    assert legacy_session.status_code == 201
    a_session_id = a_session.json()["session_id"]
    b_session_id = b_session.json()["session_id"]
    legacy_session_id = legacy_session.json()["session_id"]

    list_a = client.get(f"/projects/{project_a['project_id']}/investigation-sessions")
    list_b = client.get(f"/projects/{project_b['project_id']}/investigation-sessions")

    assert list_a.status_code == 200
    assert list_b.status_code == 200

    a_ids = {item["session_id"] for item in list_a.json()}
    b_ids = {item["session_id"] for item in list_b.json()}

    assert a_session_id in a_ids
    assert b_session_id not in a_ids
    assert legacy_session_id not in a_ids

    assert b_session_id in b_ids
    assert a_session_id not in b_ids
    assert legacy_session_id not in b_ids

    cross = client.get(f"/projects/{project_a['project_id']}/investigation-sessions/{b_session_id}")
    assert cross.status_code == 404
    assert cross.json()["detail"]["category"] == "session_not_found"


def test_legacy_session_record_without_project_id_remains_loadable(ownership_test_context):
    client, _project_store, session_store, session_root = ownership_test_context
    project = _create_project(client, name="Legacy Compatibility Project")

    session_id = str(uuid4())
    payload = {
        "schema_version": INVESTIGATION_SESSION_SCHEMA_VERSION,
        "session_id": session_id,
        "status": "collecting",
        "revision": 2,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "client_metadata": {"source": "legacy"},
        "current_analysis_attempt_id": None,
        "completed_result_id": None,
        "last_error": None,
    }

    session_path = session_root / "sessions" / f"{session_id}.json"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = session_store.load_session(session_id)
    assert loaded.project_id is None

    global_get = client.get(f"/investigation-sessions/{session_id}")
    assert global_get.status_code == 200
    assert global_get.json()["project_id"] is None

    project_list = client.get(f"/projects/{project['project_id']}/investigation-sessions")
    assert project_list.status_code == 200
    assert all(item["session_id"] != session_id for item in project_list.json())


def test_project_ownership_operations_do_not_call_openai(ownership_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, _session_store, _session_root = ownership_test_context
    project = _create_project(client, name="No OpenAI Ownership")

    calls = {"openai": 0}

    class _ForbiddenOpenAI:
        def __init__(self, *_args, **_kwargs):
            calls["openai"] += 1

    monkeypatch.setattr(api, "OpenAI", _ForbiddenOpenAI)

    created = client.post(f"/projects/{project['project_id']}/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    listed = client.get(f"/projects/{project['project_id']}/investigation-sessions")
    assert listed.status_code == 200

    fetched = client.get(f"/projects/{project['project_id']}/investigation-sessions/{session_id}")
    assert fetched.status_code == 200

    assert calls["openai"] == 0


def test_project_owned_session_persists_across_store_restart(ownership_test_context):
    client, _project_store, _session_store, session_root = ownership_test_context
    project = _create_project(client, name="Restart Ownership")

    created = client.post(f"/projects/{project['project_id']}/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    restarted_store = InvestigationSessionStore(session_root)
    reloaded = restarted_store.load_session(session_id)

    assert reloaded.project_id == project["project_id"]
