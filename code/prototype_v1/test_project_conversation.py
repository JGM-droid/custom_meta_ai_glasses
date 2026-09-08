from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import api
from investigations import (
    InvestigationEvidenceCreateRequest,
    InvestigationEvidenceType,
    InvestigationSessionStatus,
)
from projects.assistant_orchestrator import AssistantOrchestrator, MAX_PRIOR_CONVERSATION_TURNS
from projects.assistant_provider import AssistantProviderError, AssistantResponse, OpenAIAssistantProvider
from projects.conversation_store import ProjectConversationStore
from projects.project_conversation import ConversationSendRequest, ConversationTurnStatus
from test_response_planner_routing import create_project, routing_context


class FakeAssistantProvider:
    def __init__(self):
        self.calls = 0
        self.requests = []
        self.fail = False
        self.delay_seconds = 0.0
        # Phase 3A test-only stand-in for "the model decided to call the tool" - a real
        # OpenAIAssistantProvider decides this via native tool-calling inside its one call (see
        # assistant_provider.py); this fake simply lets a test declare which exact message text
        # should be treated as Explore intent, so tests stay deterministic without needing a real
        # model. Never keyword-matched in production code - only here, in a test double.
        self.explore_intent_texts: set[str] = set()

    def respond(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.fail:
            raise AssistantProviderError("fixture provider failure")
        if request.allow_explore_intent and request.user_text in self.explore_intent_texts:
            return AssistantResponse(text="", provider="fake-provider", model="fake-model",
                                      request_id="req-1", wants_explore=True)
        if request.prior_turns:
            text = f"Because the Project context says to continue next, and we previously discussed: {request.prior_turns[-1].text}"
        else:
            text = "Work on the recorded next action from the bounded Project context."
        return AssistantResponse(text=text, provider="fake-provider", model="fake-model", request_id="req-1")


@pytest.fixture
def conversation_context(routing_context, monkeypatch):
    ctx = routing_context
    store = ProjectConversationStore(ctx["project_store"])
    provider = FakeAssistantProvider()
    # Phase 3A: the SAME Explore service instance (fake-provider-backed) routing_context already
    # wires up for the legacy /ai-results path - never a second, parallel Explore construction.
    explore_service = api._create_project_explore_service()
    orchestrator = AssistantOrchestrator(
        project_store=ctx["project_store"],
        conversation_store=store,
        context_retriever=api._create_project_context_retriever(),
        provider=provider,
        session_store=ctx["session_store"],
        evidence_store=ctx["evidence_store"],
        explore_service=explore_service,
    )
    monkeypatch.setattr(api, "PROJECT_CONVERSATION_STORE", store)
    monkeypatch.setattr(api, "_create_assistant_orchestrator", lambda: orchestrator)
    return {**ctx, "conversation_store": store, "provider": provider, "orchestrator": orchestrator,
            "explore_service": explore_service}


def _send(client, project_id, text, key):
    return client.post(
        f"/projects/{project_id}/conversation/messages",
        json={"text": text, "idempotency_key": key},
    )


def test_one_primary_conversation_per_project_and_ordered_send(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    first = ctx["client"].post(f"/projects/{project['project_id']}/conversation")
    second = ctx["client"].get(f"/projects/{project['project_id']}/conversation")
    assert first.status_code == second.status_code == 200
    assert first.json()["conversation_id"] == second.json()["conversation_id"]

    sent = _send(ctx["client"], project["project_id"], "What should I work on next?", "message-1")
    assert sent.status_code == 200
    exchange = sent.json()["turns"]
    assert [item["role"] for item in exchange] == ["USER", "ASSISTANT"]
    assert [item["sequence_number"] for item in exchange] == [1, 2]
    assert all(item["status"] == "COMPLETED" for item in exchange)
    assert ctx["provider"].calls == 1

    read = ctx["client"].get(f"/projects/{project['project_id']}/conversation/turns").json()
    assert [item["turn_id"] for item in read["turns"]] == [item["turn_id"] for item in exchange]


def test_restart_reconstruction_and_follow_up_uses_bounded_prior_and_project_context(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"], goal="Ship the persistent Project assistant")
    assert _send(ctx["client"], project["project_id"], "What should I work on next?", "first").status_code == 200

    restarted_store = ProjectConversationStore(ctx["project_store"])
    restarted_provider = FakeAssistantProvider()
    restarted = AssistantOrchestrator(
        project_store=ctx["project_store"], conversation_store=restarted_store,
        context_retriever=api._create_project_context_retriever(), provider=restarted_provider,
        session_store=ctx["session_store"], evidence_store=ctx["evidence_store"],
    )
    result = restarted.send(
        project["project_id"], ConversationSendRequest(text="Why do you recommend that?", idempotency_key="follow-up"))
    assert [item.sequence_number for item in result.turns] == [3, 4]
    request = restarted_provider.requests[0]
    assert [item.role for item in request.prior_turns] == ["user", "assistant"]
    assert request.prior_turns[-1].text == "Work on the recorded next action from the bounded Project context."
    assert request.project_context["project"]["goal"] == "Ship the persistent Project assistant"
    assert "previously discussed" in result.turns[1].content_parts[0].text


def test_prior_conversation_and_project_context_are_deterministically_bounded(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    for index in range(6):
        assert _send(ctx["client"], project["project_id"], f"Message {index}", f"key-{index}").status_code == 200
    request = ctx["provider"].requests[-1]
    assert len(request.prior_turns) == MAX_PRIOR_CONVERSATION_TURNS == 8
    assert request.prior_turns[0].text == "Message 1"
    retrieval = request.project_context["retrieval"]
    assert len(request.project_context["activities"]) <= retrieval["activity_limit"]
    assert len(request.project_context["investigations"]) <= retrieval["investigation_limit"]


def test_same_key_retry_reconstructs_and_conflicting_content_is_rejected(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    first = _send(ctx["client"], project["project_id"], "Keep this stable", "same")
    retry = _send(ctx["client"], project["project_id"], "Keep this stable", "same")
    conflict = _send(ctx["client"], project["project_id"], "Different content", "same")
    assert first.status_code == retry.status_code == 200
    assert retry.json()["reconstructed"] is True
    assert first.json()["turns"] == retry.json()["turns"]
    assert ctx["provider"].calls == 1
    assert conflict.status_code == 409
    assert len(ctx["conversation_store"].load(project["project_id"]).turns) == 2


def test_concurrent_equivalent_send_converges_to_one_exchange(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    ctx["provider"].delay_seconds = 0.05
    request = ConversationSendRequest(text="Concurrent message", idempotency_key="concurrent")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: ctx["orchestrator"].send(project["project_id"], request), range(2)))
    assert results[0].turns == results[1].turns
    assert sorted(item.reconstructed for item in results) == [False, True]
    assert ctx["provider"].calls == 1
    assert len(ctx["conversation_store"].load(project["project_id"]).turns) == 2


def test_provider_failure_is_persisted_and_same_key_recovers_in_place(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    ctx["provider"].fail = True
    failed = _send(ctx["client"], project["project_id"], "Please answer", "recover")
    assert failed.status_code == 503
    persisted = ctx["conversation_store"].load(project["project_id"])
    assert len(persisted.turns) == 2
    assert persisted.turns[1].status == ConversationTurnStatus.FAILED
    original_ids = [item.turn_id for item in persisted.turns]

    ctx["provider"].fail = False
    recovered = _send(ctx["client"], project["project_id"], "Please answer", "recover")
    assert recovered.status_code == 200
    assert [item["turn_id"] for item in recovered.json()["turns"]] == original_ids
    assert len(ctx["conversation_store"].load(project["project_id"]).turns) == 2
    assert ctx["provider"].calls == 2


def test_strict_project_isolation_and_active_project_is_unchanged(conversation_context):
    ctx = conversation_context
    project_a = create_project(ctx["client"], name="Project A")
    project_b = create_project(ctx["client"], name="Project B")
    ctx["project_store"].set_active_project(project_a["project_id"])
    sent_a = _send(ctx["client"], project_a["project_id"], "Secret A context", "a")
    assert sent_a.status_code == 200
    read_b = ctx["client"].get(f"/projects/{project_b['project_id']}/conversation").json()
    assert read_b["turns"] == []
    sent_b = _send(ctx["client"], project_b["project_id"], "Message B", "b")
    assert sent_b.status_code == 200
    assert "Secret A context" not in repr(ctx["provider"].requests[-1])
    assert ctx["project_store"].get_active_project_id() == project_a["project_id"]
    assert ctx["client"].get(f"/projects/{project_b['project_id']}/conversation/turns").json()["project_id"] == project_b["project_id"]


def test_conversation_has_no_domain_side_effects_or_provider_native_persistence(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    before_project = ctx["project_store"].load_project(project["project_id"])
    before_activities = ctx["activity_store"].list_activities(project["project_id"])
    before_sessions = ctx["session_store"].list_sessions_for_project(project["project_id"])
    assert _send(ctx["client"], project["project_id"], "Read only conversation", "clean").status_code == 200
    assert ctx["project_store"].load_project(project["project_id"]) == before_project
    assert ctx["activity_store"].list_activities(project["project_id"]) == before_activities
    assert ctx["session_store"].list_sessions_for_project(project["project_id"]) == before_sessions

    path = ctx["conversation_store"]._path(project["project_id"])
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed["turns"][1]["provider_provenance"]["provider"] == "fake-provider"
    for provider_native_key in ("messages", "choices", "thread_id", "tool_calls", "response_object"):
        assert provider_native_key not in raw


def test_invalid_or_foreign_project_cannot_read_or_append(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    missing = "00000000-0000-0000-0000-000000000001"
    assert ctx["client"].get(f"/projects/{missing}/conversation").status_code == 404
    assert _send(ctx["client"], missing, "No access", "missing").status_code == 404
    assert ctx["client"].get(f"/projects/not-a-uuid/conversation").status_code == 422
    assert ctx["client"].get(f"/projects/{project['project_id']}/conversation").status_code == 200


def _attach_image(ctx, project_id: str, payload: bytes = b"safe-image-content"):
    session = ctx["session_store"].create_session(project_id=project_id, client_metadata=None)
    collecting = session.model_copy(update={
        "status": InvestigationSessionStatus.COLLECTING,
        "revision": session.revision + 1,
        "updated_at_utc": datetime.now(timezone.utc),
    })
    ctx["session_store"].save_session(collecting)
    evidence, created = ctx["evidence_store"].upload_evidence(
        session_id=collecting.session_id,
        evidence_type=InvestigationEvidenceType.IMAGE,
        raw_bytes=payload,
        mime_type="image/png",
        original_filename="safe.png",
        request=InvestigationEvidenceCreateRequest(
            source="test", filename="safe.png", mime_type="image/png", width=10, height=10,
        ),
    )
    assert created
    return collecting, evidence


def _reference(session_id: str, evidence_id: str):
    return {
        "type": "PROJECT_RESOURCE_REFERENCE",
        "resource_kind": "EVIDENCE",
        "resource_id": evidence_id,
        "relationship": "ATTACHED",
        "container_kind": "INVESTIGATION_SESSION",
        "container_id": session_id,
    }


def _send_with_evidence(client, project_id, text, key, references):
    return client.post(
        f"/projects/{project_id}/conversation/messages",
        json={"text": text, "idempotency_key": key, "evidence_refs": references},
    )


def test_multimodal_send_resolves_bytes_and_persists_reference_only(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    session, evidence = _attach_image(ctx, project["project_id"])
    evidence_before = ctx["evidence_store"].load_evidence_for_analysis(
        session_id=session.session_id, evidence_id=evidence.evidence_id)

    response = _send_with_evidence(
        ctx["client"], project["project_id"], "What is visible?", "image-1",
        [_reference(session.session_id, evidence.evidence_id)],
    )
    assert response.status_code == 200
    request = ctx["provider"].requests[-1]
    assert len(request.images) == 1
    assert request.images[0].evidence_id == evidence.evidence_id
    assert request.images[0].image_bytes == b"safe-image-content"
    persisted = ctx["conversation_store"].load(project["project_id"])
    assert [item.type for item in persisted.turns[0].content_parts] == ["TEXT", "PROJECT_RESOURCE_REFERENCE"]
    raw = ctx["conversation_store"]._path(project["project_id"]).read_text(encoding="utf-8")
    assert "safe-image-content" not in raw
    assert ctx["evidence_store"].load_evidence_for_analysis(
        session_id=session.session_id, evidence_id=evidence.evidence_id) == evidence_before


def test_restart_text_follow_up_uses_prior_exchange_without_resending_image(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    session, evidence = _attach_image(ctx, project["project_id"])
    assert _send_with_evidence(
        ctx["client"], project["project_id"], "Describe this image", "visual",
        [_reference(session.session_id, evidence.evidence_id)],
    ).status_code == 200
    restarted_provider = FakeAssistantProvider()
    restarted = AssistantOrchestrator(
        project_store=ctx["project_store"],
        conversation_store=ProjectConversationStore(ctx["project_store"]),
        context_retriever=api._create_project_context_retriever(),
        provider=restarted_provider,
        session_store=ctx["session_store"],
        evidence_store=ctx["evidence_store"],
    )
    restarted.send(project["project_id"], ConversationSendRequest(
        text="Why is that relevant?", idempotency_key="follow"))
    follow_up = restarted_provider.requests[0]
    assert len(follow_up.prior_turns) == 2
    assert follow_up.prior_turns[0].text == "Describe this image"
    assert follow_up.images == ()


def test_multimodal_evidence_is_strictly_project_scoped_and_available(conversation_context):
    ctx = conversation_context
    project_a = create_project(ctx["client"], name="A")
    project_b = create_project(ctx["client"], name="B")
    session_a, evidence_a = _attach_image(ctx, project_a["project_id"])
    foreign = _send_with_evidence(
        ctx["client"], project_b["project_id"], "Inspect", "foreign",
        [_reference(session_a.session_id, evidence_a.evidence_id)],
    )
    missing = _send_with_evidence(
        ctx["client"], project_a["project_id"], "Inspect", "missing",
        [_reference(session_a.session_id, "00000000-0000-0000-0000-000000000001")],
    )
    assert foreign.status_code == missing.status_code == 422
    assert ctx["provider"].calls == 0
    assert ctx["conversation_store"].create_or_load(project_b["project_id"]).turns == []


def test_multimodal_idempotency_conflict_and_concurrency(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    session, evidence = _attach_image(ctx, project["project_id"])
    ref = _reference(session.session_id, evidence.evidence_id)
    request = ConversationSendRequest.model_validate({
        "text": "Inspect", "idempotency_key": "same-image", "evidence_refs": [ref],
    })
    ctx["provider"].delay_seconds = 0.05
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: ctx["orchestrator"].send(project["project_id"], request), range(2)))
    assert sorted(item.reconstructed for item in results) == [False, True]
    assert ctx["provider"].calls == 1
    conflict = _send_with_evidence(ctx["client"], project["project_id"], "Inspect", "same-image", [])
    assert conflict.status_code == 409


def test_completed_multimodal_retry_does_not_reresolve_unavailable_evidence(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    session, evidence = _attach_image(ctx, project["project_id"])
    reference = _reference(session.session_id, evidence.evidence_id)
    first = _send_with_evidence(
        ctx["client"], project["project_id"], "Inspect", "stable-completed", [reference])
    assert first.status_code == 200
    _, payload_path = ctx["evidence_store"].load_evidence_content(
        session_id=session.session_id, evidence_id=evidence.evidence_id)
    payload_path.unlink()
    retry = _send_with_evidence(
        ctx["client"], project["project_id"], "Inspect", "stable-completed", [reference])
    assert retry.status_code == 200
    assert retry.json()["reconstructed"] is True
    assert retry.json()["turns"] == first.json()["turns"]
    assert ctx["provider"].calls == 1


def test_multimodal_provider_failure_preserves_evidence_and_recovers(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    session, evidence = _attach_image(ctx, project["project_id"])
    reference = _reference(session.session_id, evidence.evidence_id)
    evidence_before = ctx["evidence_store"].load_evidence_for_analysis(
        session_id=session.session_id, evidence_id=evidence.evidence_id)
    ctx["provider"].fail = True
    failed = _send_with_evidence(
        ctx["client"], project["project_id"], "Inspect", "recover-image", [reference])
    assert failed.status_code == 503
    assert ctx["conversation_store"].load(project["project_id"]).turns[1].status == ConversationTurnStatus.FAILED
    ctx["provider"].fail = False
    recovered = _send_with_evidence(
        ctx["client"], project["project_id"], "Inspect", "recover-image", [reference])
    assert recovered.status_code == 200
    assert len(ctx["conversation_store"].load(project["project_id"]).turns) == 2
    assert ctx["evidence_store"].load_evidence_for_analysis(
        session_id=session.session_id, evidence_id=evidence.evidence_id) == evidence_before


def test_openai_adapter_translates_canonical_image_only_at_edge():
    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            message = type("Message", (), {"content": "I see the safe image."})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"id": "openai-response", "choices": [choice]})()

    client = type("Client", (), {
        "chat": type("Chat", (), {"completions": Completions()})(),
    })()
    provider = OpenAIAssistantProvider(
        api_key="test", model="test-model", client_factory=lambda **_: client)
    from projects.assistant_provider import AssistantImageInput, AssistantRequest
    result = provider.respond(AssistantRequest(
        user_text="Inspect", project_context={"project": {"name": "Safe"}}, prior_turns=(),
        images=(AssistantImageInput(evidence_id="e", media_type="image/png", image_bytes=b"abc"),),
    ))
    assert result.text == "I see the safe image."
    content = captured["messages"][1]["content"]
    assert [item["type"] for item in content] == ["text", "image_url"]
    assert content[1]["image_url"]["url"] == "data:image/png;base64,YWJj"


# --- Phase 3A: Conversation -> Explore bridge ---
#
# ADR-061 Phase 3A: the existing Explore capability (ProjectExploreService/FakeExploreProvider,
# the SAME instance routing_context already wires for the legacy /ai-results path) is reused
# directly from AssistantOrchestrator.send() via one native-tool-calling signal on the SAME single
# conversation provider call - never a second classification call, never keyword matching in
# production code, never a second Explore implementation.

def test_openai_adapter_only_advertises_the_explore_tool_when_allowed_and_parses_tool_call():
    from projects.assistant_provider import AssistantRequest

    def make_client(message):
        choice = type("Choice", (), {"message": message})()
        response = type("Response", (), {"id": "openai-response", "choices": [choice]})()
        captured = {}

        class Completions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return response

        client = type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
        return client, captured

    # No tool advertised at all when the orchestrator says Explore isn't wired up.
    text_message = type("Message", (), {"content": "Just a plain answer.", "tool_calls": None})()
    client, captured = make_client(text_message)
    provider = OpenAIAssistantProvider(api_key="test", model="test-model", client_factory=lambda **_: client)
    result = provider.respond(AssistantRequest(
        user_text="How's it going?", project_context={}, prior_turns=(), allow_explore_intent=False))
    assert "tools" not in captured
    assert result.wants_explore is False
    assert result.text == "Just a plain answer."

    # Tool advertised and a tool_call response is translated to wants_explore, never leaking the
    # OpenAI-native tool_call shape into AssistantResponse.
    function = type("Function", (), {"name": "propose_project_ideas", "arguments": "{}"})()
    tool_call = type("ToolCall", (), {"function": function})()
    tool_message = type("Message", (), {"content": None, "tool_calls": [tool_call]})()
    client, captured = make_client(tool_message)
    provider = OpenAIAssistantProvider(api_key="test", model="test-model", client_factory=lambda **_: client)
    result = provider.respond(AssistantRequest(
        user_text="Give me ideas", project_context={}, prior_turns=(), allow_explore_intent=True))
    assert captured["tools"][0]["function"]["name"] == "propose_project_ideas"
    assert result.wants_explore is True
    assert result.text == ""


def test_ordinary_conversation_never_touches_explore_service(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    sent = _send(ctx["client"], project["project_id"], "What should I work on next?", "plain-1")
    assert sent.status_code == 200
    assert ctx["explore_provider"].calls == 0
    turns = sent.json()["turns"]
    assert turns[1]["content_parts"][0]["type"] == "TEXT"
    assert len(turns[1]["content_parts"]) == 1


def test_explore_intent_reaches_explore_service_exactly_once(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    ctx["provider"].explore_intent_texts.add("I want to replace this dresser. Give me some ideas.")
    sent = _send(
        ctx["client"], project["project_id"],
        "I want to replace this dresser. Give me some ideas.", "explore-1")
    assert sent.status_code == 200
    assert ctx["explore_provider"].calls == 1
    turns = sent.json()["turns"]
    assistant_text = turns[1]["content_parts"][0]["text"]
    for expected in ("Warm Modern", "Dark Contemporary", "Minimal Natural"):
        assert expected in assistant_text
    assert "EXPLORE_PLAN" not in assistant_text
    assert "response family" not in assistant_text.lower()


def test_explore_result_is_referenced_from_the_conversation_turn(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    ctx["provider"].explore_intent_texts.add("ideas please")
    sent = _send(ctx["client"], project["project_id"], "ideas please", "explore-ref-1")
    assert sent.status_code == 200
    persisted = ctx["conversation_store"].load(project["project_id"])
    assistant_turn = persisted.turns[1]
    part_types = [item.type for item in assistant_turn.content_parts]
    assert part_types == ["TEXT", "EXPLORE_REFERENCE"]
    interaction_id = assistant_turn.content_parts[1].interaction_id
    ideas = [a for a in ctx["activity_store"].list_activities(project["project_id"])
             if (a.metadata or {}).get("interaction_id") == interaction_id
             and a.activity_type.value == "idea"]
    assert len(ideas) == 3


def test_explore_bridge_preserves_project_isolation(conversation_context):
    ctx = conversation_context
    project_a = create_project(ctx["client"], name="Project A")
    project_b = create_project(ctx["client"], name="Project B")
    ctx["provider"].explore_intent_texts.add("ideas please")
    sent = _send(ctx["client"], project_a["project_id"], "ideas please", "explore-iso-1")
    assert sent.status_code == 200
    assert ctx["explore_provider"].last_context_pack.project_id == project_a["project_id"]
    b_ideas = [a for a in ctx["activity_store"].list_activities(project_b["project_id"])
               if a.activity_type.value == "idea"]
    assert b_ideas == []


def test_explore_bridge_forwards_attached_evidence_image(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    session, evidence = _attach_image(ctx, project["project_id"])
    ctx["provider"].explore_intent_texts.add("ideas about this photo")
    sent = _send_with_evidence(
        ctx["client"], project["project_id"], "ideas about this photo", "explore-img-1",
        [_reference(session.session_id, evidence.evidence_id)],
    )
    assert sent.status_code == 200
    assert len(ctx["explore_provider"].last_image_evidence) == 1
    forwarded = ctx["explore_provider"].last_image_evidence[0]
    assert forwarded.evidence_id == evidence.evidence_id
    assert forwarded.image_bytes == b"safe-image-content"


def test_reload_after_explore_preserves_conversation(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    ctx["provider"].explore_intent_texts.add("ideas please")
    sent = _send(ctx["client"], project["project_id"], "ideas please", "explore-reload-1")
    assert sent.status_code == 200
    reloaded = ctx["client"].get(f"/projects/{project['project_id']}/conversation")
    assert reloaded.status_code == 200
    assert reloaded.json()["turns"] == sent.json()["turns"]


def test_explore_retry_with_same_idempotency_key_does_not_duplicate(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    ctx["provider"].explore_intent_texts.add("ideas please")
    key = "explore-retry-1"
    first = _send(ctx["client"], project["project_id"], "ideas please", key)
    second = _send(ctx["client"], project["project_id"], "ideas please", key)
    assert first.status_code == second.status_code == 200
    assert second.json()["reconstructed"] is True
    assert ctx["provider"].calls == 1
    assert ctx["explore_provider"].calls == 1
    assert len(ctx["conversation_store"].load(project["project_id"]).turns) == 2
    ideas = [a for a in ctx["activity_store"].list_activities(project["project_id"])
             if a.activity_type.value == "idea"]
    assert len(ideas) == 3


def test_explore_generation_alone_does_not_mutate_project_or_create_proposal(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    before_revision = ctx["project_store"].load_project(project["project_id"]).revision
    ctx["provider"].explore_intent_texts.add("ideas please")
    sent = _send(ctx["client"], project["project_id"], "ideas please", "explore-mutation-1")
    assert sent.status_code == 200
    after_revision = ctx["project_store"].load_project(project["project_id"]).revision
    assert after_revision == before_revision
    ideas = [a for a in ctx["activity_store"].list_activities(project["project_id"])
             if a.activity_type.value == "idea"]
    assert all(a.confirmation_status.value == "inferred" for a in ideas)
    assert ctx["client"].get(f"/projects/{project['project_id']}/checkpoint-proposals").json() == []


def test_explore_ideas_created_from_conversation_remain_dispositionable(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    ctx["provider"].explore_intent_texts.add("ideas please")
    sent = _send(ctx["client"], project["project_id"], "ideas please", "explore-disposition-1")
    assert sent.status_code == 200
    ideas = sorted(
        (a for a in ctx["activity_store"].list_activities(project["project_id"]) if a.activity_type.value == "idea"),
        key=lambda a: (a.metadata or {}).get("option_ordinal"),
    )
    first_idea = ideas[0]
    disposed = ctx["client"].post(
        f"/projects/{project['project_id']}/ideas/{first_idea.activity_id}/disposition",
        json={"disposition": "keep", "idempotency_key": "keep-1"},
    )
    assert disposed.status_code == 200


def test_no_provider_native_structures_persisted_from_explore_bridge(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    ctx["provider"].explore_intent_texts.add("ideas please")
    sent = _send(ctx["client"], project["project_id"], "ideas please", "explore-native-1")
    assert sent.status_code == 200
    raw_conversation = ctx["conversation_store"]._path(project["project_id"]).read_text(encoding="utf-8")
    for forbidden in ("tool_calls", "function_call", "chat.completion", "\"choices\""):
        assert forbidden not in raw_conversation


# --- Architect review correction: provider-boundary contract violation ---
#
# A conforming AssistantProvider must never set wants_explore=True unless the orchestrator itself
# requested it via allow_explore_intent (which only happens when explore_service is configured).
# A rogue/non-conformant provider implementation ignoring that must never be allowed to fall
# through into an empty completed ConversationTextPart, execute Explore, or mutate Project Memory.

class _RogueAlwaysExploreProvider:
    """Ignores allow_explore_intent entirely - simulates a non-conformant AssistantProvider (or a
    genuine model hallucination producing a tool_call the orchestrator never advertised)."""

    def __init__(self):
        self.calls = 0

    def respond(self, request):
        self.calls += 1
        return AssistantResponse(text="", provider="rogue", model="rogue-model", wants_explore=True)


def test_wants_explore_without_an_explore_service_fails_the_turn_and_never_executes_explore(routing_context):
    ctx = routing_context
    store = ProjectConversationStore(ctx["project_store"])
    rogue_provider = _RogueAlwaysExploreProvider()
    # Deliberately no explore_service - the exact contract violation this correction closes.
    orchestrator = AssistantOrchestrator(
        project_store=ctx["project_store"],
        conversation_store=store,
        context_retriever=api._create_project_context_retriever(),
        provider=rogue_provider,
        session_store=ctx["session_store"],
        evidence_store=ctx["evidence_store"],
    )
    project = create_project(ctx["client"])
    before_revision = ctx["project_store"].load_project(project["project_id"]).revision

    with pytest.raises(AssistantProviderError):
        orchestrator.send(project["project_id"], ConversationSendRequest(
            text="ideas please", idempotency_key="rogue-1"))

    assert rogue_provider.calls == 1
    persisted = store.load(project["project_id"])
    assert len(persisted.turns) == 2
    assistant_turn = persisted.turns[1]
    assert assistant_turn.status == ConversationTurnStatus.FAILED
    assert assistant_turn.failure_category == "provider_failure"
    # Never an empty completed turn - the FAILED turn's own text part is non-empty and user-facing.
    assert len(assistant_turn.content_parts) == 1
    assert assistant_turn.content_parts[0].text
    # Never executed Explore, never mutated Project Memory.
    assert ctx["explore_provider"].calls == 0
    ideas = [a for a in ctx["activity_store"].list_activities(project["project_id"]) if a.activity_type.value == "idea"]
    assert ideas == []
    assert ctx["project_store"].load_project(project["project_id"]).revision == before_revision


# --- Architect review correction: ProjectExploreError endpoint mapping ---
#
# The conversation send endpoint previously had no except clause for ProjectExploreError (raised
# by AssistantOrchestrator._run_explore_bridge after it already marks the assistant turn FAILED
# with failure_category="explore_failure") - it would have fallen through to an unhandled 500
# rather than the clean, categorized response every other conversation failure gets.

def test_explore_execution_failure_maps_to_a_clean_categorized_response(conversation_context):
    ctx = conversation_context
    project = create_project(ctx["client"])
    before_revision = ctx["project_store"].load_project(project["project_id"]).revision
    ctx["provider"].explore_intent_texts.add("ideas please")
    # Real ProjectExploreError subtype, exactly as a genuinely unavailable Explore provider would
    # raise it - no fake/mocked exception type.
    ctx["explore_service"].provider = None

    response = _send(ctx["client"], project["project_id"], "ideas please", "explore-endpoint-fail-1")

    assert response.status_code == 503
    body = response.json()["detail"]
    assert body["category"] == "conversation_explore_unavailable"
    # Never a raw internal/provider exception string leaked to the client.
    assert "ProjectExploreProviderUnavailable" not in body["message"]
    assert "Traceback" not in body["message"]

    persisted = ctx["conversation_store"].load(project["project_id"])
    assert len(persisted.turns) == 2
    assistant_turn = persisted.turns[1]
    assert assistant_turn.status == ConversationTurnStatus.FAILED
    assert assistant_turn.failure_category == "explore_failure"
    assert len(assistant_turn.content_parts) == 1
    assert assistant_turn.content_parts[0].text

    assert ctx["explore_provider"].calls == 0
    ideas = [a for a in ctx["activity_store"].list_activities(project["project_id"]) if a.activity_type.value == "idea"]
    assert ideas == []
    assert ctx["project_store"].load_project(project["project_id"]).revision == before_revision

    # Retrying with the same idempotency_key after the underlying failure is resolved must not
    # duplicate anything - the failed turn is reused, not doubled.
    ctx["explore_service"].provider = ctx["explore_provider"]
    recovered = _send(ctx["client"], project["project_id"], "ideas please", "explore-endpoint-fail-1")
    assert recovered.status_code == 200
    assert ctx["explore_provider"].calls == 1
    assert len(ctx["conversation_store"].load(project["project_id"]).turns) == 2
