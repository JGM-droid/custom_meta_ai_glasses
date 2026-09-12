"""Stage 2 - Integrated Persistent Memory Shadow Slice: deterministic unit
tests + fake-provider extraction tests.

Focused, not maximized - proves the specific invariants the Stage 0/1
falsification gates found necessary: modality-aware supersession, no false
supersession across distinct subjects/slots, progress projection/completion/
reopening, scope-bounded Current Project State (blockers always retained,
resolved scopes collapsed, no AI call needed below the salience threshold).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from projects import (
    PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
    ProjectActivitySourceType,
    ProjectMemoryCandidate,
    ProjectMemoryCategory,
    ProjectMemoryExtractionService,
    ProjectMemoryModality,
    ProjectMemoryProgressState,
    ProjectMemoryRecord,
    ProjectMemoryStatus,
    ProjectMemoryStore,
    ProjectStore,
)
from projects.project_current_state import ProjectCurrentStateService, build_scope_state


def _store(tmp_path: Path) -> tuple[ProjectStore, ProjectMemoryStore, str]:
    projects_root = tmp_path / "projects"
    project_store = ProjectStore(projects_root)
    memory_store = ProjectMemoryStore(projects_root, project_store)
    project = project_store.create_project(name="Living Room", goal="Redesign it")
    return project_store, memory_store, project.project_id


def _candidate(**overrides) -> ProjectMemoryCandidate:
    base = dict(category=ProjectMemoryCategory.FACT, scope="overall", subject="budget",
                slot="amount", value="$1,500", modality=ProjectMemoryModality.COMMITTED)
    base.update(overrides)
    return ProjectMemoryCandidate(**base)


# ---------------------------------------------------------------------------
# A. Deterministic unit tests
# ---------------------------------------------------------------------------

def test_schema_rejects_progress_state_on_non_progress_category():
    with pytest.raises(ValidationError):
        ProjectMemoryRecord(
            schema_version=PROJECT_MEMORY_RECORD_SCHEMA_VERSION, memory_id="11111111-1111-1111-1111-111111111111",
            project_id="22222222-2222-2222-2222-222222222222", category=ProjectMemoryCategory.DECISION,
            scope="overall", subject="tv_stand", slot="disposition", value="keep",
            modality=ProjectMemoryModality.COMMITTED, status=ProjectMemoryStatus.CURRENT,
            progress_state=ProjectMemoryProgressState.STARTED, source_type=ProjectActivitySourceType.USER,
            occurred_at_utc=datetime.now(timezone.utc), created_at_utc=datetime.now(timezone.utc),
        )


def test_schema_requires_progress_state_on_progress_category():
    with pytest.raises(ValidationError):
        ProjectMemoryRecord(
            schema_version=PROJECT_MEMORY_RECORD_SCHEMA_VERSION, memory_id="11111111-1111-1111-1111-111111111111",
            project_id="22222222-2222-2222-2222-222222222222", category=ProjectMemoryCategory.PROGRESS,
            scope="overall", subject="rug", slot="procurement", value="ordered",
            modality=ProjectMemoryModality.COMMITTED, status=ProjectMemoryStatus.CURRENT,
            source_type=ProjectActivitySourceType.USER,
            occurred_at_utc=datetime.now(timezone.utc), created_at_utc=datetime.now(timezone.utc),
        )


def test_schema_requires_superseded_by_when_status_superseded():
    with pytest.raises(ValidationError):
        ProjectMemoryRecord(
            schema_version=PROJECT_MEMORY_RECORD_SCHEMA_VERSION, memory_id="11111111-1111-1111-1111-111111111111",
            project_id="22222222-2222-2222-2222-222222222222", category=ProjectMemoryCategory.FACT,
            scope="overall", subject="budget", slot="amount", value="$1,500",
            modality=ProjectMemoryModality.COMMITTED, status=ProjectMemoryStatus.SUPERSEDED,
            source_type=ProjectActivitySourceType.USER,
            occurred_at_utc=datetime.now(timezone.utc), created_at_utc=datetime.now(timezone.utc),
        )


def test_supersession_replaces_current_committed_fact(tmp_path):
    _, memory, project_id = _store(tmp_path)
    first = memory.write_candidate(project_id, _candidate(value="$1,500"),
                                    source_type=ProjectActivitySourceType.USER, source_turn_id=None)
    second = memory.write_candidate(project_id, _candidate(value="$2,000"),
                                     source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    records = {r.memory_id: r for r in memory.list_records(project_id)}
    assert records[first.memory_id].status == ProjectMemoryStatus.SUPERSEDED
    assert records[first.memory_id].superseded_by == second.memory_id
    assert records[second.memory_id].status == ProjectMemoryStatus.CURRENT
    # History preserved, not deleted.
    assert len(memory.list_records(project_id)) == 2


def test_modality_aware_supersession_tentative_does_not_replace_committed(tmp_path):
    _, memory, project_id = _store(tmp_path)
    committed = memory.write_candidate(project_id, _candidate(value="$1,500"),
                                        source_type=ProjectActivitySourceType.USER, source_turn_id=None)
    memory.write_candidate(
        project_id, _candidate(value="maybe $1,750", modality=ProjectMemoryModality.TENTATIVE),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    records = memory.list_records(project_id)
    still_current = [r for r in records if r.status == ProjectMemoryStatus.CURRENT
                      and r.modality == ProjectMemoryModality.COMMITTED]
    assert len(still_current) == 1
    assert still_current[0].memory_id == committed.memory_id
    assert still_current[0].value == "$1,500"


def test_modality_aware_supersession_committed_ignores_prior_tentative(tmp_path):
    """A tentative record must never be treated as "the thing being corrected"
    - a later committed write should supersede the last COMMITTED record, not
    the tentative aside, even though the tentative one is more recent."""
    _, memory, project_id = _store(tmp_path)
    original = memory.write_candidate(project_id, _candidate(value="$1,500"),
                                       source_type=ProjectActivitySourceType.USER, source_turn_id=None)
    memory.write_candidate(
        project_id, _candidate(value="maybe $1,750", modality=ProjectMemoryModality.TENTATIVE),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)
    new_committed = memory.write_candidate(project_id, _candidate(value="$2,000"),
                                            source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    records = {r.memory_id: r for r in memory.list_records(project_id)}
    assert records[original.memory_id].status == ProjectMemoryStatus.SUPERSEDED
    assert records[original.memory_id].superseded_by == new_committed.memory_id


def test_no_false_supersession_across_distinct_slots_same_subject(tmp_path):
    _, memory, project_id = _store(tmp_path)
    disposition = memory.write_candidate(
        project_id, _candidate(category=ProjectMemoryCategory.DECISION, subject="tv_stand",
                                slot="disposition", value="replace"),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)
    style = memory.write_candidate(
        project_id, _candidate(category=ProjectMemoryCategory.DECISION, subject="tv_stand",
                                slot="style_choice", value="warm wood"),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    records = {r.memory_id: r for r in memory.list_records(project_id)}
    assert records[disposition.memory_id].status == ProjectMemoryStatus.CURRENT
    assert records[style.memory_id].status == ProjectMemoryStatus.CURRENT


def test_progress_projection_completion_and_reopening(tmp_path):
    _, memory, project_id = _store(tmp_path)
    memory.write_candidate(
        project_id, _candidate(category=ProjectMemoryCategory.PROGRESS, subject="drywall",
                                slot="status", value="completed", progress_state=ProjectMemoryProgressState.COMPLETED),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)
    reopened = memory.write_candidate(
        project_id, _candidate(category=ProjectMemoryCategory.PROGRESS, subject="drywall",
                                slot="status", value="defect found, reopened",
                                progress_state=ProjectMemoryProgressState.REOPENED),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    # Progress is append-only - both events preserved, never superseded.
    records = memory.list_records(project_id)
    assert len(records) == 2
    assert all(r.status == ProjectMemoryStatus.CURRENT for r in records)

    scope_state = build_scope_state(records, "overall")
    assert any("reopened" in item for item in scope_state.active_progress)
    assert scope_state.recently_completed == []  # latest event is reopened, not completed
    assert any(reopened.value in item for item in scope_state.recent_changes)


def test_cancellation_no_longer_required_via_decision_supersession(tmp_path):
    """'We don't need to replace that panel anymore' - modeled as a decision
    supersession (replace -> no longer required), not a destructive edit."""
    _, memory, project_id = _store(tmp_path)
    original = memory.write_candidate(
        project_id, _candidate(category=ProjectMemoryCategory.DECISION, subject="panel",
                                slot="disposition", value="replace"),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)
    cancelled = memory.write_candidate(
        project_id, _candidate(category=ProjectMemoryCategory.DECISION, subject="panel",
                                slot="disposition", value="no longer required"),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    records = memory.list_records(project_id)
    current = build_scope_state(records, "overall")
    assert any("no longer required" in d for d in current.decisions)
    assert not any(d for d in current.decisions if "replace" in d and "no longer" not in d)

    by_id = {r.memory_id: r for r in records}
    assert by_id[original.memory_id].status == ProjectMemoryStatus.SUPERSEDED
    assert by_id[original.memory_id].superseded_by == cancelled.memory_id
    # History question ("didn't we originally plan to replace it?") remains answerable.
    assert by_id[original.memory_id].value == "replace"


def test_blocker_always_retained_in_current_state(tmp_path):
    _, memory, project_id = _store(tmp_path)
    memory.write_candidate(
        project_id, _candidate(category=ProjectMemoryCategory.PROGRESS, scope="electrical",
                                subject="lobby_panel", slot="status", value="breaker issue, inspection blocked",
                                progress_state=ProjectMemoryProgressState.BLOCKED, is_blocker=True),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    records = memory.list_records(project_id)
    service = ProjectCurrentStateService(salience_client=None)
    state = service.get_current_state(project_id, records)
    assert any("lobby_panel" in b for b in state.global_blockers)
    assert any("electrical" in s for s in state.scope_summaries)


def test_resolved_scope_collapses_out_of_global_summary(tmp_path):
    _, memory, project_id = _store(tmp_path)
    memory.write_candidate(
        project_id, _candidate(category=ProjectMemoryCategory.PROGRESS, scope="kitchen",
                                subject="plumbing", slot="status", value="fixed",
                                progress_state=ProjectMemoryProgressState.COMPLETED),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    records = memory.list_records(project_id)
    service = ProjectCurrentStateService(salience_client=None)
    state = service.get_current_state(project_id, records)
    assert not any("kitchen" in s for s in state.scope_summaries)
    assert state.resolved_scope_count == 1


def test_scoped_view_excludes_other_scope_detail(tmp_path):
    _, memory, project_id = _store(tmp_path)
    memory.write_candidate(
        project_id, _candidate(category=ProjectMemoryCategory.DECISION, scope="living_room",
                                subject="couch", slot="disposition", value="keep"),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)
    memory.write_candidate(
        project_id, _candidate(category=ProjectMemoryCategory.DECISION, scope="kitchen",
                                subject="cabinets", slot="disposition", value="replace"),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    records = memory.list_records(project_id)
    service = ProjectCurrentStateService(salience_client=None)
    living_room = service.get_current_state(project_id, records, scope="living_room")
    assert "living_room" in living_room.scope_detail
    assert any("couch" in d for d in living_room.scope_detail["living_room"].decisions)
    assert not any("cabinets" in d for d in living_room.scope_detail["living_room"].decisions)


def test_provenance_preserved(tmp_path):
    _, memory, project_id = _store(tmp_path)
    record = memory.write_candidate(project_id, _candidate(), source_type=ProjectActivitySourceType.USER,
                                     source_turn_id="33333333-3333-3333-3333-333333333333")
    assert record.source_turn_id == "33333333-3333-3333-3333-333333333333"
    assert record.source_type == ProjectActivitySourceType.USER


def test_no_ai_call_below_salience_threshold(tmp_path):
    """A small number of active scopes must not trigger the salience call at
    all - AI selects among already-eligible candidates only when genuinely
    needed, per the Stage 1 finding."""
    _, memory, project_id = _store(tmp_path)
    memory.write_candidate(
        project_id, _candidate(category=ProjectMemoryCategory.PROGRESS, scope="living_room",
                                subject="rug", slot="procurement", value="ordered",
                                progress_state=ProjectMemoryProgressState.STARTED),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    class ExplodingClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise AssertionError("Salience call must not fire below the threshold.")

    service = ProjectCurrentStateService(salience_client=ExplodingClient())
    state = service.get_current_state(project_id, memory.list_records(project_id))
    assert state.salience_call_used is False
    assert any("living_room" in s for s in state.scope_summaries)


# ---------------------------------------------------------------------------
# B. Fake-provider extraction tests
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [type("_C", (), {"message": type("_M", (), {"content": content})()})()]


class _FakeCompletions:
    def __init__(self, payload: str):
        self._payload = payload
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        return _FakeResponse(self._payload)


class _FakeChat:
    def __init__(self, completions: _FakeCompletions):
        self.completions = completions


class _FakeClient:
    def __init__(self, payload: str):
        self.completions = _FakeCompletions(payload)
        self.chat = _FakeChat(self.completions)


def _extraction_service(payload: str) -> tuple[ProjectMemoryExtractionService, _FakeClient]:
    fake = _FakeClient(payload)
    service = ProjectMemoryExtractionService(api_key="test-key", client_factory=lambda **_: fake)
    return service, fake


def test_extraction_parses_valid_candidates():
    payload = json.dumps({"candidates": [
        {"category": "constraint", "scope": "overall", "subject": "budget", "slot": "amount",
         "value": "$1,500", "modality": "committed"},
    ]})
    service, fake = _extraction_service(payload)
    candidates = service.extract("My budget is $1,500.")
    assert len(candidates) == 1
    assert candidates[0].subject == "budget"
    assert fake.completions.call_count == 1  # exactly one provider call per eligible turn


def test_extraction_discards_one_malformed_candidate_without_dropping_the_rest():
    payload = json.dumps({"candidates": [
        {"category": "not_a_real_category", "subject": "x", "value": "y", "modality": "committed"},
        {"category": "fact", "subject": "dog", "value": "has a dog", "modality": "committed"},
    ]})
    service, _ = _extraction_service(payload)
    candidates = service.extract("We have a dog.")
    assert len(candidates) == 1
    assert candidates[0].subject == "dog"


def test_extraction_returns_empty_for_no_candidates():
    service, fake = _extraction_service(json.dumps({"candidates": []}))
    candidates = service.extract("Where did we leave off?")
    assert candidates == []
    assert fake.completions.call_count == 1


def test_extraction_abstains_on_empty_text_without_calling_provider():
    service, fake = _extraction_service(json.dumps({"candidates": []}))
    candidates = service.extract("   ")
    assert candidates == []
    assert fake.completions.call_count == 0


# ---------------------------------------------------------------------------
# ABC Apartments structural test: one canonical substrate, many scoped views.
# Deterministic, no provider - proves scope isolation across a Project with
# several simultaneous workstreams/areas, per Stage 2's hierarchical-scope
# requirement (item 9/15).
# ---------------------------------------------------------------------------

def test_abc_apartments_scope_isolation(tmp_path):
    _, memory, project_id = _store(tmp_path)

    def write(**kwargs):
        return memory.write_candidate(project_id, _candidate(**kwargs),
                                       source_type=ProjectActivitySourceType.USER, source_turn_id=None)

    # Living Room: painting is active.
    write(category=ProjectMemoryCategory.PROGRESS, scope="living_room", subject="painting",
          slot="status", value="in progress", progress_state=ProjectMemoryProgressState.STARTED)

    # Kitchen: plumbing is active.
    write(category=ProjectMemoryCategory.PROGRESS, scope="kitchen", subject="plumbing",
          slot="status", value="in progress", progress_state=ProjectMemoryProgressState.STARTED)

    # Unit 412 / Electrical: light switch completed, but an inspection blocker is active.
    write(category=ProjectMemoryCategory.PROGRESS, scope="unit_412/electrical", subject="light_switch",
          slot="status", value="completed", progress_state=ProjectMemoryProgressState.COMPLETED)
    write(category=ProjectMemoryCategory.PROGRESS, scope="unit_412/electrical", subject="inspection",
          slot="status", value="failed safety check, blocked", progress_state=ProjectMemoryProgressState.BLOCKED,
          is_blocker=True)

    # Unit 306 / Drywall: fully completed, should collapse out of the global summary.
    write(category=ProjectMemoryCategory.PROGRESS, scope="unit_306/drywall", subject="drywall",
          slot="status", value="completed", progress_state=ProjectMemoryProgressState.COMPLETED)

    records = memory.list_records(project_id)
    service = ProjectCurrentStateService(salience_client=None)

    overall = service.get_current_state(project_id, records)
    assert any("light_switch" not in b and "unit_412/electrical" in b for b in overall.global_blockers)
    assert any("living_room" in s for s in overall.scope_summaries)
    assert any("kitchen" in s for s in overall.scope_summaries)
    assert any("unit_412/electrical" in s for s in overall.scope_summaries)
    assert not any("unit_306/drywall" in s for s in overall.scope_summaries)
    assert overall.resolved_scope_count == 1  # unit_306/drywall only

    living_room = service.get_current_state(project_id, records, scope="living_room")
    lr_detail = living_room.scope_detail["living_room"]
    assert any("painting" in p for p in lr_detail.active_progress)
    assert not any("plumbing" in p for p in lr_detail.active_progress)
    assert not any("light_switch" in p for p in lr_detail.active_progress)

    kitchen = service.get_current_state(project_id, records, scope="kitchen")
    kitchen_detail = kitchen.scope_detail["kitchen"]
    assert any("plumbing" in p for p in kitchen_detail.active_progress)
    assert not any("painting" in p for p in kitchen_detail.active_progress)

    unit_412 = service.get_current_state(project_id, records, scope="unit_412/electrical")
    unit_412_detail = unit_412.scope_detail["unit_412/electrical"]
    assert any("inspection" in b for b in unit_412_detail.blockers)
    assert any("light_switch" in c for c in unit_412_detail.recently_completed)
    # Cross-location scoping (electrical across locations would be a future composite scope key,
    # not implemented here) - confirm this single-location scope stays isolated from unit_306.
    assert not any("drywall" in p for p in unit_412_detail.active_progress + unit_412_detail.recently_completed)

    unit_306 = service.get_current_state(project_id, records, scope="unit_306/drywall")
    unit_306_detail = unit_306.scope_detail["unit_306/drywall"]
    assert any("drywall" in c for c in unit_306_detail.recently_completed)
    assert unit_306_detail.status == "resolved"
