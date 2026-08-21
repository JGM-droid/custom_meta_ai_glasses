from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from investigations.session_store import InvestigationSessionStore
from projects import ProjectActivityStore, ProjectContextRetriever, ProjectStore


class _StaticProvider:
    def analyze(self, _request_package):
        return api.InvestigationAnalysisResponse(
            schema_version=api.INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
            concise_diagnosis="Likely a UI rendering failure.",
            immediate_recommended_action="Rebuild the frontend bundle and recheck the viewport.",
            supporting_observations=["Evidence was ordered and normalized."],
            confidence_or_uncertainty="Moderate confidence.",
            warning_or_blocker=None,
            follow_up_capture_request=None,
        )


@pytest.fixture
def project_context_test_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    results_root = tmp_path / "results"
    projects_root = results_root / "projects"
    session_root = results_root / "investigation_sessions"

    project_store = ProjectStore(projects_root)
    activity_store = ProjectActivityStore(projects_root, project_store)
    session_store = InvestigationSessionStore(session_root)

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
    return client, project_store, activity_store, session_store, projects_root


def _create_project(client: TestClient, *, name: str, checkpoint: dict[str, str]) -> dict[str, object]:
    response = client.post(
        "/projects",
        json={
            "name": name,
            "goal": f"Goal for {name}",
            "checkpoint": checkpoint,
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_activity(
    client: TestClient,
    project_id: str,
    *,
    summary: str,
    occurred_at_utc: str,
):
    response = client.post(
        f"/projects/{project_id}/activities",
        json={
            "activity_type": "note",
            "source_type": "user",
            "confirmation_status": "reported",
            "summary": summary,
            "occurred_at_utc": occurred_at_utc,
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_project_owned_session_with_image(client: TestClient, project_id: str) -> str:
    created = client.post(f"/projects/{project_id}/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    uploaded = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        data={"normalized_text": "The image shows a missing configuration file error."},
        files={"file": ("capture.png", b"image-bytes", "image/png")},
    )
    assert uploaded.status_code == 201
    return session_id


def _create_unowned_session_with_image(client: TestClient) -> str:
    created = client.post("/investigation-sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    uploaded = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        data={"normalized_text": "Legacy session evidence."},
        files={"file": ("capture.png", b"image-bytes", "image/png")},
    )
    assert uploaded.status_code == 201
    return session_id


def _analyze_with_static_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        api,
        "_create_session_orchestrator",
        lambda: api.InvestigationOrchestrator(
            session_store=api.SESSION_STORE,
            evidence_store=api.EVIDENCE_STORE,
            attempt_store=api.InvestigationAnalysisAttemptStore(api.SESSION_STORE),
            analysis_provider=_StaticProvider(),
            result_persistence=api._SessionRouteResultPersistence(),
        ),
    )


def _complete_project_owned_investigation(client: TestClient, monkeypatch: pytest.MonkeyPatch, project_id: str) -> str:
    _analyze_with_static_provider(monkeypatch)
    session_id = _create_project_owned_session_with_image(client, project_id)
    response = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    return session_id


def _complete_unowned_investigation(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> str:
    _analyze_with_static_provider(monkeypatch)
    session_id = _create_unowned_session_with_image(client)
    response = client.post(f"/investigation-sessions/{session_id}/analyze", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    return session_id


def test_project_context_returns_bounded_project_only_data(project_context_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, _activity_store, _session_store, _projects_root = project_context_test_context
    project_a = _create_project(
        client,
        name="Project A",
        checkpoint={
            "current_objective": "Fix Project A issue.",
            "blockers": "Need A logs.",
            "next_action": "Review A logs.",
        },
    )
    project_b = _create_project(
        client,
        name="Project B",
        checkpoint={
            "current_objective": "Fix Project B issue.",
            "blockers": "Need B trace.",
            "next_action": "Review B trace.",
        },
    )

    a_sessions = [
        _complete_project_owned_investigation(client, monkeypatch, project_a["project_id"])
        for _ in range(4)
    ]
    b_sessions = [
        _complete_project_owned_investigation(client, monkeypatch, project_b["project_id"])
        for _ in range(2)
    ]
    unowned_session = _complete_unowned_investigation(client, monkeypatch)

    for index in range(7):
        _create_activity(
            client,
            project_a["project_id"],
            summary=f"A manual activity {index}",
            occurred_at_utc=f"2030-01-01T10:00:0{index}Z",
        )
    for index in range(3):
        _create_activity(
            client,
            project_b["project_id"],
            summary=f"B manual activity {index}",
            occurred_at_utc=f"2030-01-01T11:00:0{index}Z",
        )

    before_a = deepcopy(client.get(f"/projects/{project_a['project_id']}").json())
    before_b = deepcopy(client.get(f"/projects/{project_b['project_id']}").json())

    context_a = client.get(f"/projects/{project_a['project_id']}/context")
    context_b = client.get(f"/projects/{project_b['project_id']}/context")

    assert context_a.status_code == 200
    assert context_b.status_code == 200

    body_a = context_a.json()
    body_b = context_b.json()

    assert body_a["project_id"] == project_a["project_id"]
    assert body_a["project_name"] == "Project A"
    assert body_a["project_goal"] == "Goal for Project A"
    assert body_a["checkpoint"]["current_objective"] == "Fix Project A issue."
    assert body_a["current_objective"] == "Fix Project A issue."
    assert body_a["blockers"] == "Need A logs."
    assert body_a["next_action"] == "Review A logs."
    assert body_a["recent_activity_limit"] == 5
    assert body_a["recent_investigation_limit"] == 3
    assert len(body_a["recent_activities"]) == 5
    assert len(body_a["recent_investigations"]) == 3
    assert [item["summary"] for item in body_a["recent_activities"]] == [
        "A manual activity 6",
        "A manual activity 5",
        "A manual activity 4",
        "A manual activity 3",
        "A manual activity 2",
    ]
    assert [item["session_id"] for item in body_a["recent_investigations"]] == list(reversed(a_sessions[-3:]))
    assert all(item["project_id"] == project_a["project_id"] for item in body_a["recent_activities"])
    assert all(item["session_id"] not in b_sessions for item in body_a["recent_investigations"])
    assert all(item["session_id"] != unowned_session for item in body_a["recent_investigations"])

    assert body_b["project_id"] == project_b["project_id"]
    assert body_b["project_name"] == "Project B"
    assert body_b["checkpoint"]["current_objective"] == "Fix Project B issue."
    assert len(body_b["recent_activities"]) == 5
    assert len(body_b["recent_investigations"]) == 2
    assert all(item["project_id"] == project_b["project_id"] for item in body_b["recent_activities"])
    assert all(item["session_id"] not in a_sessions for item in body_b["recent_investigations"])

    after_a = client.get(f"/projects/{project_a['project_id']}").json()
    after_b = client.get(f"/projects/{project_b['project_id']}").json()
    assert after_a == before_a
    assert after_b == before_b


def test_project_context_persists_across_store_restart(project_context_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, _activity_store, _session_store, projects_root = project_context_test_context
    project = _create_project(
        client,
        name="Project A",
        checkpoint={
            "current_objective": "Fix Project A issue.",
            "blockers": "Need logs.",
            "next_action": "Review logs.",
        },
    )
    completed_sessions = [
        _complete_project_owned_investigation(client, monkeypatch, project["project_id"])
        for _ in range(2)
    ]
    for index in range(2):
        _create_activity(
            client,
            project["project_id"],
            summary=f"A manual activity {index}",
            occurred_at_utc=f"2030-01-01T10:00:0{index}Z",
        )

    before = client.get(f"/projects/{project['project_id']}/context")
    assert before.status_code == 200
    before_body = before.json()

    restarted_project_store = ProjectStore(projects_root)
    restarted_activity_store = ProjectActivityStore(projects_root, restarted_project_store)
    restarted_session_store = InvestigationSessionStore((projects_root.parent) / "investigation_sessions")

    monkeypatch.setattr(api, "PROJECT_STORE", restarted_project_store)
    monkeypatch.setattr(api, "PROJECT_ACTIVITY_STORE", restarted_activity_store)
    monkeypatch.setattr(api, "SESSION_STORE", restarted_session_store)

    after = client.get(f"/projects/{project['project_id']}/context")
    assert after.status_code == 200
    assert after.json() == before_body
    assert [item["session_id"] for item in after.json()["recent_investigations"]] == list(reversed(completed_sessions))

    retriever = ProjectContextRetriever(
        project_store=restarted_project_store,
        activity_store=restarted_activity_store,
        session_store=restarted_session_store,
        investigation_store_root=api._canonical_investigation_store_root(api.INVESTIGATION_LATEST_JSON),
    )
    direct = retriever.get_context(project["project_id"])
    assert direct.model_dump(mode="json") == before_body


def test_project_context_retrieval_makes_zero_openai_calls(project_context_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, _activity_store, _session_store, _projects_root = project_context_test_context
    project = _create_project(
        client,
        name="Project A",
        checkpoint={
            "current_objective": "Fix Project A issue.",
            "blockers": "Need logs.",
            "next_action": "Review logs.",
        },
    )
    _complete_project_owned_investigation(client, monkeypatch, project["project_id"])

    calls = {"openai": 0}

    class _ForbiddenOpenAI:
        def __init__(self, *_args, **_kwargs):
            calls["openai"] += 1

    monkeypatch.setattr(api, "OpenAI", _ForbiddenOpenAI)

    response = client.get(f"/projects/{project['project_id']}/context")
    assert response.status_code == 200
    assert calls["openai"] == 0


def test_project_context_invalid_and_unknown_project(project_context_test_context):
    client, _project_store, _activity_store, _session_store, _projects_root = project_context_test_context

    invalid = client.get("/projects/not-a-uuid/context")
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["category"] == "invalid_project_id"

    from uuid import uuid4

    missing = client.get(f"/projects/{uuid4()}/context")
    assert missing.status_code == 404
    assert missing.json()["detail"]["category"] == "project_not_found"


def test_question_aware_context_ranks_capacitor_items_above_unrelated_items(
    project_context_test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    client, _project_store, _activity_store, _session_store, _projects_root = project_context_test_context
    project_a = _create_project(
        client,
        name="Project A",
        checkpoint={
            "current_objective": "Diagnose the AC failure.",
            "blockers": "Need capacitor rating.",
            "next_action": "Identify the capacitor rating.",
            "discoveries_summary": "Capacitor may be swollen.",
        },
    )
    project_b = _create_project(
        client,
        name="Project B",
        checkpoint={
            "current_objective": "Unrelated project.",
            "blockers": "Need B trace.",
            "next_action": "Review B trace.",
        },
    )

    _complete_project_owned_investigation(client, monkeypatch, project_a["project_id"])
    _complete_project_owned_investigation(client, monkeypatch, project_b["project_id"])

    _create_activity(client, project_a["project_id"], summary="Thermostat settings verified.", occurred_at_utc="2030-01-01T10:00:00Z")
    _create_activity(client, project_a["project_id"], summary="Breaker reset and power stable.", occurred_at_utc="2030-01-01T10:00:01Z")
    _create_activity(client, project_a["project_id"], summary="Filter replaced and airflow improved.", occurred_at_utc="2030-01-01T10:00:02Z")
    _create_activity(client, project_a["project_id"], summary="Capacitor appears swollen during inspection.", occurred_at_utc="2030-01-01T10:00:03Z")
    _create_activity(client, project_a["project_id"], summary="Capacitor label is partially obscured.", occurred_at_utc="2030-01-01T10:00:04Z")
    _create_activity(client, project_b["project_id"], summary="Completely unrelated B activity.", occurred_at_utc="2030-01-01T11:00:00Z")

    response = client.post(
        f"/projects/{project_a['project_id']}/context/query",
        json={"question": "What did we find about the capacitor?"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["project_id"] == project_a["project_id"]
    assert body["question"] == "What did we find about the capacitor?"
    assert body["selection"]["strategy"] == "deterministic_keyword_overlap_recency"
    assert body["selection"]["detected_question_class"] == "evidence_lookup"
    assert body["selection"]["retrieval_contract"] == "e3_deterministic_contract_v1"
    assert body["selection"]["fallback_used"] is False
    assert "capacitor" in body["selection"]["matched_terms"]
    assert "recent_activities" in body["selection"]["required_categories"]
    assert "recent_investigations" in body["selection"]["required_categories"]
    assert "deep_historical_evidence" in body["selection"]["excluded_categories"]
    assert "recent_activities" in body["selection"]["selected_categories"]
    assert "recent_investigations" in body["selection"]["selected_categories"]
    assert body["current_objective"] == "Diagnose the AC failure."
    assert body["blockers"] == "Need capacitor rating."
    assert body["next_action"] == "Identify the capacitor rating."
    assert body["selected_activities"][0]["summary"] == "Capacitor label is partially obscured."
    assert body["selected_activities"][1]["summary"] == "Capacitor appears swollen during inspection."
    assert all("Project B" not in item["summary"] for item in body["selected_activities"])
    assert all(item["project_id"] == project_a["project_id"] for item in body["selected_activities"])


def test_question_aware_context_falls_back_to_checkpoint_and_recent_context_when_terms_do_not_match(
    project_context_test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    client, _project_store, _activity_store, _session_store, _projects_root = project_context_test_context
    project = _create_project(
        client,
        name="Project A",
        checkpoint={
            "current_objective": "Diagnose the AC failure.",
            "blockers": "Need capacitor rating.",
            "next_action": "Identify the capacitor rating.",
        },
    )
    _complete_project_owned_investigation(client, monkeypatch, project["project_id"])
    _create_activity(client, project["project_id"], summary="Thermostat settings verified.", occurred_at_utc="2030-01-01T10:00:00Z")
    _create_activity(client, project["project_id"], summary="Breaker reset and power stable.", occurred_at_utc="2030-01-01T10:00:01Z")

    response = client.post(
        f"/projects/{project['project_id']}/context/query",
        json={"question": "What happened to the moon crystals?"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["selection"]["detected_question_class"] == "continuity"
    assert body["selection"]["fallback_used"] is True
    assert body["selection"]["fallback_reason"] is not None
    assert body["selection"]["recent_activity_limit"] == 2
    assert body["selection"]["recent_investigation_limit"] == 0
    assert body["current_objective"] == "Diagnose the AC failure."
    assert body["blockers"] == "Need capacitor rating."
    assert body["next_action"] == "Identify the capacitor rating."
    assert len(body["selected_activities"]) == 2
    assert len(body["selected_investigations"]) == 0


def test_question_aware_context_is_deterministic_and_restart_stable(project_context_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, _activity_store, _session_store, projects_root = project_context_test_context
    project = _create_project(
        client,
        name="Project A",
        checkpoint={
            "current_objective": "Diagnose the AC failure.",
            "blockers": "Need capacitor rating.",
            "next_action": "Identify the capacitor rating.",
        },
    )
    _complete_project_owned_investigation(client, monkeypatch, project["project_id"])
    _create_activity(client, project["project_id"], summary="Capacitor appears swollen during inspection.", occurred_at_utc="2030-01-01T10:00:03Z")
    _create_activity(client, project["project_id"], summary="Thermostat settings verified.", occurred_at_utc="2030-01-01T10:00:00Z")

    payload = {"question": "What did we find about the capacitor?"}
    first = client.post(f"/projects/{project['project_id']}/context/query", json=payload)
    second = client.post(f"/projects/{project['project_id']}/context/query", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    restarted_project_store = ProjectStore(projects_root)
    restarted_activity_store = ProjectActivityStore(projects_root, restarted_project_store)
    restarted_session_store = InvestigationSessionStore((projects_root.parent) / "investigation_sessions")

    monkeypatch.setattr(api, "PROJECT_STORE", restarted_project_store)
    monkeypatch.setattr(api, "PROJECT_ACTIVITY_STORE", restarted_activity_store)
    monkeypatch.setattr(api, "SESSION_STORE", restarted_session_store)

    after_restart = client.post(f"/projects/{project['project_id']}/context/query", json=payload)
    assert after_restart.status_code == 200
    assert after_restart.json() == first.json()


def test_question_aware_context_retrieval_makes_zero_openai_calls(project_context_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, _activity_store, _session_store, _projects_root = project_context_test_context
    project = _create_project(
        client,
        name="Project A",
        checkpoint={
            "current_objective": "Diagnose the AC failure.",
            "blockers": "Need capacitor rating.",
            "next_action": "Identify the capacitor rating.",
        },
    )
    _complete_project_owned_investigation(client, monkeypatch, project["project_id"])

    calls = {"openai": 0}

    class _ForbiddenOpenAI:
        def __init__(self, *_args, **_kwargs):
            calls["openai"] += 1

    monkeypatch.setattr(api, "OpenAI", _ForbiddenOpenAI)

    response = client.post(
        f"/projects/{project['project_id']}/context/query",
        json={"question": "Where did we leave off?"},
    )
    assert response.status_code == 200
    assert calls["openai"] == 0


def test_question_classes_map_to_expected_contracts(project_context_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, _activity_store, _session_store, _projects_root = project_context_test_context
    project = _create_project(
        client,
        name="Project A",
        checkpoint={
            "current_objective": "Diagnose the AC failure.",
            "blockers": "Need capacitor rating.",
            "next_action": "Identify the capacitor rating.",
            "discoveries_summary": "Capacitor may be swollen.",
            "completed_summary": "Verified thermostat and breaker.",
        },
    )
    _complete_project_owned_investigation(client, monkeypatch, project["project_id"])
    _create_activity(client, project["project_id"], summary="Capacitor appears swollen during inspection.", occurred_at_utc="2030-01-01T10:00:03Z")

    cases = [
        ("Where did we leave off?", "continuity"),
        ("What have we completed?", "status"),
        ("What should I do next?", "next_action"),
        ("What did we determine about the capacitor?", "evidence_lookup"),
    ]

    for question, expected_question_class in cases:
        response = client.post(
            f"/projects/{project['project_id']}/context/query",
            json={"question": question},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["selection"]["detected_question_class"] == expected_question_class
        assert body["selection"]["retrieval_contract"] == "e3_deterministic_contract_v1"


def test_question_contracts_are_interpretable_and_exclusions_are_explicit(project_context_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, _activity_store, _session_store, _projects_root = project_context_test_context
    project = _create_project(
        client,
        name="Project A",
        checkpoint={
            "current_objective": "Diagnose the AC failure.",
            "blockers": "Need capacitor rating.",
            "next_action": "Identify the capacitor rating.",
        },
    )
    _complete_project_owned_investigation(client, monkeypatch, project["project_id"])
    _create_activity(client, project["project_id"], summary="Breaker reset and power stable.", occurred_at_utc="2030-01-01T10:00:01Z")

    response = client.post(
        f"/projects/{project['project_id']}/context/query",
        json={"question": "What have we completed?"},
    )
    assert response.status_code == 200
    body = response.json()

    selection = body["selection"]
    assert selection["detected_question_class"] == "status"
    assert "project_identity" in selection["required_categories"]
    assert "checkpoint" in selection["required_categories"]
    assert "recent_activities" in selection["optional_categories"]
    assert "recent_investigations" in selection["excluded_categories"]
    assert "deep_historical_evidence" in selection["excluded_categories"]
    assert "project_identity" in selection["selected_categories"]
    assert "checkpoint" in selection["selected_categories"]
    assert isinstance(selection["category_inclusion_reasons"], dict)
    assert "recent_investigations" in selection["category_inclusion_reasons"]
    assert selection["recent_activity_limit"] == 3
    assert selection["recent_investigation_limit"] == 0


def test_unknown_phrase_falls_back_safely_and_deterministically(project_context_test_context, monkeypatch: pytest.MonkeyPatch):
    client, _project_store, _activity_store, _session_store, _projects_root = project_context_test_context
    project = _create_project(
        client,
        name="Project A",
        checkpoint={
            "current_objective": "Diagnose the AC failure.",
            "blockers": "Need capacitor rating.",
            "next_action": "Identify the capacitor rating.",
        },
    )
    _complete_project_owned_investigation(client, monkeypatch, project["project_id"])

    payload = {"question": "Give me a quick pulse check with odd phrasing xyzzy"}
    first = client.post(f"/projects/{project['project_id']}/context/query", json=payload)
    second = client.post(f"/projects/{project['project_id']}/context/query", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body == second_body
    assert first_body["selection"]["detected_question_class"] == "continuity"
    assert first_body["selection"]["fallback_used"] is True
    assert first_body["selection"]["fallback_reason"] is not None
