from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from investigations.session_store import InvestigationSessionStore
from projects import CheckpointProposalStore, ProjectActivityStore, ProjectStore


@pytest.fixture
def knowledge_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
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
    response = client.post("/projects", json={"name": name, "goal": f"Goal {name}"})
    assert response.status_code == 201
    return response.json()


def _activity(client, project_id, summary, *, activity_type="note", source_type="user",
              confirmation_status="reported", occurred="2026-01-01T00:00:00Z", metadata=None):
    response = client.post(f"/projects/{project_id}/activities", json={
        "activity_type": activity_type, "source_type": source_type,
        "confirmation_status": confirmation_status, "summary": summary,
        "occurred_at_utc": occurred, "metadata": metadata,
    })
    assert response.status_code == 201
    return response.json()


def test_knowledge_classifies_evidence_decisions_findings_without_promoting_ai(knowledge_context):
    client = knowledge_context
    project = _project(client)
    project_id = project["project_id"]
    session = client.post(f"/projects/{project_id}/investigation-sessions", json={}).json()
    uploaded = client.post(
        f"/investigation-sessions/{session['session_id']}/evidence/image",
        data={"normalized_text": "Capacitor measured 3.1 uF"},
        files={"file": ("meter.png", b"image", "image/png")},
    )
    assert uploaded.status_code == 201
    observation = _activity(client, project_id, "Measured 3.1 uF", activity_type="observation", confirmation_status="observed", occurred="2026-01-01T00:00:01Z")
    ai = _activity(client, project_id, "Capacitor may be faulty", activity_type="result", source_type="ai", confirmation_status="inferred", occurred="2026-01-01T00:00:02Z")
    decision = _activity(client, project_id, "Replace capacitor", activity_type="decision", confirmation_status="confirmed", occurred="2026-01-01T00:00:03Z")
    finding = _activity(client, project_id, "Capacitor below specification", activity_type="result", confirmation_status="confirmed", occurred="2026-01-01T00:00:04Z")

    body = client.get(f"/projects/{project_id}/knowledge").json()
    assert {e["origin"] for e in body["evidence"]} == {"investigation_evidence", "activity_observation"}
    assert any(e["evidence_id"] == uploaded.json()["evidence_id"] and e["investigation_session_id"] == session["session_id"] for e in body["evidence"])
    assert any(e["activity_id"] == observation["activity_id"] and e["confirmation_status"] == "observed" for e in body["evidence"])
    assert [d["activity_id"] for d in body["decisions"]] == [decision["activity_id"]]
    assert [f["activity_id"] for f in body["findings"]] == [finding["activity_id"]]
    assert ai["activity_id"] not in {d["activity_id"] for d in body["decisions"]}
    assert ai["activity_id"] not in {f["activity_id"] for f in body["findings"]}


def test_pending_proposal_is_not_decision_but_applied_proposal_is(knowledge_context):
    client = knowledge_context
    project = _project(client)
    source = _activity(client, project["project_id"], "User chose direction")
    payload = {"expected_project_revision": 0, "source_activity_ids": [source["activity_id"]],
               "proposed_checkpoint_patch": {"next_action": "Run validation"}, "reason": "Validated direction"}
    pending = client.post(f"/projects/{project['project_id']}/checkpoint-proposals", json=payload).json()
    assert client.get(f"/projects/{project['project_id']}/knowledge").json()["decisions"] == []
    assert client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{pending['proposal_id']}/apply").status_code == 200
    decisions = client.get(f"/projects/{project['project_id']}/knowledge").json()["decisions"]
    assert decisions[0]["proposal_id"] == pending["proposal_id"]
    assert decisions[0]["confirmation_status"] == "confirmed"


def test_history_and_recent_changes_are_deterministic_bounded_and_filtered(knowledge_context):
    client = knowledge_context
    project = _project(client)
    project_id = project["project_id"]
    _activity(client, project_id, "Trivial note", occurred="2026-01-01T00:00:00Z")
    for index in range(12):
        _activity(client, project_id, f"Milestone {index}", activity_type="milestone", occurred=f"2026-01-01T00:00:{index + 1:02d}Z")
    first = client.get(f"/projects/{project_id}/knowledge").json()
    second = client.get(f"/projects/{project_id}/knowledge").json()
    assert first == second
    assert first["history_limit"] == 100
    assert first["recent_important_change_limit"] == 10
    assert len(first["history"]) == 13
    assert first["history"][0]["summary"] == "Milestone 11"
    assert len(first["recent_important_changes"]) == 10
    assert first["recent_important_changes"][0]["summary"] == "Milestone 11"
    assert "Trivial note" not in {item["summary"] for item in first["recent_important_changes"]}


def test_knowledge_is_project_isolated_empty_non_mutating_and_zero_ai(knowledge_context, monkeypatch):
    client = knowledge_context
    project_a = _project(client, "A")
    project_b = _project(client, "B")
    _activity(client, project_b["project_id"], "B private decision", activity_type="decision", confirmation_status="confirmed")
    before = deepcopy(client.get(f"/projects/{project_a['project_id']}").json())
    before_activities = deepcopy(client.get(f"/projects/{project_a['project_id']}/activities").json())
    monkeypatch.setattr(api, "OpenAI", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no AI")))
    response = client.get(f"/projects/{project_a['project_id']}/knowledge")
    assert response.status_code == 200
    body = response.json()
    assert body["evidence"] == body["decisions"] == body["findings"] == body["history"] == body["recent_important_changes"] == []
    assert client.get(f"/projects/{project_a['project_id']}").json() == before
    assert client.get(f"/projects/{project_a['project_id']}/activities").json() == before_activities
    assert "B private decision" not in str(body)
