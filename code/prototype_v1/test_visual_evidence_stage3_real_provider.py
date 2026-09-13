"""Stage 3 - Visual Evidence Continuity: minimal REAL-provider checks (item 17). Deliberately
small - only where actual visual interpretation/semantic judgment matters, which no fake test can
verify: does a real vision call produce a conservative, non-inventing description, and can a real
selection call correctly distinguish "before" from "current" for two same-scope candidates. Skipped
automatically if no OPENAI_API_KEY is configured.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import api
from projects.visual_evidence import VisualEvidenceCandidate, VisualEvidenceContinuityService

_API_KEY = api._load_openai_api_key()

pytestmark = pytest.mark.skipif(not _API_KEY, reason="OPENAI_API_KEY not configured")


@pytest.fixture(scope="module")
def service():
    return VisualEvidenceContinuityService(api_key=_API_KEY)


def test_describe_produces_conservative_non_empty_description(service):
    from PIL import Image, ImageDraw
    import io
    img = Image.new("RGB", (400, 300), color=(220, 210, 190))
    draw = ImageDraw.Draw(img)
    draw.rectangle([30, 200, 370, 280], fill=(100, 65, 35))  # couch-like shape
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    result = service.describe(image_bytes=buf.getvalue(), media_type="image/png")
    assert result.description
    assert len(result.description) > 0
    # Conservative guardrail: must not invent exact, unverifiable measurements for a plain
    # synthetic image with no dimension markings.
    lowered = result.description.lower()
    assert "feet" not in lowered and "inches" not in lowered and "cm" not in lowered


def test_select_distinguishes_before_from_current(service):
    now = datetime.now(timezone.utc)
    candidates = [
        VisualEvidenceCandidate(session_id="s1", evidence_id="after", scope="living_room",
                                 description="Living room after painting: warm terracotta walls.",
                                 occurred_at_utc=now),
        VisualEvidenceCandidate(session_id="s1", evidence_id="before", scope="living_room",
                                 description="Living room before painting: plain white walls.",
                                 occurred_at_utc=now - timedelta(days=5)),
    ]
    result = service.select(
        question_text="What did the living room look like before we painted?", candidates=candidates)
    assert result is not None
    assert result.evidence_id == "before"


def test_select_prefers_current_for_a_now_question(service):
    now = datetime.now(timezone.utc)
    candidates = [
        VisualEvidenceCandidate(session_id="s1", evidence_id="after", scope="living_room",
                                 description="Living room after painting: warm terracotta walls.",
                                 occurred_at_utc=now),
        VisualEvidenceCandidate(session_id="s1", evidence_id="before", scope="living_room",
                                 description="Living room before painting: plain white walls.",
                                 occurred_at_utc=now - timedelta(days=5)),
    ]
    result = service.select(
        question_text="What does the living room look like right now?", candidates=candidates)
    assert result is not None
    assert result.evidence_id == "after"


def test_select_abstains_for_unrelated_question(service):
    now = datetime.now(timezone.utc)
    candidates = [
        VisualEvidenceCandidate(session_id="s1", evidence_id="e1", scope="living_room",
                                 description="Beige couch with a large wall mirror.", occurred_at_utc=now),
    ]
    result = service.select(question_text="What was my budget again?", candidates=candidates)
    assert result is None
