"""Stage 5 repair (Fix 1): missing-memory fabrication safety.

Proves the exact dogfood-discovered failure cannot recur: a question about a topic with NO durable
Structured Project Memory record must never be answered using an unrelated known subject (e.g.
"budget" presented as if it answers a question about a "TV stand") - the system must either
abstain silently (ordinary non-memory-seeking question) or explicitly signal insufficient durable
information (a question that looks like it wants Project history), never confidently invert or
fabricate a claim.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from projects import (
    ProjectActivitySourceType,
    ProjectMemoryCandidate,
    ProjectMemoryCategory,
    ProjectMemoryModality,
    ProjectMemoryStore,
    ProjectStore,
)
from projects.memory_retrieval import (
    MemorySelection,
    _NO_RELEVANT_MEMORY_NOTICE,
    _selection_is_grounded,
    retrieve_memory_context,
)


def _store(tmp_path: Path):
    projects_root = tmp_path / "projects"
    project_store = ProjectStore(projects_root)
    memory_store = ProjectMemoryStore(projects_root, project_store)
    project = project_store.create_project(name="t", goal="g")
    return memory_store, project.project_id


def _write(memory_store, project_id, **overrides):
    base = dict(category=ProjectMemoryCategory.FACT, scope="overall", subject="budget",
                slot="amount", value="$1,500", modality=ProjectMemoryModality.COMMITTED)
    base.update(overrides)
    return memory_store.write_candidate(
        project_id, ProjectMemoryCandidate(**base),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)


# ---------------------------------------------------------------------------
# Deterministic grounding-check unit tests
# ---------------------------------------------------------------------------

def test_grounding_check_rejects_subject_absent_from_question_and_context():
    selection = MemorySelection(intent="historical", scope="overall", subject="budget")
    assert not _selection_is_grounded(
        selection, "Didn't we originally say we were keeping the TV stand? Why did that change?", "")


def test_grounding_check_accepts_subject_present_in_question():
    selection = MemorySelection(intent="current", scope="overall", subject="budget")
    assert _selection_is_grounded(selection, "What was my budget again?", "")


def test_grounding_check_accepts_subject_present_only_in_recent_conversation():
    selection = MemorySelection(intent="historical", scope="living_room", subject="tv_stand")
    assert _selection_is_grounded(
        selection, "Why did that change?",
        "user: Are we still keeping the TV stand?\nassistant: No, replacing it.")


def test_grounding_check_always_trusts_continuation_selection():
    selection = MemorySelection(intent="continuation", scope=None, subject=None)
    assert _selection_is_grounded(selection, "anything at all", "")


def test_grounding_check_rejects_keyword_only_present_in_an_assistant_recap():
    """Real dogfood-repair regression: an assistant's own recap turn ("...budget of $1,500...
    keeping the TV stand...") routinely lists many unrelated topics side by side. A keyword's mere
    presence there must never ground a selection - only something the USER themselves raised
    counts, or the check is trivially defeated the next time the assistant recaps the project."""
    selection = MemorySelection(intent="historical", scope="overall", subject="budget")
    prior_turns_text = (
        "assistant: No photo was supplied originally.\n"
        "user: What were the main things I told you I cared about for this room?\n"
        "assistant: Working within a total budget of around $1,500, and keeping the TV stand."
    )
    assert not _selection_is_grounded(
        selection, "Didn't we originally say we were keeping the TV stand? Why did that change?",
        prior_turns_text)


# ---------------------------------------------------------------------------
# Item A: an unrelated-fallback selection must never be presented as evidence
# ---------------------------------------------------------------------------

def test_unrelated_subject_selection_is_discarded_not_presented(tmp_path):
    memory_store, project_id = _store(tmp_path)
    _write(memory_store, project_id, subject="budget", value="$1,500")
    _write(memory_store, project_id, category=ProjectMemoryCategory.DECISION, scope="living_room",
           subject="couch", slot="disposition", value="keep")
    _write(memory_store, project_id, category=ProjectMemoryCategory.PROGRESS, scope="living_room",
           subject="rug", slot="procurement", value="ordered",
           progress_state=__import__("projects").ProjectMemoryProgressState.STARTED)
    records = memory_store.list_records(project_id)

    class UnrelatedFallbackSelectionService:
        """Simulates the exact dogfood bug: picks the least-bad known subject instead of
        abstaining when the question's real topic (TV stand) is not represented at all."""
        def select(self, **kwargs):
            return MemorySelection(intent="historical", scope="overall", subject="budget")

    result = retrieve_memory_context(
        project_id=project_id, records=records,
        question_text="Didn't we originally say we were keeping the TV stand? Why did that change?",
        selection_service=UnrelatedFallbackSelectionService())

    assert result.intent == "not_found"
    assert result.subject is None
    assert "budget" not in (result.context_text or "").lower()
    assert "$1,500" not in (result.context_text or "")
    assert "NO_RELEVANT_MEMORY" in result.context_text


def test_clean_abstention_on_historical_question_also_produces_honesty_notice(tmp_path):
    memory_store, project_id = _store(tmp_path)
    _write(memory_store, project_id, subject="budget", value="$1,500")
    records = memory_store.list_records(project_id)

    class AbstainingSelectionService:
        def select(self, **kwargs):
            return None

    result = retrieve_memory_context(
        project_id=project_id, records=records,
        question_text="What did we originally decide about the TV stand?",
        selection_service=AbstainingSelectionService())
    assert result.intent == "not_found"
    assert result.context_text == _NO_RELEVANT_MEMORY_NOTICE


def test_ordinary_unrelated_question_stays_silent_no_unnecessary_notice(tmp_path):
    """A question that does not look like it wants Project history at all must stay silent on
    abstention - the honesty notice is reserved for historical-flavored questions, not injected
    into every ordinary aside, to avoid needless prompt noise."""
    memory_store, project_id = _store(tmp_path)
    _write(memory_store, project_id, subject="budget", value="$1,500")
    records = memory_store.list_records(project_id)

    class AbstainingSelectionService:
        def select(self, **kwargs):
            return None

    result = retrieve_memory_context(
        project_id=project_id, records=records, question_text="Can you recommend a podcast?",
        selection_service=AbstainingSelectionService())
    assert result.context_text is None
    assert result.intent is None
