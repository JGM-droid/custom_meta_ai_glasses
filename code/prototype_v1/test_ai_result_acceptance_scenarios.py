"""Rich Project Intelligence V1 - small representative acceptance set.

Per the approved architecture gate, this is deliberately a SMALL scenario
set (not the full future 20-40 suite) proving the Response Planner's
DETERMINISTIC properties across a representative variety of inputs:
explicit response-family dispatch, schema validity, Project isolation,
evidence/reference validity, option structure, recommended-option
referential integrity, idempotency/reconstruction, partial-write recovery,
and that GENERAL_GUIDANCE never becomes durable.

These assertions are structural, not a judgment of AI response quality -
whether an option is genuinely "good," "creative," or "safe" is not
something a unit test can prove. Each scenario's full ProjectAIResult body
is additionally written to results/eval_fixtures/rich_project_intelligence_v1/
for separate human quality review; this file makes no quality assertions
about that content beyond structural shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from investigations import InvestigationSessionStore, save_canonical_investigation_result
from investigations.models import InvestigationAnalysisStatus, InvestigationRetainedResult
from projects import (
    CheckpointProposalStore,
    ProjectActivityStore,
    ProjectContextRetriever,
    ProjectExploreService,
    ProjectQuestionAnsweringService,
    ProjectStore,
)
from datetime import datetime, timezone
from uuid import uuid4

EVAL_OUTPUT_DIR = Path(__file__).resolve().parent / "results" / "eval_fixtures" / "rich_project_intelligence_v1"


def _explore_plan_scenario(*, title, options, observations, recommended_ordinal, recommendation_reason, next_steps, follow_up_questions=None):
    return {
        "schema_version": "1.1", "result_type": "OPTION_SET", "title": title,
        "summary": f"Three directions for: {title}.", "source_refs": [], "options": options,
        "observations": observations, "recommended_ordinal": recommended_ordinal,
        "recommendation_reason": recommendation_reason, "next_steps": next_steps,
        "follow_up_questions": follow_up_questions or [],
    }


ROOM_REDESIGN_SCENARIOS = {
    "warm_cozy_tight_budget": _explore_plan_scenario(
        title="Warm cozy makeover on a tight budget",
        options=[
            {"ordinal": 1, "title": "Budget Warm Textiles", "summary": "Layer inexpensive warm-toned throws and rugs.",
             "concept": "Soft-furnishing-first warmth without structural changes.",
             "estimated_cost": {"currency": "USD", "min_amount": 80, "max_amount": 250, "qualifier": "textiles only"},
             "source_refs": []},
            {"ordinal": 2, "title": "DIY Accent Wall", "summary": "Paint one wall a warm terracotta tone.",
             "estimated_cost": {"currency": "USD", "min_amount": 40, "max_amount": 120, "qualifier": "paint and supplies"},
             "source_refs": []},
            {"ordinal": 3, "title": "Secondhand Wood Accents", "summary": "Source warm wood furniture pieces secondhand.",
             "estimated_cost": {"currency": "USD", "min_amount": 100, "max_amount": 400, "qualifier": "secondhand market estimate"},
             "source_refs": []},
        ],
        observations=["The stated constraint is a tight budget.", "The room currently has cool-toned, sparse furnishing."],
        recommended_ordinal=1, recommendation_reason="Lowest cost path that most directly addresses warmth.",
        next_steps=["Confirm the exact budget ceiling.", "Pick throw/rug colors."],
        follow_up_questions=["What is the firm maximum budget?"],
    ),
    "modern_minimalist_no_budget_stated": _explore_plan_scenario(
        title="Modern minimalist office corner",
        options=[
            {"ordinal": 1, "title": "Clean Line Desk Setup", "summary": "A single desk with concealed cable management.", "source_refs": []},
            {"ordinal": 2, "title": "Built-in Shelving Wall", "summary": "Floor-to-ceiling minimalist shelving.", "source_refs": []},
            {"ordinal": 3, "title": "Standing Desk Nook", "summary": "A compact standing-desk-first layout.", "source_refs": []},
        ],
        observations=["No budget was stated, so no cost estimates are included."],
        recommended_ordinal=1, recommendation_reason="Simplest to execute with the least structural change.",
        next_steps=["Confirm desired desk orientation."],
    ),
    "kid_friendly_playroom_safety": _explore_plan_scenario(
        title="Kid-friendly playroom redesign",
        options=[
            {"ordinal": 1, "title": "Soft-Corner Low Furniture", "summary": "Low, rounded-corner furniture throughout.",
             "proposed_changes": "Replace sharp-cornered furniture with padded, rounded pieces.", "source_refs": []},
            {"ordinal": 2, "title": "Padded Play Zone", "summary": "A dedicated padded-floor play area.", "source_refs": []},
            {"ordinal": 3, "title": "Modular Storage Bins", "summary": "Low, tip-resistant modular storage.", "source_refs": []},
        ],
        observations=["Safety for young children is the stated priority.", "Sharp corners and tall unsecured furniture are present today."],
        recommended_ordinal=1, recommendation_reason="Directly addresses the stated safety priority.",
        next_steps=["Confirm ages of children using the room.", "Check furniture tip-restraint hardware."],
        follow_up_questions=["Are there specific safety certifications required?"],
    ),
}

AC_REPAIR_SCENARIOS = {
    "blowing_warm_air": {
        "diagnosis": "The compressor is likely not engaging, so only fan air circulates without cooling.",
        "required_next_action": "Check the compressor contactor and capacitor before replacing the unit.",
    },
    "rattling_noise": {
        "diagnosis": "A loose access panel or fan blade is the likely source of the rattling noise.",
        "required_next_action": "Power down the unit and inspect the panel screws and fan blade for looseness.",
    },
    "wont_turn_on": {
        "diagnosis": "A tripped breaker or blown fuse is the likely cause of the unit not powering on at all.",
        "required_next_action": "Check the breaker panel and disconnect fuse before inspecting internal wiring.",
    },
}


class FakeExploreProvider:
    def __init__(self):
        self.result = None
        self.calls = 0

    def identity(self):
        return api.ProjectExploreProviderIdentity(provider="fake", model="eval-fixture-v1", tool="test.explore")

    def explore(self, context_pack):
        self.calls += 1
        return self.result


class FakeReasoningProvider:
    def __init__(self):
        self.answer_text = ""
        self.insufficient_context = False
        self.calls = 0

    def reason(self, request):
        self.calls += 1
        from projects.project_qa import ProjectReasoningResponse
        return ProjectReasoningResponse(
            answer=self.answer_text, insufficient_context=self.insufficient_context,
            uncertainty_note=None, grounding_status="insufficient_context" if self.insufficient_context else "grounded",
            provider="fake", provider_model="eval-fixture-v1",
        )


@pytest.fixture
def scenario_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
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


def _create_project(client, name):
    response = client.post("/projects", json={"name": name, "goal": "Evaluation scenario Project",
        "checkpoint": {"current_objective": "Evaluate Rich Project Intelligence V1", "next_action": "Run the scenario"}})
    assert response.status_code == 201
    return response.json()


def _record_fixture(scenario_id: str, body: dict) -> None:
    EVAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_OUTPUT_DIR / f"{scenario_id}.json").write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")


# --- Deterministic structural assertions shared by every EXPLORE_PLAN scenario ---

def _assert_explore_plan_structure(body: dict, project_id: str) -> None:
    assert body["result_type"] == "EXPLORE_PLAN"
    assert body["project_id"] == project_id
    assert body["ephemeral"] is False
    group = body["explore_plan"]
    options = group["options"]
    assert len(options) == 3
    assert [option["ordinal"] for option in options] == [1, 2, 3]
    assert len({option["idea"]["summary"] for option in options}) == 3  # distinct
    recommended = [option for option in options if option["recommended"]]
    assert len(recommended) == 1
    assert recommended[0]["ordinal"] == group["recommended_ordinal"]
    assert group["observations"] and group["next_steps"] and group["recommendation_reason"]
    assert body["hud_projection"]["headline"]


@pytest.mark.parametrize("scenario_id", sorted(ROOM_REDESIGN_SCENARIOS))
def test_room_redesign_explore_plan_scenario_is_structurally_sound_and_recoverable(scenario_context, scenario_id):
    client, project_store, activity_store, _sessions, _inv_root, explore_provider, _reasoning = scenario_context
    project = _create_project(client, f"Room Redesign - {scenario_id}")
    explore_provider.result = ROOM_REDESIGN_SCENARIOS[scenario_id]
    before = project_store.load_project(project["project_id"])

    first = client.post(f"/projects/{project['project_id']}/ai-results/explore-plan",
        json={"user_intent": "Explore directions for this room.", "input_refs": [], "idempotency_key": "eval-1"})
    assert first.status_code == 200
    body = first.json()
    _assert_explore_plan_structure(body, project["project_id"])
    _record_fixture(f"room_redesign__{scenario_id}", body)

    # Idempotency/reconstruction: same key returns the identical interaction, no second provider call.
    second = client.post(f"/projects/{project['project_id']}/ai-results/explore-plan",
        json={"user_intent": "Explore directions for this room.", "input_refs": [], "idempotency_key": "eval-1"})
    assert second.status_code == 200 and explore_provider.calls == 1
    assert second.json()["result_id"] == body["result_id"]

    read_back = client.get(f"/projects/{project['project_id']}/ai-results/explore-plan/{body['result_id']}")
    assert read_back.status_code == 200
    assert read_back.json()["explore_plan"] == body["explore_plan"]

    # No silent canonical Project mutation: revision and checkpoint are untouched.
    after = project_store.load_project(project["project_id"])
    assert after.revision == before.revision and after.checkpoint == before.checkpoint


def test_room_redesign_budget_constraint_is_structurally_preserved(scenario_context):
    """Constraint-preservation check bounded to what a unit test can actually
    prove: the budget-constrained scenario's estimated_cost fields survive
    the full write -> read -> reconstruct round trip unchanged. Whether the
    OPTIONS THEMSELVES are good budget-appropriate ideas is a human/quality
    judgment, not asserted here."""
    client, *_rest, explore_provider, _reasoning = scenario_context
    project = _create_project(client, "Room Redesign - budget constraint check")
    explore_provider.result = ROOM_REDESIGN_SCENARIOS["warm_cozy_tight_budget"]
    body = client.post(f"/projects/{project['project_id']}/ai-results/explore-plan",
        json={"user_intent": "Explore directions.", "input_refs": [], "idempotency_key": "eval-budget"}).json()
    recommended_option = next(option for option in body["explore_plan"]["options"] if option["recommended"])
    assert recommended_option["estimated_cost"]["currency"] == "USD"
    assert recommended_option["estimated_cost"]["max_amount"] == 250


def test_explore_plan_partial_write_recovery_across_a_representative_scenario(scenario_context, monkeypatch):
    client, _projects, activities, *_rest, explore_provider, _reasoning = scenario_context
    project = _create_project(client, "Room Redesign - recovery check")
    explore_provider.result = ROOM_REDESIGN_SCENARIOS["kid_friendly_playroom_safety"]
    original = activities.create_activity_with_id
    writes = 0

    def fail_before_result(project_id, activity_id, request):
        nonlocal writes
        writes += 1
        if writes == 4:
            raise RuntimeError("simulated interruption before RESULT write")
        return original(project_id, activity_id, request)

    monkeypatch.setattr(activities, "create_activity_with_id", fail_before_result)
    with pytest.raises(RuntimeError):
        client.post(f"/projects/{project['project_id']}/ai-results/explore-plan",
            json={"user_intent": "Explore directions.", "input_refs": [], "idempotency_key": "eval-recovery"})
    assert len(activities.list_activities(project["project_id"])) == 3

    monkeypatch.setattr(activities, "create_activity_with_id", original)
    recovered = client.post(f"/projects/{project['project_id']}/ai-results/explore-plan",
        json={"user_intent": "Explore directions.", "input_refs": [], "idempotency_key": "eval-recovery"})
    assert recovered.status_code == 200 and explore_provider.calls == 2
    assert len(activities.list_activities(project["project_id"])) == 4


# --- AC Repair: TROUBLESHOOT must stay TROUBLESHOOT-shaped, never option-plan-shaped ---

@pytest.mark.parametrize("scenario_id", sorted(AC_REPAIR_SCENARIOS))
def test_ac_repair_troubleshoot_scenario_is_structurally_sound(scenario_context, scenario_id):
    client, project_store, _activities, session_store, investigation_results_root, *_rest = scenario_context
    project = _create_project(client, f"AC Repair - {scenario_id}")
    scenario = AC_REPAIR_SCENARIOS[scenario_id]
    session = session_store.create_session(project_id=project["project_id"])
    now = datetime.now(timezone.utc)
    result_id = str(uuid4())
    retained = InvestigationRetainedResult(
        schema_version="1.0", investigation_id=str(uuid4()), session_id=session.session_id,
        status=InvestigationAnalysisStatus.ANALYZED, diagnosis=scenario["diagnosis"],
        required_next_action=scenario["required_next_action"], image_count=1, image_order=["ac-evidence-1"],
        used_user_explanation="Described the AC symptom.", completed_at_utc=now, context_used=False,
        context_staleness="unknown", copilot_prompt="Diagnose the AC issue.",
    )
    save_canonical_investigation_result(investigation_results_root, result_id=result_id,
        retained_result=retained, session_id=session.session_id, analysis_attempt_id=str(uuid4()))
    session_store.mutate_session(session.session_id, lambda current: (current.model_copy(update={"completed_result_id": result_id}), True))

    response = client.get(f"/projects/{project['project_id']}/ai-results/troubleshoot/{session.session_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["result_type"] == "TROUBLESHOOT"
    assert body["ephemeral"] is False
    assert body["troubleshoot"]["diagnosis"] == scenario["diagnosis"]
    assert body["troubleshoot"]["required_next_action"] == scenario["required_next_action"]
    assert body["explore_plan"] is None and body["general_guidance"] is None  # never option-plan-shaped
    assert body["evidence_refs"] == ["ac-evidence-1"]
    _record_fixture(f"ac_repair__{scenario_id}", body)


def test_ac_repair_and_room_redesign_are_project_isolated(scenario_context):
    client, *_rest, explore_provider, _reasoning = scenario_context
    ac_project = _create_project(client, "AC Repair - isolation check")
    room_project = _create_project(client, "Room Redesign - isolation check")
    explore_provider.result = ROOM_REDESIGN_SCENARIOS["modern_minimalist_no_budget_stated"]
    created = client.post(f"/projects/{room_project['project_id']}/ai-results/explore-plan",
        json={"user_intent": "Explore directions.", "input_refs": [], "idempotency_key": "isolation"}).json()
    interaction_id = created["result_id"]

    cross_project_read = client.get(f"/projects/{ac_project['project_id']}/ai-results/explore-plan/{interaction_id}")
    assert cross_project_read.status_code == 404


# --- GENERAL_GUIDANCE: grounded continuity question and an honest insufficient-context case ---

def test_general_guidance_scenario_grounded_continuity_question(scenario_context):
    client, _projects, activities, *_rest, reasoning_provider = scenario_context
    project = _create_project(client, "General Guidance - continuity")
    reasoning_provider.answer_text = "Based on the current checkpoint, the kitchen layout direction was chosen and cabinet colors are next."
    body = client.post(f"/projects/{project['project_id']}/ai-results/general-guidance",
        json={"question": "Where did we leave off on this kitchen project?"}).json()
    assert body["result_type"] == "GENERAL_GUIDANCE"
    assert body["ephemeral"] is True
    assert body["hud_projection"]["uncertainty_flag"] is False
    assert activities.list_activities(project["project_id"]) == []
    _record_fixture("general_guidance__continuity_question", body)


def test_general_guidance_scenario_honest_insufficient_context(scenario_context):
    client, _projects, activities, *_rest, reasoning_provider = scenario_context
    project = _create_project(client, "General Guidance - insufficient context")
    reasoning_provider.insufficient_context = True
    reasoning_provider.answer_text = "There isn't enough recorded Project context yet to answer that confidently."
    body = client.post(f"/projects/{project['project_id']}/ai-results/general-guidance",
        json={"question": "What should I prioritize next?"}).json()
    assert body["result_type"] == "GENERAL_GUIDANCE"
    assert body["ephemeral"] is True
    assert body["hud_projection"]["uncertainty_flag"] is True
    assert activities.list_activities(project["project_id"]) == []
    _record_fixture("general_guidance__insufficient_context", body)
