"""Stage 4 - Real Conversation Integration: conversation-level integration tests, run through the
real /projects/{id}/conversation/messages endpoint and real AssistantOrchestrator.send(). Structured
Project Memory is pre-populated directly via the real ProjectMemoryStore (bypassing extraction
fakery, since this file's purpose is proving RETRIEVAL behavior, not extraction - that is Stage 2's
own test suite). Only the conversation reply provider and the memory-retrieval selection service are
fakes.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import api
from projects import (
    ProjectActivitySourceType,
    ProjectMemoryCandidate,
    ProjectMemoryCategory,
    ProjectMemoryModality,
    ProjectMemoryProgressState,
    ProjectMemoryStore,
    ProjectMemoryStoreError,
)
from projects.assistant_orchestrator import AssistantOrchestrator
from projects.conversation_store import ProjectConversationStore
from projects.memory_retrieval import MemorySelection
from projects.project_current_state import ProjectCurrentStateService
from test_project_conversation import FakeAssistantProvider
from test_response_planner_routing import create_project, routing_context  # noqa: F401


class FakeMemoryRetrievalService:
    def __init__(self):
        self.select_calls: list[dict] = []
        self.select_result: MemorySelection | None = None

    def select(self, *, question_text, prior_turns_text, subjects, records):
        self.select_calls.append({"question_text": question_text, "subjects": subjects})
        return self.select_result


class BrokenMemoryStore:
    """Simulates a Structured Project Memory read failure at retrieval time."""

    def list_records(self, project_id):
        raise ProjectMemoryStoreError("simulated storage failure")


@pytest.fixture
def memory_retrieval_conversation_context(routing_context, monkeypatch, tmp_path: Path):
    ctx = routing_context
    conversation_store = ProjectConversationStore(ctx["project_store"])
    provider = FakeAssistantProvider()
    memory_store = ProjectMemoryStore(tmp_path / "projects", ctx["project_store"])
    retrieval_service = FakeMemoryRetrievalService()
    current_state_service = ProjectCurrentStateService(salience_client=None)

    orchestrator = AssistantOrchestrator(
        project_store=ctx["project_store"],
        conversation_store=conversation_store,
        context_retriever=api._create_project_context_retriever(),
        provider=provider,
        session_store=ctx["session_store"],
        evidence_store=ctx["evidence_store"],
        investigation_trust_service=api._project_trust_service(),
        memory_store=memory_store,
        memory_retrieval_service=retrieval_service,
        current_state_service=current_state_service,
    )
    monkeypatch.setattr(api, "PROJECT_CONVERSATION_STORE", conversation_store)
    monkeypatch.setattr(api, "PROJECT_MEMORY_STORE", memory_store)
    monkeypatch.setattr(api, "_create_assistant_orchestrator", lambda: orchestrator)
    return {**ctx, "conversation_store": conversation_store, "provider": provider,
            "orchestrator": orchestrator, "memory_store": memory_store,
            "retrieval_service": retrieval_service}


def _send(client, project_id, text, key):
    return client.post(f"/projects/{project_id}/conversation/messages",
                        json={"text": text, "idempotency_key": key})


def _candidate(**overrides):
    base = dict(category=ProjectMemoryCategory.FACT, scope="overall", subject="budget",
                slot="amount", value="$1,500", modality=ProjectMemoryModality.COMMITTED)
    base.update(overrides)
    return ProjectMemoryCandidate(**base)


def test_no_memory_yet_omits_structured_memory_key(memory_retrieval_conversation_context):
    ctx = memory_retrieval_conversation_context
    project = create_project(ctx["client"])
    response = _send(ctx["client"], project["project_id"], "What was my budget?", "turn-1")
    assert response.status_code == 200
    request = ctx["provider"].requests[-1]
    assert "structured_project_memory" not in request.project_context
    assert ctx["retrieval_service"].select_calls == []


def test_deterministic_subject_question_populates_current_context(memory_retrieval_conversation_context):
    ctx = memory_retrieval_conversation_context
    project = create_project(ctx["client"])
    ctx["memory_store"].write_candidate(
        project["project_id"], _candidate(), source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    response = _send(ctx["client"], project["project_id"], "What was my budget again?", "turn-1")
    assert response.status_code == 200
    request = ctx["provider"].requests[-1]
    assert "$1,500" in request.project_context["structured_project_memory"]
    assert request.project_context["structured_project_memory"].startswith("CURRENT")
    assert ctx["retrieval_service"].select_calls == []  # deterministic match, no AI call needed

    turn = response.json()["turns"][1]
    assert turn["provider_provenance"]["memory_retrieval_intent"] == "current"
    assert turn["provider_provenance"]["memory_retrieval_subject"] == "budget"


def test_tentative_and_third_party_never_contaminate_current_context(memory_retrieval_conversation_context):
    ctx = memory_retrieval_conversation_context
    project = create_project(ctx["client"])
    ctx["memory_store"].write_candidate(
        project["project_id"], _candidate(value="$1,500"),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)
    ctx["memory_store"].write_candidate(
        project["project_id"], _candidate(value="maybe $1,750", modality=ProjectMemoryModality.TENTATIVE),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)
    ctx["memory_store"].write_candidate(
        project["project_id"], _candidate(value="$3,000 per my friend", modality=ProjectMemoryModality.THIRD_PARTY),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    response = _send(ctx["client"], project["project_id"], "What was my budget again?", "turn-1")
    context_text = ctx["provider"].requests[-1].project_context["structured_project_memory"]
    assert "$1,500" in context_text
    assert "1,750" not in context_text
    assert "3,000" not in context_text


def test_deterministic_continuation_question_uses_current_project_state(memory_retrieval_conversation_context):
    ctx = memory_retrieval_conversation_context
    project = create_project(ctx["client"])
    ctx["memory_store"].write_candidate(
        project["project_id"], _candidate(category=ProjectMemoryCategory.PROGRESS, scope="living_room",
                                           subject="rug", slot="procurement", value="ordered",
                                           progress_state=ProjectMemoryProgressState.STARTED),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    response = _send(ctx["client"], project["project_id"], "Where did we leave off?", "turn-1")
    assert response.status_code == 200
    context_text = ctx["provider"].requests[-1].project_context["structured_project_memory"]
    assert "living_room" in context_text
    assert "rug" in context_text
    assert ctx["retrieval_service"].select_calls == []

    turn = response.json()["turns"][1]
    assert turn["provider_provenance"]["memory_retrieval_intent"] == "continuation"


def test_ambiguous_question_falls_back_to_selection_service(memory_retrieval_conversation_context):
    ctx = memory_retrieval_conversation_context
    project = create_project(ctx["client"])
    ctx["memory_store"].write_candidate(
        project["project_id"], _candidate(category=ProjectMemoryCategory.DECISION, scope="living_room",
                                           subject="tv_stand", slot="disposition", value="replace with warm wood"),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    # A legitimate anaphora resolution always has SOME textual antecedent in the bounded recent
    # conversation - matching the Stage 5 repair's grounding sanity check (a selection with no
    # textual basis anywhere in question+recent-context is discarded, not trusted blindly).
    _send(ctx["client"], project["project_id"], "Are we still keeping the TV stand?", "turn-0")

    ctx["retrieval_service"].select_result = MemorySelection(
        intent="historical", scope="living_room", subject="tv_stand")
    response = _send(ctx["client"], project["project_id"], "Why did that change?", "turn-1")
    assert response.status_code == 200
    assert len(ctx["retrieval_service"].select_calls) == 1
    context_text = ctx["provider"].requests[-1].project_context["structured_project_memory"]
    assert "replace with warm wood" in context_text

    turn = response.json()["turns"][1]
    assert turn["provider_provenance"]["memory_retrieval_intent"] == "historical"
    assert turn["provider_provenance"]["memory_retrieval_subject"] == "tv_stand"


def test_selection_service_abstention_omits_structured_memory(memory_retrieval_conversation_context):
    ctx = memory_retrieval_conversation_context
    project = create_project(ctx["client"])
    ctx["memory_store"].write_candidate(
        project["project_id"], _candidate(), source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    ctx["retrieval_service"].select_result = None
    response = _send(ctx["client"], project["project_id"], "How's the weather today?", "turn-1")
    assert response.status_code == 200
    assert "structured_project_memory" not in ctx["provider"].requests[-1].project_context


def test_retrieval_failure_does_not_break_real_conversation_turn(routing_context, monkeypatch, tmp_path):
    ctx = routing_context
    conversation_store = ProjectConversationStore(ctx["project_store"])
    provider = FakeAssistantProvider()
    orchestrator = AssistantOrchestrator(
        project_store=ctx["project_store"],
        conversation_store=conversation_store,
        context_retriever=api._create_project_context_retriever(),
        provider=provider,
        session_store=ctx["session_store"],
        evidence_store=ctx["evidence_store"],
        investigation_trust_service=api._project_trust_service(),
        memory_store=BrokenMemoryStore(),
        memory_retrieval_service=FakeMemoryRetrievalService(),
    )
    monkeypatch.setattr(api, "PROJECT_CONVERSATION_STORE", conversation_store)
    monkeypatch.setattr(api, "_create_assistant_orchestrator", lambda: orchestrator)

    project = create_project(ctx["client"])
    response = _send(ctx["client"], project["project_id"], "What was my budget?", "turn-1")
    assert response.status_code == 200
    assert [t["status"] for t in response.json()["turns"]] == ["COMPLETED", "COMPLETED"]
    assert "structured_project_memory" not in provider.requests[-1].project_context
