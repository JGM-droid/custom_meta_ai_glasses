"""Stage 5 repair (Fix 3): subject-identity stabilization.

Deterministic tests prove the bounded known-subject-hint plumbing (extract() signature, hint
construction, backward compatibility). Real-provider tests prove the actual semantic reuse/
abstention judgment the hints are meant to improve - deliberately small (item: "no giant matrix").
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import api
from projects import (
    ProjectActivitySourceType,
    ProjectMemoryCandidate,
    ProjectMemoryCategory,
    ProjectMemoryExtractionService,
    ProjectMemoryModality,
    ProjectMemoryStore,
    ProjectStore,
)
from projects.memory_retrieval import known_subject_hints


def _store(tmp_path: Path):
    projects_root = tmp_path / "projects"
    project_store = ProjectStore(projects_root)
    memory_store = ProjectMemoryStore(projects_root, project_store)
    project = project_store.create_project(name="t", goal="g")
    return memory_store, project.project_id


def _write(memory_store, project_id, **overrides):
    base = dict(category=ProjectMemoryCategory.PROGRESS, scope="living_room",
                subject="wall_painting", slot="status", value="done",
                modality=ProjectMemoryModality.COMMITTED,
                progress_state=__import__("projects").ProjectMemoryProgressState.COMPLETED)
    base.update(overrides)
    return memory_store.write_candidate(
        project_id, ProjectMemoryCandidate(**base),
        source_type=ProjectActivitySourceType.USER, source_turn_id=None)


# ---------------------------------------------------------------------------
# Deterministic: known_subject_hints() construction
# ---------------------------------------------------------------------------

def test_known_subject_hints_bounded_and_most_recent_first(tmp_path):
    memory_store, project_id = _store(tmp_path)
    base = datetime.now(timezone.utc) - timedelta(days=1)
    for i in range(25):
        memory_store.write_candidate(
            project_id, ProjectMemoryCandidate(
                category=ProjectMemoryCategory.FACT, scope="overall", subject=f"topic{i}",
                slot="value", value=f"value {i}", modality=ProjectMemoryModality.COMMITTED),
            source_type=ProjectActivitySourceType.USER, source_turn_id=None,
            occurred_at_utc=base + timedelta(minutes=i))
    records = memory_store.list_records(project_id)
    hints = known_subject_hints(records)
    assert len(hints) == 20  # _MAX_KNOWN_SUBJECT_HINTS
    assert hints[0][1] == "topic24"  # most recent first


def test_known_subject_hints_excludes_noncommitted_and_superseded(tmp_path):
    memory_store, project_id = _store(tmp_path)
    _write(memory_store, project_id, subject="budget", slot="amount", value="$1,500",
           category=ProjectMemoryCategory.FACT, progress_state=None)
    _write(memory_store, project_id, subject="hunch", slot="value", value="maybe more",
           category=ProjectMemoryCategory.FACT, progress_state=None,
           modality=ProjectMemoryModality.TENTATIVE)
    records = memory_store.list_records(project_id)
    hints = known_subject_hints(records)
    subjects = {s for _, s, _, _ in hints}
    assert "budget" in subjects
    assert "hunch" not in subjects


# ---------------------------------------------------------------------------
# Deterministic: extract() signature/backward compatibility
# ---------------------------------------------------------------------------

class _FakeCompletions:
    def __init__(self, payload: str):
        self._payload = payload
        self.last_user_content: str | None = None

    def create(self, **kwargs):
        self.last_user_content = kwargs["messages"][-1]["content"]
        return type("_R", (), {"choices": [type("_C", (), {
            "message": type("_M", (), {"content": self._payload})()})()]})()


class _FakeClient:
    def __init__(self, payload: str):
        self.completions = _FakeCompletions(payload)
        self.chat = type("_Chat", (), {"completions": self.completions})()


def test_extract_without_known_subjects_preserves_plain_message_shape():
    import json
    fake = _FakeClient(json.dumps({"candidates": []}))
    service = ProjectMemoryExtractionService(api_key="test-key", client_factory=lambda **_: fake)
    service.extract("Some message.")
    assert fake.completions.last_user_content == "Some message."


def test_extract_with_known_subjects_includes_bounded_hint_block():
    import json
    fake = _FakeClient(json.dumps({"candidates": []}))
    service = ProjectMemoryExtractionService(api_key="test-key", client_factory=lambda **_: fake)
    service.extract("Actually only halfway done.", [("living_room", "wall_painting", "status", "done")])
    assert "living_room/wall_painting/status" in fake.completions.last_user_content
    assert "Actually only halfway done." in fake.completions.last_user_content


def test_extract_with_empty_known_subjects_list_preserves_plain_shape():
    import json
    fake = _FakeClient(json.dumps({"candidates": []}))
    service = ProjectMemoryExtractionService(api_key="test-key", client_factory=lambda **_: fake)
    service.extract("Some message.", [])
    assert fake.completions.last_user_content == "Some message."


# ---------------------------------------------------------------------------
# Real-provider: items D (reuse same task), E (cross-domain), F (trust preserved)
# ---------------------------------------------------------------------------

_API_KEY = api._load_openai_api_key()
pytestmark_real = pytest.mark.skipif(not _API_KEY, reason="OPENAI_API_KEY not configured")


@pytest.fixture(scope="module")
def extraction_service():
    return ProjectMemoryExtractionService(api_key=_API_KEY)


@pytestmark_real
def test_d_progress_correction_reuses_same_canonical_subject(extraction_service):
    known = [("living_room", "wall_painting", "status", "done")]
    candidates = extraction_service.extract("Actually I'm only halfway done.", known)
    assert len(candidates) >= 1
    reused = [c for c in candidates if c.subject == "wall_painting" and c.scope == "living_room"]
    assert reused, f"expected reuse of living_room/wall_painting, got {[(c.scope, c.subject) for c in candidates]}"
    assert reused[0].slot == "status", (
        f"expected the update to land on the EXISTING 'status' slot, not a new one, got slot={reused[0].slot!r}")


@pytestmark_real
def test_e_cross_domain_subject_reuse_server(extraction_service):
    known = [("overall", "server", "disposition", "keep old server")]
    candidates = extraction_service.extract("Actually replace the old server with the new Dell.", known)
    assert len(candidates) >= 1
    reused = [c for c in candidates if c.subject == "server"]
    assert reused, f"expected reuse of 'server', got {[(c.scope, c.subject) for c in candidates]}"
    assert reused[0].modality.value == "committed"
    assert reused[0].slot == "disposition"


@pytestmark_real
def test_e_cross_domain_subject_reuse_faucet(extraction_service):
    known = [("kitchen", "faucet", "disposition", "keep")]
    candidates = extraction_service.extract("Replace it with the brass one.", known)
    # May reuse "faucet" (good) or abstain if "it" is judged ambiguous without more context - both
    # are safe; the only unsafe outcome is inventing an unrelated new subject for the same item.
    if candidates:
        assert any(c.subject == "faucet" for c in candidates)


@pytestmark_real
def test_f_known_subject_hints_do_not_weaken_tentative_abstention(extraction_service):
    known = [("overall", "budget", "amount", "$1,500")]
    candidates = extraction_service.extract("Maybe I could stretch the budget to $1,750, I'm not sure.", known)
    assert all(c.modality.value != "committed" for c in candidates if c.subject == "budget")


@pytestmark_real
def test_f_known_subject_hints_do_not_weaken_third_party_abstention(extraction_service):
    known = [("living_room", "couch", "disposition", "keep")]
    candidates = extraction_service.extract("My friend thinks I should get rid of the couch.", known)
    assert all(c.modality.value != "committed" for c in candidates if c.subject == "couch")


@pytestmark_real
def test_f_known_subject_hints_do_not_weaken_ambiguous_plural_abstention(extraction_service):
    known = [
        ("living_room", "couch", "disposition", "keep"),
        ("living_room", "tv_stand", "disposition", "replace with warm wood"),
    ]
    candidates = extraction_service.extract("Those are both already done.", known)
    assert candidates == []


@pytestmark_real
def test_f_known_subject_hints_do_not_force_merge_of_distinct_progress_items(extraction_service):
    """The over-eager-merge regression found during Stage 5 repair verification: a genuinely
    different, additional task in the same area must get its own subject, not overwrite an
    existing blocker's progress state."""
    known = [("electrical", "wiring_issue", "status", "blocking electrician from finishing")]
    candidates = extraction_service.extract("We still need to fix the outlet near the window.", known)
    assert candidates, "expected at least one candidate"
    assert all(c.subject != "wiring_issue" for c in candidates), (
        f"outlet task must not overwrite the wiring_issue blocker subject, got "
        f"{[(c.scope, c.subject, c.value) for c in candidates]}")
