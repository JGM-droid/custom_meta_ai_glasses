from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from investigations.session_store import InvestigationSessionStore
from projects import (
    CheckpointProposalStore,
    ProjectActivityStore,
    ProjectExploreService,
    ProjectContextRetriever,
    ProjectStore,
)


def option_set(suffix=""):
    return {"schema_version": "1.1", "result_type": "OPTION_SET", "title": "Room directions", "summary": "Three possible directions.",
            "source_refs": [], "options": [
                {"ordinal": 1, "title": f"Warm Modern{suffix}", "summary": "Warm wood and soft neutral layers.", "rationale": "Supports a welcoming room.", "tradeoffs": "Needs material samples.", "source_refs": [],
                 "concept": "Layer warm wood tones with soft neutral textiles.", "proposed_changes": "Add oak accents and warm-white lighting.",
                 "estimated_cost": {"currency": "USD", "min_amount": 500, "max_amount": 1200, "qualifier": "rough estimate"}},
                {"ordinal": 2, "title": f"Dark Contemporary{suffix}", "summary": "Deep contrast with restrained accents.", "source_refs": []},
                {"ordinal": 3, "title": f"Minimal Natural{suffix}", "summary": "Natural textures and a quiet palette.", "source_refs": []},
            ],
            "observations": ["The room currently reads as cold and under-furnished."],
            "recommended_ordinal": 1,
            "recommendation_reason": "Warm Modern best matches the stated goal of a warmer, welcoming room.",
            "next_steps": ["Confirm budget range with the user.", "Select material samples for the recommended direction."],
            "follow_up_questions": ["Is there an existing color palette to keep?"]}


class FakeProvider:
    def __init__(self, result=None):
        self.result = result if result is not None else option_set()
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


def test_success_projects_exactly_three_ai_inferred_ideas_and_context(explore_context):
    client, _service, provider, project_store, activity_store, sessions = explore_context
    project = create_project(client)
    active_project = create_project(client, "Existing Active")
    project_store.set_active_project(active_project["project_id"])
    active_before = project_store.get_active_project_id()
    assert _service.read_projection(project["project_id"]).next_action == "Start Explore to generate Project-scoped suggestions."
    response = run_explore(client, project["project_id"])
    assert response.status_code == 200
    body = response.json()
    assert body["result_type"] == "OPTION_SET" and body["suggestions_created"] is True
    assert [item["ordinal"] for item in body["option_set"]["options"]] == [1, 2, 3]
    all_activities = activity_store.list_activities(project["project_id"])
    ideas = [item for item in all_activities if item.activity_type.value == "idea"]
    results = [item for item in all_activities if item.activity_type.value == "result"]
    assert len(all_activities) == 4
    assert len(ideas) == 3 and len(results) == 1
    assert {(item.activity_type.value, item.source_type.value, item.confirmation_status.value) for item in ideas} == {("idea", "ai", "inferred")}
    assert (results[0].source_type.value, results[0].confirmation_status.value) == ("ai", "inferred")
    assert len({item.metadata["interaction_id"] for item in all_activities}) == 1
    assert results[0].metadata["recommended_ordinal"] == 1
    group = body["option_set"]
    assert group["recommended_ordinal"] == 1 and group["options"][0]["recommended"] is True
    assert group["options"][1]["recommended"] is False
    assert group["options"][0]["concept"] and group["options"][0]["estimated_cost"]["currency"] == "USD"
    assert group["observations"] and group["next_steps"] and group["recommendation_reason"]
    assert provider.calls == 1 and provider.contexts[0].contract_id == "explore_option_generation_v1"
    assert provider.contexts[0].project_id == project["project_id"]
    assert project_store.load_project(project["project_id"]).revision == project["revision"]
    assert project_store.get_active_project_id() == active_before
    assert sessions.list_sessions() == []
    assert _service.read_projection(project["project_id"]).next_action == "Review the AI suggestions and choose what to keep, dismiss, or prefer."
    metadata = ideas[0].metadata
    assert len(metadata["context_fingerprint"]) == 64
    assert (metadata["provider"], metadata["provider_model"], metadata["provider_tool"]) == (
        "fake", "fixture-v1", "test.explore"
    )


def test_complete_sequential_and_concurrent_retries_converge_without_provider_recall(explore_context):
    client, _service, provider, _projects, activities, _sessions = explore_context
    project = create_project(client)
    first = run_explore(client, project["project_id"])
    assert first.status_code == 200 and provider.calls == 1
    second = run_explore(client, project["project_id"])
    assert second.status_code == 200 and provider.calls == 1
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: run_explore(client, project["project_id"]), range(3)))
    assert all(item.status_code == 200 for item in responses)
    assert provider.calls == 1 and len(activities.list_activities(project["project_id"])) == 4


def test_changed_request_same_key_conflicts(explore_context):
    client, *_ = explore_context
    project = create_project(client)
    assert run_explore(client, project["project_id"]).status_code == 200
    conflict = run_explore(client, project["project_id"], intent="A materially different request")
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["category"] == "explore_idempotency_conflict"


@pytest.mark.parametrize("invalid", [
    "not json",
    {key: value for key, value in option_set().items() if key != "schema_version"},
    {**option_set(), "schema_version": "2.0"},
    {"result_type": "OPTION_SET", "title": "x", "summary": "x", "source_refs": [], "options": []},
    {**option_set(), "provider_action": "apply_checkpoint"},
    {**option_set(), "options": [option_set()["options"][0], option_set()["options"][0], option_set()["options"][2]]},
])
def test_invalid_structured_output_writes_nothing(explore_context, invalid):
    client, _service, provider, _projects, activities, _sessions = explore_context
    project = create_project(client)
    provider.result = invalid
    response = run_explore(client, project["project_id"])
    assert response.status_code == 502
    assert activities.list_activities(project["project_id"]) == []


def test_information_request_is_explicit_transient_and_nonmutating(explore_context):
    client, _service, provider, projects, activities, sessions = explore_context
    project = create_project(client)
    before = projects.load_project(project["project_id"])
    provider.result = {"schema_version": "1.1", "result_type": "INFORMATION_REQUEST", "title": "Need constraints",
                       "prompt": "What must remain?", "requested_inputs": ["Existing furniture"], "source_refs": []}
    first = run_explore(client, project["project_id"])
    second = run_explore(client, project["project_id"])
    assert first.status_code == second.status_code == 200
    assert first.json()["suggestions_created"] is False
    assert "No suggestions were created" in first.json()["message"]
    assert provider.calls == 2 and activities.list_activities(project["project_id"]) == []
    assert projects.load_project(project["project_id"]) == before and sessions.list_sessions() == []


def test_partial_group_is_hidden_and_matching_recovery_only_adds_missing(explore_context, monkeypatch):
    client, _service, provider, _projects, activities, _sessions = explore_context
    project = create_project(client)
    original = activities.create_activity_with_id
    writes = 0

    def fail_after_first(project_id, activity_id, request):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise RuntimeError("simulated process interruption")
        return original(project_id, activity_id, request)

    monkeypatch.setattr(activities, "create_activity_with_id", fail_after_first)
    with pytest.raises(RuntimeError):
        _service.execute(project["project_id"], api.ProjectExploreRequest(
            user_intent="Give me three room directions", input_refs=[], idempotency_key="room-v1"))
    assert len(activities.list_activities(project["project_id"])) == 1
    partial_projection = _service.read_projection(project["project_id"])
    assert partial_projection.option_sets == []
    assert partial_projection.next_action == "Retry Explore to recover the interrupted suggestion set."
    partial_idea_id = activities.list_activities(project["project_id"])[0].activity_id
    proposal = client.post(f"/projects/{project['project_id']}/checkpoint-proposals", json={
        "expected_project_revision": project["revision"],
        "source_activity_ids": [partial_idea_id],
        "proposed_checkpoint_patch": {"next_action": "Review the preferred room direction"},
        "reason": "Explicitly review this Project change",
    })
    assert proposal.status_code == 201
    assert _service.read_projection(project["project_id"]).next_action == "Review the pending suggested Project change."
    monkeypatch.setattr(activities, "create_activity_with_id", original)
    recovered = run_explore(client, project["project_id"])
    assert recovered.status_code == 200 and provider.calls == 2
    assert len(activities.list_activities(project["project_id"])) == 4


def test_divergent_partial_recovery_returns_precise_conflict(explore_context, monkeypatch):
    client, service, provider, _projects, activities, _sessions = explore_context
    project = create_project(client)
    original = activities.create_activity_with_id
    writes = 0
    def interrupt(project_id, activity_id, request):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise RuntimeError("interrupt")
        return original(project_id, activity_id, request)
    monkeypatch.setattr(activities, "create_activity_with_id", interrupt)
    with pytest.raises(RuntimeError):
        service.execute(project["project_id"], api.ProjectExploreRequest(
            user_intent="Give me three room directions", input_refs=[], idempotency_key="room-v1"))
    monkeypatch.setattr(activities, "create_activity_with_id", original)
    provider.result = option_set(" changed")
    response = run_explore(client, project["project_id"])
    assert response.status_code == 409
    assert response.json()["detail"]["category"] == "explore_recovery_conflict"
    assert len(activities.list_activities(project["project_id"])) == 1


def test_dispositions_latest_wins_selection_is_noncanonical_and_promotion_stays_explicit(explore_context):
    client, _service, _provider, projects, activities, _sessions = explore_context
    project = create_project(client)
    checkpoint_before = projects.load_project(project["project_id"])
    options = run_explore(client, project["project_id"]).json()["option_set"]["options"]
    first_id = options[0]["idea"]["activity_id"]
    second_id = options[1]["idea"]["activity_id"]
    keep = client.post(f"/projects/{project['project_id']}/ideas/{first_id}/disposition",
                       json={"disposition": "keep", "idempotency_key": "keep-1"})
    assert keep.status_code == 200 and keep.json()["created"] is True
    assert client.post(f"/projects/{project['project_id']}/ideas/{first_id}/disposition",
                       json={"disposition": "keep", "idempotency_key": "keep-1"}).json()["created"] is False
    selected = client.post(f"/projects/{project['project_id']}/ideas/{first_id}/disposition",
                           json={"disposition": "select", "idempotency_key": "select-1"})
    assert selected.status_code == 200
    projection = client.get(f"/projects/{project['project_id']}/interactions/explore").json()
    assert projection["preferred_direction"]["idea"]["activity_id"] == first_id
    assert projection["next_action"] == "Preferred direction recorded. Create or review a suggested Project change when ready."
    assert projection["option_sets"][0]["options"][0]["disposition"] == "select"
    assert [item["metadata"]["explore_disposition"] for item in projection["option_sets"][0]["options"][0]["disposition_history"]] == ["keep", "select"]
    assert client.post(f"/projects/{project['project_id']}/ideas/{second_id}/disposition",
        json={"disposition": "keep", "idempotency_key": "keep-2"}).status_code == 200
    projection = client.get(f"/projects/{project['project_id']}/interactions/explore").json()
    assert projection["preferred_direction"]["idea"]["activity_id"] == first_id
    assert client.post(f"/projects/{project['project_id']}/ideas/{second_id}/disposition",
        json={"disposition": "dismiss", "idempotency_key": "dismiss-2"}).status_code == 200
    projection = client.get(f"/projects/{project['project_id']}/interactions/explore").json()
    assert projection["preferred_direction"]["idea"]["activity_id"] == first_id
    assert client.post(f"/projects/{project['project_id']}/ideas/{second_id}/disposition",
        json={"disposition": "select", "idempotency_key": "select-2"}).status_code == 200
    projection = client.get(f"/projects/{project['project_id']}/interactions/explore").json()
    assert projection["preferred_direction"]["idea"]["activity_id"] == second_id
    assert client.post(f"/projects/{project['project_id']}/ideas/{second_id}/disposition",
        json={"disposition": "dismiss", "idempotency_key": "dismiss-2-after-select"}).status_code == 200
    projection = client.get(f"/projects/{project['project_id']}/interactions/explore").json()
    assert projection["preferred_direction"] is None
    assert projection["option_sets"][0]["options"][0]["disposition"] == "select"
    assert projection["option_sets"][0]["options"][1]["disposition"] == "dismiss"
    assert projection["next_action"] == "Review the AI suggestions and choose what to keep, dismiss, or prefer."
    assert projects.load_project(project["project_id"]) == checkpoint_before
    assert client.get(f"/projects/{project['project_id']}/checkpoint-proposals").json() == []
    assert not any((a.metadata or {}).get("promoted_from_activity_id") for a in activities.list_activities(project["project_id"]))
    promoted = client.post(f"/projects/{project['project_id']}/ideas/{first_id}/promote").json()
    assert promoted["created"] is True
    assert client.post(f"/projects/{project['project_id']}/ideas/{first_id}/promote").json()["created"] is False


def test_explicit_context_refs_are_project_scoped_and_provider_refs_cannot_escape(explore_context):
    client, _service, provider, _projects, activities, _sessions = explore_context
    project_a = create_project(client, "A")
    project_b = create_project(client, "B")
    ref_a = client.post(f"/projects/{project_a['project_id']}/activities", json={
        "activity_type": "observation", "source_type": "user", "confirmation_status": "reported",
        "summary": "Keep the existing oak table",
    }).json()
    ref_b = client.post(f"/projects/{project_b['project_id']}/activities", json={
        "activity_type": "observation", "source_type": "user", "confirmation_status": "reported",
        "summary": "Private Project B constraint",
    }).json()
    payload = {"user_intent": "Explore directions", "input_refs": [ref_a["activity_id"]], "idempotency_key": "refs"}
    assert client.post(f"/projects/{project_a['project_id']}/interactions/explore", json=payload).status_code == 200
    assert [item["activity_id"] for item in provider.contexts[-1].input_activities] == [ref_a["activity_id"]]
    assert ref_b["activity_id"] not in str(provider.contexts[-1])
    cross = {**payload, "idempotency_key": "foreign", "input_refs": [ref_b["activity_id"]]}
    assert client.post(f"/projects/{project_a['project_id']}/interactions/explore", json=cross).status_code == 409
    provider.result = option_set()
    provider.result["source_refs"] = [ref_b["activity_id"]]
    invented = client.post(f"/projects/{project_a['project_id']}/interactions/explore", json={
        "user_intent": "Invented ref", "input_refs": [], "idempotency_key": "invented"})
    assert invented.status_code == 502
    assert len([a for a in activities.list_activities(project_a["project_id"]) if a.activity_type.value == "idea"]) == 3


def test_prior_explore_decision_context_has_bounded_semantic_idea_link(explore_context):
    client, _service, provider, *_ = explore_context
    project = create_project(client)
    idea = run_explore(client, project["project_id"], key="first").json()["option_set"]["options"][0]["idea"]
    assert client.post(f"/projects/{project['project_id']}/ideas/{idea['activity_id']}/disposition",
        json={"disposition": "keep", "idempotency_key": "keep-context"}).status_code == 200
    assert run_explore(client, project["project_id"], key="second", intent="Explore another set").status_code == 200
    linked_decisions = [item for item in provider.contexts[-1].relevant_context
                        if item["activity_type"] == "decision"]
    assert len(linked_decisions) == 1
    assert linked_decisions[0]["linked_idea"] == {
        "activity_id": idea["activity_id"], "title": idea["summary"]
    }
    assert "metadata" not in linked_decisions[0]


def test_restart_reconstruction_and_project_isolation(explore_context):
    client, _service, provider, projects, activities, _sessions = explore_context
    project_a = create_project(client, "A")
    project_b = create_project(client, "B")
    result = run_explore(client, project_a["project_id"]).json()
    idea_id = result["option_set"]["options"][0]["idea"]["activity_id"]
    restarted_activity_store = ProjectActivityStore(activities.root, projects)
    restarted_proposal_store = CheckpointProposalStore(activities.root, projects, restarted_activity_store)
    forbidden_provider = FakeProvider()
    restarted = ProjectExploreService(project_store=projects, activity_store=restarted_activity_store,
        proposal_store=restarted_proposal_store,
        context_retriever=ProjectContextRetriever(project_store=projects, activity_store=restarted_activity_store,
            session_store=_sessions, investigation_store_root=activities.root.parent / "investigation_results"),
        provider=forbidden_provider)
    projection = restarted.read_projection(project_a["project_id"])
    assert len(projection.option_sets) == 1 and forbidden_provider.calls == 0
    assert restarted.execute(project_a["project_id"], api.ProjectExploreRequest(
        user_intent="Give me three room directions", input_refs=[], idempotency_key="room-v1")).option_set
    assert forbidden_provider.calls == 0
    assert restarted.read_projection(project_b["project_id"]).option_sets == []
    cross = client.post(f"/projects/{project_b['project_id']}/ideas/{idea_id}/disposition",
                        json={"disposition": "dismiss", "idempotency_key": "cross"})
    assert cross.status_code == 404
