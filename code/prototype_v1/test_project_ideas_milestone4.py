from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from investigations.session_store import InvestigationSessionStore
from projects import CheckpointProposalStore, ProjectActivityStore, ProjectStore


@pytest.fixture
def idea_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    results = tmp_path / "results"
    projects_root = results / "projects"
    sessions_root = results / "investigation_sessions"
    project_store = ProjectStore(projects_root)
    activity_store = ProjectActivityStore(projects_root, project_store)
    proposal_store = CheckpointProposalStore(projects_root, project_store, activity_store)
    session_store = InvestigationSessionStore(sessions_root)
    monkeypatch.setattr(api, "PROJECT_STORE", project_store)
    monkeypatch.setattr(api, "PROJECT_ACTIVITY_STORE", activity_store)
    monkeypatch.setattr(api, "CHECKPOINT_PROPOSAL_STORE", proposal_store)
    monkeypatch.setattr(api, "SESSION_STORE", session_store)
    monkeypatch.setattr(api, "EVIDENCE_STORE", api.InvestigationEvidenceStore(session_store))
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")
    return TestClient(api.app)


def _project(client, name="Project"):
    response = client.post("/projects", json={"name": name, "goal": f"Goal {name}", "checkpoint": {"current_work": "Current work", "next_action": "Current next"}})
    assert response.status_code == 201
    return response.json()


def _idea(client, project_id, summary="Future possibility"):
    response = client.post(f"/projects/{project_id}/ideas", json={"summary": summary, "details": "Keep for later", "metadata": {"capture_context": "user thought"}})
    assert response.status_code == 201
    return response.json()


def test_create_idea_is_append_only_and_does_not_change_canonical_plan(idea_context, monkeypatch):
    client = idea_context
    project = _project(client)
    before = deepcopy(client.get(f"/projects/{project['project_id']}").json())
    orientation_before = deepcopy(client.get(f"/projects/{project['project_id']}/orientation").json())
    monkeypatch.setattr(api, "OpenAI", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no AI")))
    idea = _idea(client, project["project_id"])
    assert idea["activity_type"] == "idea"
    assert idea["source_type"] == "user" and idea["confirmation_status"] == "reported"
    assert idea["metadata"]["idea_state"] == "captured"
    assert client.get(f"/projects/{project['project_id']}").json() == before
    assert client.get(f"/projects/{project['project_id']}/orientation").json() == orientation_before
    knowledge = client.get(f"/projects/{project['project_id']}/knowledge").json()
    assert [item["activity_id"] for item in knowledge["history"]] == [idea["activity_id"]]
    assert knowledge["evidence"] == knowledge["decisions"] == knowledge["findings"] == knowledge["recent_important_changes"] == []


def test_ideas_are_isolated_deterministic_and_bounded(idea_context):
    client = idea_context
    project_a = _project(client, "A")
    project_b = _project(client, "B")
    for index in range(102):
        _idea(client, project_a["project_id"], f"A idea {index}")
    _idea(client, project_b["project_id"], "B private")
    first = client.get(f"/projects/{project_a['project_id']}/ideas").json()
    second = client.get(f"/projects/{project_a['project_id']}/ideas").json()
    assert first == second
    assert first["limit"] == 100 and len(first["ideas"]) == 100
    assert first["ideas"][0]["summary"] == "A idea 101"
    assert "B private" not in str(first)


def test_promotion_preserves_idea_creates_upcoming_roadmap_and_is_idempotent(idea_context):
    client = idea_context
    project = _project(client)
    idea = _idea(client, project["project_id"], "Replace thermostat someday")
    project_before = deepcopy(client.get(f"/projects/{project['project_id']}").json())
    promoted = client.post(f"/projects/{project['project_id']}/ideas/{idea['activity_id']}/promote")
    assert promoted.status_code == 200
    body = promoted.json()
    assert body["created"] is True
    roadmap = body["roadmap_activity"]
    assert roadmap["activity_id"] != idea["activity_id"]
    assert roadmap["activity_type"] == "milestone"
    assert roadmap["metadata"] == {"roadmap_status": "upcoming", "promoted_from_activity_id": idea["activity_id"]}
    assert client.get(f"/projects/{project['project_id']}/activities/{idea['activity_id']}").json() == idea
    orientation = client.get(f"/projects/{project['project_id']}/orientation").json()
    assert [item["activity_id"] for item in orientation["roadmap"]["upcoming"]] == [roadmap["activity_id"]]
    after = client.get(f"/projects/{project['project_id']}").json()
    assert after["checkpoint"]["current_work"] == project_before["checkpoint"]["current_work"]
    assert after["checkpoint"]["next_action"] == project_before["checkpoint"]["next_action"]
    again = client.post(f"/projects/{project['project_id']}/ideas/{idea['activity_id']}/promote").json()
    assert again["created"] is False and again["roadmap_activity"]["activity_id"] == roadmap["activity_id"]
    assert len(client.get(f"/projects/{project['project_id']}/orientation").json()["roadmap"]["upcoming"]) == 1
    knowledge = client.get(f"/projects/{project['project_id']}/knowledge").json()
    assert roadmap["activity_id"] in {item["activity_id"] for item in knowledge["recent_important_changes"]}
    assert idea["activity_id"] not in {item["activity_id"] for item in knowledge["recent_important_changes"]}


def test_cross_project_promotion_rejected_and_open_question_type_supported(idea_context):
    client = idea_context
    project_a = _project(client, "A")
    project_b = _project(client, "B")
    idea = _idea(client, project_a["project_id"])
    cross = client.post(f"/projects/{project_b['project_id']}/ideas/{idea['activity_id']}/promote")
    assert cross.status_code == 404
    question = client.post(f"/projects/{project_a['project_id']}/activities", json={
        "activity_type": "open_question", "source_type": "user", "confirmation_status": "reported",
        "summary": "Which approach should we test?",
    })
    assert question.status_code == 201
    knowledge = client.get(f"/projects/{project_a['project_id']}/knowledge").json()
    assert question.json()["activity_id"] in {item["activity_id"] for item in knowledge["history"]}
    assert question.json()["activity_id"] not in {item.get("activity_id") for item in knowledge["recent_important_changes"]}
