"""Stage 3 - Visual Evidence Continuity: the realistic acceptance scenario (item 15), run through
the REAL backend - real ProjectStore/InvestigationSessionStore/InvestigationEvidenceStore, real
AssistantOrchestrator.send(), real OpenAIAssistantProvider (real conversation replies) and real
VisualEvidenceContinuityService (real description-generation and selection calls). The image is a
synthetically generated "living room" photo (PIL-drawn shapes: wall, floor, window, picture frame,
couch, TV stand, rug, a patterned pillow with a small printed tag) - generated at test run time, not
committed to the repo, so no new binary test fixture is added. This keeps the scenario fully
self-contained and reproducible while still exercising genuine, real vision-model interpretation:
a preliminary manual check confirmed a real gpt-4.1-mini call (a) describes the room's major visible
elements without mentioning the small pillow tag, and (b) can correctly read the tag's two
characters ("B7") when asked to look closely at it - giving a real, non-hand-waved Tier 1 vs Tier 2
distinction. Skipped automatically if no OPENAI_API_KEY is configured.

Pixel transmission is proven by wrapping the real OpenAI client in a thin RECORDING proxy (forwards
every call to the real API, never fakes a response) so each request's `messages` can be inspected
afterward for the presence/absence of an `image_url` content part - this is the literal instrumentation
behind report items S/T/R.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

import api
from projects import (
    ProjectActivityStore,
    ProjectContextRetriever,
    ProjectStore,
    VisualEvidenceContinuityService,
)
from projects.assistant_orchestrator import AssistantOrchestrator
from projects.assistant_provider import OpenAIAssistantProvider
from projects.conversation_store import ProjectConversationStore
from investigations import (
    InvestigationEvidenceCreateRequest,
    InvestigationEvidenceStore,
    InvestigationEvidenceType,
    InvestigationSessionStatus,
    InvestigationSessionStore,
)

_API_KEY = api._load_openai_api_key()

pytestmark = pytest.mark.skipif(not _API_KEY, reason="OPENAI_API_KEY not configured")


def _generate_room_image() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (900, 650), color=(224, 214, 190))  # beige wall
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 480, 900, 650], fill=(150, 110, 70))  # floor
    draw.rectangle([650, 60, 850, 300], fill=(190, 220, 235))  # window
    draw.line([750, 60, 750, 300], fill=(255, 255, 255), width=6)
    draw.line([650, 180, 850, 180], fill=(255, 255, 255), width=6)
    draw.rectangle([80, 70, 220, 190], fill=(90, 90, 90))  # picture frame border
    draw.rectangle([95, 85, 205, 175], fill=(210, 190, 150))
    draw.rectangle([60, 380, 620, 560], fill=(101, 67, 33))  # couch
    draw.rectangle([60, 340, 620, 400], fill=(120, 82, 45))
    draw.rectangle([630, 420, 850, 560], fill=(70, 50, 35))  # TV stand
    draw.ellipse([150, 560, 700, 640], fill=(180, 60, 60))  # rug
    draw.rectangle([150, 400, 280, 470], fill=(190, 30, 30))  # pillow
    draw.rectangle([255, 450, 278, 468], fill=(255, 255, 255))  # small tag on the pillow
    font = ImageFont.load_default(size=14)
    draw.text((258, 452), "B7", fill=(0, 0, 0), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class _RecordingCompletions:
    def __init__(self, real_completions, sink: list[dict]):
        self._real = real_completions
        self._sink = sink

    def create(self, **kwargs):
        self._sink.append(kwargs)
        return self._real.create(**kwargs)


class _RecordingClient:
    """Forwards every call to the REAL OpenAI client - never fakes a response. Only records the
    outgoing kwargs so the test can inspect exactly what was sent (image content present or not)."""

    def __init__(self, real_client, sink: list[dict]):
        self.chat = type("_Chat", (), {"completions": _RecordingCompletions(real_client.chat.completions, sink)})()


def _has_image_content(create_kwargs: dict) -> bool:
    for message in create_kwargs.get("messages", []):
        content = message.get("content")
        if isinstance(content, list):
            if any(isinstance(part, dict) and part.get("type") == "image_url" for part in content):
                return True
    return False


@pytest.fixture
def living_room_visual_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from openai import OpenAI

    projects_root = tmp_path / "projects"
    project_store = ProjectStore(projects_root)
    activity_store = ProjectActivityStore(projects_root, project_store)
    conversation_store = ProjectConversationStore(project_store)
    session_store = InvestigationSessionStore(tmp_path / "sessions")
    evidence_store = InvestigationEvidenceStore(session_store)
    context_retriever = ProjectContextRetriever(
        project_store=project_store, activity_store=activity_store, session_store=session_store,
        investigation_store_root=tmp_path / "investigations",
    )

    provider_calls: list[dict] = []
    visual_service_calls: list[dict] = []
    provider = OpenAIAssistantProvider(
        api_key=_API_KEY, client_factory=lambda **kwargs: _RecordingClient(OpenAI(**kwargs), provider_calls))
    visual_service = VisualEvidenceContinuityService(
        api_key=_API_KEY, client_factory=lambda **kwargs: _RecordingClient(OpenAI(**kwargs), visual_service_calls))

    orchestrator = AssistantOrchestrator(
        project_store=project_store,
        conversation_store=conversation_store,
        context_retriever=context_retriever,
        provider=provider,
        session_store=session_store,
        evidence_store=evidence_store,
        visual_evidence_service=visual_service,
    )

    from fastapi.testclient import TestClient
    monkeypatch.setattr(api, "PROJECT_STORE", project_store)
    monkeypatch.setattr(api, "PROJECT_CONVERSATION_STORE", conversation_store)
    monkeypatch.setattr(api, "_create_assistant_orchestrator", lambda: orchestrator)
    client = TestClient(api.app)
    return {
        "client": client, "project_store": project_store, "session_store": session_store,
        "evidence_store": evidence_store, "provider_calls": provider_calls,
        "visual_service_calls": visual_service_calls,
    }


def _reference(session_id: str, evidence_id: str) -> dict:
    return {
        "type": "PROJECT_RESOURCE_REFERENCE", "resource_kind": "EVIDENCE", "resource_id": evidence_id,
        "relationship": "ATTACHED", "container_kind": "INVESTIGATION_SESSION", "container_id": session_id,
    }


def test_living_room_visual_continuity_two_tier_scenario(living_room_visual_backend):
    ctx = living_room_visual_backend
    project_response = ctx["client"].post(
        "/projects", json={"name": "Living Room Redesign", "goal": "Warm up the living room on a budget"})
    assert project_response.status_code == 201
    project_id = project_response.json()["project_id"]

    session = ctx["session_store"].create_session(project_id=project_id, client_metadata=None)
    from datetime import datetime, timezone
    collecting = session.model_copy(update={
        "status": InvestigationSessionStatus.COLLECTING, "revision": session.revision + 1,
        "updated_at_utc": datetime.now(timezone.utc),
    })
    ctx["session_store"].save_session(collecting)
    image_bytes = _generate_room_image()
    evidence, created = ctx["evidence_store"].upload_evidence(
        session_id=collecting.session_id, evidence_type=InvestigationEvidenceType.IMAGE,
        raw_bytes=image_bytes, mime_type="image/png", original_filename="living_room.png",
        request=InvestigationEvidenceCreateRequest(source="test", filename="living_room.png", mime_type="image/png"),
    )
    assert created

    # --- Turn A: attach the image, ask a natural question. ---
    turn_a = ctx["client"].post(
        f"/projects/{project_id}/conversation/messages",
        json={"text": "What do you think of this room?", "idempotency_key": "turn-a",
              "evidence_refs": [_reference(collecting.session_id, evidence.evidence_id)]},
    )
    assert turn_a.status_code == 200, turn_a.text

    described = ctx["evidence_store"].load_evidence_for_analysis(
        session_id=collecting.session_id, evidence_id=evidence.evidence_id)
    assert described.visual_description  # durable description created
    assert described.visual_description_scope  # linked/provenanced with a scope
    assert "b7" not in described.visual_description.lower()  # the fine tag detail was not captured

    # Turn A's own conversation call legitimately included the image (freshly attached this turn).
    assert _has_image_content(ctx["provider_calls"][-1])

    # --- Turn B (Tier 1): a later, text-only question the stored description should cover. ---
    turn_b = ctx["client"].post(
        f"/projects/{project_id}/conversation/messages",
        json={"text": "Would blue work in this room?", "idempotency_key": "turn-b"},
    )
    assert turn_b.status_code == 200, turn_b.text
    turn_b_provenance = turn_b.json()["turns"][1]["provider_provenance"]
    assert turn_b_provenance["visual_retrieval_tier"] == "description_sufficient"
    assert turn_b_provenance["visual_evidence_id"] == evidence.evidence_id
    # Instrumented proof: the conversation call for Turn B carried NO image content at all -
    # original pixels were never re-fetched/sent for a Tier 1 turn.
    assert not _has_image_content(ctx["provider_calls"][-1])

    # --- Turn C (Tier 2): a fine visual detail the stored description does not cover. ---
    turn_c = ctx["client"].post(
        f"/projects/{project_id}/conversation/messages",
        json={"text": ("In the photo I sent of the room, there's a small tag on the corner of the "
                       "pillow. What two characters are printed on that tag?"),
              "idempotency_key": "turn-c"},
    )
    assert turn_c.status_code == 200, turn_c.text
    turn_c_provenance = turn_c.json()["turns"][1]["provider_provenance"]
    assert turn_c_provenance["visual_retrieval_tier"] == "original_required"
    assert turn_c_provenance["visual_evidence_id"] == evidence.evidence_id
    # Instrumented proof: the conversation call for Turn C DID carry the original image content.
    assert _has_image_content(ctx["provider_calls"][-1])
    # Grounded answer: the real vision-augmented reply correctly reads the tag from the actual pixels.
    turn_c_text = turn_c.json()["turns"][1]["content_parts"][0]["text"]
    assert "b7" in turn_c_text.lower()

    # --- Provider call count instrumentation (item R). ---
    # visual_service_calls: 1 describe (Turn A) + 1 select (Turn B) + 1 select (Turn C) = 3.
    assert len(ctx["visual_service_calls"]) == 3
    # provider_calls: exactly one real conversation-reply call per turn (A, B, C) = 3 - Tier 2 reuses
    # the SAME normal conversation call with images populated, never a second dedicated call.
    assert len(ctx["provider_calls"]) == 3
