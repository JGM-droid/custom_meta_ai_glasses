from __future__ import annotations

import io
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import api
from investigations.session_store import InvestigationSessionStore
from projects import CheckpointProposalStore, ProjectActivityStore, ProjectStore


# Narrow regression coverage for the Active Capture Project slice: exposing
# the existing Phase B ActiveProjectPointer mechanism
# (PUT/GET /projects/active[/{id}]) plus one small addition (DELETE
# /projects/active, to clear it) as a real product concept, and wiring
# Investigation-start attribution precedence (explicit project_id > Active
# Capture Project > unscoped) through the two entry points that accept an
# optional project_id: POST /demo/investigations and POST
# /investigation-sessions. The project-scoped POST
# /projects/{project_id}/investigation-sessions endpoint is not touched -
# its project_id always comes from the URL path, so there is never
# ambiguity for it to resolve.
#
# These tests do not re-prove Phase B set/get active-pointer persistence
# itself (see test_projects_phaseb.py::test_active_project_selection_is_
# persistent_and_does_not_mutate_records and
# ::test_restart_persistence_for_multiple_projects_and_active_pointer) or
# D1/D2 ownership/projection mechanics (see
# test_investigation_project_ownership_phased1.py and
# test_investigation_project_activity_phase_d2.py) - they prove clear
# (the one new endpoint) and the new attribution-precedence composition.


@pytest.fixture
def active_project_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    results_root = tmp_path / "results"
    projects_root = results_root / "projects"
    session_root = results_root / "investigation_sessions"

    project_store = ProjectStore(projects_root)
    activity_store = ProjectActivityStore(projects_root, project_store)
    checkpoint_proposal_store = CheckpointProposalStore(projects_root, project_store, activity_store)
    session_store = InvestigationSessionStore(session_root)

    monkeypatch.setattr(api, "RESULTS_DIR", results_root)
    monkeypatch.setattr(api, "PROJECTS_ROOT", projects_root)
    monkeypatch.setattr(api, "PROJECT_STORE", project_store)
    monkeypatch.setattr(api, "PROJECT_ACTIVITY_STORE", activity_store)
    monkeypatch.setattr(api, "CHECKPOINT_PROPOSAL_STORE", checkpoint_proposal_store)
    monkeypatch.setattr(api, "INVESTIGATION_SESSIONS_ROOT", session_root)
    monkeypatch.setattr(api, "SESSION_STORE", session_store)
    monkeypatch.setattr(api, "EVIDENCE_STORE", api.InvestigationEvidenceStore(session_store))
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", results_root / "investigation_latest.json")
    monkeypatch.setattr(api, "DEMO_INVESTIGATION_REGISTRY", api._DemoInvestigationRegistry())
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")

    client = TestClient(api.app)
    return client, project_store, activity_store, session_store, projects_root


def _create_project(client: TestClient, *, name: str) -> dict[str, object]:
    response = client.post("/projects", json={"name": name, "goal": f"Goal for {name}"})
    assert response.status_code == 201
    return response.json()


def _image_part(name: str, content: bytes = b"1", content_type: str = "image/png") -> tuple[str, io.BytesIO, str]:
    return (name, io.BytesIO(content), content_type)


def _one_image() -> list[tuple[str, io.BytesIO, str]]:
    return [_image_part("first.png")]


def _two_images() -> list[tuple[str, io.BytesIO, str]]:
    # A demo Investigation only produces a canonical retained result (and is
    # therefore only eligible for D2 Activity projection) with >= 2 images.
    return [_image_part("first.png", b"1"), _image_part("second.png", b"2")]


def _post_demo_investigation(client: TestClient, files: list[tuple[str, io.BytesIO, str]], **overrides: str):
    data = {
        "mode": "dry_run",
        "user_explanation": "active capture project slice validation",
    }
    data.update(overrides)
    multipart = [("images", file_part) for file_part in files]
    return client.post("/demo/investigations", data=data, files=multipart)


def _wait_for_demo_terminal_snapshot(client: TestClient, demo_id: str) -> dict[str, object]:
    snapshot = client.get(f"/demo/investigations/{demo_id}").json()
    for _ in range(60):
        if snapshot["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
        snapshot = client.get(f"/demo/investigations/{demo_id}").json()
    return snapshot


# --------------------------------------------------------------------------
# 1-8: Active Capture Project set/get/switch/clear behavior
# --------------------------------------------------------------------------


def test_set_get_switch_active_project(active_project_context):
    client, *_rest = active_project_context
    a = _create_project(client, name="Upstairs AC Repair")
    b = _create_project(client, name="Lanyard Construction Website")

    set_a = client.put(f"/projects/active/{a['project_id']}")
    assert set_a.status_code == 200
    assert client.get("/projects/active").json()["project_id"] == a["project_id"]

    set_b = client.put(f"/projects/active/{b['project_id']}")
    assert set_b.status_code == 200
    active_after_switch = client.get("/projects/active")
    assert active_after_switch.status_code == 200
    assert active_after_switch.json()["project_id"] == b["project_id"]
    assert active_after_switch.json()["project_id"] != a["project_id"]


def test_clear_active_project(active_project_context):
    client, *_rest = active_project_context
    a = _create_project(client, name="Upstairs AC Repair")

    assert client.put(f"/projects/active/{a['project_id']}").status_code == 200
    assert client.get("/projects/active").status_code == 200

    clear = client.delete("/projects/active")
    assert clear.status_code == 204
    assert clear.content == b""

    after_clear = client.get("/projects/active")
    assert after_clear.status_code == 404
    assert after_clear.json()["detail"]["category"] == "active_project_not_set"


def test_clear_active_project_is_idempotent_when_nothing_is_active(active_project_context):
    client, *_rest = active_project_context
    # No project has ever been made active in this fixture - clearing must
    # still succeed rather than error.
    clear = client.delete("/projects/active")
    assert clear.status_code == 204


def test_clearing_active_project_does_not_delete_or_mutate_the_project(active_project_context):
    client, *_rest = active_project_context
    a = _create_project(client, name="Upstairs AC Repair")
    before = client.get(f"/projects/{a['project_id']}").json()

    client.put(f"/projects/active/{a['project_id']}")
    client.delete("/projects/active")

    after = client.get(f"/projects/{a['project_id']}").json()
    assert after == before


def test_set_active_project_with_unknown_id_fails_safely(active_project_context):
    client, *_rest = active_project_context
    unknown = client.put(f"/projects/active/{uuid4()}")
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["category"] == "project_not_found"
    assert client.get("/projects/active").status_code == 404


def test_switching_active_project_does_not_mutate_either_project(active_project_context):
    client, *_rest = active_project_context
    a = _create_project(client, name="Upstairs AC Repair")
    b = _create_project(client, name="Lanyard Construction Website")
    a_before = client.get(f"/projects/{a['project_id']}").json()
    b_before = client.get(f"/projects/{b['project_id']}").json()

    client.put(f"/projects/active/{a['project_id']}")
    client.put(f"/projects/active/{b['project_id']}")

    assert client.get(f"/projects/{a['project_id']}").json() == a_before
    assert client.get(f"/projects/{b['project_id']}").json() == b_before


def test_clear_active_project_persists_across_restart(active_project_context):
    client, _project_store, _activity_store, _session_store, projects_root = active_project_context
    a = _create_project(client, name="Upstairs AC Repair")

    client.put(f"/projects/active/{a['project_id']}")
    client.delete("/projects/active")

    restarted_store = ProjectStore(projects_root)
    with pytest.raises(api.ActiveProjectNotSet):
        restarted_store.get_active_project_id()


# --------------------------------------------------------------------------
# 9-13: Investigation-start attribution precedence
# --------------------------------------------------------------------------


def test_demo_investigation_with_no_explicit_project_uses_active_project(active_project_context):
    client, *_rest = active_project_context
    active_project = _create_project(client, name="Upstairs AC Repair")
    client.put(f"/projects/active/{active_project['project_id']}")

    response = _post_demo_investigation(client, _one_image())
    assert response.status_code == 202
    snapshot = _wait_for_demo_terminal_snapshot(client, response.json()["demo_id"])
    assert snapshot["status"] == "completed"

    owned = client.get(f"/projects/{active_project['project_id']}/investigation-sessions")
    assert owned.status_code == 200
    assert snapshot["session_id"] in [item["session_id"] for item in owned.json()]


def test_demo_investigation_with_explicit_project_overrides_active_project(active_project_context):
    client, *_rest = active_project_context
    active_project = _create_project(client, name="Upstairs AC Repair")
    explicit_project = _create_project(client, name="Lanyard Construction Website")
    client.put(f"/projects/active/{active_project['project_id']}")

    response = _post_demo_investigation(client, _one_image(), project_id=explicit_project["project_id"])
    assert response.status_code == 202
    snapshot = _wait_for_demo_terminal_snapshot(client, response.json()["demo_id"])
    assert snapshot["status"] == "completed"

    owned_by_explicit = client.get(f"/projects/{explicit_project['project_id']}/investigation-sessions")
    assert snapshot["session_id"] in [item["session_id"] for item in owned_by_explicit.json()]

    owned_by_active = client.get(f"/projects/{active_project['project_id']}/investigation-sessions")
    assert snapshot["session_id"] not in [item["session_id"] for item in owned_by_active.json()]


def test_demo_investigation_with_no_project_id_and_no_active_project_remains_unscoped(active_project_context):
    client, _project_store, _activity_store, session_store, _root = active_project_context
    # No project created, no active project set.
    response = _post_demo_investigation(client, _one_image())
    assert response.status_code == 202
    snapshot = _wait_for_demo_terminal_snapshot(client, response.json()["demo_id"])
    assert snapshot["status"] == "completed"

    session = session_store.load_session(snapshot["session_id"])
    assert session.project_id is None


def test_active_project_investigation_creates_exactly_one_correctly_owned_activity(active_project_context):
    client, *_rest = active_project_context
    active_project = _create_project(client, name="Upstairs AC Repair")
    client.put(f"/projects/active/{active_project['project_id']}")

    response = _post_demo_investigation(client, _two_images())
    snapshot = _wait_for_demo_terminal_snapshot(client, response.json()["demo_id"])
    assert snapshot["status"] == "completed"
    assert snapshot["retained_result"] is not None

    activities = client.get(f"/projects/{active_project['project_id']}/activities")
    assert activities.status_code == 200
    body = activities.json()
    assert len(body) == 1
    assert body[0]["project_id"] == active_project["project_id"]
    assert body[0]["activity_type"] == "result"
    assert body[0]["source_type"] == "ai"


def test_active_project_isolation_no_cross_project_activity_leakage(active_project_context):
    client, *_rest = active_project_context
    active_project = _create_project(client, name="Upstairs AC Repair")
    other_project = _create_project(client, name="Lanyard Construction Website")
    client.put(f"/projects/active/{active_project['project_id']}")

    response = _post_demo_investigation(client, _two_images())
    snapshot = _wait_for_demo_terminal_snapshot(client, response.json()["demo_id"])
    assert snapshot["status"] == "completed"

    other_activities = client.get(f"/projects/{other_project['project_id']}/activities")
    assert other_activities.status_code == 200
    assert other_activities.json() == []


def test_global_investigation_session_endpoint_uses_same_precedence(active_project_context):
    # The generic (non-project-scoped, non-demo) POST /investigation-sessions
    # entry point also accepts an optional project_id and must resolve
    # attribution with the identical explicit > active > unscoped rule.
    client, *_rest = active_project_context
    active_project = _create_project(client, name="Upstairs AC Repair")
    explicit_project = _create_project(client, name="Lanyard Construction Website")
    client.put(f"/projects/active/{active_project['project_id']}")

    implicit = client.post("/investigation-sessions", json={})
    assert implicit.status_code == 201
    assert implicit.json()["project_id"] == active_project["project_id"]

    explicit = client.post("/investigation-sessions", json={"project_id": explicit_project["project_id"]})
    assert explicit.status_code == 201
    assert explicit.json()["project_id"] == explicit_project["project_id"]

    client.delete("/projects/active")
    unscoped = client.post("/investigation-sessions", json={})
    assert unscoped.status_code == 201
    assert unscoped.json()["project_id"] is None


def test_project_scoped_investigation_endpoint_is_unaffected_by_active_project(active_project_context):
    # The path-scoped endpoint's project_id is never ambiguous - it always
    # comes from the URL, so an unrelated Active Capture Project must not
    # change its behavior at all.
    client, *_rest = active_project_context
    path_project = _create_project(client, name="Upstairs AC Repair")
    different_active_project = _create_project(client, name="Lanyard Construction Website")
    client.put(f"/projects/active/{different_active_project['project_id']}")

    created = client.post(f"/projects/{path_project['project_id']}/investigation-sessions", json={})
    assert created.status_code == 201
    assert created.json()["project_id"] == path_project["project_id"]
