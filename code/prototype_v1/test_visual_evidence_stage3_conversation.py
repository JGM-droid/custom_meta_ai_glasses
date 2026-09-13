"""Stage 3 - Visual Evidence Continuity: conversation-level integration tests, run through the real
/projects/{id}/conversation/messages endpoint and real AssistantOrchestrator.send() - the exact
production call path. Only the conversation reply provider and the visual-evidence provider calls
(describe/select) are fakes, following the same pattern as Stage 2's conversation integration tests.

These are the tests that directly prove the Tier 1/Tier 2 guardrail: item S/T of the Stage 3 report
("evidence Tier 1 did NOT send pixels" / "evidence Tier 2 DID send the correct original pixels") is
checked here by inspecting the exact AssistantRequest the fake conversation provider received.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import api
from projects import VisualEvidenceContinuityError
from projects.assistant_orchestrator import AssistantOrchestrator
from projects.conversation_store import ProjectConversationStore
from test_project_conversation import FakeAssistantProvider, _attach_image, _reference
from test_response_planner_routing import create_project, routing_context  # noqa: F401


class FakeVisualEvidenceService:
    """Test double for VisualEvidenceContinuityService - lets a test declare exactly which
    description/selection outcome (or failure) a given call should produce, without a real
    provider call, while exercising the SAME orchestration code AssistantOrchestrator uses in
    production."""

    def __init__(self):
        self.describe_calls: list[bytes] = []
        self.select_calls: list[tuple[str, list]] = []
        self.describe_result = None
        self.describe_fail = False
        self.select_result = None

    def describe(self, *, image_bytes: bytes, media_type: str):
        self.describe_calls.append(image_bytes)
        if self.describe_fail:
            raise VisualEvidenceContinuityError("fixture-forced description failure")
        from projects import VisualEvidenceDescriptionResult
        return self.describe_result or VisualEvidenceDescriptionResult(description="A room.", scope="overall")

    def select(self, *, question_text: str, candidates):
        self.select_calls.append((question_text, candidates))
        return self.select_result


@pytest.fixture
def visual_evidence_conversation_context(routing_context, monkeypatch, tmp_path: Path):
    ctx = routing_context
    conversation_store = ProjectConversationStore(ctx["project_store"])
    provider = FakeAssistantProvider()
    visual_service = FakeVisualEvidenceService()

    orchestrator = AssistantOrchestrator(
        project_store=ctx["project_store"],
        conversation_store=conversation_store,
        context_retriever=api._create_project_context_retriever(),
        provider=provider,
        session_store=ctx["session_store"],
        evidence_store=ctx["evidence_store"],
        investigation_trust_service=api._project_trust_service(),
        visual_evidence_service=visual_service,
    )
    monkeypatch.setattr(api, "PROJECT_CONVERSATION_STORE", conversation_store)
    monkeypatch.setattr(api, "_create_assistant_orchestrator", lambda: orchestrator)
    return {**ctx, "conversation_store": conversation_store, "provider": provider,
            "orchestrator": orchestrator, "visual_service": visual_service}


def _send(client, project_id, text, key, references=None):
    payload = {"text": text, "idempotency_key": key}
    if references is not None:
        payload["evidence_refs"] = references
    return client.post(f"/projects/{project_id}/conversation/messages", json=payload)


def _make_selection(session_id, evidence_id, tier, description="A stored description."):
    from projects.visual_evidence import VisualEvidenceSelection
    return VisualEvidenceSelection(session_id=session_id, evidence_id=evidence_id, tier=tier, description=description)


def test_fresh_attachment_triggers_shadow_description_generation(visual_evidence_conversation_context):
    ctx = visual_evidence_conversation_context
    project = create_project(ctx["client"])
    session, evidence = _attach_image(ctx, project["project_id"])

    response = _send(ctx["client"], project["project_id"], "What do you think of this room?", "turn-1",
                      [_reference(session.session_id, evidence.evidence_id)])
    assert response.status_code == 200

    assert len(ctx["visual_service"].describe_calls) == 1
    reloaded = ctx["evidence_store"].load_evidence_for_analysis(
        session_id=session.session_id, evidence_id=evidence.evidence_id)
    assert reloaded.visual_description == "A room."
    assert reloaded.visual_description_scope == "overall"

    # A fresh attachment is not "retrieval" - provenance must not claim a tier was used.
    turns = response.json()["turns"]
    assert turns[1]["provider_provenance"]["visual_retrieval_tier"] is None


def test_shadow_description_failure_does_not_break_real_turn(visual_evidence_conversation_context):
    ctx = visual_evidence_conversation_context
    project = create_project(ctx["client"])
    session, evidence = _attach_image(ctx, project["project_id"])
    ctx["visual_service"].describe_fail = True

    response = _send(ctx["client"], project["project_id"], "What do you think of this room?", "turn-1",
                      [_reference(session.session_id, evidence.evidence_id)])
    assert response.status_code == 200
    assert [t["status"] for t in response.json()["turns"]] == ["COMPLETED", "COMPLETED"]

    reloaded = ctx["evidence_store"].load_evidence_for_analysis(
        session_id=session.session_id, evidence_id=evidence.evidence_id)
    assert reloaded.visual_description is None  # original Evidence preserved, nothing corrupted


def test_no_visual_retrieval_for_ordinary_non_visual_question(visual_evidence_conversation_context):
    ctx = visual_evidence_conversation_context
    project = create_project(ctx["client"])
    response = _send(ctx["client"], project["project_id"], "My budget is around $1,500.", "turn-1")
    assert response.status_code == 200
    assert ctx["visual_service"].select_calls == []
    turn = response.json()["turns"][1]
    assert turn["provider_provenance"]["visual_retrieval_tier"] is None


def test_tier1_retrieval_does_not_fetch_original_pixels(visual_evidence_conversation_context):
    ctx = visual_evidence_conversation_context
    project = create_project(ctx["client"])
    session, evidence = _attach_image(ctx, project["project_id"])
    _send(ctx["client"], project["project_id"], "What do you think of this room?", "turn-1",
          [_reference(session.session_id, evidence.evidence_id)])

    ctx["visual_service"].select_result = _make_selection(
        session.session_id, evidence.evidence_id, "description_sufficient",
        description="Beige couch with a large wall mirror.")
    response = _send(ctx["client"], project["project_id"], "Would blue work in this room?", "turn-2")
    assert response.status_code == 200

    request = ctx["provider"].requests[-1]
    assert request.images == ()  # Tier 1 - original pixels never fetched/sent
    assert request.visual_context == "Beige couch with a large wall mirror."

    turn = response.json()["turns"][1]
    assert turn["provider_provenance"]["visual_retrieval_tier"] == "description_sufficient"
    assert turn["provider_provenance"]["visual_evidence_id"] == evidence.evidence_id


def test_tier2_retrieval_fetches_correct_original_pixels(visual_evidence_conversation_context):
    ctx = visual_evidence_conversation_context
    project = create_project(ctx["client"])
    session, evidence = _attach_image(ctx, project["project_id"])
    _send(ctx["client"], project["project_id"], "What do you think of this room?", "turn-1",
          [_reference(session.session_id, evidence.evidence_id)])

    ctx["visual_service"].select_result = _make_selection(
        session.session_id, evidence.evidence_id, "original_required",
        description="Beige couch with two patterned pillows.")
    response = _send(ctx["client"], project["project_id"],
                      "What pattern was on the pillow in the original picture?", "turn-2")
    assert response.status_code == 200

    request = ctx["provider"].requests[-1]
    assert len(request.images) == 1  # Tier 2 - original pixels ARE fetched and sent
    assert request.images[0].evidence_id == evidence.evidence_id
    assert request.images[0].image_bytes == b"safe-image-content"  # the ACTUAL original bytes
    assert request.visual_context is None  # pixels carry the answer, no stored-text context needed

    turn = response.json()["turns"][1]
    assert turn["provider_provenance"]["visual_retrieval_tier"] == "original_required"
    assert turn["provider_provenance"]["visual_evidence_id"] == evidence.evidence_id


def test_tier2_selection_with_unavailable_pixels_falls_back_without_hallucinating(visual_evidence_conversation_context):
    ctx = visual_evidence_conversation_context
    project = create_project(ctx["client"])
    session, evidence = _attach_image(ctx, project["project_id"])
    _send(ctx["client"], project["project_id"], "What do you think of this room?", "turn-1",
          [_reference(session.session_id, evidence.evidence_id)])

    # A selection pointing at Evidence that does not actually exist - simulates original pixels
    # being unavailable at retrieval time (e.g. deleted, corrupted, storage failure).
    ctx["visual_service"].select_result = _make_selection(
        session.session_id, "00000000-0000-0000-0000-000000000000", "original_required",
        description="Beige couch with two patterned pillows.")
    response = _send(ctx["client"], project["project_id"],
                      "What pattern was on the pillow in the original picture?", "turn-2")
    assert response.status_code == 200

    request = ctx["provider"].requests[-1]
    assert request.images == ()  # never fabricated/guessed pixels
    assert "could not be retrieved" in request.visual_context
    assert "cannot be verified" in request.visual_context or "cannot be verified" in request.visual_context.lower()

    turn = response.json()["turns"][1]
    assert turn["provider_provenance"]["visual_retrieval_tier"] == "description_sufficient"


def test_fresh_evidence_refs_bypass_retrieval_entirely(visual_evidence_conversation_context):
    """A turn with its OWN evidence_refs must never be treated as a retrieval turn, even though the
    text might otherwise match the visual-continuity keyword gate."""
    ctx = visual_evidence_conversation_context
    project = create_project(ctx["client"])
    session, evidence = _attach_image(ctx, project["project_id"])

    response = _send(ctx["client"], project["project_id"], "What do you think of this room?", "turn-1",
                      [_reference(session.session_id, evidence.evidence_id)])
    assert response.status_code == 200
    assert ctx["visual_service"].select_calls == []
    turn = response.json()["turns"][1]
    assert turn["provider_provenance"]["visual_retrieval_tier"] is None
