from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api
from investigations.session_store import InvestigationSessionStore
from projects import (
    CheckpointProposalStore,
    ProjectActivityStore,
    ProjectContextRetriever,
    ProjectExploreService,
    ProjectStore,
)
from projects.models import (
    CheckpointProposalCreateRequest,
    CheckpointProposalPatch,
    ExplorePlanEstimatedCost,
    ProjectActivityConfirmationStatus,
    ProjectActivityCreateRequest,
    ProjectActivitySourceType,
    ProjectActivityType,
    ProjectExploreOptionSet,
)
from projects.project_explore import (
    ProjectExploreRecoveryConflict,
    _ProjectExploreProviderResponse,
    _response_contains_refusal,
    _decode_estimated_cost,
    _encode_estimated_cost,
)


def test_responses_parse_transport_schema_avoids_unsupported_one_of():
    schema = _ProjectExploreProviderResponse.model_json_schema()
    def keys(value):
        if isinstance(value, dict):
            return set(value) | {key for item in value.values() for key in keys(item)}
        if isinstance(value, list):
            return {key for item in value for key in keys(item)}
        return set()

    assert "oneOf" not in keys(schema)


def test_responses_parse_transport_wrapper_requires_exact_selected_payload():
    wrapped = _ProjectExploreProviderResponse.model_validate(
        {"result_type": "OPTION_SET", "option_set": rich_option_set(), "information_request": None}
    )
    assert wrapped.selected_result().result_type == "OPTION_SET"
    with pytest.raises(ValidationError):
        _ProjectExploreProviderResponse.model_validate(
            {"result_type": "OPTION_SET", "option_set": rich_option_set(),
             "information_request": {"schema_version": "1.1", "result_type": "INFORMATION_REQUEST",
                                     "title": "Need context", "prompt": "What stays?",
                                     "requested_inputs": ["Constraints"], "source_refs": []}}
        )


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
            {"ordinal": 2, "title": "Dark Contemporary", "summary": "Deep contrast with restrained accents.",
             "source_refs": [], "concept": "Lean into deep charcoal walls with brass accents.",
             "proposed_changes": "Repaint feature wall, add brass fixtures.",
             "estimated_cost": {"currency": "USD", "min_amount": 800, "max_amount": 2000, "qualifier": None}},
            {"ordinal": 3, "title": "Minimal Natural", "summary": "Natural textures and a quiet palette.", "source_refs": []},
        ],
        "observations": ["The room currently reads as cold and under-furnished.", "Natural light is limited in the afternoon."],
        "recommended_ordinal": 1,
        "recommendation_reason": "Warm Modern best matches the stated goal of a warmer, welcoming room.",
        "next_steps": ["Confirm budget range with the user.", "Select material samples for the recommended direction."],
        "follow_up_questions": ["Is there an existing color palette to keep?"],
    }
    payload.update(overrides)
    return payload


class FakeProvider:
    def __init__(self, result=None):
        self.result = result if result is not None else rich_option_set()
        self.calls = 0
        self.contexts = []

    def identity(self):
        return api.ProjectExploreProviderIdentity(provider="fake", model="fixture-v1", tool="test.explore")

    def explore(self, context_pack):
        self.calls += 1
        self.contexts.append(context_pack)
        return self.result


@pytest.fixture
def explore_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    projects_root = tmp_path / "projects"
    project_store = ProjectStore(projects_root)
    activity_store = ProjectActivityStore(projects_root, project_store)
    proposal_store = CheckpointProposalStore(projects_root, project_store, activity_store)
    session_store = InvestigationSessionStore(tmp_path / "investigation_sessions")
    context_retriever = ProjectContextRetriever(project_store=project_store, activity_store=activity_store,
        session_store=session_store, investigation_store_root=tmp_path / "investigation_results")
    provider = FakeProvider()
    service = ProjectExploreService(project_store=project_store, activity_store=activity_store,
                                    proposal_store=proposal_store, context_retriever=context_retriever,
                                    provider=provider)
    monkeypatch.setattr(api, "PROJECT_STORE", project_store)
    monkeypatch.setattr(api, "PROJECT_ACTIVITY_STORE", activity_store)
    monkeypatch.setattr(api, "CHECKPOINT_PROPOSAL_STORE", proposal_store)
    monkeypatch.setattr(api, "SESSION_STORE", session_store)
    monkeypatch.setattr(api, "EVIDENCE_STORE", api.InvestigationEvidenceStore(session_store))
    monkeypatch.setattr(api, "_create_project_explore_service", lambda: service)
    monkeypatch.setattr(api, "_create_project_explore_read_service", lambda: service)
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")
    return TestClient(api.app), service, provider, project_store, activity_store, session_store


def create_project(client, name="Room Redesign"):
    response = client.post("/projects", json={"name": name, "goal": "Make the room warmer and modern",
        "checkpoint": {"current_objective": "Choose a design direction", "next_action": "Explore options"}})
    assert response.status_code == 201
    return response.json()


def run_explore(client, project_id, key="room-v1", intent="Give me three room directions"):
    return client.post(f"/projects/{project_id}/interactions/explore",
                       json={"user_intent": intent, "input_refs": [], "idempotency_key": key})


# --- Unit-level: estimated_cost lossless encoding (Activity metadata, flat scalar, never nested JSON) ---

def test_estimated_cost_roundtrip_is_lossless():
    cost = ExplorePlanEstimatedCost(currency="USD", min_amount=500, max_amount=1200, qualifier="rough estimate")
    encoded = _encode_estimated_cost(cost)
    assert isinstance(encoded, str) and "|" in encoded
    decoded = _decode_estimated_cost(encoded)
    assert decoded == cost


def test_estimated_cost_roundtrip_handles_missing_optional_fields():
    cost = ExplorePlanEstimatedCost(currency="EUR")
    decoded = _decode_estimated_cost(_encode_estimated_cost(cost))
    assert decoded == cost
    assert _encode_estimated_cost(None) is None
    assert _decode_estimated_cost(None) is None


def test_estimated_cost_rejects_min_greater_than_max():
    with pytest.raises(ValidationError):
        ExplorePlanEstimatedCost(currency="USD", min_amount=1000, max_amount=500)


def test_estimated_cost_rejects_delimiter_in_qualifier():
    with pytest.raises(ValidationError):
        ExplorePlanEstimatedCost(currency="USD", qualifier="rough|estimate")


def test_estimated_cost_rejects_reserved_pua_delimiter_in_qualifier():
    with pytest.raises(ValidationError):
        ExplorePlanEstimatedCost(currency="USD", qualifier="rough" + chr(0xE000) + "estimate")


# --- Referential integrity: recommended_ordinal must reference a returned option ---

def test_recommended_ordinal_must_reference_a_returned_option():
    # Ordinal 3 is absent from the returned options (1 appears twice); a
    # provider claiming to recommend ordinal 3 must be rejected rather than
    # silently accepted, even though 3 independently satisfies ge=1/le=3.
    with pytest.raises(ValidationError):
        ProjectExploreOptionSet.model_validate(rich_option_set(recommended_ordinal=3, options=[
            {"ordinal": 1, "title": "A", "summary": "a", "source_refs": []},
            {"ordinal": 1, "title": "B", "summary": "b", "source_refs": []},
            {"ordinal": 2, "title": "C", "summary": "c", "source_refs": []},
        ], recommendation_reason="x", observations=["o"], next_steps=["n"]))


def test_end_to_end_response_exposes_recommended_option_flag_and_id(explore_context):
    client, _service, _provider, _projects, activities, _sessions = explore_context
    project = create_project(client)
    body = run_explore(client, project["project_id"]).json()
    group = body["option_set"]
    recommended = [option for option in group["options"] if option["recommended"]]
    assert len(recommended) == 1
    assert recommended[0]["ordinal"] == group["recommended_ordinal"] == 1


# --- Reserved delimiter guard: text fields must reject the internal encoding character ---

def test_reserved_delimiter_is_rejected_in_option_text_fields():
    with pytest.raises(ValidationError):
        ProjectExploreOptionSet.model_validate(rich_option_set(options=[
            {"ordinal": 1, "title": "Warm Modern" + chr(0xE000), "summary": "s", "source_refs": []},
            {"ordinal": 2, "title": "B", "summary": "s", "source_refs": []},
            {"ordinal": 3, "title": "C", "summary": "s", "source_refs": []},
        ]))


def test_reserved_delimiter_is_rejected_in_whole_result_text_fields():
    with pytest.raises(ValidationError):
        ProjectExploreOptionSet.model_validate(rich_option_set(recommendation_reason="Pick Warm Modern" + chr(0xE000)))


# --- Lossless reconstruction after restart: every rich field round-trips exactly ---

def test_lossless_reconstruction_of_rich_fields_after_restart(explore_context):
    client, _service, _provider, projects, activities, sessions = explore_context
    project = create_project(client)
    live_body = run_explore(client, project["project_id"]).json()["option_set"]

    restarted_activity_store = ProjectActivityStore(activities.root, projects)
    restarted_proposal_store = CheckpointProposalStore(activities.root, projects, restarted_activity_store)
    restarted = ProjectExploreService(project_store=projects, activity_store=restarted_activity_store,
        proposal_store=restarted_proposal_store,
        context_retriever=ProjectContextRetriever(project_store=projects, activity_store=restarted_activity_store,
            session_store=sessions, investigation_store_root=activities.root.parent / "investigation_results"),
        provider=None)
    reconstructed = restarted.read_projection(project["project_id"]).option_sets[0]
    reconstructed_body = reconstructed.model_dump(mode="json")

    # Whole-result fields owned by the sibling RESULT Activity.
    assert reconstructed_body["title"] == live_body["title"]
    assert reconstructed_body["summary"] == live_body["summary"]
    assert reconstructed_body["observations"] == live_body["observations"]
    assert reconstructed_body["recommended_ordinal"] == live_body["recommended_ordinal"]
    assert reconstructed_body["recommendation_reason"] == live_body["recommendation_reason"]
    assert reconstructed_body["next_steps"] == live_body["next_steps"]
    assert reconstructed_body["follow_up_questions"] == live_body["follow_up_questions"]

    # Per-option fields owned by each IDEA Activity.
    for live_option, reconstructed_option in zip(live_body["options"], reconstructed_body["options"]):
        assert reconstructed_option["idea"]["summary"] == live_option["idea"]["summary"]
        assert reconstructed_option["summary"] == live_option["summary"]
        assert reconstructed_option["rationale"] == live_option["rationale"]
        assert reconstructed_option["tradeoffs"] == live_option["tradeoffs"]
        assert reconstructed_option["concept"] == live_option["concept"]
        assert reconstructed_option["proposed_changes"] == live_option["proposed_changes"]
        assert reconstructed_option["estimated_cost"] == live_option["estimated_cost"]
        assert reconstructed_option["recommended"] == live_option["recommended"]


def test_select_creates_one_revision_bound_proposal_and_apply_updates_only_direction(explore_context):
    client, _service, _provider, projects, activities, _sessions = explore_context
    project = create_project(client)
    project_id = project["project_id"]
    generated = run_explore(client, project_id).json()["option_set"]
    selected = generated["options"][0]
    idea_id = selected["idea"]["activity_id"]

    # An AI recommendation alone is neither a user selection nor a Project mutation.
    before = projects.load_project(project_id)
    assert generated["options"][0]["recommended"] is True
    assert client.get(f"/projects/{project_id}/checkpoint-proposals").json() == []
    assert not any(a.activity_type.value == "decision" for a in activities.list_activities(project_id))

    payload = {"disposition": "select", "idempotency_key": "select-room-direction"}
    first = client.post(f"/projects/{project_id}/ideas/{idea_id}/disposition", json=payload)
    retry = client.post(f"/projects/{project_id}/ideas/{idea_id}/disposition", json=payload)
    assert first.status_code == retry.status_code == 200
    first_body, retry_body = first.json(), retry.json()
    assert first_body["created"] is True and retry_body["created"] is False
    assert first_body["decision_activity"]["source_type"] == "user"
    assert first_body["decision_activity"]["confirmation_status"] == "reported"
    proposal = first_body["checkpoint_proposal"]
    assert proposal["proposal_id"] == retry_body["checkpoint_proposal"]["proposal_id"]
    assert proposal["status"] == "pending"
    assert proposal["base_project_revision"] == before.revision
    assert proposal["source_activity_ids"] == [
        idea_id,
        generated["result_activity"]["activity_id"],
        first_body["decision_activity"]["activity_id"],
    ]
    assert proposal["proposed_checkpoint_patch"] == {
        "current_objective": None,
        "completed_summary": None,
        "discoveries_summary": None,
        "current_work": (
            "Selected direction: Warm Modern. Warm wood and soft neutral layers. "
            "Concept: Layer warm wood tones with soft neutral textiles. "
            "Planned changes: Add oak accents and warm-white lighting."
        ),
        "stopped_at": None,
        "blockers": None,
        "next_action": "Confirm budget range with the user.",
    }
    assert len(client.get(f"/projects/{project_id}/checkpoint-proposals").json()) == 1
    assert projects.load_project(project_id) == before

    applied = client.post(f"/projects/{project_id}/checkpoint-proposals/{proposal['proposal_id']}/apply")
    assert applied.status_code == 200 and applied.json()["status"] == "applied"
    after = projects.load_project(project_id)
    assert after.revision == before.revision + 1
    assert after.checkpoint.current_objective == before.checkpoint.current_objective
    assert after.checkpoint.current_work == proposal["proposed_checkpoint_patch"]["current_work"]
    assert after.checkpoint.next_action == "Confirm budget range with the user."
    assert after.checkpoint.completed_summary == before.checkpoint.completed_summary
    assert after.checkpoint.discoveries_summary == before.checkpoint.discoveries_summary
    assert after.checkpoint.blockers == before.checkpoint.blockers


def test_divergent_selection_proposal_is_a_409_conflict_not_a_500(explore_context):
    """A conflicting stored proposal for the same Explore selection must
    surface as a structured 409 (client can retry/reload), not an unhandled
    500 - the endpoint previously did not catch ProjectExploreRecoveryConflict
    at all, so this would have propagated as a raw, unstructured 500."""
    client, service, _provider, projects, activities, _sessions = explore_context
    project = create_project(client)
    project_id = project["project_id"]
    generated = run_explore(client, project_id).json()["option_set"]
    idea_id = generated["options"][0]["idea"]["activity_id"]
    result_activity_id = generated["result_activity"]["activity_id"]

    # Seed a DECISION + CheckpointProposal that _selection_proposal's own
    # "caused by this Explore selection" matcher will find, but whose patch
    # deliberately does not match what a fresh reconstruction would compute.
    forged_decision = activities.create_activity(project_id, ProjectActivityCreateRequest(
        activity_type=ProjectActivityType.DECISION, source_type=ProjectActivitySourceType.USER,
        confirmation_status=ProjectActivityConfirmationStatus.REPORTED,
        summary="Choose as preferred direction", details="Forged prior decision for conflict testing.",
        metadata={"interaction_type": "explore", "interaction_id": generated["interaction_id"],
                  "source_activity_id": idea_id, "explore_disposition": "select",
                  "idempotency_key": "forged", "request_fingerprint": "forged"},
    ))
    project_before = projects.load_project(project_id)
    service.proposal_store.create_proposal(project_id, CheckpointProposalCreateRequest(
        expected_project_revision=project_before.revision,
        source_activity_ids=[idea_id, result_activity_id, forged_decision.activity_id],
        proposed_checkpoint_patch=CheckpointProposalPatch(current_work="A deliberately different direction."),
        reason="Forged conflicting proposal for conflict testing.",
    ))

    response = client.post(f"/projects/{project_id}/ideas/{idea_id}/disposition",
        json={"disposition": "select", "idempotency_key": "select-real"})
    assert response.status_code == 409
    assert response.json()["detail"]["category"] == "explore_recovery_conflict"


# --- Partial 4-activity group recovery: 3 Ideas written, RESULT missing (the QA-found gap) ---

def test_three_ideas_no_result_is_incomplete_and_recovers_with_exactly_one_more_provider_call(explore_context, monkeypatch):
    client, service, provider, _projects, activities, _sessions = explore_context
    project = create_project(client)
    original = activities.create_activity_with_id
    writes = 0

    def fail_before_result(project_id, activity_id, request):
        nonlocal writes
        writes += 1
        if writes == 4:  # the 3 IDEA writes succeed; the 4th call (RESULT) is interrupted
            raise RuntimeError("simulated interruption before RESULT write")
        return original(project_id, activity_id, request)

    monkeypatch.setattr(activities, "create_activity_with_id", fail_before_result)
    with pytest.raises(RuntimeError):
        service.execute(project["project_id"], api.ProjectExploreRequest(
            user_intent="Give me three room directions", input_refs=[], idempotency_key="room-v1"))

    stored = activities.list_activities(project["project_id"])
    assert len(stored) == 3
    assert {item.activity_type.value for item in stored} == {"idea"}

    partial_projection = service.read_projection(project["project_id"])
    assert partial_projection.option_sets == []
    assert partial_projection.next_action == "Retry Explore to recover the interrupted suggestion set."

    monkeypatch.setattr(activities, "create_activity_with_id", original)
    recovered = run_explore(client, project["project_id"])
    assert recovered.status_code == 200 and provider.calls == 2
    final = activities.list_activities(project["project_id"])
    assert len(final) == 4
    assert {item.activity_type.value for item in final} == {"idea", "result"}
    assert service.read_projection(project["project_id"]).option_sets != []


def test_result_only_divergence_before_result_exists_is_accepted_not_rejected(explore_context, monkeypatch):
    """Because RESULT is always the 4th, last write, a crash before it leaves
    nothing stored to diverge from at the whole-result level - only the 3
    option Ideas anchor idempotency at that point. A retry that changes only
    whole-result fields (not yet persisted anywhere) must be accepted and
    produce a fresh RESULT Activity, not spuriously rejected as a conflict.
    """
    client, service, provider, _projects, activities, _sessions = explore_context
    project = create_project(client)
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
        service.execute(project["project_id"], api.ProjectExploreRequest(
            user_intent="Give me three room directions", input_refs=[], idempotency_key="room-v1"))
    monkeypatch.setattr(activities, "create_activity_with_id", original)

    provider.result = rich_option_set(recommendation_reason="A completely different recommendation reason.")
    response = run_explore(client, project["project_id"])
    assert response.status_code == 200
    assert response.json()["option_set"]["recommendation_reason"] == "A completely different recommendation reason."
    stored = activities.list_activities(project["project_id"])
    assert len(stored) == 4


def test_result_activity_mismatch_is_detected_by_the_recovery_guard(explore_context):
    """Unit-level coverage for _verify_matching_result's defense-in-depth
    check: given write ordering (options always precede RESULT), a stored
    RESULT can only exist once the group is already complete, so this path
    is unreachable via ordinary crash recovery end-to-end - it is still
    exercised directly so the guard itself is proven correct.
    """
    client, service, provider, _projects, activities, _sessions = explore_context
    project = create_project(client)
    response = run_explore(client, project["project_id"])
    assert response.status_code == 200
    stored_result = next(a for a in activities.list_activities(project["project_id"]) if a.activity_type.value == "result")
    interaction_id = stored_result.metadata["interaction_id"]
    fingerprint = stored_result.metadata["request_fingerprint"]

    from projects.models import ProjectExploreOptionSet as _OptionSet
    diverging = _OptionSet.model_validate(rich_option_set(recommendation_reason="A materially different reason."))
    with pytest.raises(ProjectExploreRecoveryConflict):
        service._verify_matching_result(stored_result, diverging, fingerprint, interaction_id)

    matching = _OptionSet.model_validate(rich_option_set())
    service._verify_matching_result(stored_result, matching, fingerprint, interaction_id)  # does not raise


# --- Provider refusal detection (ported from Investigation's proven pattern) ---

def test_provider_refusal_is_distinguished_from_a_malformed_response():
    class _ContentItem:
        def __init__(self, type_):
            self.type = type_

    class _Output:
        def __init__(self, type_, content=None):
            self.type = type_
            self.content = content

    class _Response:
        def __init__(self, output):
            self.output = output

    refusal_response = _Response([_Output("message", [_ContentItem("refusal")])])
    assert _response_contains_refusal(refusal_response) is True

    normal_response = _Response([_Output("message", [_ContentItem("output_text")])])
    assert _response_contains_refusal(normal_response) is False

    assert _response_contains_refusal(_Response(None)) is False
