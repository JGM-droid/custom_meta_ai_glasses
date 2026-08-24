from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api as api_module

from projects import (
    CheckpointProposalStore,
    ProjectActivityConfirmationStatus,
    ProjectActivitySourceType,
    ProjectActivityStore,
    ProjectCheckpoint,
    ProjectProgressCheckpointPatch,
    ProjectProgressIdempotencyConflict,
    ProjectProgressRecoveryConflict,
    ProjectProgressRequest,
    ProjectProgressService,
    ProjectRevisionConflict,
    ProjectStore,
)


def _service(root: Path):
    projects = ProjectStore(root)
    activities = ProjectActivityStore(root, projects)
    proposals = CheckpointProposalStore(root, projects, activities)
    return projects, activities, proposals, ProjectProgressService(projects, activities, proposals)


def _request(key: str = "attempt-1", **changes) -> ProjectProgressRequest:
    values = dict(
        idempotency_key=key,
        summary="I replaced the capacitor.",
        details="The unit powers on now.",
        expected_project_revision=0,
        checkpoint_patch=None,
    )
    values.update(changes)
    return ProjectProgressRequest(**values)


def test_preview_is_read_only_and_noop_checkpoint_change_creates_no_proposal(tmp_path: Path) -> None:
    projects, activities, proposals, service = _service(tmp_path)
    project = projects.create_project(
        name="AC Repair",
        goal="Restore cooling",
        checkpoint=ProjectCheckpoint(current_work="Capacitor removed"),
    )
    request = _request(
        checkpoint_patch=ProjectProgressCheckpointPatch(current_work="Capacitor removed")
    )

    preview = service.preview(project.project_id, request)

    assert preview.proposal_required is False
    assert preview.effective_checkpoint_patch is None
    assert activities.list_activities(project.project_id) == []
    assert proposals.list_proposals(project.project_id) == []
    assert projects.load_project(project.project_id).revision == 0


def test_save_records_one_user_activity_without_mutating_project(tmp_path: Path) -> None:
    projects, activities, proposals, service = _service(tmp_path)
    project = projects.create_project(name="AC Repair", goal="Restore cooling")

    result = service.save(project.project_id, _request())

    assert result.proposal is None
    assert result.activity.source_type == ProjectActivitySourceType.USER
    assert result.activity.confirmation_status == ProjectActivityConfirmationStatus.REPORTED
    assert len(activities.list_activities(project.project_id)) == 1
    assert proposals.list_proposals(project.project_id) == []
    unchanged = projects.load_project(project.project_id)
    assert unchanged.revision == 0
    assert unchanged.checkpoint.current_work is None


def test_changed_checkpoint_creates_separate_pending_proposal_and_equivalent_retry_converges(
    tmp_path: Path,
) -> None:
    projects, activities, proposals, service = _service(tmp_path)
    project = projects.create_project(name="AC Repair", goal="Restore cooling")
    request = _request(
        checkpoint_patch=ProjectProgressCheckpointPatch(
            current_work="New capacitor installed",
            next_action="Test cooling",
        )
    )

    first = service.save(project.project_id, request)
    second = service.save(project.project_id, request)

    assert first.activity.activity_id == second.activity.activity_id
    assert first.proposal is not None and second.proposal is not None
    assert first.proposal.proposal_id == second.proposal.proposal_id
    assert second.reconstructed is True
    assert first.proposal.source_activity_ids == [first.activity.activity_id]
    assert len(activities.list_activities(project.project_id)) == 1
    assert len(proposals.list_proposals(project.project_id)) == 1
    assert projects.load_project(project.project_id).revision == 0


def test_conflicting_key_reuse_is_rejected_without_duplicate_records(tmp_path: Path) -> None:
    projects, activities, proposals, service = _service(tmp_path)
    project = projects.create_project(name="AC Repair", goal="Restore cooling")
    service.save(project.project_id, _request())

    with pytest.raises(ProjectProgressIdempotencyConflict):
        service.save(project.project_id, _request(summary="That did not fix it."))

    assert len(activities.list_activities(project.project_id)) == 1
    assert proposals.list_proposals(project.project_id) == []


def test_equivalent_concurrent_retries_converge(tmp_path: Path) -> None:
    projects, activities, proposals, service = _service(tmp_path)
    project = projects.create_project(name="AC Repair", goal="Restore cooling")
    request = _request(
        checkpoint_patch=ProjectProgressCheckpointPatch(blockers="Cooling still fails")
    )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.save(project.project_id, request), range(16)))

    assert len({item.activity.activity_id for item in results}) == 1
    assert len({item.proposal.proposal_id for item in results if item.proposal}) == 1
    assert len(activities.list_activities(project.project_id)) == 1
    assert len(proposals.list_proposals(project.project_id)) == 1


def test_restart_reconstructs_and_same_key_is_isolated_by_project(tmp_path: Path) -> None:
    projects, activities, proposals, service = _service(tmp_path)
    project_a = projects.create_project(name="A", goal="A goal")
    project_b = projects.create_project(name="B", goal="B goal")
    request = _request(key="same-key")
    a = service.save(project_a.project_id, request)
    b = service.save(project_b.project_id, request)

    _, restarted_activities, _, restarted = _service(tmp_path)
    reconstructed = restarted.save(project_a.project_id, request)

    assert a.activity.activity_id != b.activity.activity_id
    assert reconstructed.activity.activity_id == a.activity.activity_id
    assert len(restarted_activities.list_activities(project_a.project_id)) == 1
    assert len(restarted_activities.list_activities(project_b.project_id)) == 1


def test_stale_first_attempt_writes_nothing_and_active_project_is_unchanged(tmp_path: Path) -> None:
    projects, activities, proposals, service = _service(tmp_path)
    active = projects.create_project(name="Active", goal="Stay active")
    target = projects.create_project(name="Target", goal="Record progress")
    projects.set_active_project(active.project_id)

    with pytest.raises(ProjectRevisionConflict):
        service.save(target.project_id, _request(expected_project_revision=2))

    assert activities.list_activities(target.project_id) == []
    assert proposals.list_proposals(target.project_id) == []
    assert projects.get_active_project().project_id == active.project_id


def test_long_supported_checkpoint_text_does_not_overflow_activity_metadata(tmp_path: Path) -> None:
    projects, activities, proposals, service = _service(tmp_path)
    project = projects.create_project(name="Long note", goal="Exercise bounded fields")
    long_current_work = "x" * 1200

    result = service.save(
        project.project_id,
        _request(checkpoint_patch=ProjectProgressCheckpointPatch(current_work=long_current_work)),
    )

    assert result.proposal is not None
    assert result.proposal.proposed_checkpoint_patch.current_work == long_current_work
    assert len(activities.list_activities(project.project_id)) == 1
    assert len(proposals.list_proposals(project.project_id)) == 1


def test_retry_completes_proposal_after_activity_only_partial_write(tmp_path: Path, monkeypatch) -> None:
    projects, activities, proposals, service = _service(tmp_path)
    project = projects.create_project(name="Recovery", goal="Recover partial progress")
    request = _request(checkpoint_patch=ProjectProgressCheckpointPatch(next_action="Test again"))
    original_save = proposals._save_proposal_no_lock
    failed = False

    def fail_once(proposal):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("simulated proposal write loss")
        return original_save(proposal)

    monkeypatch.setattr(proposals, "_save_proposal_no_lock", fail_once)
    with pytest.raises(OSError):
        service.save(project.project_id, request)

    recovered = service.save(project.project_id, request)
    assert recovered.reconstructed is True
    assert recovered.proposal is not None
    assert len(activities.list_activities(project.project_id)) == 1
    assert len(proposals.list_proposals(project.project_id)) == 1


def test_partial_write_does_not_rebase_if_project_revision_advanced(tmp_path: Path, monkeypatch) -> None:
    projects, activities, proposals, service = _service(tmp_path)
    project = projects.create_project(name="Recovery conflict", goal="Stay honest")
    request = _request(checkpoint_patch=ProjectProgressCheckpointPatch(blockers="Waiting on a part"))

    monkeypatch.setattr(
        proposals,
        "_save_proposal_no_lock",
        lambda proposal: (_ for _ in ()).throw(OSError("simulated proposal failure")),
    )
    with pytest.raises(OSError):
        service.save(project.project_id, request)

    monkeypatch.undo()
    projects.mutate_project(
        project.project_id,
        expected_revision=0,
        mutator=lambda current: (
            current.model_copy(
                update={
                    "checkpoint": ProjectCheckpoint(next_action="Someone else changed this Project"),
                    "revision": current.revision + 1,
                    "updated_at_utc": datetime.now(timezone.utc),
                }
            ),
            True,
        ),
    )

    with pytest.raises(ProjectProgressRecoveryConflict):
        service.save(project.project_id, request)
    assert len(activities.list_activities(project.project_id)) == 1
    assert proposals.list_proposals(project.project_id) == []


def test_project_scoped_preview_and_save_api_contract(tmp_path: Path, monkeypatch) -> None:
    projects, activities, proposals, _ = _service(tmp_path)
    project = projects.create_project(name="API Project", goal="Record progress")
    monkeypatch.setattr(api_module, "PROJECT_STORE", projects)
    monkeypatch.setattr(api_module, "PROJECT_ACTIVITY_STORE", activities)
    monkeypatch.setattr(api_module, "CHECKPOINT_PROPOSAL_STORE", proposals)
    client = TestClient(api_module.app)
    payload = {
        "idempotency_key": "api-attempt",
        "summary": "I finished the backend.",
        "expected_project_revision": 0,
        "checkpoint_patch": {"next_action": "Connect Android"},
    }

    preview = client.post(f"/projects/{project.project_id}/progress/preview", json=payload)
    saved = client.post(f"/projects/{project.project_id}/progress", json=payload)
    retry = client.post(f"/projects/{project.project_id}/progress", json=payload)

    assert preview.status_code == 200
    assert preview.json()["proposal_required"] is True
    assert saved.status_code == 200
    assert saved.json()["activity"]["project_id"] == project.project_id
    assert saved.json()["proposal"]["project_id"] == project.project_id
    assert retry.status_code == 200
    assert retry.json()["activity"]["activity_id"] == saved.json()["activity"]["activity_id"]
    assert retry.json()["proposal"]["proposal_id"] == saved.json()["proposal"]["proposal_id"]
    assert retry.json()["reconstructed"] is True
