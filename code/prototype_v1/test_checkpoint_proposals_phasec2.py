from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import api
from projects import CheckpointProposalStore, ProjectActivityStore, ProjectStore


@pytest.fixture
def checkpoint_proposal_test_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    results_root = tmp_path / "results"
    projects_root = results_root / "projects"
    session_root = results_root / "investigation_sessions"

    project_store = ProjectStore(projects_root)
    activity_store = ProjectActivityStore(projects_root, project_store)
    proposal_store = CheckpointProposalStore(projects_root, project_store, activity_store)
    session_store = api.InvestigationSessionStore(session_root)

    monkeypatch.setattr(api, "RESULTS_DIR", results_root)
    monkeypatch.setattr(api, "PROJECTS_ROOT", projects_root)
    monkeypatch.setattr(api, "PROJECT_STORE", project_store)
    monkeypatch.setattr(api, "PROJECT_ACTIVITY_STORE", activity_store)
    monkeypatch.setattr(api, "CHECKPOINT_PROPOSAL_STORE", proposal_store)
    monkeypatch.setattr(api, "INVESTIGATION_SESSIONS_ROOT", session_root)
    monkeypatch.setattr(api, "SESSION_STORE", session_store)
    monkeypatch.setattr(api, "EVIDENCE_STORE", api.InvestigationEvidenceStore(session_store))
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", results_root / "investigation_latest.json")
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")

    client = TestClient(api.app)
    return client, project_store, activity_store, proposal_store, projects_root


def _create_project(client: TestClient, *, name: str, goal: str, checkpoint: dict[str, str] | None = None):
    payload: dict[str, object] = {"name": name, "goal": goal}
    if checkpoint is not None:
        payload["checkpoint"] = checkpoint
    response = client.post("/projects", json=payload)
    assert response.status_code == 201
    return response.json()


def _create_activity(
    client: TestClient,
    project_id: str,
    *,
    activity_type: str = "note",
    source_type: str = "user",
    confirmation_status: str = "reported",
    summary: str = "Captured finding",
):
    response = client.post(
        f"/projects/{project_id}/activities",
        json={
            "activity_type": activity_type,
            "source_type": source_type,
            "confirmation_status": confirmation_status,
            "summary": summary,
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_proposal(
    client: TestClient,
    project_id: str,
    *,
    expected_project_revision: int,
    source_activity_ids: list[str] | None = None,
    proposed_checkpoint_patch: dict[str, str] | None = None,
    reason: str = "Checkpoint update proposal",
):
    response = client.post(
        f"/projects/{project_id}/checkpoint-proposals",
        json={
            "expected_project_revision": expected_project_revision,
            "source_activity_ids": source_activity_ids or [],
            "proposed_checkpoint_patch": proposed_checkpoint_patch
            or {"next_action": "Collect additional evidence"},
            "reason": reason,
        },
    )
    return response


def _advance_project_to_revision(client: TestClient, project_id: str, target_revision: int):
    current = client.get(f"/projects/{project_id}").json()
    while current["revision"] < target_revision:
        patch = client.patch(
            f"/projects/{project_id}/checkpoint",
            json={
                "expected_revision": current["revision"],
                "next_action": f"rev-{current['revision'] + 1}",
            },
        )
        assert patch.status_code == 200
        current = patch.json()
    return current


def test_proposal_creation_no_project_mutation_and_persistence(checkpoint_proposal_test_context):
    client, _project_store, _activity_store, _proposal_store, projects_root = checkpoint_proposal_test_context
    project = _create_project(client, name="Project A", goal="Goal A")

    before = deepcopy(client.get(f"/projects/{project['project_id']}").json())

    create_resp = _create_proposal(
        client,
        project["project_id"],
        expected_project_revision=before["revision"],
        proposed_checkpoint_patch={"discoveries_summary": "Observed vibration pattern"},
    )
    assert create_resp.status_code == 201
    proposal = create_resp.json()

    assert proposal["proposal_id"]
    assert proposal["project_id"] == project["project_id"]
    assert proposal["base_project_revision"] == before["revision"]
    assert proposal["status"] == "pending"
    assert proposal["applied_at_utc"] is None
    assert proposal["rejected_at_utc"] is None

    after = client.get(f"/projects/{project['project_id']}").json()
    assert after["checkpoint"] == before["checkpoint"]
    assert after["revision"] == before["revision"]
    assert after["updated_at_utc"] == before["updated_at_utc"]

    proposal_file = projects_root / "checkpoint_proposals" / project["project_id"] / f"{proposal['proposal_id']}.json"
    assert proposal_file.exists()


def test_partial_patch_behavior_preserves_unspecified_fields(checkpoint_proposal_test_context):
    client, _project_store, _activity_store, _proposal_store, _projects_root = checkpoint_proposal_test_context
    project = _create_project(
        client,
        name="Project A",
        goal="Goal A",
        checkpoint={
            "completed_summary": "Checked thermostat",
            "discoveries_summary": "Capacitor visually suspicious.",
            "next_action": "Identify capacitor rating.",
        },
    )

    created = _create_proposal(
        client,
        project["project_id"],
        expected_project_revision=project["revision"],
        proposed_checkpoint_patch={
            "discoveries_summary": "Capacitor appears swollen; not yet confirmed.",
            "next_action": "Identify capacitor rating and test capacitance.",
        },
    )
    assert created.status_code == 201
    proposal_id = created.json()["proposal_id"]

    applied = client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal_id}/apply")
    assert applied.status_code == 200

    updated_project = client.get(f"/projects/{project['project_id']}").json()
    assert updated_project["checkpoint"]["completed_summary"] == "Checked thermostat"
    assert updated_project["checkpoint"]["discoveries_summary"] == "Capacitor appears swollen; not yet confirmed."
    assert updated_project["checkpoint"]["next_action"] == "Identify capacitor rating and test capacitance."


def test_acceptance_scenario_apply_and_equivalent_retry_converges(checkpoint_proposal_test_context):
    client, _project_store, _activity_store, _proposal_store, _projects_root = checkpoint_proposal_test_context
    project = _create_project(
        client,
        name="Upstairs AC Repair",
        goal="Restore reliable cooling upstairs.",
        checkpoint={
            "discoveries_summary": "Capacitor visually suspicious.",
            "next_action": "Identify capacitor rating.",
        },
    )
    project = _advance_project_to_revision(client, project["project_id"], 4)

    a1 = _create_activity(
        client,
        project["project_id"],
        activity_type="observation",
        source_type="ai",
        confirmation_status="inferred",
        summary="Capacitor appears swollen.",
    )

    created = _create_proposal(
        client,
        project["project_id"],
        expected_project_revision=4,
        source_activity_ids=[a1["activity_id"]],
        proposed_checkpoint_patch={
            "discoveries_summary": "Capacitor appears swollen; not yet confirmed.",
            "next_action": "Identify capacitor rating and test capacitance.",
        },
        reason="Update checkpoint based on latest inspection activity.",
    )
    assert created.status_code == 201
    proposal = created.json()

    before_apply = client.get(f"/projects/{project['project_id']}").json()
    assert before_apply["revision"] == 4
    assert proposal["status"] == "pending"

    applied = client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal['proposal_id']}/apply")
    assert applied.status_code == 200
    applied_body = applied.json()
    assert applied_body["status"] == "applied"
    assert applied_body["applied_at_utc"] is not None

    after_apply = client.get(f"/projects/{project['project_id']}").json()
    assert after_apply["checkpoint"]["discoveries_summary"] == "Capacitor appears swollen; not yet confirmed."
    assert after_apply["checkpoint"]["next_action"] == "Identify capacitor rating and test capacitance."
    assert after_apply["revision"] == 5
    assert after_apply["updated_at_utc"] != before_apply["updated_at_utc"]

    second_apply = client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal['proposal_id']}/apply")
    assert second_apply.status_code == 200
    assert second_apply.json() == applied.json()


def test_stale_revision_keeps_proposal_pending_without_partial_mutation(checkpoint_proposal_test_context):
    client, _project_store, _activity_store, _proposal_store, _projects_root = checkpoint_proposal_test_context
    project = _create_project(client, name="Project A", goal="Goal A")

    proposal_create = _create_proposal(
        client,
        project["project_id"],
        expected_project_revision=project["revision"],
        proposed_checkpoint_patch={"next_action": "Do A then B"},
    )
    assert proposal_create.status_code == 201
    proposal = proposal_create.json()

    mutate_project = client.patch(
        f"/projects/{project['project_id']}/checkpoint",
        json={
            "expected_revision": project["revision"],
            "discoveries_summary": "New info from another source",
        },
    )
    assert mutate_project.status_code == 200
    assert mutate_project.json()["revision"] == project["revision"] + 1

    apply_resp = client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal['proposal_id']}/apply")
    assert apply_resp.status_code == 409
    assert apply_resp.json()["detail"]["category"] == "revision_conflict"

    unchanged_project = client.get(f"/projects/{project['project_id']}").json()
    assert unchanged_project["revision"] == project["revision"] + 1
    assert unchanged_project["checkpoint"]["next_action"] != "Do A then B"

    proposal_after = client.get(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal['proposal_id']}")
    assert proposal_after.status_code == 200
    assert proposal_after.json()["status"] == "pending"


def test_reject_proposal_no_project_mutation_and_cannot_apply_after(checkpoint_proposal_test_context):
    client, _project_store, _activity_store, _proposal_store, _projects_root = checkpoint_proposal_test_context
    project = _create_project(client, name="Project A", goal="Goal A")

    created = _create_proposal(
        client,
        project["project_id"],
        expected_project_revision=project["revision"],
        proposed_checkpoint_patch={"next_action": "Should not apply"},
    )
    assert created.status_code == 201
    proposal = created.json()

    before_reject = deepcopy(client.get(f"/projects/{project['project_id']}").json())

    rejected = client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal['proposal_id']}/reject")
    assert rejected.status_code == 200
    repeated_reject = client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal['proposal_id']}/reject")
    assert repeated_reject.status_code == 200
    assert repeated_reject.json() == rejected.json()
    rejected_body = rejected.json()
    assert rejected_body["status"] == "rejected"
    assert rejected_body["rejected_at_utc"] is not None
    assert rejected_body["applied_at_utc"] is None

    after_reject = client.get(f"/projects/{project['project_id']}").json()
    assert after_reject == before_reject

    apply_after_reject = client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal['proposal_id']}/apply")
    assert apply_after_reject.status_code == 409
    assert apply_after_reject.json()["detail"]["category"] == "invalid_proposal_state"


def test_cross_project_activity_reference_rejected(checkpoint_proposal_test_context):
    client, _project_store, _activity_store, _proposal_store, _projects_root = checkpoint_proposal_test_context
    project_a = _create_project(client, name="Project A", goal="Goal A")
    project_b = _create_project(client, name="Project B", goal="Goal B")

    a1 = _create_activity(client, project_a["project_id"], summary="A-only evidence")

    response = _create_proposal(
        client,
        project_b["project_id"],
        expected_project_revision=project_b["revision"],
        source_activity_ids=[a1["activity_id"]],
        proposed_checkpoint_patch={"next_action": "Use foreign activity"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["category"] == "foreign_activity_reference"


def test_cross_project_proposal_access_is_ownership_safe(checkpoint_proposal_test_context):
    client, _project_store, _activity_store, _proposal_store, _projects_root = checkpoint_proposal_test_context
    project_a = _create_project(client, name="Project A", goal="Goal A")
    project_b = _create_project(client, name="Project B", goal="Goal B")

    created = _create_proposal(
        client,
        project_a["project_id"],
        expected_project_revision=project_a["revision"],
        proposed_checkpoint_patch={"next_action": "A-only update"},
    )
    assert created.status_code == 201
    proposal_id = created.json()["proposal_id"]

    get_via_b = client.get(f"/projects/{project_b['project_id']}/checkpoint-proposals/{proposal_id}")
    assert get_via_b.status_code == 404
    assert get_via_b.json()["detail"]["category"] == "proposal_not_found"

    apply_via_b = client.post(f"/projects/{project_b['project_id']}/checkpoint-proposals/{proposal_id}/apply")
    assert apply_via_b.status_code == 404
    assert apply_via_b.json()["detail"]["category"] == "proposal_not_found"


def test_invalid_ids_and_list_ordering(checkpoint_proposal_test_context):
    client, _project_store, _activity_store, _proposal_store, _projects_root = checkpoint_proposal_test_context
    project = _create_project(client, name="Project A", goal="Goal A")

    invalid_project = client.post(
        "/projects/not-a-uuid/checkpoint-proposals",
        json={
            "expected_project_revision": 0,
            "source_activity_ids": [],
            "proposed_checkpoint_patch": {"next_action": "x"},
            "reason": "x",
        },
    )
    assert invalid_project.status_code == 422
    assert invalid_project.json()["detail"]["category"] == "invalid_project_id"

    invalid_proposal = client.get(f"/projects/{project['project_id']}/checkpoint-proposals/not-a-uuid")
    assert invalid_proposal.status_code == 422
    assert invalid_proposal.json()["detail"]["category"] == "invalid_proposal_id"

    first = _create_proposal(
        client,
        project["project_id"],
        expected_project_revision=project["revision"],
        proposed_checkpoint_patch={"next_action": "first"},
    )
    assert first.status_code == 201

    second = _create_proposal(
        client,
        project["project_id"],
        expected_project_revision=project["revision"],
        proposed_checkpoint_patch={"next_action": "second"},
    )
    assert second.status_code == 201

    listed = client.get(f"/projects/{project['project_id']}/checkpoint-proposals")
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 2

    sorted_copy = sorted(body, key=lambda item: (item["created_at_utc"], item["proposal_id"]))
    assert body == sorted_copy


def test_restart_persistence_for_proposal_states(checkpoint_proposal_test_context):
    client, _project_store, activity_store, _proposal_store, projects_root = checkpoint_proposal_test_context
    project = _create_project(client, name="Project A", goal="Goal A")

    pending = _create_proposal(
        client,
        project["project_id"],
        expected_project_revision=project["revision"],
        proposed_checkpoint_patch={"current_work": "Pending work"},
    )
    assert pending.status_code == 201

    applied = _create_proposal(
        client,
        project["project_id"],
        expected_project_revision=project["revision"],
        proposed_checkpoint_patch={"next_action": "Apply me"},
    )
    assert applied.status_code == 201
    applied_id = applied.json()["proposal_id"]
    apply_resp = client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{applied_id}/apply")
    assert apply_resp.status_code == 200

    rejected = _create_proposal(
        client,
        project["project_id"],
        expected_project_revision=project["revision"] + 1,
        proposed_checkpoint_patch={"blockers": "Reject me"},
    )
    assert rejected.status_code == 201
    rejected_id = rejected.json()["proposal_id"]
    reject_resp = client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{rejected_id}/reject")
    assert reject_resp.status_code == 200

    restarted_project_store = ProjectStore(projects_root)
    restarted_activity_store = ProjectActivityStore(projects_root, restarted_project_store)
    restarted_proposal_store = CheckpointProposalStore(projects_root, restarted_project_store, restarted_activity_store)

    proposals = restarted_proposal_store.list_proposals(project["project_id"])
    by_id = {item.proposal_id: item for item in proposals}

    assert by_id[pending.json()["proposal_id"]].status.value == "pending"
    assert by_id[applied_id].status.value == "applied"
    assert by_id[applied_id].applied_at_utc is not None
    assert by_id[rejected_id].status.value == "rejected"
    assert by_id[rejected_id].rejected_at_utc is not None


def test_apply_does_not_mutate_source_activities(checkpoint_proposal_test_context):
    client, _project_store, _activity_store, _proposal_store, _projects_root = checkpoint_proposal_test_context
    project = _create_project(client, name="Project A", goal="Goal A")

    activity = _create_activity(
        client,
        project["project_id"],
        source_type="ai",
        confirmation_status="inferred",
        summary="Capacitor appears swollen.",
    )

    before = client.get(f"/projects/{project['project_id']}/activities/{activity['activity_id']}")
    assert before.status_code == 200

    created = _create_proposal(
        client,
        project["project_id"],
        expected_project_revision=project["revision"],
        source_activity_ids=[activity["activity_id"]],
        proposed_checkpoint_patch={"discoveries_summary": "Capacitor appears swollen; not yet confirmed."},
    )
    assert created.status_code == 201

    apply_resp = client.post(
        f"/projects/{project['project_id']}/checkpoint-proposals/{created.json()['proposal_id']}/apply"
    )
    assert apply_resp.status_code == 200

    after = client.get(f"/projects/{project['project_id']}/activities/{activity['activity_id']}")
    assert after.status_code == 200
    assert before.json() == after.json()


def test_proposal_operations_do_not_call_openai(monkeypatch: pytest.MonkeyPatch, checkpoint_proposal_test_context):
    client, _project_store, _activity_store, _proposal_store, _projects_root = checkpoint_proposal_test_context

    called = {"value": False}

    def _fail_openai(*args, **kwargs):
        called["value"] = True
        raise AssertionError("OpenAI should not be called for checkpoint proposal operations")

    monkeypatch.setattr(api, "OpenAI", _fail_openai)

    project = _create_project(client, name="Project A", goal="Goal A")
    proposal = _create_proposal(
        client,
        project["project_id"],
        expected_project_revision=project["revision"],
        proposed_checkpoint_patch={"next_action": "No AI"},
    )
    assert proposal.status_code == 201

    proposal_id = proposal.json()["proposal_id"]
    assert client.get(f"/projects/{project['project_id']}/checkpoint-proposals").status_code == 200
    assert client.get(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal_id}").status_code == 200
    assert client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal_id}/apply").status_code == 200

    proposal2 = _create_proposal(
        client,
        project["project_id"],
        expected_project_revision=project["revision"] + 1,
        proposed_checkpoint_patch={"current_work": "No AI reject"},
    )
    assert proposal2.status_code == 201
    proposal2_id = proposal2.json()["proposal_id"]
    assert client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal2_id}/reject").status_code == 200

    assert called["value"] is False


def test_duplicate_source_activity_ids_are_normalized(checkpoint_proposal_test_context):
    client, _project_store, _activity_store, _proposal_store, _projects_root = checkpoint_proposal_test_context
    project = _create_project(client, name="Project A", goal="Goal A")
    activity = _create_activity(client, project["project_id"], summary="dup")

    created = _create_proposal(
        client,
        project["project_id"],
        expected_project_revision=project["revision"],
        source_activity_ids=[activity["activity_id"], activity["activity_id"]],
        proposed_checkpoint_patch={"next_action": "dedupe refs"},
    )
    assert created.status_code == 201

    source_ids = created.json()["source_activity_ids"]
    assert source_ids == [activity["activity_id"]]


def test_empty_patch_rejected(checkpoint_proposal_test_context):
    client, _project_store, _activity_store, _proposal_store, _projects_root = checkpoint_proposal_test_context
    project = _create_project(client, name="Project A", goal="Goal A")

    response = client.post(
        f"/projects/{project['project_id']}/checkpoint-proposals",
        json={
            "expected_project_revision": 0,
            "source_activity_ids": [],
            "proposed_checkpoint_patch": {},
            "reason": "No-op patch",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["category"] == "validation_error"


def test_reject_applied_is_invalid_state(checkpoint_proposal_test_context):
    client, _project_store, _activity_store, _proposal_store, _projects_root = checkpoint_proposal_test_context
    project = _create_project(client, name="Project A", goal="Goal A")

    proposal = _create_proposal(
        client,
        project["project_id"],
        expected_project_revision=0,
        proposed_checkpoint_patch={"next_action": "apply me"},
    )
    assert proposal.status_code == 201
    proposal_id = proposal.json()["proposal_id"]

    applied = client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal_id}/apply")
    assert applied.status_code == 200

    reject_after_apply = client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal_id}/reject")
    assert reject_after_apply.status_code == 409
    assert reject_after_apply.json()["detail"]["category"] == "invalid_proposal_state"


def test_unknown_proposal_returns_not_found(checkpoint_proposal_test_context):
    client, _project_store, _activity_store, _proposal_store, _projects_root = checkpoint_proposal_test_context
    project = _create_project(client, name="Project A", goal="Goal A")

    response = client.get(f"/projects/{project['project_id']}/checkpoint-proposals/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"]["category"] == "proposal_not_found"


def test_sibling_proposal_with_matching_patch_cannot_ride_along_as_applied(checkpoint_proposal_test_context):
    # Regression coverage for a confirmed Bug Hunter finding, independently reproduced in the
    # live AC Repair acceptance Project's real data: apply_proposal's crash-recovery
    # reconciliation (PROJECT_MEMORY_ARCHITECTURE.md's "Atomicity note") only checked
    # project.revision == base_revision + 1 and patch content, with no way to tell "this
    # proposal's own retry after a partial write" apart from "an unrelated sibling proposal
    # that happens to propose identical content." Two independently-created sibling proposals
    # at the same base_project_revision with byte-identical patches previously both ended up
    # status="applied" even though only one of them ever caused the Project's revision to
    # advance - exactly the provenance violation ADR-024/ADR-029 exist to prevent.
    client, _project_store, _activity_store, _proposal_store, _projects_root = checkpoint_proposal_test_context
    project = _create_project(client, name="AC Repair", goal="Restore reliable cooling")
    a1 = _create_activity(client, project["project_id"], summary="Capacitor appears swollen.")

    patch = {"next_action": "Measure capacitance."}
    first = _create_proposal(
        client, project["project_id"],
        expected_project_revision=0, source_activity_ids=[a1["activity_id"]],
        proposed_checkpoint_patch=patch, reason="First suggestion.",
    ).json()
    second = _create_proposal(
        client, project["project_id"],
        expected_project_revision=0, source_activity_ids=[a1["activity_id"]],
        proposed_checkpoint_patch=patch, reason="Second, independent suggestion with the same wording.",
    ).json()
    assert first["proposal_id"] != second["proposal_id"]

    applied_first = client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{first['proposal_id']}/apply")
    assert applied_first.status_code == 200
    assert applied_first.json()["status"] == "applied"

    after_first = client.get(f"/projects/{project['project_id']}").json()
    assert after_first["revision"] == 1

    # The real bug: applying the second, never-attempted sibling used to silently succeed
    # (marked "applied") purely because the Project's content already matched its patch.
    applied_second = client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{second['proposal_id']}/apply")
    assert applied_second.status_code == 409
    assert applied_second.json()["detail"]["category"] == "revision_conflict"

    second_after = client.get(f"/projects/{project['project_id']}/checkpoint-proposals/{second['proposal_id']}").json()
    assert second_after["status"] == "pending"

    # The Project must not have been touched a second time by the rejected sibling.
    after_second_attempt = client.get(f"/projects/{project['project_id']}").json()
    assert after_second_attempt["revision"] == 1
    assert after_second_attempt["updated_at_utc"] == after_first["updated_at_utc"]

    # A repeat apply of the SAME (first) proposal must still be idempotent success - this fix
    # must not break ordinary retry-of-an-already-applied-proposal behavior.
    retry_first = client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{first['proposal_id']}/apply")
    assert retry_first.status_code == 200
    assert retry_first.json()["status"] == "applied"
