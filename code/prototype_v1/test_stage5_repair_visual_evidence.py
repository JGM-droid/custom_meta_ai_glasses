"""Stage 5 repair (Fix 2): pre-Stage-3 Evidence must never be denied.

Proves the exact dogfood-discovered failure cannot recur: Evidence with valid stored pixels but no
durable visual_description (because it predates Stage 3, or description generation previously
failed) must still be recognized as EXISTING - never silently excluded from candidates, which
previously let the model conclude and state that no photo was ever provided at all.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from investigations import (
    InvestigationEvidenceCreateRequest,
    InvestigationEvidenceStore,
    InvestigationEvidenceType,
    InvestigationSessionStatus,
    InvestigationSessionStore,
)
from projects.visual_evidence import (
    _EVIDENCE_EXISTS_BUT_UNMATCHED_NOTICE,
    _NO_DESCRIPTION_PLACEHOLDER,
    VisualEvidenceCandidate,
    VisualEvidenceContinuityService,
    select_candidates,
)


def _stores(tmp_path: Path):
    session_store = InvestigationSessionStore(tmp_path / "sessions")
    evidence_store = InvestigationEvidenceStore(session_store)
    return session_store, evidence_store


def _upload(session_store, evidence_store, *, project_id: str, filename: str = "photo.png"):
    session = session_store.create_session(project_id=project_id, client_metadata=None)
    collecting = session.model_copy(update={
        "status": InvestigationSessionStatus.COLLECTING, "revision": session.revision + 1,
        "updated_at_utc": datetime.now(timezone.utc),
    })
    session_store.save_session(collecting)
    evidence, created = evidence_store.upload_evidence(
        session_id=collecting.session_id, evidence_type=InvestigationEvidenceType.IMAGE,
        raw_bytes=b"fake-png-bytes", mime_type="image/png", original_filename=filename,
        request=InvestigationEvidenceCreateRequest(source="test", filename=filename, mime_type="image/png"),
    )
    assert created
    return collecting, evidence


# ---------------------------------------------------------------------------
# Item B: Evidence exists with valid pixels but no description
# ---------------------------------------------------------------------------

def test_select_candidates_includes_undescribed_evidence(tmp_path):
    session_store, evidence_store = _stores(tmp_path)
    project_id = "11111111-1111-1111-1111-111111111111"
    session, evidence = _upload(session_store, evidence_store, project_id=project_id)
    all_evidence = evidence_store.list_evidence_for_analysis(session.session_id)

    candidates = select_candidates(all_evidence, question_text="What did the room look like?")
    assert len(candidates) == 1
    assert candidates[0].evidence_id == evidence.evidence_id
    assert candidates[0].has_description is False
    assert candidates[0].description == _NO_DESCRIPTION_PLACEHOLDER


def test_select_candidates_does_not_exclude_undescribed_evidence_via_scope_filter(tmp_path):
    """An undescribed candidate has no known scope - it must never be excluded just because some
    OTHER, described candidate's scope happened to match the question."""
    session_store, evidence_store = _stores(tmp_path)
    project_id = "11111111-1111-1111-1111-111111111111"
    kitchen_session, kitchen_evidence = _upload(session_store, evidence_store, project_id=project_id, filename="kitchen.png")
    evidence_store.set_visual_description(
        session_id=kitchen_session.session_id, evidence_id=kitchen_evidence.evidence_id,
        description="White cabinets.", scope="kitchen", generated_at_utc=datetime.now(timezone.utc))
    undescribed_session, undescribed_evidence = _upload(session_store, evidence_store, project_id=project_id, filename="mystery.png")

    all_evidence = (evidence_store.list_evidence_for_analysis(kitchen_session.session_id)
                     + evidence_store.list_evidence_for_analysis(undescribed_session.session_id))
    candidates = select_candidates(all_evidence, question_text="What does the kitchen look like?")
    candidate_ids = {c.evidence_id for c in candidates}
    assert kitchen_evidence.evidence_id in candidate_ids
    assert undescribed_evidence.evidence_id in candidate_ids  # never silently excluded


class _FakeCompletions:
    def __init__(self, payload: str):
        self._payload = payload
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        return type("_R", (), {"choices": [type("_C", (), {
            "message": type("_M", (), {"content": self._payload})()})()]})()


class _FakeClient:
    def __init__(self, payload: str):
        self.completions = _FakeCompletions(payload)
        self.chat = type("_Chat", (), {"completions": self.completions})()


def test_selecting_an_undescribed_candidate_forces_original_required_tier():
    import json
    payload = json.dumps({"applicable": True, "selected_index": 0, "tier": "description_sufficient"})
    fake = _FakeClient(payload)
    service = VisualEvidenceContinuityService(api_key="test-key", client_factory=lambda **_: fake)
    candidate = VisualEvidenceCandidate(
        session_id="s1", evidence_id="e1", scope="overall",
        description=_NO_DESCRIPTION_PLACEHOLDER, occurred_at_utc=datetime.now(timezone.utc),
        has_description=False,
    )
    result = service.select(question_text="What did the room look like?", candidates=[candidate])
    assert result is not None
    # Deterministic override: Tier 1 is impossible without a real description, regardless of what
    # the model itself returned - never trust the model's own honesty alone for this.
    assert result.tier == "original_required"


def test_selecting_a_described_candidate_respects_model_tier():
    import json
    payload = json.dumps({"applicable": True, "selected_index": 0, "tier": "description_sufficient"})
    fake = _FakeClient(payload)
    service = VisualEvidenceContinuityService(api_key="test-key", client_factory=lambda **_: fake)
    candidate = VisualEvidenceCandidate(
        session_id="s1", evidence_id="e1", scope="overall",
        description="Beige couch with a mirror.", occurred_at_utc=datetime.now(timezone.utc),
        has_description=True,
    )
    result = service.select(question_text="What did the room look like?", candidates=[candidate])
    assert result is not None
    assert result.tier == "description_sufficient"


# ---------------------------------------------------------------------------
# Conversation-level: Evidence exists but selection abstains / pixels unavailable
# ---------------------------------------------------------------------------

import api as _api
from projects.assistant_orchestrator import AssistantOrchestrator
from projects.conversation_store import ProjectConversationStore
from test_project_conversation import FakeAssistantProvider, _attach_image, _reference
from test_response_planner_routing import create_project, routing_context  # noqa: F401


class _FakeVisualEvidenceService:
    def __init__(self):
        self.select_result = None

    def describe(self, *, image_bytes: bytes, media_type: str):
        from projects import VisualEvidenceDescriptionResult
        return VisualEvidenceDescriptionResult(description="A room.", scope="overall")

    def select(self, *, question_text: str, candidates):
        return self.select_result


@pytest.fixture
def _visual_repair_context(routing_context, monkeypatch, tmp_path: Path):
    ctx = routing_context
    conversation_store = ProjectConversationStore(ctx["project_store"])
    provider = FakeAssistantProvider()
    visual_service = _FakeVisualEvidenceService()
    orchestrator = AssistantOrchestrator(
        project_store=ctx["project_store"], conversation_store=conversation_store,
        context_retriever=_api._create_project_context_retriever(), provider=provider,
        session_store=ctx["session_store"], evidence_store=ctx["evidence_store"],
        investigation_trust_service=_api._project_trust_service(), visual_evidence_service=visual_service,
    )
    monkeypatch.setattr(_api, "PROJECT_CONVERSATION_STORE", conversation_store)
    monkeypatch.setattr(_api, "_create_assistant_orchestrator", lambda: orchestrator)
    return {**ctx, "conversation_store": conversation_store, "provider": provider, "visual_service": visual_service}


def _send(client, project_id, text, key, references=None):
    payload = {"text": text, "idempotency_key": key}
    if references is not None:
        payload["evidence_refs"] = references
    return client.post(f"/projects/{project_id}/conversation/messages", json=payload)


def test_evidence_exists_but_unmatched_never_denies_photo(_visual_repair_context):
    """Item: selection abstains (nothing confidently matched) but Evidence genuinely exists -
    must acknowledge existence, never let the model conclude no photo was ever provided."""
    ctx = _visual_repair_context
    project = create_project(ctx["client"])
    session, evidence = _attach_image(ctx, project["project_id"])
    _send(ctx["client"], project["project_id"], "Here's the room.", "turn-1",
          [_reference(session.session_id, evidence.evidence_id)])

    ctx["visual_service"].select_result = None  # abstain - candidates existed, nothing matched
    response = _send(ctx["client"], project["project_id"], "What did the room look like again?", "turn-2")
    assert response.status_code == 200
    request = ctx["provider"].requests[-1]
    assert request.images == ()
    assert request.visual_context == _EVIDENCE_EXISTS_BUT_UNMATCHED_NOTICE

    turn = response.json()["turns"][1]
    assert turn["provider_provenance"]["visual_retrieval_tier"] == "not_found"


def test_pixels_unavailable_for_undescribed_evidence_states_cannot_verify(_visual_repair_context, monkeypatch):
    """Item C: Evidence metadata exists but original pixels cannot be retrieved - must produce an
    explicit unable-to-verify signal, never fabricate a visual detail nor claim no photo exists."""
    from projects.visual_evidence import VisualEvidenceSelection, _NO_DESCRIPTION_PLACEHOLDER

    ctx = _visual_repair_context
    project = create_project(ctx["client"])
    session, evidence = _attach_image(ctx, project["project_id"])
    _send(ctx["client"], project["project_id"], "Here's the room.", "turn-1",
          [_reference(session.session_id, evidence.evidence_id)])

    # Simulate pixels becoming unavailable at retrieval time: point the selection at a
    # non-existent evidence_id (same session), so load_evidence_content fails deterministically.
    ctx["visual_service"].select_result = VisualEvidenceSelection(
        session_id=session.session_id, evidence_id="00000000-0000-0000-0000-000000000000",
        tier="original_required", description=_NO_DESCRIPTION_PLACEHOLDER,
    )
    response = _send(ctx["client"], project["project_id"], "What did the room look like?", "turn-2")
    assert response.status_code == 200
    request = ctx["provider"].requests[-1]
    assert request.images == ()
    assert "cannot currently verify" in (request.visual_context or "").lower()
    assert "no photo" not in (request.visual_context or "").lower()
