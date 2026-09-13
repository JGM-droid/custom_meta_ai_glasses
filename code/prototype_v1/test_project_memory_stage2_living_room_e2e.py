"""Stage 2 - Integrated Persistent Memory Shadow Slice: the realistic
acceptance scenario (item 14), run through the REAL backend - real
ProjectStore, real ProjectConversationStore, real AssistantOrchestrator.send(),
real ProjectMemoryExtractionService (real OpenAI calls), real
ProjectMemoryStore, real ProjectCurrentStateService. Only the conversation
REPLY provider is fake (FakeAssistantProvider) - what is under test here is
the shadow memory pipeline, not the assistant's prose, and using a fake reply
provider keeps provider-call-count accounting exact (item 17) by producing
only the extraction calls this test explicitly wants to count. Skipped
automatically if no OPENAI_API_KEY is configured.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import api
from projects import (
    ProjectActivityStore,
    ProjectContextRetriever,
    ProjectCurrentStateService,
    ProjectMemoryExtractionService,
    ProjectMemoryModality,
    ProjectMemoryStore,
    ProjectStore,
)
from projects.assistant_orchestrator import AssistantOrchestrator
from projects.conversation_store import ProjectConversationStore
from projects.project_current_state import build_scope_state
from test_project_conversation import FakeAssistantProvider

_API_KEY = api._load_openai_api_key()

pytestmark = pytest.mark.skipif(not _API_KEY, reason="OPENAI_API_KEY not configured")

# The exact 12-turn script from the task specification.
_TURNS = [
    "I want the room warm, not stark white.",
    "My budget is around $1,500.",
    "We're keeping the couch.",
    "I have a dog, so durability matters.",
    "Let's keep the TV stand.",
    "Actually, let's replace the TV stand with something warm wood.",
    "I ordered the rug.",
    "The rug arrived.",
    "I was thinking maybe $1,750, but I'm not sure.",
    "My friend thinks I should spend $3,000.",
    "If I changed the couch someday, maybe I'd go lighter.",
    "Actually, we don't need to replace the TV stand anymore.",
]


@pytest.fixture
def living_room_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    projects_root = tmp_path / "projects"
    project_store = ProjectStore(projects_root)
    activity_store = ProjectActivityStore(projects_root, project_store)
    conversation_store = ProjectConversationStore(project_store)
    memory_store = ProjectMemoryStore(projects_root, project_store)
    session_store = api.InvestigationSessionStore(tmp_path / "investigation_sessions")
    evidence_store = api.InvestigationEvidenceStore(session_store)
    # Built directly from this fixture's OWN stores - api._create_project_context_retriever()
    # reads the api module's global PROJECT_STORE/PROJECT_ACTIVITY_STORE/SESSION_STORE at call
    # time, so calling it here (before those globals are monkeypatched below) would silently wire
    # the orchestrator to the real production project store instead of this test's tmp_path one.
    context_retriever = ProjectContextRetriever(
        project_store=project_store, activity_store=activity_store, session_store=session_store,
        investigation_store_root=tmp_path / "investigations",
    )
    extraction_service = ProjectMemoryExtractionService(api_key=_API_KEY)
    reply_provider = FakeAssistantProvider()

    orchestrator = AssistantOrchestrator(
        project_store=project_store,
        conversation_store=conversation_store,
        context_retriever=context_retriever,
        provider=reply_provider,
        session_store=session_store,
        evidence_store=evidence_store,
        investigation_trust_service=api._project_trust_service(),
        memory_extraction_service=extraction_service,
        memory_store=memory_store,
    )
    monkeypatch.setattr(api, "PROJECT_STORE", project_store)
    monkeypatch.setattr(api, "PROJECT_ACTIVITY_STORE", activity_store)
    monkeypatch.setattr(api, "PROJECT_CONVERSATION_STORE", conversation_store)
    monkeypatch.setattr(api, "PROJECT_MEMORY_STORE", memory_store)
    monkeypatch.setattr(api, "SESSION_STORE", session_store)
    monkeypatch.setattr(api, "EVIDENCE_STORE", evidence_store)
    monkeypatch.setattr(api, "_create_assistant_orchestrator", lambda: orchestrator)

    from fastapi.testclient import TestClient
    client = TestClient(api.app)
    return {"client": client, "project_store": project_store, "memory_store": memory_store,
            "extraction_service": extraction_service, "reply_provider": reply_provider}


def _run_scenario(ctx):
    project_response = ctx["client"].post(
        "/projects", json={"name": "Living Room Redesign", "goal": "Warm up the living room on a budget"})
    assert project_response.status_code == 201
    project_id = project_response.json()["project_id"]

    for i, text in enumerate(_TURNS):
        response = ctx["client"].post(
            f"/projects/{project_id}/conversation/messages",
            json={"text": text, "idempotency_key": f"turn-{i}"},
        )
        assert response.status_code == 200, f"turn {i} ({text!r}) failed: {response.text}"

    return project_id


def test_living_room_scenario_current_truth(living_room_backend):
    ctx = living_room_backend
    project_id = _run_scenario(ctx)

    records = ctx["memory_store"].list_records(project_id)

    service = ProjectCurrentStateService()
    overall = service.get_current_state(project_id, records)

    def _all_summaries(state):
        out = list(state.scope_summaries) + list(state.global_blockers) + list(state.recent_changes)
        for detail in state.scope_detail.values():
            out += (detail.facts + detail.decisions + detail.blockers + detail.active_progress
                    + detail.pending_decisions + detail.recently_completed + detail.recent_changes)
        return out

    everything = " | ".join(_all_summaries(overall))

    # Style: warm/not stark white present.
    assert "warm" in everything.lower()

    # Budget: current committed truth is ~$1,500, NOT $1,750 and NOT $3,000.
    committed_budget_records = [
        r for r in records if r.subject == "budget" and r.status.value == "current"
        and r.modality == ProjectMemoryModality.COMMITTED
    ]
    assert len(committed_budget_records) == 1
    assert "1,500" in committed_budget_records[0].value or "1500" in committed_budget_records[0].value
    assert "1,750" not in committed_budget_records[0].value
    assert "3,000" not in committed_budget_records[0].value

    # Couch: keep, and durability/dog constraint present.
    assert "couch" in everything.lower()
    assert "dog" in everything.lower() or "durab" in everything.lower()

    # TV stand: current truth on the "disposition" slot is "no longer needs replacement," with the
    # original "keep" superseded (not deleted) underneath - the "material" slot (warm wood) is a
    # separate fact the extractor tracks independently, since it recorded "replace with warm wood"
    # as a material preference rather than folding it into a disposition update (see the Stage 2
    # report's known-limitations section on slot-splitting for compound statements).
    tv_stand_records = sorted(
        [r for r in records if r.subject == "tv_stand"], key=lambda r: r.occurred_at_utc)
    assert len(tv_stand_records) >= 2
    disposition_records = [r for r in tv_stand_records if r.slot == "disposition"]
    assert len(disposition_records) >= 2  # original "keep" plus the final correction
    current_disposition = [r for r in disposition_records if r.status.value == "current"]
    assert len(current_disposition) == 1
    final_value = current_disposition[0].value.lower()
    assert any(kw in final_value for kw in
               ("no longer", "cancel", "not ", "don't", "do not", "no replacement", "no need", "keep"))
    superseded_disposition = [r for r in disposition_records if r.status.value == "superseded"]
    assert len(superseded_disposition) >= 1  # history preserved, not deleted

    # Rug: delivered/arrived, with ordered -> delivered history preserved (both events kept,
    # progress is append-only).
    rug_records = [r for r in records if r.subject == "rug"]
    assert len(rug_records) >= 2
    assert any("order" in r.value.lower() for r in rug_records)
    assert any("arriv" in r.value.lower() or "deliver" in r.value.lower() for r in rug_records)


def test_living_room_scoped_view_derives_from_same_canonical_records(living_room_backend):
    ctx = living_room_backend
    project_id = _run_scenario(ctx)
    records = ctx["memory_store"].list_records(project_id)

    # The real extractor split this scenario across two scopes on its own: Project-general
    # standing facts (budget/style/durability) under "overall", and item-level decisions/progress
    # (couch/tv_stand/rug) under "living_room" - both must derive from the SAME canonical record
    # list, never a separate per-scope store.
    known_scopes = {r.scope for r in records}
    assert "overall" in known_scopes
    assert "living_room" in known_scopes

    service = ProjectCurrentStateService()
    overall = service.get_current_state(project_id, records)
    for scope in known_scopes:
        scoped = service.get_current_state(project_id, records, scope=scope)
        if scope in overall.scope_detail:
            assert scoped.scope_detail[scope].facts == overall.scope_detail[scope].facts
            assert scoped.scope_detail[scope].decisions == overall.scope_detail[scope].decisions
        # Whether or not a scope was salience-selected into the global view, the scoped lookup
        # itself always derives straight from `records` - the same canonical substrate.
        assert scoped.scope_detail[scope] == build_scope_state(records, scope)


def test_living_room_scenario_provider_call_count(living_room_backend):
    ctx = living_room_backend
    calls = {"count": 0}
    real_extract = ctx["extraction_service"].extract

    def counting_extract(text, known_subjects=None):
        calls["count"] += 1
        return real_extract(text, known_subjects)

    ctx["extraction_service"].extract = counting_extract
    _run_scenario(ctx)

    # Exactly one extraction call per turn - no multi-step agent loop, no extra classification call.
    assert calls["count"] == len(_TURNS)
    # The conversation reply itself never calls a real provider in this test (fake reply provider).
    assert ctx["reply_provider"].calls == len(_TURNS)
