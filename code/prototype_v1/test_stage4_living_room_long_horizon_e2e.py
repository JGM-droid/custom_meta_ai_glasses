"""Stage 4 - Real Conversation Integration: THE realistic long-horizon acceptance scenario (items
12-15). Real backend throughout: real ProjectStore/InvestigationSessionStore/
InvestigationEvidenceStore/ProjectConversationStore/ProjectMemoryStore, real
AssistantOrchestrator.send(), real Stage 2 extraction, real Stage 3 visual continuity, real Stage 4
memory retrieval.

Two-phase design, to keep real-provider usage proportionate to what each phase actually needs to
prove (see the "Provider call discipline" requirement): the ~20-turn SETUP phase (building up
Project history) uses a FAKE conversation-reply provider - extraction/description generation still
fire for REAL regardless of what the assistant "says" back, since they trigger on the USER's own
turn text, not the reply - so the memory/Evidence state this phase builds is completely real. The
13 GRADED final questions, asked after a genuine leave/return (a brand-new orchestrator instance,
fresh store objects re-reading the same persisted files - no in-process state carries over), use the
REAL conversation provider, since the acceptance criteria are about the actual natural-language
answers, not just internal retrieval correctness (already covered separately by the unit and
fake-provider suites).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import api
from investigations import (
    InvestigationEvidenceCreateRequest,
    InvestigationEvidenceStore,
    InvestigationEvidenceType,
    InvestigationSessionStatus,
    InvestigationSessionStore,
)
from projects import (
    ProjectActivityStore,
    ProjectContextRetriever,
    ProjectCurrentStateService,
    ProjectMemoryExtractionService,
    ProjectMemoryModality,
    ProjectMemoryRetrievalService,
    ProjectMemoryStatus,
    ProjectMemoryStore,
    ProjectStore,
    VisualEvidenceContinuityService,
)
from projects.assistant_orchestrator import AssistantOrchestrator, MAX_PRIOR_CONVERSATION_TURNS
from projects.assistant_provider import OpenAIAssistantProvider
from projects.conversation_store import ProjectConversationStore
from test_project_conversation import FakeAssistantProvider
from test_visual_evidence_stage3_living_room_e2e import _generate_room_image

_API_KEY = api._load_openai_api_key()

pytestmark = pytest.mark.skipif(not _API_KEY, reason="OPENAI_API_KEY not configured")


def _build_stores(tmp_path: Path):
    projects_root = tmp_path / "projects"
    project_store = ProjectStore(projects_root)
    activity_store = ProjectActivityStore(projects_root, project_store)
    conversation_store = ProjectConversationStore(project_store)
    session_store = InvestigationSessionStore(tmp_path / "sessions")
    evidence_store = InvestigationEvidenceStore(session_store)
    memory_store = ProjectMemoryStore(projects_root, project_store)
    context_retriever = ProjectContextRetriever(
        project_store=project_store, activity_store=activity_store, session_store=session_store,
        investigation_store_root=tmp_path / "investigations",
    )
    return {
        "project_store": project_store, "activity_store": activity_store,
        "conversation_store": conversation_store, "session_store": session_store,
        "evidence_store": evidence_store, "memory_store": memory_store,
        "context_retriever": context_retriever,
    }


class _CountingWrapper:
    """Wraps a real service, counting calls to named methods without altering behavior."""

    def __init__(self, real, counters: dict, *, prefix: str, methods: tuple[str, ...]):
        self._real = real
        for name in methods:
            counters.setdefault(f"{prefix}.{name}", 0)
            setattr(self, name, self._make_counted(name, counters, prefix))

    def _make_counted(self, name, counters, prefix):
        real_method = getattr(self._real, name)

        def _wrapped(*args, **kwargs):
            counters[f"{prefix}.{name}"] += 1
            return real_method(*args, **kwargs)
        return _wrapped


def _build_orchestrator(stores, *, reply_provider, real_calls: bool, call_counters: dict | None = None):
    extraction_service = ProjectMemoryExtractionService(api_key=_API_KEY) if real_calls else None
    visual_service = VisualEvidenceContinuityService(api_key=_API_KEY) if real_calls else None
    retrieval_service = ProjectMemoryRetrievalService(api_key=_API_KEY) if real_calls else None
    current_state_service = ProjectCurrentStateService(salience_client=None)
    if call_counters is not None:
        if extraction_service is not None:
            extraction_service = _CountingWrapper(
                extraction_service, call_counters, prefix="extraction", methods=("extract",))
        if visual_service is not None:
            visual_service = _CountingWrapper(
                visual_service, call_counters, prefix="visual", methods=("describe", "select"))
        if retrieval_service is not None:
            retrieval_service = _CountingWrapper(
                retrieval_service, call_counters, prefix="memory_retrieval", methods=("select",))
    return AssistantOrchestrator(
        project_store=stores["project_store"],
        conversation_store=stores["conversation_store"],
        context_retriever=stores["context_retriever"],
        provider=reply_provider,
        session_store=stores["session_store"],
        evidence_store=stores["evidence_store"],
        memory_extraction_service=extraction_service,
        memory_store=stores["memory_store"],
        visual_evidence_service=visual_service,
        memory_retrieval_service=retrieval_service,
        current_state_service=current_state_service,
    )


def _reference(session_id: str, evidence_id: str) -> dict:
    return {
        "type": "PROJECT_RESOURCE_REFERENCE", "resource_kind": "EVIDENCE", "resource_id": evidence_id,
        "relationship": "ATTACHED", "container_kind": "INVESTIGATION_SESSION", "container_id": session_id,
    }


_SETUP_TURNS = [
    # (text, evidence_refs_or_None)
    ("What do you think of this room?", "EVIDENCE"),
    ("I want it warm, not stark white.", None),
    ("My budget is around $1,500.", None),
    ("We're keeping the couch.", None),
    ("I have a dog, so durability matters.", None),
    ("Let's keep the TV stand.", None),
    ("Actually, let's replace the TV stand with something warm wood.", None),
    ("I ordered the rug.", None),
    ("The rug arrived.", None),
    ("I finished painting the wall.", None),
    ("There's a wiring issue behind the wall that's blocking the electrician from finishing.", None),
    ("We still need to fix the outlet near the window.", None),
    ("Maybe I could stretch the budget to $1,750, I'm not sure.", None),
    ("My friend thinks I should spend $3,000.", None),
    ("Someday I might replace the couch with a lighter one.", None),
    ("What's the weather usually like for painting projects?", None),
    ("Do you have any general tips for choosing curtains?", None),
    ("I'm also thinking about repainting the hallway sometime.", None),
    ("What's a good way to protect hardwood floors during a renovation?", None),
    ("Any general tips for keeping a work site clean?", None),
    ("I saw a nice lamp at the store today.", None),
    ("How long does paint usually take to fully cure?", None),
    ("What's a reasonable overall timeline for a project like this?", None),
]

_FINAL_QUESTIONS = [
    "Where did we leave off?",
    "What was my budget again?",
    "What constraints should we keep in mind?",
    "Are we still keeping the TV stand?",
    "What did we originally decide about the TV stand?",
    "Why did that change?",
    "What have I already completed?",
    "What still needs to be done?",
    "What should I do next?",
    "Is anything blocking the project?",
    "What did the living room look like?",
    "Would blue work in this room?",
    ("In the photo I sent of the room, there's a small tag on the corner of the pillow. "
     "What two characters are printed on that tag?"),
]


@pytest.fixture
def long_horizon_scenario(tmp_path: Path):
    stores = _build_stores(tmp_path)
    fake_provider = FakeAssistantProvider()
    setup_call_counters: dict = {}
    setup_orchestrator = _build_orchestrator(
        stores, reply_provider=fake_provider, real_calls=True, call_counters=setup_call_counters)

    project = stores["project_store"].create_project(
        name="Living Room Redesign", goal="Warm up the living room on a budget")
    project_id = project.project_id

    session = stores["session_store"].create_session(project_id=project_id, client_metadata=None)
    collecting = session.model_copy(update={
        "status": InvestigationSessionStatus.COLLECTING, "revision": session.revision + 1,
        "updated_at_utc": datetime.now(timezone.utc),
    })
    stores["session_store"].save_session(collecting)
    image_bytes = _generate_room_image()
    evidence, created = stores["evidence_store"].upload_evidence(
        session_id=collecting.session_id, evidence_type=InvestigationEvidenceType.IMAGE,
        raw_bytes=image_bytes, mime_type="image/png", original_filename="living_room.png",
        request=InvestigationEvidenceCreateRequest(source="test", filename="living_room.png", mime_type="image/png"),
    )
    assert created

    from projects.project_conversation import ConversationSendRequest, ConversationEvidenceReferencePart

    for i, (text, evidence_marker) in enumerate(_SETUP_TURNS):
        refs = []
        if evidence_marker == "EVIDENCE":
            refs = [ConversationEvidenceReferencePart(
                resource_id=evidence.evidence_id, container_id=collecting.session_id)]
        response = setup_orchestrator.send(project_id, ConversationSendRequest(
            text=text, idempotency_key=f"setup-{i}", evidence_refs=refs))
        assert response.turns[-1].status.value == "COMPLETED", f"setup turn {i} failed: {text!r}"

    return {
        "tmp_path": tmp_path, "stores": stores, "project_id": project_id,
        "session_id": collecting.session_id, "evidence_id": evidence.evidence_id,
        "fake_provider": fake_provider, "setup_call_counters": setup_call_counters,
    }


def test_long_horizon_living_room_acceptance(long_horizon_scenario):
    ctx = long_horizon_scenario
    project_id = ctx["project_id"]

    # --- Prove early information genuinely falls outside the raw recent-turn window. ---
    conversation_before_final = ctx["stores"]["conversation_store"].load(project_id)
    budget_turn = next(t for t in conversation_before_final.turns
                        if any(getattr(p, "text", "") == "My budget is around $1,500."
                               for p in t.content_parts))
    next_sequence = conversation_before_final.turns[-1].sequence_number + 1
    bounded_prior = AssistantOrchestrator._bounded_prior_turns(
        conversation_before_final, before_sequence=next_sequence)
    assert len(bounded_prior) == MAX_PRIOR_CONVERSATION_TURNS
    prior_texts = {t.text for t in bounded_prior}
    assert "My budget is around $1,500." not in prior_texts  # confirmed evicted from raw window

    # --- Leave/return: brand-new orchestrator, fresh store objects re-reading the same files. ---
    fresh_stores = _build_stores(ctx["tmp_path"])
    real_provider_calls: list[dict] = []

    from openai import OpenAI

    class _RecordingCompletions:
        def __init__(self, real, sink):
            self._real, self._sink = real, sink

        def create(self, **kwargs):
            self._sink.append(kwargs)
            return self._real.create(**kwargs)

    class _RecordingClient:
        def __init__(self, real, sink):
            self.chat = type("_Chat", (), {"completions": _RecordingCompletions(real.chat.completions, sink)})()

    final_call_counters: dict = {}
    real_reply_provider = OpenAIAssistantProvider(
        api_key=_API_KEY, client_factory=lambda **kw: _RecordingClient(OpenAI(**kw), real_provider_calls))
    final_orchestrator = _build_orchestrator(
        fresh_stores, reply_provider=real_reply_provider, real_calls=True, call_counters=final_call_counters)

    from projects.project_conversation import ConversationSendRequest

    answers: dict[str, str] = {}
    provenance: dict[str, dict] = {}
    for i, question in enumerate(_FINAL_QUESTIONS):
        response = final_orchestrator.send(project_id, ConversationSendRequest(
            text=question, idempotency_key=f"final-{i}"))
        turn = response.turns[-1]
        assert turn.status.value == "COMPLETED", f"question {i} failed: {question!r}"
        text_part = next(p for p in turn.content_parts if hasattr(p, "text"))
        answers[question] = text_part.text
        provenance[question] = {
            "visual_retrieval_tier": turn.provider_provenance.visual_retrieval_tier,
            "visual_evidence_id": turn.provider_provenance.visual_evidence_id,
            "memory_retrieval_intent": turn.provider_provenance.memory_retrieval_intent,
            "memory_retrieval_subject": turn.provider_provenance.memory_retrieval_subject,
        }

    # ============================= ACCEPTANCE ASSERTIONS =============================

    records = fresh_stores["memory_store"].list_records(project_id)
    committed_current = [r for r in records if r.status == ProjectMemoryStatus.CURRENT
                          and r.modality == ProjectMemoryModality.COMMITTED]

    print("\n\n========== ANSWERS ==========")
    for q in _FINAL_QUESTIONS:
        print(f"\nQ: {q}\nA: {answers[q]}\nPROVENANCE: {provenance[q]}")
    print("\n\n========== ALL MEMORY RECORDS ==========")
    for r in sorted(records, key=lambda r: r.occurred_at_utc):
        print(f"{r.scope} | {r.category.value} | {r.subject}/{r.slot} | {r.value!r} | "
              f"{r.modality.value} | {r.status.value} | "
              f"{r.progress_state.value if r.progress_state else ''}")
    print("\n\n========== CURRENT PROJECT STATE (global) ==========")
    global_state = fresh_stores["memory_store"] and __import__(
        "projects").ProjectCurrentStateService(salience_client=None).get_current_state(project_id, records)
    print("blockers:", global_state.global_blockers)
    print("scope_summaries:", global_state.scope_summaries)
    print("resolved_scope_count:", global_state.resolved_scope_count)
    print("recent_changes:", global_state.recent_changes)
    print("scope_detail keys:", list(global_state.scope_detail.keys()))

    # A. Budget recall - current committed budget ~$1,500, not $1,750/$3,000.
    budget_records = [r for r in committed_current if r.subject == "budget"]
    assert len(budget_records) == 1
    assert "1,500" in budget_records[0].value or "1500" in budget_records[0].value
    q2 = answers[_FINAL_QUESTIONS[1]].lower()
    assert "1,500" in q2 or "1500" in q2
    assert "1,750" not in q2 and "1750" not in q2
    assert "3,000" not in q2 and "3000" not in q2

    # B. Constraint recall.
    q3 = answers[_FINAL_QUESTIONS[2]].lower()
    assert "dog" in q3 or "durab" in q3
    assert "warm" in q3 or "white" in q3

    # C. Changed decision - current TV-stand decision is "replace"/no-longer-keep.
    q4 = answers[_FINAL_QUESTIONS[3]].lower()
    assert "no" in q4 or "not" in q4 or "replac" in q4

    # D. Historical decision retrievable.
    q5 = answers[_FINAL_QUESTIONS[4]].lower()
    assert "keep" in q5

    # E. Decision explanation grounded in real history (not fabricated - just needs to reference
    # the actual transition, warm wood).
    q6 = answers[_FINAL_QUESTIONS[5]].lower()
    assert "warm" in q6 or "wood" in q6 or "replac" in q6

    # F. Progress - completed work known.
    q7 = answers[_FINAL_QUESTIONS[6]].lower()
    assert "paint" in q7 or "rug" in q7

    # G. Open work known.
    q8 = answers[_FINAL_QUESTIONS[7]].lower()
    assert "outlet" in q8 or "electric" in q8 or "wir" in q8

    # H/I. Continuation + next action grounded in current state, not random recent history.
    q1 = answers[_FINAL_QUESTIONS[0]].lower()
    assert len(q1) > 0
    assert provenance[_FINAL_QUESTIONS[0]]["memory_retrieval_intent"] == "continuation"

    # J. Blocker surfaced.
    q10 = answers[_FINAL_QUESTIONS[9]].lower()
    assert "wir" in q10 or "electric" in q10 or "block" in q10

    # L. Visual Tier 1 - room appearance / blue suitability answered without pixels.
    assert provenance[_FINAL_QUESTIONS[10]]["visual_retrieval_tier"] == "description_sufficient"
    assert provenance[_FINAL_QUESTIONS[11]]["visual_retrieval_tier"] == "description_sufficient"

    # M. Visual Tier 2 - exact detail retrieves and uses correct original Evidence pixels.
    tag_question = _FINAL_QUESTIONS[12]
    assert provenance[tag_question]["visual_retrieval_tier"] == "original_required"
    assert provenance[tag_question]["visual_evidence_id"] == ctx["evidence_id"]
    assert "b7" in answers[tag_question].lower()

    # T (part) - grounded proof pixels were actually sent for the Tier 2 turn.
    assert len(real_provider_calls) == len(_FINAL_QUESTIONS)  # exactly one real reply call per question
    tag_call = real_provider_calls[-1]  # the tag question was the last real conversation call
    has_image = any(
        isinstance(m.get("content"), list) and any(
            isinstance(p, dict) and p.get("type") == "image_url" for p in m["content"])
        for m in tag_call["messages"]
    )
    assert has_image

    # S. Tier 1 turns (room appearance, blue suitability) carried NO image content.
    for index in (10, 11):  # "What did the living room look like?", "Would blue work in this room?"
        call = real_provider_calls[index]
        has_image_here = any(
            isinstance(m.get("content"), list) and any(
                isinstance(p, dict) and p.get("type") == "image_url" for p in m["content"])
            for m in call["messages"]
        )
        assert not has_image_here

    # O. Boundedness - the JSON text payload sent to the real provider (which embeds
    # bounded_project_context, including structured_project_memory) stayed small for every graded
    # question - proof ordinary context is question-aware/bounded, not the entire Project dumped in.
    payload_sizes = []
    for call in real_provider_calls:
        user_message = call["messages"][-1]
        text_part = next(p for p in user_message["content"] if p.get("type") == "text")
        payload_sizes.append(len(text_part["text"]))
    # Bounded means "does not scale with total Project history" (Stage 1 found naive designs blow
    # up to 31,000-166,000 characters at scale) - not an arbitrary tiny number. The continuation
    # question ("where did we leave off?") is expected to be the largest since it legitimately
    # combines the existing checkpoint/activity context with the new global Current Project State
    # summary; 12,000 is generous headroom while still being dramatically smaller than the
    # known-pathological naive-dump range.
    assert max(payload_sizes) < 12000, f"payload sizes were not bounded: {payload_sizes}"

    print("\n\n========== PROVIDER CALL COUNTS ==========")
    print("setup phase (23 turns, fake conversation replies, real everything else):", ctx["setup_call_counters"])
    print("final phase (13 graded questions, real conversation replies):", final_call_counters)
    print("final phase real conversation-reply calls:", len(real_provider_calls))
    print("payload sizes (chars) per graded question:", list(zip(_FINAL_QUESTIONS, payload_sizes)))
