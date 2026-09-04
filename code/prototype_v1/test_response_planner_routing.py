"""ADR-060: Bounded Response Planner intent inference.

Deterministic coverage for ProjectAIResultPlanner.route() and the new unified
POST /projects/{project_id}/ai-results endpoint, using a fake classifier
(FakeRoutingProvider) so no real OpenAI call is made. Real-model routing
accuracy is evaluated separately (see docs/research or the routing
evaluation script), not by this deterministic suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from investigations import InvestigationSessionStore
from projects import (
    CheckpointProposalStore,
    ProjectActivityStore,
    ProjectContextRetriever,
    ProjectExploreService,
    ProjectQuestionAnsweringService,
    ProjectStore,
)
from projects.models import ProjectAIResultRoutingDecision, ProjectAIResultType


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


class FakeRoutingProvider:
    """Stands in for OpenAIProjectResponseRoutingProvider - no real OpenAI call is made."""

    def __init__(self):
        self.decision: ProjectAIResultRoutingDecision | None = None
        self.raise_exc: Exception | None = None
        self.calls = 0
        self.last_context_payload: dict[str, object] | None = None

    def classify(self, context_payload):
        self.calls += 1
        self.last_context_payload = context_payload
        if self.raise_exc is not None:
            raise self.raise_exc
        assert self.decision is not None, "test must set routing_provider.decision or .raise_exc"
        return self.decision


class FakeTextTroubleshootProvider:
    """Stands in for OpenAIProjectTextTroubleshootProvider - no real OpenAI call is made."""

    def __init__(self):
        self.diagnosis = "The mechanism is likely misaligned or obstructed."
        self.recommended_next_action = "Check for obstructions and realign before further use."
        self.uncertain = False
        self.calls = 0
        self.last_user_request: str | None = None
        self.last_context_pack = None

    def diagnose(self, *, user_request, context_pack):
        self.calls += 1
        self.last_user_request = user_request
        self.last_context_pack = context_pack
        from projects.project_troubleshoot import ProjectTextTroubleshootResponse
        return ProjectTextTroubleshootResponse(
            diagnosis=self.diagnosis, recommended_next_action=self.recommended_next_action,
            uncertain=self.uncertain, provider="fake", provider_model="fixture-v1",
        )


class _StaticInvestigationProvider:
    """A fixed, deterministic diagnostic result - bypasses the real vision/analysis provider."""

    def analyze(self, _request_package):
        return api.InvestigationAnalysisResponse(
            schema_version=api.INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
            concise_diagnosis="The mechanism is misaligned and binding.",
            immediate_recommended_action="Realign the mechanism before further use.",
            supporting_observations=["Evidence ordered and parsed."],
            confidence_or_uncertainty="Moderate confidence.",
            warning_or_blocker=None,
            follow_up_capture_request=None,
        )


def _real_orchestrator_with_provider(provider):
    return api.InvestigationOrchestrator(
        session_store=api.SESSION_STORE,
        evidence_store=api.EVIDENCE_STORE,
        attempt_store=api.InvestigationAnalysisAttemptStore(api.SESSION_STORE),
        analysis_provider=provider,
        result_persistence=api._SessionRouteResultPersistence(),
    )


def _upload_image(client: TestClient, session_id: str, *, name: str, content: bytes, normalized_text: str = "") -> str:
    response = client.post(
        f"/investigation-sessions/{session_id}/evidence/image",
        data={"normalized_text": normalized_text},
        files={"file": (name, content, "image/png")},
    )
    assert response.status_code == 201
    return response.json()["evidence_id"]


@pytest.fixture
def routing_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    projects_root = tmp_path / "projects"
    project_store = ProjectStore(projects_root)
    activity_store = ProjectActivityStore(projects_root, project_store)
    proposal_store = CheckpointProposalStore(projects_root, project_store, activity_store)
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    # Matches _canonical_investigation_store_root's convention for a non-"latest.json"-named
    # path (appends "/investigations"), so the real orchestrator's persist_result() and the
    # ProjectContextRetriever/ProjectAIResultPlanner reads below agree on one location.
    investigation_results_root = tmp_path / "investigations"
    context_retriever = ProjectContextRetriever(
        project_store=project_store, activity_store=activity_store,
        session_store=session_store, investigation_store_root=investigation_results_root,
    )
    explore_provider = FakeExploreProvider()
    explore_service = ProjectExploreService(
        project_store=project_store, activity_store=activity_store,
        proposal_store=proposal_store, context_retriever=context_retriever, provider=explore_provider,
    )
    reasoning_provider = FakeReasoningProvider()
    qa_service = ProjectQuestionAnsweringService(context_retriever=context_retriever, reasoning_provider=reasoning_provider)
    routing_provider = FakeRoutingProvider()
    text_troubleshoot_provider = FakeTextTroubleshootProvider()
    evidence_store = api.InvestigationEvidenceStore(session_store)

    monkeypatch.setattr(api, "PROJECT_STORE", project_store)
    monkeypatch.setattr(api, "PROJECT_ACTIVITY_STORE", activity_store)
    monkeypatch.setattr(api, "CHECKPOINT_PROPOSAL_STORE", proposal_store)
    monkeypatch.setattr(api, "SESSION_STORE", session_store)
    monkeypatch.setattr(api, "EVIDENCE_STORE", evidence_store)
    monkeypatch.setattr(api, "_create_project_explore_service", lambda: explore_service)
    monkeypatch.setattr(api, "_create_project_explore_read_service", lambda: explore_service)
    monkeypatch.setattr(api, "_create_project_question_answering_service", lambda: qa_service)
    monkeypatch.setattr(api, "_create_project_context_retriever", lambda: context_retriever)
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", tmp_path / "investigation_latest.json")
    monkeypatch.setattr(api, "_load_openai_api_key", lambda: "fake-key")
    monkeypatch.setattr(api, "OpenAIProjectResponseRoutingProvider", lambda **kwargs: routing_provider)
    monkeypatch.setattr(api, "OpenAIProjectTextTroubleshootProvider", lambda **kwargs: text_troubleshoot_provider)
    monkeypatch.setattr(api, "_create_session_orchestrator", lambda: _real_orchestrator_with_provider(_StaticInvestigationProvider()))
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")

    return {
        "client": TestClient(api.app),
        "project_store": project_store,
        "activity_store": activity_store,
        "session_store": session_store,
        "evidence_store": evidence_store,
        "explore_provider": explore_provider,
        "reasoning_provider": reasoning_provider,
        "text_troubleshoot_provider": text_troubleshoot_provider,
        "routing_provider": routing_provider,
    }


def create_project(client, name="Room Redesign", goal="Make the room warmer and modern"):
    response = client.post("/projects", json={"name": name, "goal": goal})
    assert response.status_code == 201
    return response.json()


def route(client, project_id, *, user_request, investigation_session_id=None, idempotency_key="route-1"):
    payload = {"user_request": user_request, "idempotency_key": idempotency_key}
    if investigation_session_id is not None:
        payload["investigation_session_id"] = investigation_session_id
    return client.post(f"/projects/{project_id}/ai-results", json=payload)


# --- EXPLORE_PLAN dispatch ---

def test_route_dispatches_to_explore_plan(routing_context):
    ctx = routing_context
    project = create_project(ctx["client"])
    ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
        response_family=ProjectAIResultType.EXPLORE_PLAN, confidence=0.9,
        brief_reason="Design/planning request for a Room Redesign project.",
    )

    response = route(ctx["client"], project["project_id"], user_request="What would you change about this room? Give me some ideas.")

    assert response.status_code == 200
    body = response.json()
    assert body["result_type"] == "EXPLORE_PLAN"
    assert body["project_id"] == project["project_id"]
    assert body["explore_plan"]["recommended_ordinal"] == 1
    assert ctx["routing_provider"].calls == 1

    # Bounded context payload only - no raw image bytes, no full Project dump.
    payload = ctx["routing_provider"].last_context_payload
    assert set(payload.keys()) == {
        "project", "checkpoint", "recent_activities", "recent_investigations",
        "current_investigation_session", "current_request",
    }
    assert payload["current_request"] == "What would you change about this room? Give me some ideas."
    assert payload["current_investigation_session"] is None


def test_route_explore_plan_needs_more_information_is_clarification_not_a_fabricated_result(routing_context):
    ctx = routing_context
    project = create_project(ctx["client"])
    ctx["explore_provider"].result = {
        "schema_version": "1.1", "result_type": "INFORMATION_REQUEST", "title": "Need constraints",
        "prompt": "What must remain unchanged in this room?", "requested_inputs": ["Existing furniture"], "source_refs": [],
    }
    ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
        response_family=ProjectAIResultType.EXPLORE_PLAN, confidence=0.85, brief_reason="Design request.",
    )

    response = route(ctx["client"], project["project_id"], user_request="Give me some ideas for this room.")

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["category"] == "routing_needs_clarification"
    assert detail["message"] == "What must remain unchanged in this room?"


# --- TROUBLESHOOT dispatch with an existing session ---

def test_route_dispatches_to_troubleshoot_with_existing_session(routing_context):
    ctx = routing_context
    project = create_project(ctx["client"], name="Fix Upstairs AC", goal="Get the AC working again")
    session_resp = ctx["client"].post(f"/projects/{project['project_id']}/investigation-sessions", json={})
    assert session_resp.status_code == 201
    session_id = session_resp.json()["session_id"]
    _upload_image(ctx["client"], session_id, name="ac.png", content=b"ac", normalized_text="The condenser won't start.")

    ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
        response_family=ProjectAIResultType.TROUBLESHOOT, confidence=0.95,
        brief_reason="Diagnostic request about equipment malfunction.",
    )

    response = route(
        ctx["client"], project["project_id"],
        user_request="The condenser won't start. What should I check?",
        investigation_session_id=session_id,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result_type"] == "TROUBLESHOOT"
    assert body["troubleshoot"]["diagnosis"] == "The mechanism is misaligned and binding."
    assert body["troubleshoot_text"] is None
    assert body["ephemeral"] is False
    assert body["result_id"]
    assert ctx["text_troubleshoot_provider"].calls == 0, "evidence-backed dispatch must never call the text-only provider"

    payload = ctx["routing_provider"].last_context_payload
    assert payload["current_investigation_session"] == {"status": "collecting", "evidence_count": 1}

    # Exactly one session for this Project - reused, never duplicated.
    assert len(ctx["session_store"].list_sessions_for_project(project["project_id"])) == 1


# --- TROUBLESHOOT Path B (ADR-060 2026-09-04): text-only execution when no usable ---
# --- Investigation session/evidence exists yet - never fabricated, never a fresh empty session ---

def test_route_text_only_troubleshoot_succeeds_with_no_investigation_session_required(routing_context):
    """Test 1: text-only AC Repair troubleshooting - 'My condenser won't start. What should I
    check first?' - must return a TROUBLESHOOT result with no Investigation session at all."""
    ctx = routing_context
    project = create_project(ctx["client"], name="Fix Upstairs AC", goal="Get the AC working again")
    ctx["text_troubleshoot_provider"].diagnosis = "The condenser likely isn't getting power or the contactor has failed."
    ctx["text_troubleshoot_provider"].recommended_next_action = "Check the disconnect switch and breaker before inspecting the contactor."
    ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
        response_family=ProjectAIResultType.TROUBLESHOOT, confidence=0.9,
        brief_reason="Diagnostic request about equipment malfunction.",
    )

    response = route(ctx["client"], project["project_id"], user_request="My condenser won't start. What should I check first?")

    assert response.status_code == 200
    body = response.json()
    assert body["result_type"] == "TROUBLESHOOT"
    assert body["troubleshoot"] is None
    assert body["troubleshoot_text"]["diagnosis"] == "The condenser likely isn't getting power or the contactor has failed."
    assert body["troubleshoot_text"]["recommended_next_action"] == "Check the disconnect switch and breaker before inspecting the contactor."
    assert body["hud_projection"]["headline"]
    assert ctx["text_troubleshoot_provider"].calls == 1
    assert ctx["text_troubleshoot_provider"].last_user_request == "My condenser won't start. What should I check first?"


def test_route_text_only_troubleshoot_creates_no_session_evidence_or_activity(routing_context):
    """Test 2: text-only troubleshooting must not fabricate Evidence/Activity/session merely to
    execute - the architecture decision explicitly forbids this."""
    ctx = routing_context
    project = create_project(ctx["client"])
    ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
        response_family=ProjectAIResultType.TROUBLESHOOT, confidence=0.85, brief_reason="Malfunction description.",
    )

    response = route(ctx["client"], project["project_id"], user_request="This drawer won't close. What's wrong?")

    assert response.status_code == 200
    assert ctx["session_store"].list_sessions_for_project(project["project_id"]) == []
    assert ctx["activity_store"].list_activities(project["project_id"]) == []


def test_route_text_only_troubleshoot_result_is_ephemeral_and_inferred(routing_context):
    """Test 7: the text-only result remains inferred/unconfirmed - nothing durable was created,
    so it must be marked ephemeral exactly like GENERAL_GUIDANCE (never implying it can be
    reconstructed after a reload), and there is no trust-decision/session id to confirm it against."""
    ctx = routing_context
    project = create_project(ctx["client"])
    ctx["text_troubleshoot_provider"].uncertain = True
    ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
        response_family=ProjectAIResultType.TROUBLESHOOT, confidence=0.8, brief_reason="Malfunction description.",
    )

    response = route(ctx["client"], project["project_id"], user_request="This drawer won't close. What's wrong?")

    body = response.json()
    assert body["ephemeral"] is True
    assert body["hud_projection"]["uncertainty_flag"] is True
    assert body["troubleshoot_text"]["uncertain"] is True


def test_route_text_only_troubleshoot_has_empty_evidence_refs_and_valid_shape(routing_context):
    """Test 8: ProjectAIResult shape remains valid with empty evidence_refs for the text-only path."""
    ctx = routing_context
    project = create_project(ctx["client"])
    ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
        response_family=ProjectAIResultType.TROUBLESHOOT, confidence=0.8, brief_reason="Malfunction description.",
    )

    response = route(ctx["client"], project["project_id"], user_request="This drawer won't close. What's wrong?")

    assert response.status_code == 200
    body = response.json()
    assert body["evidence_refs"] == []
    assert body["suggested_project_updates"] is False
    assert body["explore_plan"] is None and body["general_guidance"] is None


def test_route_troubleshoot_with_existing_session_still_uses_investigation_path_not_text_only(routing_context):
    """Test 4 (paired with test_route_dispatches_to_troubleshoot_with_existing_session above):
    an existing session with usable evidence must go through the Investigation pipeline, and the
    text-only provider must never be called for it."""
    ctx = routing_context
    project = create_project(ctx["client"], name="Fix Upstairs AC", goal="Get the AC working again")
    session_resp = ctx["client"].post(f"/projects/{project['project_id']}/investigation-sessions", json={})
    session_id = session_resp.json()["session_id"]
    _upload_image(ctx["client"], session_id, name="ac.png", content=b"ac", normalized_text="The condenser won't start.")

    ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
        response_family=ProjectAIResultType.TROUBLESHOOT, confidence=0.95, brief_reason="Diagnostic request.",
    )

    response = route(ctx["client"], project["project_id"], user_request="The condenser won't start.", investigation_session_id=session_id)

    assert response.status_code == 200
    body = response.json()
    assert body["troubleshoot"] is not None
    assert body["troubleshoot_text"] is None
    assert body["ephemeral"] is False
    assert ctx["text_troubleshoot_provider"].calls == 0, "evidence-backed dispatch must never call the text-only provider"


# --- Contract correction (2026-09-04): an explicit investigation_session_id is NEVER silently
# --- ignored in favor of text-only TROUBLESHOOT, regardless of that session's state. ---

def _force_session_status(session_store, session_id: str, status) -> None:
    session = session_store.load_session(session_id)
    session_store.save_session(session.model_copy(update={"status": status, "revision": session.revision + 1}))


@pytest.mark.parametrize(
    ("status_name", "expected_category"),
    [
        ("ANALYZING", "analysis_attempt_conflict"),
        ("FINALIZING", "analysis_attempt_conflict"),
        ("CANCELLED", "invalid_state_transition"),
    ],
)
def test_route_explicit_session_in_invalid_state_returns_existing_conflict_error_not_text_only(
    routing_context, status_name, expected_category,
):
    ctx = routing_context
    project = create_project(ctx["client"], name="Fix Upstairs AC", goal="Get the AC working again")
    session_resp = ctx["client"].post(f"/projects/{project['project_id']}/investigation-sessions", json={})
    session_id = session_resp.json()["session_id"]
    _upload_image(ctx["client"], session_id, name="ac.png", content=b"ac", normalized_text="The condenser won't start.")
    _force_session_status(ctx["session_store"], session_id, getattr(api.InvestigationSessionStatus, status_name))

    ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
        response_family=ProjectAIResultType.TROUBLESHOOT, confidence=0.9, brief_reason="Diagnostic request.",
    )

    response = route(
        ctx["client"], project["project_id"],
        user_request="The condenser won't start. What should I check?",
        investigation_session_id=session_id,
    )

    # The SAME existing state/conflict error the explicit /investigation-sessions/{id}/analyze
    # route already raises for this state - never silently substituted with a 200 text-only
    # TROUBLESHOOT result.
    assert response.status_code == 409
    assert response.json()["detail"]["category"] == expected_category
    assert ctx["text_troubleshoot_provider"].calls == 0, "an explicit session reference must never fall through to text-only"
    # No second, unrelated session was created either.
    assert len(ctx["session_store"].list_sessions_for_project(project["project_id"])) == 1


def test_route_troubleshoot_without_session_reuses_existing_collecting_session(routing_context):
    ctx = routing_context
    project = create_project(ctx["client"])
    session_resp = ctx["client"].post(f"/projects/{project['project_id']}/investigation-sessions", json={})
    session_id = session_resp.json()["session_id"]
    _upload_image(ctx["client"], session_id, name="drawer.png", content=b"drawer", normalized_text="This drawer won't close.")

    ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
        response_family=ProjectAIResultType.TROUBLESHOOT, confidence=0.85,
        brief_reason="Malfunction description.",
    )

    response = route(ctx["client"], project["project_id"], user_request="This drawer won't close. What's wrong?")

    assert response.status_code == 200
    body = response.json()
    assert body["result_type"] == "TROUBLESHOOT"
    assert body["troubleshoot_text"] is None
    sessions = ctx["session_store"].list_sessions_for_project(project["project_id"])
    assert len(sessions) == 1
    assert sessions[0].session_id == session_id
    assert ctx["text_troubleshoot_provider"].calls == 0


# --- GENERAL_GUIDANCE dispatch ---

def test_route_dispatches_to_general_guidance(routing_context):
    ctx = routing_context
    project = create_project(ctx["client"])
    ctx["reasoning_provider"].answer_text = "You picked Warm Modern because it best matched the stated goal."
    ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
        response_family=ProjectAIResultType.GENERAL_GUIDANCE, confidence=0.7,
        brief_reason="Follow-up explanation question, not a diagnosis or a set of options.",
    )

    response = route(ctx["client"], project["project_id"], user_request="Why did you recommend that?")

    assert response.status_code == 200
    body = response.json()
    assert body["result_type"] == "GENERAL_GUIDANCE"
    assert body["ephemeral"] is True
    assert "Warm Modern" in body["general_guidance"]["answer"]


def test_route_general_guidance_creates_no_activity_and_no_project_mutation(routing_context):
    ctx = routing_context
    project = create_project(ctx["client"])
    before = ctx["project_store"].load_project(project["project_id"])
    ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
        response_family=ProjectAIResultType.GENERAL_GUIDANCE, confidence=0.9, brief_reason="General question.",
    )

    response = route(ctx["client"], project["project_id"], user_request="Where did we leave off?")

    assert response.status_code == 200
    after = ctx["project_store"].load_project(project["project_id"])
    assert after.revision == before.revision
    assert after.checkpoint == before.checkpoint
    assert ctx["activity_store"].list_activities(project["project_id"]) == []


# --- Clarification-needed: a legitimate outcome, not a guess ---

def test_route_returns_clarification_needed_without_guessing_a_family(routing_context):
    ctx = routing_context
    project = create_project(ctx["client"])
    ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
        needs_clarification=True, confidence=0.4, brief_reason="Ambiguous request.",
        clarifying_question="Do you want design ideas, or is something not working?",
    )

    response = route(ctx["client"], project["project_id"], user_request="hmm")

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["category"] == "routing_needs_clarification"
    assert detail["message"] == "Do you want design ideas, or is something not working?"
    assert detail["brief_reason"] == "Ambiguous request."
    # No Project state changed from asking a clarifying question.
    assert ctx["activity_store"].list_activities(project["project_id"]) == []


# --- Technical classifier failure: retryable, never silently GENERAL_GUIDANCE ---

def test_route_classifier_technical_failure_is_a_retryable_error_not_general_guidance(routing_context):
    ctx = routing_context
    project = create_project(ctx["client"])
    ctx["routing_provider"].raise_exc = api.ProjectAIResultRoutingUnavailable("provider timeout")

    response = route(ctx["client"], project["project_id"], user_request="Give me ideas for this room.")

    assert response.status_code == 503
    assert response.json()["detail"]["category"] == "routing_unavailable"
    # Confirm no GENERAL_GUIDANCE (or any) ProjectAIResult was fabricated as a fallback.
    assert ctx["reasoning_provider"].calls == 0
    assert ctx["explore_provider"].calls == 0


def test_routing_provider_invalid_json_is_a_retryable_failure():
    from projects.project_ai_result import OpenAIProjectResponseRoutingProvider, ProjectAIResultRoutingUnavailable

    provider = OpenAIProjectResponseRoutingProvider(
        api_key="fake-key", model="gpt-4.1-mini",
        client_factory=lambda api_key: _FakeOpenAIClient("not valid json at all"),
    )
    with pytest.raises(ProjectAIResultRoutingUnavailable):
        provider.classify({"current_request": "test"})


def test_routing_provider_invalid_response_family_is_a_retryable_failure():
    import json as _json

    from projects.project_ai_result import OpenAIProjectResponseRoutingProvider, ProjectAIResultRoutingUnavailable

    malformed = _json.dumps({
        "response_family": "SOMETHING_ELSE_ENTIRELY",
        "confidence": 0.9,
        "brief_reason": "x",
        "needs_clarification": False,
    })
    provider = OpenAIProjectResponseRoutingProvider(
        api_key="fake-key", model="gpt-4.1-mini",
        client_factory=lambda api_key: _FakeOpenAIClient(malformed),
    )
    with pytest.raises(ProjectAIResultRoutingUnavailable):
        provider.classify({"current_request": "test"})


class _FakeOpenAIMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeOpenAIChoice:
    def __init__(self, content: str):
        self.message = _FakeOpenAIMessage(content)


class _FakeOpenAIChatCompletionsResponse:
    def __init__(self, content: str):
        self.choices = [_FakeOpenAIChoice(content)]


class _FakeOpenAIChatCompletions:
    def __init__(self, content: str):
        self._content = content

    def create(self, **kwargs):
        return _FakeOpenAIChatCompletionsResponse(self._content)


class _FakeOpenAIChat:
    def __init__(self, content: str):
        self.completions = _FakeOpenAIChatCompletions(content)


class _FakeOpenAIClient:
    def __init__(self, content: str):
        self.chat = _FakeOpenAIChat(content)


# --- Cross-project isolation ---

def test_route_session_from_another_project_is_isolated(routing_context):
    ctx = routing_context
    project_a = create_project(ctx["client"], name="Project A")
    project_b = create_project(ctx["client"], name="Project B")
    session_resp = ctx["client"].post(f"/projects/{project_b['project_id']}/investigation-sessions", json={})
    session_id = session_resp.json()["session_id"]

    ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
        response_family=ProjectAIResultType.TROUBLESHOOT, confidence=0.9, brief_reason="x",
    )

    response = route(
        ctx["client"], project_a["project_id"],
        user_request="Something is broken.",
        investigation_session_id=session_id,
    )

    assert response.status_code == 404
    assert ctx["routing_provider"].calls == 0, "must isolate before ever asking the classifier"
    assert ctx["text_troubleshoot_provider"].calls == 0, "an explicit session reference must never fall through to text-only"


def test_route_missing_project_is_404_before_any_classifier_call(routing_context):
    ctx = routing_context
    missing_project_id = "11111111-1111-1111-1111-111111111111"

    response = route(ctx["client"], missing_project_id, user_request="Anything.")

    assert response.status_code == 404
    assert ctx["routing_provider"].calls == 0
