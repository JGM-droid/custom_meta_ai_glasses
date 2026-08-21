from __future__ import annotations

import io
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from investigations.session_store import InvestigationSessionStore
from projects import CheckpointProposalStore, ProjectActivityStore, ProjectStore


# Narrow regression coverage for the demo-investigation -> Project integration
# slice: connecting the existing dashboard "Start Demo Investigation" path to
# an optional, already-existing Project using the existing D1 (session
# ownership) and D2 (Investigation -> Activity projection) mechanisms.
#
# These tests do not re-prove D1/D2 themselves (see
# test_investigation_project_ownership_phased1.py and
# test_investigation_project_activity_phase_d2.py); they prove the demo path
# now composes correctly with that existing, already-tested machinery.
#
# Note: a demo Investigation only produces a canonical retained result (and
# therefore only becomes eligible for D2 Activity projection) with 2 or more
# images, matching the existing one-image dry-run constraint already covered
# by test_demo_investigation_accepts_one_image_dry_run in
# test_investigations_api.py (its retained_result is None for one image).
# Tests below that assert Activity projection use two images accordingly;
# ownership/backward-compatibility tests, which do not depend on projection,
# use a single image.


@pytest.fixture
def demo_project_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
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
    return client, project_store, activity_store, session_store


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
        "user_explanation": "dashboard demo explanation for project integration",
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


def test_demo_investigation_with_project_id_is_owned_by_that_project(demo_project_context):
    client, *_rest = demo_project_context
    project = _create_project(client, name="Project A")

    response = _post_demo_investigation(client, _one_image(), project_id=project["project_id"])
    assert response.status_code == 202
    snapshot = _wait_for_demo_terminal_snapshot(client, response.json()["demo_id"])
    assert snapshot["status"] == "completed"
    session_id = snapshot["session_id"]

    owned = client.get(f"/projects/{project['project_id']}/investigation-sessions")
    assert owned.status_code == 200
    assert session_id in [item["session_id"] for item in owned.json()]

    session_detail = client.get(f"/projects/{project['project_id']}/investigation-sessions/{session_id}")
    assert session_detail.status_code == 200
    assert session_detail.json()["project_id"] == project["project_id"]


def test_demo_investigation_with_unknown_project_id_returns_404_and_creates_no_session(demo_project_context):
    client, _project_store, _activity_store, session_store = demo_project_context

    response = _post_demo_investigation(
        client,
        _one_image(),
        project_id="00000000-0000-0000-0000-000000000000",
    )
    assert response.status_code == 404
    assert session_store.list_sessions() == []


def test_demo_investigation_completion_creates_exactly_one_project_activity(demo_project_context):
    client, _project_store, _activity_store, _session_store = demo_project_context
    project = _create_project(client, name="Project A")

    response = _post_demo_investigation(client, _two_images(), project_id=project["project_id"])
    snapshot = _wait_for_demo_terminal_snapshot(client, response.json()["demo_id"])
    assert snapshot["status"] == "completed"
    assert snapshot["retained_result"] is not None

    activities = client.get(f"/projects/{project['project_id']}/activities")
    assert activities.status_code == 200
    body = activities.json()
    assert len(body) == 1

    activity = body[0]
    assert activity["project_id"] == project["project_id"]
    assert activity["activity_type"] == "result"
    assert activity["source_type"] == "ai"
    assert activity["confirmation_status"] == "inferred"
    assert activity["metadata"]["investigation_session_id"] == snapshot["session_id"]
    assert activity["metadata"]["investigation_result_id"]


def test_demo_investigation_project_isolation_between_a_and_b(demo_project_context):
    client, *_rest = demo_project_context
    project_a = _create_project(client, name="Project A")
    project_b = _create_project(client, name="Project B")

    response = _post_demo_investigation(client, _two_images(), project_id=project_a["project_id"])
    snapshot = _wait_for_demo_terminal_snapshot(client, response.json()["demo_id"])
    assert snapshot["status"] == "completed"
    session_id = snapshot["session_id"]

    a_sessions = client.get(f"/projects/{project_a['project_id']}/investigation-sessions").json()
    b_sessions = client.get(f"/projects/{project_b['project_id']}/investigation-sessions").json()
    assert session_id in [item["session_id"] for item in a_sessions]
    assert session_id not in [item["session_id"] for item in b_sessions]

    cross_project_lookup = client.get(f"/projects/{project_b['project_id']}/investigation-sessions/{session_id}")
    assert cross_project_lookup.status_code == 404

    a_activities = client.get(f"/projects/{project_a['project_id']}/activities").json()
    b_activities = client.get(f"/projects/{project_b['project_id']}/activities").json()
    assert len(a_activities) == 1
    assert len(b_activities) == 0


def test_demo_investigation_does_not_mutate_project_checkpoint_or_revision(demo_project_context):
    client, *_rest = demo_project_context
    project = _create_project(client, name="Project A")
    before = client.get(f"/projects/{project['project_id']}").json()

    response = _post_demo_investigation(client, _two_images(), project_id=project["project_id"])
    snapshot = _wait_for_demo_terminal_snapshot(client, response.json()["demo_id"])
    assert snapshot["status"] == "completed"

    after = client.get(f"/projects/{project['project_id']}").json()
    assert after["checkpoint"] == before["checkpoint"]
    assert after["revision"] == before["revision"]
    assert after["updated_at_utc"] == before["updated_at_utc"]

    proposals = client.get(f"/projects/{project['project_id']}/checkpoint-proposals")
    assert proposals.status_code == 200
    assert proposals.json() == []


def test_demo_investigation_activity_projection_is_idempotent(demo_project_context):
    client, _project_store, _activity_store, session_store = demo_project_context
    project = _create_project(client, name="Project A")

    response = _post_demo_investigation(client, _two_images(), project_id=project["project_id"])
    demo_id = response.json()["demo_id"]
    snapshot = _wait_for_demo_terminal_snapshot(client, demo_id)
    assert snapshot["status"] == "completed"

    # Repeated dashboard polling of the (already-completed) demo snapshot must
    # not create additional Activities.
    for _ in range(5):
        again = client.get(f"/demo/investigations/{demo_id}")
        assert again.status_code == 200
        assert again.json()["status"] == "completed"

    activities_after_polling = client.get(f"/projects/{project['project_id']}/activities").json()
    assert len(activities_after_polling) == 1
    first_activity_id = activities_after_polling[0]["activity_id"]

    # Directly re-invoking the shared D2 projection helper for the same
    # completed session must return the existing Activity rather than create
    # a duplicate (store-level idempotency, reused unchanged from D2).
    completed_session = session_store.load_session(snapshot["session_id"])
    duplicate = api._project_completed_investigation_activity(completed_session)
    assert duplicate is not None
    assert duplicate.activity_id == first_activity_id

    activities_after_duplicate_call = client.get(f"/projects/{project['project_id']}/activities").json()
    assert len(activities_after_duplicate_call) == 1


def test_demo_investigation_without_project_id_remains_ownerless(demo_project_context):
    client, _project_store, _activity_store, session_store = demo_project_context

    response = _post_demo_investigation(client, _one_image())
    assert response.status_code == 202
    snapshot = _wait_for_demo_terminal_snapshot(client, response.json()["demo_id"])
    assert snapshot["status"] == "completed"

    session = session_store.load_session(snapshot["session_id"])
    assert session.project_id is None

    project = _create_project(client, name="Unrelated Project")
    assert client.get(f"/projects/{project['project_id']}/activities").json() == []


def test_demo_investigation_blank_project_id_behaves_as_no_project(demo_project_context):
    client, _project_store, _activity_store, session_store = demo_project_context

    response = _post_demo_investigation(client, _one_image(), project_id="")
    assert response.status_code == 202
    snapshot = _wait_for_demo_terminal_snapshot(client, response.json()["demo_id"])
    assert snapshot["status"] == "completed"

    session = session_store.load_session(snapshot["session_id"])
    assert session.project_id is None
