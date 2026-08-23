from __future__ import annotations

import io
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from investigations.session_store import InvestigationSessionStore
from projects import CheckpointProposalStore, ProjectActivityStore, ProjectStore


@pytest.fixture
def mvp_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
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
    monkeypatch.setattr(api, "DEMO_INVESTIGATION_REGISTRY", api._DemoInvestigationRegistry())
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")
    return TestClient(api.app), projects_root, sessions_root


def _activity(client, project_id, summary, activity_type, confirmation="confirmed", metadata=None):
    response = client.post(f"/projects/{project_id}/activities", json={
        "activity_type": activity_type, "source_type": "user",
        "confirmation_status": confirmation, "summary": summary, "metadata": metadata,
    })
    assert response.status_code == 201
    return response.json()


def _wait_demo(client, demo_id):
    for _ in range(80):
        snap = client.get(f"/demo/investigations/{demo_id}").json()
        if snap["status"] in {"completed", "failed"}:
            return snap
        time.sleep(.05)
    raise AssertionError("demo Investigation did not finish")


def test_complete_offline_mvp_story_survives_store_restart_and_isolates_projects(mvp_context, monkeypatch):
    client, projects_root, sessions_root = mvp_context
    monkeypatch.setattr(api, "OpenAI", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("offline MVP must not call AI")))
    project = client.post("/projects", json={
        "name": "AC Repair", "goal": "Restore reliable cooling",
        "checkpoint": {"current_objective": "Electrical diagnosis", "current_work": "Testing capacitor", "next_action": "Measure capacitance"},
    }).json()
    other = client.post("/projects", json={"name": "Software Project", "goal": "Ship safely"}).json()
    for summary, status in [("Inspect system", "completed"), ("Test capacitor", "current"), ("Repair fault", "upcoming"), ("Replace thermostat", "deferred")]:
        _activity(client, project["project_id"], summary, "milestone", metadata={"roadmap_status": status})
    orientation = client.get(f"/projects/{project['project_id']}/orientation").json()
    assert orientation["now"] == "Testing capacitor"
    assert orientation["roadmap"]["current"][0]["summary"] == "Test capacitor"

    files = [("images", ("meter.png", io.BytesIO(b"one"), "image/png")), ("images", ("unit.png", io.BytesIO(b"two"), "image/png"))]
    run = client.post("/demo/investigations", data={"mode": "dry_run", "project_id": project["project_id"], "user_explanation": "Capacitor and outdoor unit evidence"}, files=files)
    assert run.status_code == 202
    snapshot = _wait_demo(client, run.json()["demo_id"])
    assert snapshot["status"] == "completed" and snapshot["retained_result"]
    session_id = snapshot["session_id"]
    ai_activity = [a for a in client.get(f"/projects/{project['project_id']}/activities").json() if a["source_type"] == "ai"][0]
    assert ai_activity["confirmation_status"] == "inferred"

    continued = client.post(f"/projects/{project['project_id']}/investigation-sessions/{session_id}/trust-decision", json={"decision": "continue"})
    assert continued.status_code == 201
    assert continued.json()["trust_state"]["status"] == "working_hypothesis"
    assert continued.json()["checkpoint_proposal"]["status"] == "pending"
    assert client.get(f"/projects/{project['project_id']}/orientation").json()["next"] == "Measure capacitance"
    proposal_id = continued.json()["checkpoint_proposal"]["proposal_id"]
    assert client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal_id}/apply").status_code == 200
    assert client.get(f"/projects/{project['project_id']}/orientation").json()["next"] == snapshot["retained_result"]["required_next_action"]

    _activity(client, project["project_id"], "Capacitor measured below specification", "observation", "observed")
    _activity(client, project["project_id"], "Replace capacitor", "decision")
    _activity(client, project["project_id"], "Capacitor is below specification", "result")
    knowledge = client.get(f"/projects/{project['project_id']}/knowledge").json()
    assert knowledge["evidence"] and knowledge["decisions"] and knowledge["findings"] and knowledge["history"]
    assert any(x["activity_id"] == ai_activity["activity_id"] and x["confirmation_status"] == "inferred" for x in knowledge["recent_important_changes"])

    idea = client.post(f"/projects/{project['project_id']}/ideas", json={"summary": "Replace thermostat later"}).json()
    before_promotion = client.get(f"/projects/{project['project_id']}/orientation").json()
    assert idea["activity_id"] not in str(before_promotion["roadmap"])
    promoted = client.post(f"/projects/{project['project_id']}/ideas/{idea['activity_id']}/promote").json()
    assert promoted["roadmap_activity"]["metadata"]["promoted_from_activity_id"] == idea["activity_id"]
    after_promotion = client.get(f"/projects/{project['project_id']}/orientation").json()
    assert promoted["roadmap_activity"]["activity_id"] in {x["activity_id"] for x in after_promotion["roadmap"]["upcoming"]}
    assert idea["activity_id"] in {x["activity_id"] for x in client.get(f"/projects/{project['project_id']}/knowledge").json()["history"]}
    assert client.get(f"/projects/{other['project_id']}/knowledge").json()["history"] == []

    expected_orientation = after_promotion
    restarted_project_store = ProjectStore(projects_root)
    restarted_activity_store = ProjectActivityStore(projects_root, restarted_project_store)
    restarted_proposal_store = CheckpointProposalStore(projects_root, restarted_project_store, restarted_activity_store)
    restarted_session_store = InvestigationSessionStore(sessions_root)
    monkeypatch.setattr(api, "PROJECT_STORE", restarted_project_store)
    monkeypatch.setattr(api, "PROJECT_ACTIVITY_STORE", restarted_activity_store)
    monkeypatch.setattr(api, "CHECKPOINT_PROPOSAL_STORE", restarted_proposal_store)
    monkeypatch.setattr(api, "SESSION_STORE", restarted_session_store)
    monkeypatch.setattr(api, "EVIDENCE_STORE", api.InvestigationEvidenceStore(restarted_session_store))
    assert client.get(f"/projects/{project['project_id']}/orientation").json() == expected_orientation
    assert client.get(f"/projects/{project['project_id']}/knowledge").json()["findings"]
    assert client.get(f"/projects/{project['project_id']}/ideas").json()["ideas"][0]["activity_id"] == idea["activity_id"]


def test_mvp_demo_page_exposes_locked_workflow_without_touching_dashboard(mvp_context):
    client, *_ = mvp_context
    response = client.get("/mvp-demo")
    assert response.status_code == 200
    source = response.text
    for required in ["Where we are", "Roadmap", "Recent Important Changes", "Evidence", "Decisions", "Confirmed Findings", "History", "Capture Idea", "Promote", "Continue", "Disagree", "More Evidence", "AI hypothesis", "Recommended next action"]:
        assert required in source
    assert "mode','dry_run" in source
    assert "/orientation" in source and "/knowledge" in source and "/ideas" in source and "/trust-decision" in source
    assert "/trust`" in source


def test_mvp_demo_bootstrap_is_repeatable_and_trust_controls_are_gated(mvp_context):
    client, projects_root, _ = mvp_context
    source = client.get("/mvp-demo").text

    assert "Open AC Repair MVP Demo" in source
    assert "AC Repair — MVP Demo" in source
    assert "ac-repair-mvp-v1" in source
    assert "findDemoProject" in source
    assert "demo_fixture_id" in source
    assert "if(!p)" in source
    assert 'data-decision="continue" disabled' in source
    assert 'data-decision="disagree" disabled' in source
    assert 'data-decision="more_evidence" disabled' in source
    assert "setTrustEnabled(true)" in source
    assert "inferred suggestion, not confirmed Project truth" in source

    # The acceptance harness is bound to its pytest temp store, never the configured live store.
    assert projects_root.parent.name == "results"
    assert projects_root != api.PROJECTS_ROOT
