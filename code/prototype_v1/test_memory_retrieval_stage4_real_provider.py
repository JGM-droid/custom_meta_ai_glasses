"""Stage 4 - Real Conversation Integration: minimal REAL-provider checks for
ProjectMemoryRetrievalService.select() - the one call the deterministic layer cannot resolve on its
own (anaphora resolution using prior conversation, and distinguishing continuation from
subject-specific intent for phrasing the deterministic keyword lists do not cover). Skipped
automatically if no OPENAI_API_KEY is configured.
"""
from __future__ import annotations

import pytest

import api
from projects.memory_retrieval import ProjectMemoryRetrievalService

_API_KEY = api._load_openai_api_key()

pytestmark = pytest.mark.skipif(not _API_KEY, reason="OPENAI_API_KEY not configured")


@pytest.fixture(scope="module")
def service():
    return ProjectMemoryRetrievalService(api_key=_API_KEY)


def test_resolves_anaphora_to_correct_subject_and_historical_intent(service):
    subjects = [("overall", "budget"), ("living_room", "tv_stand"), ("living_room", "couch")]
    records = []  # current_value hints degrade gracefully to "(no current value)" with no records
    result = service.select(
        question_text="Why did that change?",
        prior_turns_text=(
            "user: Are we still keeping the TV stand?\n"
            "assistant: No, the current decision is to replace it with something in warm wood."
        ),
        subjects=subjects, records=records,
    )
    assert result is not None
    assert result.intent == "historical"
    assert result.subject == "tv_stand"


def test_recognizes_continuation_intent_without_deterministic_phrasing(service):
    subjects = [("overall", "budget"), ("living_room", "tv_stand")]
    result = service.select(
        question_text="So, where do things stand overall on this project?",
        prior_turns_text="", subjects=subjects, records=[],
    )
    assert result is not None
    assert result.intent == "continuation"


def test_abstains_on_unrelated_question(service):
    subjects = [("overall", "budget")]
    result = service.select(
        question_text="Can you recommend a good podcast?",
        prior_turns_text="", subjects=subjects, records=[],
    )
    assert result is None
