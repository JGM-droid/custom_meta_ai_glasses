"""Stage 2 - Integrated Persistent Memory Shadow Slice: minimal REAL-provider
checks (item 16.C). Deliberately small - only where language interpretation
genuinely matters: whether the extraction system prompt reliably distinguishes
committed vs. tentative vs. third-party vs. hypothetical vs. a plain question,
which no fake/deterministic test can verify. Skipped automatically if no
OPENAI_API_KEY is configured.
"""
from __future__ import annotations

import pytest

import api
from projects import ProjectMemoryExtractionService, ProjectMemoryModality

_API_KEY = api._load_openai_api_key()

pytestmark = pytest.mark.skipif(not _API_KEY, reason="OPENAI_API_KEY not configured")


@pytest.fixture(scope="module")
def extraction_service():
    return ProjectMemoryExtractionService(api_key=_API_KEY)


def test_committed_first_person_statement_extracted_as_committed(extraction_service):
    candidates = extraction_service.extract("My budget is around $1,500.")
    assert len(candidates) >= 1
    assert any(c.modality == ProjectMemoryModality.COMMITTED for c in candidates)


def test_tentative_hedge_not_extracted_as_committed(extraction_service):
    candidates = extraction_service.extract("I was thinking maybe $1,750, but I'm not sure.")
    assert all(c.modality != ProjectMemoryModality.COMMITTED for c in candidates)


def test_third_party_opinion_not_extracted_as_committed(extraction_service):
    candidates = extraction_service.extract("My friend thinks I should spend $3,000.")
    assert all(c.modality != ProjectMemoryModality.COMMITTED for c in candidates)


def test_hypothetical_aside_not_extracted_as_committed(extraction_service):
    candidates = extraction_service.extract("If I changed the couch someday, maybe I'd go lighter.")
    assert all(c.modality != ProjectMemoryModality.COMMITTED for c in candidates)


def test_plain_question_extracts_nothing(extraction_service):
    candidates = extraction_service.extract("What was my budget again?")
    assert candidates == []


def test_correction_extracted_as_committed_decision_update(extraction_service):
    candidates = extraction_service.extract("Actually, we don't need to replace the TV stand anymore.")
    assert any(c.modality == ProjectMemoryModality.COMMITTED for c in candidates)
