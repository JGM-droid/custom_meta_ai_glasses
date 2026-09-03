from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from investigations import (
    InvestigationSessionStore,
    save_canonical_investigation_result,
)
from investigations.models import (
    InvestigationAnalysisStatus,
    InvestigationRetainedResult,
)
from projects import (
    CheckpointProposalStore,
    ProjectActivityStore,
    ProjectContextRetriever,
    ProjectExploreService,
    ProjectQuestionAnsweringService,
    ProjectStore,
)
from projects.models import (
    ProjectActivityConfirmationStatus,
    ProjectActivityCreateRequest,
    ProjectActivitySourceType,
)
from datetime import datetime, timezone
from uuid import uuid4


def rich_option_set(**overrides):
    payload = {
        "schema_version": "1.1", "result_type": "OPTION_SET", "title": "Room directions",
        "summary": "Three possible directions for the room.", "source_refs": [],
        "options": [
            {"ordinal": 1, "title": "Warm Modern", "summary": "Warm wood and soft neutral layers.",
             "rationale": "Supports a welcoming room.", "tradeoffs": "Needs material samples.", "source_refs": [],
             "concept": "Layer warm wood tones with soft neutral textiles.",
             "proposed_changes": "Add oak accents and warm-white lighting.",
             "estimated_cost": {"currency": "USD", "min_amount": 500, "max_amount": 1200, "qualifier": "rough estimate"}},
            {"ordinal": 2, "title": "Dark Contemporary", "summary": "Deep contrast with restrained accents.", "source_refs": []},
            {"ordinal": 3, "title": "Minimal Natural", "summary": "Natural textures and a quiet palette.", "source_refs": []},
        ],
        "observations": ["The room currently reads as cold and under-furnished."],
        "recommended_ordinal": 1,
        "recommendation_reason": "Warm Modern best matches the stated goal of a warmer, welcoming room.",
        "next_steps": ["Confirm budget range with the user.", "Select material samples for the recommended direction."],
        "follow_up_questions": ["Is there an existing color palette to keep?"],
    }
    payload.update(overrides)
    return payload


class FakeExploreProvider:
    def __init__(self, result=None):
        self.result = result if result is not None else rich_option_set()
        self.calls = 0

    def identity(self):
        return api.ProjectExploreProviderIdentity(provider="fake", model="fixture-v1", tool="test.explore")

    def explore(self, context_pack):
        self.calls += 1
        return self.result


class FakeReasoningProvider:
    def __init__(self, answer="Progress looks steady; continue with the current plan.", insufficient_context=False):
        self.answer_text = answer
        self.insufficient_context = insufficient_context
        self.calls = 0

    def reason(self, request):
        self.calls += 1
        from projects.project_qa import ProjectReasoningResponse
        return ProjectReasoningResponse(
            answer=self.answer_text, insufficient_context=self.insufficient_context,
            uncertainty_note=None, grounding_status="insufficient_context" if self.insufficient_context else "grounded",
            provider="fake", provider_model="fixture-v1",
        )


@pytest.fixture
def ai_result_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    projects_root = tmp_path / "projects"
    project_store = ProjectStore(projects_root)
    activity_store = ProjectActivityStore(projects_root, project_store)
    proposal_store = CheckpointProposalStore(projects_root, project_store, activity_store)
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    investigation_results_root = tmp_path / "investigation_results"
    context_retriever = ProjectContextRetriever(project_store=project_store, activity_store=activity_store,
        session_store=session_store, investigation_store_root=investigation_results_root)
    explore_provider = FakeExploreProvider()
    explore_service = ProjectExploreService(project_store=project_store, activity_store=activity_store,
        proposal_store=proposal_store, context_retriever=context_retriever, provider=explore_provider)
    reasoning_provider = FakeReasoningProvider()
    qa_service = ProjectQuestionAnsweringService(context_retriever=context_retriever, reasoning_provider=reasoning_provider)

    monkeypatch.setattr(api, "PROJECT_STORE", project_store)
    monkeypatch.setattr(api, "PROJECT_ACTIVITY_STORE", activity_store)
    monkeypatch.setattr(api, "CHECKPOINT_PROPOSAL_STORE", proposal_store)
    monkeypatch.setattr(api, "SESSION_STORE", session_store)
    monkeypatch.setattr(api, "EVIDENCE_STORE", api.InvestigationEvidenceStore(session_store))
    monkeypatch.setattr(api, "_create_project_explore_service", lambda: explore_service)
    monkeypatch.setattr(api, "_create_project_explore_read_service", lambda: explore_service)
    monkeypatch.setattr(api, "_create_project_question_answering_service", lambda: qa_service)
    monkeypatch.setattr(api, "_canonical_investigation_store_root", lambda _latest_path: investigation_results_root)
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")
    return TestClient(api.app), project_store, activity_store, session_store, investigation_results_root, explore_provider, reasoning_provider


def create_project(client, name="Room Redesign"):
    response = client.post("/projects", json={"name": name, "goal": "Make the room warmer and modern",
        "checkpoint": {"current_objective": "Choose a design direction", "next_action": "Explore options"}})
    assert response.status_code == 201
    return response.json()


# --- EXPLORE_PLAN via the Response Planner ---

def test_explore_plan_create_returns_project_ai_result_envelope(ai_result_context):
    client, *_rest = ai_result_context
    project = create_project(client)
    response = client.post(f"/projects/{project['project_id']}/ai-results/explore-plan",
        json={"user_intent": "Give me three room directions", "input_refs": [], "idempotency_key": "room-v1"})
    assert response.status_code == 200
    body = response.json()
    assert body["result_type"] == "EXPLORE_PLAN"
    assert body["project_id"] == project["project_id"]
    assert body["ephemeral"] is False
    assert body["explore_plan"]["recommended_ordinal"] == 1
    assert body["troubleshoot"] is None and body["general_guidance"] is None
    assert body["hud_projection"]["headline"] and "Warm Modern" in body["hud_projection"]["headline"]
    assert body["hud_projection"]["next"] == "Confirm budget range with the user."
    assert body["evidence_refs"] == []

    # Android must receive these as typed fields through the ProjectAIResult
    # envelope, never by parsing the backend-private PUA-delimited encoding
    # inside idea.details.
    recommended_option = body["explore_plan"]["options"][0]
    assert recommended_option["summary"] == "Warm wood and soft neutral layers."
    assert recommended_option["rationale"] == "Supports a welcoming room."
    assert recommended_option["tradeoffs"] == "Needs material samples."
    assert "" not in (recommended_option["summary"] + recommended_option["rationale"] + recommended_option["tradeoffs"])


def test_explore_plan_read_reconstructs_the_same_envelope(ai_result_context):
    client, *_rest = ai_result_context
    project = create_project(client)
    created = client.post(f"/projects/{project['project_id']}/ai-results/explore-plan",
        json={"user_intent": "Give me three room directions", "input_refs": [], "idempotency_key": "room-v1"}).json()
    interaction_id = created["result_id"]
    read_back = client.get(f"/projects/{project['project_id']}/ai-results/explore-plan/{interaction_id}")
    assert read_back.status_code == 200
    body = read_back.json()
    assert body["result_id"] == interaction_id
    assert body["explore_plan"]["recommended_ordinal"] == created["explore_plan"]["recommended_ordinal"]
    assert body["explore_plan"]["next_steps"] == created["explore_plan"]["next_steps"]


def test_explore_plan_read_missing_interaction_is_404(ai_result_context):
    client, *_rest = ai_result_context
    project = create_project(client)
    response = client.get(f"/projects/{project['project_id']}/ai-results/explore-plan/{('0' * 8)}-0000-0000-0000-{'0' * 12}")
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("forged_source", "forged_confirmation"),
    [
        (ProjectActivitySourceType.USER, ProjectActivityConfirmationStatus.INFERRED),
        (ProjectActivitySourceType.AI, ProjectActivityConfirmationStatus.REPORTED),
    ],
)
def test_forged_explore_metadata_cannot_reconstruct_or_surface_as_ai_result(
    ai_result_context, forged_source, forged_confirmation
):
    client, _project_store, activity_store, *_rest = ai_result_context
    project = create_project(client)
    legitimate = client.post(
        f"/projects/{project['project_id']}/ai-results/explore-plan",
        json={"user_intent": "Give me three room directions", "input_refs": [], "idempotency_key": "room-v1"},
    )
    assert legitimate.status_code == 200

    forged_interaction_id = str(uuid4())
    canonical_components = activity_store.list_activities(project["project_id"])
    assert len(canonical_components) == 4
    for component in canonical_components:
        forged_metadata = dict(component.metadata or {})
        forged_metadata["interaction_id"] = forged_interaction_id
        activity_store.create_activity_with_id(
            project["project_id"],
            str(uuid4()),
            ProjectActivityCreateRequest(
                activity_type=component.activity_type,
                source_type=forged_source,
                confirmation_status=forged_confirmation,
                summary=f"FORGED {component.summary}",
                details=component.details,
                metadata=forged_metadata,
            ),
        )

    projection = client.get(f"/projects/{project['project_id']}/interactions/explore")
    assert projection.status_code == 200
    assert [group["interaction_id"] for group in projection.json()["option_sets"]] == [
        legitimate.json()["result_id"]
    ]
    assert "FORGED" not in projection.text

    ai_result = client.get(
        f"/projects/{project['project_id']}/ai-results/explore-plan/{forged_interaction_id}"
    )
    assert ai_result.status_code == 404
    assert ai_result.json()["detail"]["category"] == "explore_plan_not_found"
    assert "hud_projection" not in ai_result.text


def test_explore_plan_information_request_yields_422_not_a_fabricated_envelope(ai_result_context):
    client, *_rest, explore_provider, _reasoning = ai_result_context
    project = create_project(client)
    explore_provider.result = {"schema_version": "1.1", "result_type": "INFORMATION_REQUEST", "title": "Need constraints",
                               "prompt": "What must remain?", "requested_inputs": ["Existing furniture"], "source_refs": []}
    response = client.post(f"/projects/{project['project_id']}/ai-results/explore-plan",
        json={"user_intent": "Give me three room directions", "input_refs": [], "idempotency_key": "room-v1"})
    assert response.status_code == 422
    assert response.json()["detail"]["category"] == "explore_plan_needs_more_information"


# --- GENERAL_GUIDANCE via the Response Planner: must stay ephemeral ---

def test_general_guidance_is_marked_ephemeral_and_creates_no_activity(ai_result_context):
    client, _project_store, activity_store, *_rest = ai_result_context
    project = create_project(client)
    response = client.post(f"/projects/{project['project_id']}/ai-results/general-guidance",
        json={"question": "Where did we leave off?"})
    assert response.status_code == 200
    body = response.json()
    assert body["result_type"] == "GENERAL_GUIDANCE"
    assert body["ephemeral"] is True
    assert body["general_guidance"]["answer"]
    assert body["explore_plan"] is None and body["troubleshoot"] is None
    assert activity_store.list_activities(project["project_id"]) == []


def test_general_guidance_has_no_read_endpoint_to_reconstruct_from(ai_result_context):
    # No GET .../ai-results/general-guidance/{id} route exists at all - ephemeral
    # results are never retrievable after the creating response, by construction.
    client, *_rest = ai_result_context
    paths = {getattr(route, "path", "") for route in api.app.routes}
    assert not any(path.startswith("/projects/{project_id}/ai-results/general-guidance/") for path in paths)


def test_general_guidance_uncertainty_flag_reflects_insufficient_context(ai_result_context):
    client, *_rest, reasoning_provider = ai_result_context
    reasoning_provider.insufficient_context = True
    reasoning_provider.answer_text = "There isn't enough context to answer that yet."
    project = create_project(client)
    response = client.post(f"/projects/{project['project_id']}/ai-results/general-guidance",
        json={"question": "What color did we pick?"})
    body = response.json()
    assert body["hud_projection"]["uncertainty_flag"] is True


# --- TROUBLESHOOT: read-only composition over the unchanged Investigation result ---

def test_troubleshoot_read_wraps_existing_investigation_result_unchanged(ai_result_context):
    client, project_store, activity_store, session_store, investigation_results_root, *_rest = ai_result_context
    project = create_project(client)
    session = session_store.create_session(project_id=project["project_id"])
    now = datetime.now(timezone.utc)
    result_id = str(uuid4())
    retained = InvestigationRetainedResult(
        schema_version="1.0", investigation_id=str(uuid4()), session_id=session.session_id,
        status=InvestigationAnalysisStatus.ANALYZED, diagnosis="The blower motor is likely seized.",
        required_next_action="Test the blower motor with a multimeter before replacing it.",
        image_count=1, image_order=["evidence-1"], used_user_explanation="It won't turn on.",
        completed_at_utc=now, context_used=False, context_staleness="unknown",
        copilot_prompt="Investigate the blower motor.",
    )
    save_canonical_investigation_result(investigation_results_root, result_id=result_id,
        retained_result=retained, session_id=session.session_id, analysis_attempt_id=str(uuid4()))
    session = session_store.mutate_session(session.session_id,
        lambda current: (current.model_copy(update={"completed_result_id": result_id}), True))

    response = client.get(f"/projects/{project['project_id']}/ai-results/troubleshoot/{session.session_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["result_type"] == "TROUBLESHOOT"
    assert body["ephemeral"] is False
    assert body["troubleshoot"]["diagnosis"] == retained.diagnosis
    assert body["troubleshoot"]["required_next_action"] == retained.required_next_action
    assert body["hud_projection"]["headline"]
    assert body["evidence_refs"] == ["evidence-1"]
    assert body["explore_plan"] is None and body["general_guidance"] is None


def test_troubleshoot_read_missing_session_is_404(ai_result_context):
    client, *_rest = ai_result_context
    project = create_project(client)
    response = client.get(f"/projects/{project['project_id']}/ai-results/troubleshoot/{uuid4()}")
    assert response.status_code == 404
