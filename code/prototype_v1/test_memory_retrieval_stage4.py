"""Stage 4 - Real Conversation Integration: deterministic unit tests for projects/memory_retrieval.py.

Proves the question-aware retrieval invariants: deterministic subject/continuation/category
matching short-circuits correctly (no AI call needed), historical rendering correctly separates
CURRENT from HISTORY and never lets tentative/superseded/third-party contaminate CURRENT, and the
full retrieve_memory_context() entry point degrades safely (never guesses) when nothing resolves.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    category_keyword_match,
    deterministic_subject_match,
    is_continuation_question,
    is_historical_question,
    known_current_subjects,
    render_category_context,
    render_continuation_context,
    render_subject_context,
    retrieve_memory_context,
)
from projects.project_current_state import ProjectCurrentStateService


def _store(tmp_path: Path):
    projects_root = tmp_path / "projects"
    project_store = ProjectStore(projects_root)
    memory_store = ProjectMemoryStore(projects_root, project_store)
    project = project_store.create_project(name="Living Room", goal="Redesign it")
    return memory_store, project.project_id


def _candidate(**overrides):
    base = dict(category=ProjectMemoryCategory.FACT, scope="overall", subject="budget",
                slot="amount", value="$1,500", modality=ProjectMemoryModality.COMMITTED)
    base.update(overrides)
    return ProjectMemoryCandidate(**base)


def _write(memory_store, project_id, **overrides):
    return memory_store.write_candidate(
        project_id, _candidate(**overrides), source_type=ProjectActivitySourceType.USER, source_turn_id=None)


# ---------------------------------------------------------------------------
# Keyword gates
# ---------------------------------------------------------------------------

def test_is_continuation_question():
    assert is_continuation_question("Where did we leave off?")
    assert is_continuation_question("What still needs to be done?")
    assert is_continuation_question("Is anything blocking the project?")
    assert not is_continuation_question("What was my budget?")


def test_is_historical_question():
    assert is_historical_question("What did we originally decide about the TV stand?")
    assert is_historical_question("Why did that change?")
    assert not is_historical_question("Are we still keeping the TV stand?")


def test_category_keyword_match():
    assert category_keyword_match("What constraints should we keep in mind?") == (
        ProjectMemoryCategory.CONSTRAINT, ProjectMemoryCategory.PREFERENCE)
    assert category_keyword_match("What was my budget?") is None


# ---------------------------------------------------------------------------
# Deterministic subject matching
# ---------------------------------------------------------------------------

def test_known_current_subjects_excludes_superseded_and_noncommitted(tmp_path):
    memory_store, project_id = _store(tmp_path)
    _write(memory_store, project_id, subject="budget", value="$1,500")
    _write(memory_store, project_id, subject="budget", value="$2,000")  # supersedes the first
    _write(memory_store, project_id, subject="hunch", value="maybe $1,750",
           modality=ProjectMemoryModality.TENTATIVE)

    subjects = known_current_subjects(memory_store.list_records(project_id))
    assert ("overall", "budget") in subjects
    assert ("overall", "hunch") not in subjects  # tentative, never counts as a "known current subject"
    assert len(subjects) == 1


def test_deterministic_subject_match_unambiguous():
    subjects = [("overall", "budget"), ("living_room", "couch")]
    assert deterministic_subject_match("What was my budget again?", subjects) == ("overall", "budget")
    assert deterministic_subject_match("Are we keeping the couch?", subjects) == ("living_room", "couch")
    assert deterministic_subject_match("What's for dinner?", subjects) is None


def test_deterministic_subject_match_ambiguous_returns_none():
    subjects = [("living_room", "panel"), ("unit_412", "panel")]
    assert deterministic_subject_match("What about the panel?", subjects) is None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_render_category_context_current_only(tmp_path):
    memory_store, project_id = _store(tmp_path)
    _write(memory_store, project_id, category=ProjectMemoryCategory.CONSTRAINT,
           subject="durability", value="dog owner, needs durable fabric")
    _write(memory_store, project_id, category=ProjectMemoryCategory.PREFERENCE,
           subject="style", value="warm, not stark white")
    _write(memory_store, project_id, category=ProjectMemoryCategory.DECISION,
           subject="couch", slot="disposition", value="keep")

    records = memory_store.list_records(project_id)
    text = render_category_context(records, (ProjectMemoryCategory.CONSTRAINT, ProjectMemoryCategory.PREFERENCE))
    assert "durability" in text
    assert "style" in text
    assert "couch" not in text  # decision category excluded
    assert text.startswith("CURRENT (confirmed):")


def test_render_subject_context_current_excludes_tentative_and_superseded(tmp_path):
    memory_store, project_id = _store(tmp_path)
    _write(memory_store, project_id, subject="budget", value="$1,500")
    _write(memory_store, project_id, subject="budget", value="maybe $1,750",
           modality=ProjectMemoryModality.TENTATIVE)

    records = memory_store.list_records(project_id)
    text = render_subject_context(records, "overall", "budget", historical=False)
    assert "$1,500" in text
    assert "1,750" not in text


def test_render_subject_context_historical_includes_full_chain_with_labels(tmp_path):
    memory_store, project_id = _store(tmp_path)
    _write(memory_store, project_id, category=ProjectMemoryCategory.DECISION, scope="living_room",
           subject="tv_stand", slot="disposition", value="keep")
    _write(memory_store, project_id, category=ProjectMemoryCategory.DECISION, scope="living_room",
           subject="tv_stand", slot="disposition", value="replace with warm wood")

    records = memory_store.list_records(project_id)
    text = render_subject_context(records, "living_room", "tv_stand", historical=True)
    assert "CURRENT (confirmed" in text
    assert "replace with warm wood" in text
    assert "HISTORY" in text
    assert "keep" in text
    assert "ORIGINAL" in text
    assert "superseded" in text


def test_render_subject_context_historical_includes_original_turn_text_when_resolvable(tmp_path):
    memory_store, project_id = _store(tmp_path)
    first = memory_store.write_candidate(
        project_id, _candidate(category=ProjectMemoryCategory.DECISION, scope="living_room",
                                subject="tv_stand", slot="disposition", value="keep"),
        source_type=ProjectActivitySourceType.USER, source_turn_id="11111111-1111-1111-1111-111111111111")
    memory_store.write_candidate(
        project_id, _candidate(category=ProjectMemoryCategory.DECISION, scope="living_room",
                                subject="tv_stand", slot="disposition", value="replace with warm wood"),
        source_type=ProjectActivitySourceType.USER, source_turn_id="22222222-2222-2222-2222-222222222222")

    lookup = {
        "11111111-1111-1111-1111-111111111111": "Let's keep the TV stand.",
        "22222222-2222-2222-2222-222222222222": "Actually, let's replace it with something warm wood.",
    }
    records = memory_store.list_records(project_id)
    text = render_subject_context(records, "living_room", "tv_stand", historical=True,
                                   turn_text_lookup=lambda tid: lookup.get(tid))
    assert "Let's keep the TV stand." in text
    assert "replace it with something warm wood" in text


# ---------------------------------------------------------------------------
# Regression tests for two rendering bugs found during Stage 4 independent
# review - both were reachable through the real retrieval path but not
# exercised by the tests above, which only covered short two-event chains.
# ---------------------------------------------------------------------------

def test_historical_view_never_labels_a_noncommitted_record_current(tmp_path):
    """A tentative aside sitting at status=CURRENT (Stage 2 never supersedes a non-committed
    record) must never share the "CURRENT" label with the real committed current record - a
    reviewer found both entries rendered as "CURRENT / most recent" before this fix, directly
    contradicting the header's own claim that only one entry is still true."""
    memory_store, project_id = _store(tmp_path)
    memory_store.write_candidate(
        project_id, _candidate(subject="budget", value="$1,500"),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)
    memory_store.write_candidate(
        project_id, _candidate(subject="budget", value="maybe $1,750", modality=ProjectMemoryModality.TENTATIVE),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    records = memory_store.list_records(project_id)
    text = render_subject_context(records, "overall", "budget", historical=True)
    entry_lines = [line for line in text.splitlines() if line.startswith("- ")]
    assert sum(1 for line in entry_lines if "CURRENT / most recent" in line) == 1
    committed_line = next(line for line in entry_lines if "$1,500" in line)
    assert "CURRENT / most recent" in committed_line
    tentative_line = next(line for line in entry_lines if "1,750" in line)
    assert "CURRENT / most recent" not in tentative_line
    assert "not confirmed" in tentative_line.lower()


def test_historical_view_preserves_true_original_beyond_the_history_window(tmp_path):
    """A subject with more than the rendered history-window size of events must still label the
    TRUE oldest event ORIGINAL, never a later event that happened to survive truncation - a
    reviewer found the naive `sorted(...)[-N:]` truncation silently dropped the real original and
    mislabeled the window's oldest surviving entry as ORIGINAL instead."""
    memory_store, project_id = _store(tmp_path)
    base = datetime.now(timezone.utc) - timedelta(days=10)
    for i in range(12):
        memory_store.write_candidate(
            project_id,
            _candidate(category=ProjectMemoryCategory.DECISION, scope="living_room",
                       subject="tv_stand", slot="disposition", value=f"decision #{i}"),
            source_type=ProjectActivitySourceType.USER, source_turn_id=None,
            occurred_at_utc=base + timedelta(hours=i),
        )

    records = memory_store.list_records(project_id)
    text = render_subject_context(records, "living_room", "tv_stand", historical=True)
    entry_lines = [line for line in text.splitlines() if line.startswith("- ")]
    original_line = next(line for line in entry_lines if "ORIGINAL" in line)
    assert "decision #0" in original_line  # the true first event, not a truncation artifact
    assert "omitted" in text.lower()  # bounded - middle events are collapsed, not silently dropped
    current_line = next(line for line in entry_lines if "CURRENT / most recent" in line)
    assert "decision #11" in current_line


def test_render_category_context_is_bounded(tmp_path):
    """Unlike subject-specific history (bounded to _MAX_HISTORY_EVENTS), a category-wide lookup
    ("what constraints should we keep in mind") had no cap at all - a reviewer found this could
    grow unbounded with total Project history. Now capped and most-recent-first."""
    memory_store, project_id = _store(tmp_path)
    for i in range(30):
        memory_store.write_candidate(
            project_id,
            _candidate(category=ProjectMemoryCategory.CONSTRAINT, subject=f"constraint_{i}",
                       value=f"constraint value {i}"),
            source_type=ProjectActivitySourceType.USER, source_turn_id=None,
        )
    records = memory_store.list_records(project_id)
    text = render_category_context(records, (ProjectMemoryCategory.CONSTRAINT, ProjectMemoryCategory.PREFERENCE))
    rendered_count = text.count("constraint value")
    assert 0 < rendered_count < 30


def test_recent_changes_are_explicitly_labeled_not_current(tmp_path):
    """A superseded record surfaced under Current Project State's "recent changes" must be
    unambiguously labeled as prior/no-longer-current - a reviewer found the bare rendered string
    (e.g. "[living_room] tv_stand/disposition: keep") gave the model no signal that this was old,
    already-superseded information, which produced a confusing/backwards-sounding real answer in
    the long-horizon E2E ("recently decided to keep" about a decision that had in fact just changed
    away from "keep")."""
    memory_store, project_id = _store(tmp_path)
    memory_store.write_candidate(
        project_id, _candidate(category=ProjectMemoryCategory.DECISION, scope="living_room",
                                subject="tv_stand", slot="disposition", value="keep"),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)
    memory_store.write_candidate(
        project_id, _candidate(category=ProjectMemoryCategory.DECISION, scope="living_room",
                                subject="tv_stand", slot="disposition", value="replace with warm wood"),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    records = memory_store.list_records(project_id)
    service = ProjectCurrentStateService(salience_client=None)
    state = service.get_current_state(project_id, records)
    text = render_continuation_context(state)
    assert "keep" in text
    # The label must appear on the SAME line/section as the stale value, not merely somewhere in
    # the whole document, so a reader cannot separate the value from its "not current" status.
    changes_section = text.split("RECENT CHANGES")[1] if "RECENT CHANGES" in text else ""
    assert "not current" in changes_section.lower() or "superseded" in changes_section.lower()


def test_render_continuation_context_reflects_current_state(tmp_path):
    memory_store, project_id = _store(tmp_path)
    _write(memory_store, project_id, category=ProjectMemoryCategory.PROGRESS, scope="living_room",
           subject="rug", slot="procurement", value="ordered", progress_state=__import__(
               "projects").ProjectMemoryProgressState.STARTED)

    records = memory_store.list_records(project_id)
    service = ProjectCurrentStateService(salience_client=None)
    state = service.get_current_state(project_id, records)
    text = render_continuation_context(state)
    assert "living_room" in text
    assert "rug" in text


def test_render_continuation_context_empty_state():
    from projects.models import PROJECT_CURRENT_STATE_SCHEMA_VERSION, ProjectCurrentState
    empty = ProjectCurrentState(
        schema_version=PROJECT_CURRENT_STATE_SCHEMA_VERSION, project_id="x", requested_scope=None,
        global_blockers=[], scope_summaries=[], resolved_scope_count=0, recent_changes=[],
        scope_detail={}, salience_call_used=False,
    )
    assert render_continuation_context(empty) == "No active Project state recorded yet."


# ---------------------------------------------------------------------------
# retrieve_memory_context() full entry point (pure, no real service)
# ---------------------------------------------------------------------------

def test_retrieve_memory_context_no_memory_yet_returns_nothing(tmp_path):
    memory_store, project_id = _store(tmp_path)
    result = retrieve_memory_context(
        project_id=project_id, records=[], question_text="What was my budget?")
    assert result.context_text is None
    assert result.intent is None


def test_retrieve_memory_context_deterministic_subject_short_circuits(tmp_path):
    memory_store, project_id = _store(tmp_path)
    _write(memory_store, project_id, subject="budget", value="$1,500")
    records = memory_store.list_records(project_id)

    class ExplodingSelectionService:
        def select(self, **kwargs):
            raise AssertionError("Selection call must not fire for an unambiguous deterministic match.")

    result = retrieve_memory_context(
        project_id=project_id, records=records, question_text="What was my budget again?",
        selection_service=ExplodingSelectionService())
    assert result.intent == "current"
    assert result.subject == "budget"
    assert "$1,500" in result.context_text


def test_retrieve_memory_context_deterministic_continuation_short_circuits(tmp_path):
    memory_store, project_id = _store(tmp_path)
    # A "replace" decision (not "keep") with no tracking progress record becomes a pending
    # decision under Stage 1's heuristic, so it surfaces in the scope's next-hint - "keep" decisions
    # are deliberately treated as needing no follow-up and would not appear here.
    _write(memory_store, project_id, category=ProjectMemoryCategory.DECISION, scope="living_room",
           subject="tv_stand", slot="disposition", value="replace with warm wood")
    records = memory_store.list_records(project_id)

    class ExplodingSelectionService:
        def select(self, **kwargs):
            raise AssertionError("Selection call must not fire for a deterministic continuation match.")

    result = retrieve_memory_context(
        project_id=project_id, records=records, question_text="Where did we leave off?",
        current_state_service=ProjectCurrentStateService(salience_client=None),
        selection_service=ExplodingSelectionService())
    assert result.intent == "continuation"
    assert "tv_stand" in result.context_text


def test_retrieve_memory_context_falls_back_to_selection_service(tmp_path):
    memory_store, project_id = _store(tmp_path)
    _write(memory_store, project_id, category=ProjectMemoryCategory.DECISION, scope="living_room",
           subject="tv_stand", slot="disposition", value="replace with warm wood")
    records = memory_store.list_records(project_id)

    class FakeSelectionService:
        def select(self, **kwargs):
            return MemorySelection(intent="historical", scope="living_room", subject="tv_stand")

    result = retrieve_memory_context(
        project_id=project_id, records=records, question_text="Why did that change?",
        selection_service=FakeSelectionService())
    assert result.intent == "historical"
    assert result.subject == "tv_stand"
    assert "replace with warm wood" in result.context_text


def test_retrieve_memory_context_abstains_when_selection_service_returns_none(tmp_path):
    memory_store, project_id = _store(tmp_path)
    _write(memory_store, project_id, subject="budget", value="$1,500")
    records = memory_store.list_records(project_id)

    class AbstainingSelectionService:
        def select(self, **kwargs):
            return None

    result = retrieve_memory_context(
        project_id=project_id, records=records, question_text="How's the weather?",
        selection_service=AbstainingSelectionService())
    assert result.context_text is None
    assert result.intent is None
