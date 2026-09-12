"""Stage 2 - Integrated Persistent Memory Shadow Slice: conversation-level
integration tests (item 16.B: extraction orchestration, validation,
persistence, no accidental extra provider calls, failure/abstention behavior)
run through the real /projects/{id}/conversation/messages endpoint and real
AssistantOrchestrator.send(), exactly the production call path - only the
conversation reply provider and the memory-extraction provider are fakes.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import api
from projects import ProjectMemoryExtractionError, ProjectMemoryStore
from projects.conversation_store import ProjectConversationStore
from projects.assistant_orchestrator import AssistantOrchestrator
from test_project_conversation import FakeAssistantProvider
from test_response_planner_routing import create_project, routing_context  # noqa: F401


class FakeMemoryExtractionService:
    """Test double for ProjectMemoryExtractionService - lets a test declare
    exactly which candidates (or failure) a given user message should produce,
    without a real provider call, while exercising the SAME orchestration/
    validation/persistence code AssistantOrchestrator and ProjectMemoryStore
    use in production."""

    def __init__(self):
        self.calls: list[str] = []
        self.candidates_by_text: dict[str, list] = {}
        self.fail_texts: set[str] = set()

    def extract(self, user_text: str):
        self.calls.append(user_text)
        if user_text in self.fail_texts:
            raise ProjectMemoryExtractionError("fixture-forced extraction failure")
        return self.candidates_by_text.get(user_text, [])


@pytest.fixture
def memory_conversation_context(routing_context, monkeypatch, tmp_path: Path):
    ctx = routing_context
    conversation_store = ProjectConversationStore(ctx["project_store"])
    provider = FakeAssistantProvider()
    memory_store = ProjectMemoryStore(tmp_path / "projects", ctx["project_store"])
    memory_extraction_service = FakeMemoryExtractionService()

    orchestrator = AssistantOrchestrator(
        project_store=ctx["project_store"],
        conversation_store=conversation_store,
        context_retriever=api._create_project_context_retriever(),
        provider=provider,
        session_store=ctx["session_store"],
        evidence_store=ctx["evidence_store"],
        investigation_trust_service=api._project_trust_service(),
        memory_extraction_service=memory_extraction_service,
        memory_store=memory_store,
    )
    monkeypatch.setattr(api, "PROJECT_CONVERSATION_STORE", conversation_store)
    monkeypatch.setattr(api, "PROJECT_MEMORY_STORE", memory_store)
    monkeypatch.setattr(api, "_create_assistant_orchestrator", lambda: orchestrator)
    return {**ctx, "conversation_store": conversation_store, "provider": provider,
            "orchestrator": orchestrator, "memory_store": memory_store,
            "memory_extraction_service": memory_extraction_service}


def _send(client, project_id, text, key):
    return client.post(
        f"/projects/{project_id}/conversation/messages",
        json={"text": text, "idempotency_key": key},
    )


def _candidate(**overrides):
    from projects import ProjectMemoryCandidate, ProjectMemoryCategory, ProjectMemoryModality
    base = dict(category=ProjectMemoryCategory.FACT, scope="overall", subject="budget",
                slot="amount", value="$1,500", modality=ProjectMemoryModality.COMMITTED)
    base.update(overrides)
    return ProjectMemoryCandidate(**base)


def test_eligible_turn_extracts_and_shadow_persists(memory_conversation_context):
    ctx = memory_conversation_context
    project = create_project(ctx["client"])
    ctx["memory_extraction_service"].candidates_by_text["My budget is $1,500."] = [_candidate()]

    response = _send(ctx["client"], project["project_id"], "My budget is $1,500.", "msg-1")
    assert response.status_code == 200

    records = ctx["memory_store"].list_records(project["project_id"])
    assert len(records) == 1
    assert records[0].subject == "budget"
    assert records[0].source_turn_id is not None

    state_response = ctx["client"].get(f"/projects/{project['project_id']}/memory/state")
    assert state_response.status_code == 200
    assert "budget" in state_response.json()["scope_detail"]["overall"]["facts"][0]


def test_one_extraction_call_per_eligible_turn_not_more(memory_conversation_context):
    ctx = memory_conversation_context
    project = create_project(ctx["client"])
    ctx["memory_extraction_service"].candidates_by_text["We're keeping the couch."] = []

    _send(ctx["client"], project["project_id"], "We're keeping the couch.", "msg-1")
    assert ctx["memory_extraction_service"].calls == ["We're keeping the couch."]
    assert ctx["provider"].calls == 1  # the real conversation reply call - unaffected by shadow path


def test_shadow_extraction_failure_does_not_break_real_conversation_turn(memory_conversation_context):
    ctx = memory_conversation_context
    project = create_project(ctx["client"])
    ctx["memory_extraction_service"].fail_texts.add("Ambiguous aside that will fail extraction.")

    response = _send(ctx["client"], project["project_id"], "Ambiguous aside that will fail extraction.", "msg-1")
    assert response.status_code == 200
    turns = response.json()["turns"]
    assert [t["status"] for t in turns] == ["COMPLETED", "COMPLETED"]
    assert ctx["memory_store"].list_records(project["project_id"]) == []


def test_abstention_produces_no_candidates_and_no_records(memory_conversation_context):
    ctx = memory_conversation_context
    project = create_project(ctx["client"])
    ctx["memory_extraction_service"].candidates_by_text["What was my budget again?"] = []

    response = _send(ctx["client"], project["project_id"], "What was my budget again?", "msg-1")
    assert response.status_code == 200
    assert ctx["memory_store"].list_records(project["project_id"]) == []


def test_reconstructed_idempotent_replay_does_not_double_extract(memory_conversation_context):
    ctx = memory_conversation_context
    project = create_project(ctx["client"])
    ctx["memory_extraction_service"].candidates_by_text["My budget is $1,500."] = [_candidate()]

    first = _send(ctx["client"], project["project_id"], "My budget is $1,500.", "msg-1")
    second = _send(ctx["client"], project["project_id"], "My budget is $1,500.", "msg-1")
    assert first.status_code == second.status_code == 200
    assert second.json()["reconstructed"] is True
    assert ctx["memory_extraction_service"].calls == ["My budget is $1,500."]  # only the original send extracted
    assert len(ctx["memory_store"].list_records(project["project_id"])) == 1


def test_multiple_candidates_from_one_turn_all_persisted(memory_conversation_context):
    ctx = memory_conversation_context
    project = create_project(ctx["client"])
    from projects import ProjectMemoryCategory, ProjectMemoryModality
    ctx["memory_extraction_service"].candidates_by_text["I have a dog, keep the couch, budget $1,500."] = [
        _candidate(subject="budget", value="$1,500"),
        _candidate(category=ProjectMemoryCategory.DECISION, subject="couch", slot="disposition", value="keep"),
        _candidate(category=ProjectMemoryCategory.CONSTRAINT, subject="durability", value="dog owner",
                   modality=ProjectMemoryModality.COMMITTED),
    ]

    _send(ctx["client"], project["project_id"], "I have a dog, keep the couch, budget $1,500.", "msg-1")
    records = ctx["memory_store"].list_records(project["project_id"])
    assert {r.subject for r in records} == {"budget", "couch", "durability"}
