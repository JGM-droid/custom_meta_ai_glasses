from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from investigations.session_store import InvestigationSessionStore
from projects import CheckpointProposalStore, ProjectActivityStore, ProjectStore


class _StaticProvider:
    def analyze(self, _request):
        return api.InvestigationAnalysisResponse(
            schema_version=api.INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
            concise_diagnosis="Capacitor may be faulty.",
            immediate_recommended_action="Test capacitance.",
            supporting_observations=["Visual evidence is inconclusive."],
            confidence_or_uncertainty="Moderate confidence.",
            warning_or_blocker=None,
            follow_up_capture_request=None,
        )


@pytest.fixture
def trust_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
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
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", results / "investigation_latest.json")
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")
    client = TestClient(api.app)
    return client, projects_root, sessions_root


def _completed_investigation(client: TestClient, monkeypatch: pytest.MonkeyPatch, name="AC"):
    project = client.post("/projects", json={"name": name, "goal": "Restore cooling"}).json()
    session = client.post(f"/projects/{project['project_id']}/investigation-sessions", json={}).json()
    uploaded = client.post(
        f"/investigation-sessions/{session['session_id']}/evidence/image",
        data={"normalized_text": "Outdoor unit is not starting."},
        files={"file": ("capture.png", b"image", "image/png")},
    )
    assert uploaded.status_code == 201
    monkeypatch.setattr(api, "_create_session_orchestrator", lambda: api.InvestigationOrchestrator(
        session_store=api.SESSION_STORE, evidence_store=api.EVIDENCE_STORE,
        attempt_store=api.InvestigationAnalysisAttemptStore(api.SESSION_STORE),
        analysis_provider=_StaticProvider(), result_persistence=api._SessionRouteResultPersistence(),
    ))
    analyzed = client.post(f"/investigation-sessions/{session['session_id']}/analyze", json={})
    assert analyzed.status_code == 200
    return project, session["session_id"]


def test_continue_records_working_hypothesis_and_requires_proposal_apply(trust_context, monkeypatch):
    client, _projects_root, _sessions_root = trust_context
    project, session_id = _completed_investigation(client, monkeypatch)
    before = deepcopy(client.get(f"/projects/{project['project_id']}").json())
    original_activity = client.get(f"/projects/{project['project_id']}/activities").json()[0]

    response = client.post(f"/projects/{project['project_id']}/investigation-sessions/{session_id}/trust-decision", json={"decision": "continue"})
    assert response.status_code == 201
    body = response.json()
    assert body["trust_state"]["status"] == "working_hypothesis"
    assert body["checkpoint_proposal"]["status"] == "pending"
    assert body["decision_activity"]["source_type"] == "user"
    assert body["decision_activity"]["confirmation_status"] == "reported"
    assert client.get(f"/projects/{project['project_id']}").json() == before
    activities = client.get(f"/projects/{project['project_id']}/activities").json()
    assert activities[0] == original_activity
    assert activities[0]["confirmation_status"] == "inferred"
    assert not any(a["confirmation_status"] == "confirmed" for a in activities)
    assert not any((a.get("metadata") or {}).get("roadmap_status") == "completed" for a in activities)

    proposal_id = body["checkpoint_proposal"]["proposal_id"]
    assert client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal_id}/apply").status_code == 200
    orientation = client.get(f"/projects/{project['project_id']}/orientation").json()
    assert orientation["next"] == "Test capacitance."


def test_disagree_preserves_ai_result_and_append_only_user_correction(trust_context, monkeypatch):
    client, _projects_root, _sessions_root = trust_context
    project, session_id = _completed_investigation(client, monkeypatch)
    original = client.get(f"/projects/{project['project_id']}/activities").json()[0]
    response = client.post(f"/projects/{project['project_id']}/investigation-sessions/{session_id}/trust-decision", json={"decision": "disagree", "correction": "Capacitor tested within specification."})
    assert response.status_code == 201
    state = response.json()["trust_state"]
    assert state["status"] == "needs_reassessment"
    assert state["user_correction"] == "Capacitor tested within specification."
    activities = client.get(f"/projects/{project['project_id']}/activities").json()
    assert activities[0] == original
    assert activities[0]["source_type"] == "ai"
    assert activities[1]["source_type"] == "user"
    assert activities[1]["metadata"]["source_activity_id"] == original["activity_id"]
    assert activities[1]["metadata"]["trust_result_id"] == original["metadata"]["investigation_result_id"]


def test_more_evidence_keeps_original_and_creates_linked_follow_up(trust_context, monkeypatch):
    client, _projects_root, _sessions_root = trust_context
    project, session_id = _completed_investigation(client, monkeypatch)
    original_session = client.get(f"/projects/{project['project_id']}/investigation-sessions/{session_id}").json()
    response = client.post(f"/projects/{project['project_id']}/investigation-sessions/{session_id}/trust-decision", json={"decision": "more_evidence"})
    assert response.status_code == 201
    state = response.json()["trust_state"]
    assert state["status"] == "unresolved"
    follow_up_id = state["follow_up_investigation_session_id"]
    assert follow_up_id and follow_up_id != session_id
    assert client.get(f"/projects/{project['project_id']}/investigation-sessions/{session_id}").json() == original_session
    follow_up = client.get(f"/projects/{project['project_id']}/investigation-sessions/{follow_up_id}").json()
    assert follow_up["status"] == "created"


def test_trust_read_is_isolated_deterministic_non_mutating_and_zero_ai(trust_context, monkeypatch):
    client, _projects_root, _sessions_root = trust_context
    project_a, session_a = _completed_investigation(client, monkeypatch, "A")
    project_b = client.post("/projects", json={"name": "B", "goal": "B goal"}).json()
    client.post(f"/projects/{project_a['project_id']}/investigation-sessions/{session_a}/trust-decision", json={"decision": "disagree", "correction": "Wrong component."})
    before_project = deepcopy(client.get(f"/projects/{project_a['project_id']}").json())
    before_activities = deepcopy(client.get(f"/projects/{project_a['project_id']}/activities").json())
    monkeypatch.setattr(api, "OpenAI", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no AI")))
    first = client.get(f"/projects/{project_a['project_id']}/investigation-sessions/{session_a}/trust")
    second = client.get(f"/projects/{project_a['project_id']}/investigation-sessions/{session_a}/trust")
    assert first.status_code == 200 and first.json() == second.json()
    assert client.get(f"/projects/{project_b['project_id']}/investigation-sessions/{session_a}/trust").status_code == 404
    assert client.get(f"/projects/{project_a['project_id']}").json() == before_project
    assert client.get(f"/projects/{project_a['project_id']}/activities").json() == before_activities
