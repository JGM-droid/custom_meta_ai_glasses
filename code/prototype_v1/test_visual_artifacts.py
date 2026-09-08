from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import base64
from types import SimpleNamespace

import pytest

import api
from projects.models import ProjectAIResultRoutingDecision, ProjectAIResultType
from projects.visual_artifacts import (
    MAX_VISUAL_ARTIFACTS_PER_RESULT,
    VisualArtifactProviderError,
    OpenAIVisualArtifactProvider,
    VisualArtifactCreateRequest,
    VisualArtifactProviderResult,
    VisualArtifactRetention,
    VisualArtifactService,
    VisualArtifactStatus,
    VisualArtifactStore,
)
from test_response_planner_routing import _upload_image, create_project, route, routing_context


class FakeVisualProvider:
    def __init__(self):
        self.calls = 0
        self.fail = False
        self.source_bytes = None
        self.prompt = None

    def edit(self, *, source_bytes, source_filename, source_mime_type, prompt):
        self.calls += 1
        self.source_bytes = source_bytes
        self.prompt = prompt
        if self.fail:
            raise VisualArtifactProviderError("fixture failure")
        return VisualArtifactProviderResult(
            image_bytes=b"generated-webp",
            mime_type="image/webp",
            provider="fake",
            model="fixture-image-v1",
            request_id="image-request-1",
        )


@pytest.fixture
def visual_context(routing_context, monkeypatch, tmp_path: Path):
    ctx = routing_context
    project = create_project(ctx["client"])
    session = ctx["client"].post(
        f"/projects/{project['project_id']}/investigation-sessions", json={}
    ).json()
    evidence_id = _upload_image(
        ctx["client"], session["session_id"], name="room.png", content=b"actual-room-image"
    )
    ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
        response_family=ProjectAIResultType.EXPLORE_PLAN,
        confidence=0.98,
        brief_reason="Visual planning request.",
    )
    guidance = route(
        ctx["client"], project["project_id"],
        user_request="Give me room redesign options.",
        investigation_session_id=session["session_id"],
        idempotency_key="guidance-visual-1",
    )
    assert guidance.status_code == 200
    body = guidance.json()
    artifact_store = VisualArtifactStore(ctx["project_store"])
    provider = FakeVisualProvider()
    service = VisualArtifactService(
        project_store=ctx["project_store"],
        explore_service=api._create_project_explore_read_service(),
        session_store=ctx["session_store"],
        evidence_store=ctx["evidence_store"],
        artifact_store=artifact_store,
        provider=provider,
    )
    monkeypatch.setattr(api, "VISUAL_ARTIFACT_STORE", artifact_store)
    monkeypatch.setattr(api, "_create_visual_artifact_service", lambda *, with_provider: service)
    return {
        **ctx,
        "project": project,
        "session": session,
        "evidence_id": evidence_id,
        "guidance": body,
        "store": artifact_store,
        "provider": provider,
        "service": service,
    }


def _base(ctx, option_index=0):
    project_id = ctx["project"]["project_id"]
    result_id = ctx["guidance"]["result_id"]
    option_id = ctx["guidance"]["explore_plan"]["options"][option_index]["idea"]["activity_id"]
    return project_id, result_id, option_id


def test_explicit_visualize_uses_actual_source_once_and_preserves_provenance(visual_context):
    ctx = visual_context
    project_id, result_id, option_id = _base(ctx)
    before_activities = len(ctx["activity_store"].list_activities(project_id))
    before_evidence = len(ctx["evidence_store"].list_evidence_for_analysis(ctx["session"]["session_id"]))

    response = ctx["client"].post(
        f"/projects/{project_id}/ai-results/explore-plan/{result_id}/options/{option_id}/visual-artifacts",
        json={"idempotency_key": "visualize-1"},
    )

    assert response.status_code == 202
    artifact_id = response.json()["artifact_id"]
    ready = ctx["service"].read(project_id, result_id, option_id, artifact_id)
    assert ready.status == VisualArtifactStatus.READY
    assert ready.source_evidence_ids == [ctx["evidence_id"]]
    assert ready.provider_request_id == "image-request-1"
    assert ctx["provider"].calls == 1
    assert ctx["provider"].source_bytes == b"actual-room-image"
    assert "preserving the recognizable room structure" in ctx["provider"].prompt
    assert len(ctx["activity_store"].list_activities(project_id)) == before_activities
    assert len(ctx["evidence_store"].list_evidence_for_analysis(ctx["session"]["session_id"])) == before_evidence

    assert ctx["client"].get(
        f"/projects/{project_id}/ai-results/explore-plan/{result_id}/options/{option_id}/visual-artifacts/{artifact_id}/content"
    ).content == b"generated-webp"
    assert ctx["client"].get(
        f"/projects/{project_id}/ai-results/explore-plan/{result_id}/options/{option_id}/visual-artifacts/{artifact_id}/source"
    ).content == b"actual-room-image"


def test_completed_retry_reconstructs_without_regeneration(visual_context):
    ctx = visual_context
    project_id, result_id, option_id = _base(ctx)
    path = f"/projects/{project_id}/ai-results/explore-plan/{result_id}/options/{option_id}/visual-artifacts"
    first = ctx["client"].post(path, json={"idempotency_key": "same-visual"})
    retry = ctx["client"].post(path, json={"idempotency_key": "same-visual"})
    assert first.status_code == retry.status_code == 202
    assert first.json()["artifact_id"] == retry.json()["artifact_id"]
    assert ctx["provider"].calls == 1


def test_failed_generation_is_recoverable_with_same_key(visual_context):
    ctx = visual_context
    project_id, result_id, option_id = _base(ctx)
    ctx["provider"].fail = True
    path = f"/projects/{project_id}/ai-results/explore-plan/{result_id}/options/{option_id}/visual-artifacts"
    created = ctx["client"].post(path, json={"idempotency_key": "recover-visual"})
    artifact_id = created.json()["artifact_id"]
    assert ctx["service"].read(project_id, result_id, option_id, artifact_id).status == VisualArtifactStatus.FAILED
    ctx["provider"].fail = False
    recovered = ctx["client"].post(
        f"{path}/{artifact_id}/retry", json={"idempotency_key": "recover-visual"}
    )
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "READY"
    assert ctx["provider"].calls == 2


def test_foreign_project_result_and_option_are_not_read_or_generated(visual_context):
    ctx = visual_context
    project_id, result_id, option_id = _base(ctx)
    foreign = create_project(ctx["client"], name="Foreign")
    response = ctx["client"].post(
        f"/projects/{foreign['project_id']}/ai-results/explore-plan/{result_id}/options/{option_id}/visual-artifacts",
        json={"idempotency_key": "foreign"},
    )
    assert response.status_code == 404
    assert ctx["provider"].calls == 0

    project_id, result_id, option_id = _base(ctx)
    created = ctx["client"].post(
        f"/projects/{project_id}/ai-results/explore-plan/{result_id}/options/{option_id}/visual-artifacts",
        json={"idempotency_key": "owned"},
    )
    artifact_id = created.json()["artifact_id"]
    foreign_read = ctx["client"].get(
        f"/projects/{foreign['project_id']}/ai-results/explore-plan/{result_id}/options/{option_id}/visual-artifacts/{artifact_id}")
    assert foreign_read.status_code == 404


def test_result_is_bounded_to_one_visualization_per_each_of_three_options(visual_context):
    ctx = visual_context
    project_id, result_id, _ = _base(ctx)
    for index in range(MAX_VISUAL_ARTIFACTS_PER_RESULT):
        _, _, option_id = _base(ctx, index)
        response = ctx["client"].post(
            f"/projects/{project_id}/ai-results/explore-plan/{result_id}/options/{option_id}/visual-artifacts",
            json={"idempotency_key": f"visual-{index}"},
        )
        assert response.status_code == 202
    assert len(ctx["store"].list_for_result(project_id, result_id)) == 3


def test_retain_removes_ephemeral_expiry(visual_context):
    ctx = visual_context
    project_id, result_id, option_id = _base(ctx)
    path = f"/projects/{project_id}/ai-results/explore-plan/{result_id}/options/{option_id}/visual-artifacts"
    created = ctx["client"].post(path, json={"idempotency_key": "retain-visual"})
    artifact_id = created.json()["artifact_id"]
    retained = ctx["client"].post(f"{path}/{artifact_id}/retain")
    assert retained.status_code == 200
    assert retained.json()["retention"] == VisualArtifactRetention.RETAINED.value
    assert retained.json()["expires_at_utc"] is None


def test_selecting_an_option_retains_its_ready_visualization(visual_context):
    ctx = visual_context
    project_id, result_id, option_id = _base(ctx)
    created = ctx["client"].post(
        f"/projects/{project_id}/ai-results/explore-plan/{result_id}/options/{option_id}/visual-artifacts",
        json={"idempotency_key": "select-retain"},
    )
    artifact_id = created.json()["artifact_id"]
    selected = ctx["client"].post(
        f"/projects/{project_id}/ideas/{option_id}/disposition",
        json={"disposition": "select", "idempotency_key": "select-after-visual"},
    )
    assert selected.status_code == 200
    retained = ctx["store"].load(project_id, artifact_id)
    assert retained.retention == VisualArtifactRetention.RETAINED
    assert retained.expires_at_utc is None


def test_all_guidance_families_make_zero_image_generation_calls(routing_context, monkeypatch):
    ctx = routing_context
    project = create_project(ctx["client"])
    factory_calls = 0
    original_factory = api._create_visual_artifact_service
    def counted_factory(*, with_provider):
        nonlocal factory_calls
        factory_calls += 1
        return original_factory(with_provider=with_provider)
    monkeypatch.setattr(api, "_create_visual_artifact_service", counted_factory)
    for family, request in [
        (ProjectAIResultType.EXPLORE_PLAN, "Give me options."),
        (ProjectAIResultType.GENERAL_GUIDANCE, "What should I consider?"),
        (ProjectAIResultType.TROUBLESHOOT, "Why is this not working?"),
    ]:
        ctx["routing_provider"].decision = ProjectAIResultRoutingDecision(
            response_family=family, confidence=0.9, brief_reason="fixture"
        )
        response = route(
            ctx["client"], project["project_id"], user_request=request,
            idempotency_key=f"family-{family.value}",
        )
        assert response.status_code == 200
    assert factory_calls == 0


def test_openai_adapter_sends_one_actual_image_edit_with_bounded_settings():
    captured = []
    class Images:
        def edit(self, **kwargs):
            captured.append(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(b"edited").decode())], id="req-1")
    provider = OpenAIVisualArtifactProvider(
        api_key="test-key", client_factory=lambda **_: SimpleNamespace(images=Images()))
    result = provider.edit(
        source_bytes=b"source-room", source_filename="room.png",
        source_mime_type="image/png", prompt="preserve room; add warm design")
    assert result.image_bytes == b"edited"
    assert len(captured) == 1
    request = captured[0]
    assert request["image"][0] == "room.png"
    assert request["image"][1].read() == b"source-room"
    assert request["image"][2] == "image/png"
    assert request["n"] == 1
    assert request["model"] == "gpt-image-2"


def test_expired_ephemeral_is_removed_but_retained_survives(visual_context):
    ctx = visual_context
    project_id, result_id, option_id = _base(ctx)
    pending = ctx["service"].prepare(
        project_id, result_id, option_id, VisualArtifactCreateRequest(idempotency_key="expiry"))
    artifact = ctx["service"].generate(project_id, pending.artifact_id)
    expired = artifact.model_copy(update={"expires_at_utc": datetime.now(timezone.utc) - timedelta(seconds=1)})
    ctx["store"].save(expired)
    base = f"/projects/{project_id}/ai-results/explore-plan/{result_id}/options/{option_id}/visual-artifacts/{artifact.artifact_id}"
    assert ctx["client"].get(base).status_code == 404
    assert ctx["client"].get(base + "/content").status_code == 404
    assert ctx["client"].get(base + "/source").status_code == 404
    reconstructed = ctx["service"].prepare(
        project_id, result_id, option_id, VisualArtifactCreateRequest(idempotency_key="expiry"))
    assert reconstructed.status == VisualArtifactStatus.PENDING

    retained = artifact.model_copy(update={
        "retention": VisualArtifactRetention.RETAINED,
        "expires_at_utc": datetime.now(timezone.utc) - timedelta(seconds=1),
    })
    ctx["store"].save(retained)
    assert ctx["store"].purge_expired_for_result(project_id, result_id) == []
    assert ctx["store"].load(project_id, artifact.artifact_id).retention == VisualArtifactRetention.RETAINED


def test_visual_retention_failure_cannot_fail_successful_select(visual_context, monkeypatch):
    ctx = visual_context
    project_id, _, option_id = _base(ctx)
    def fail_retention(*_):
        raise VisualArtifactProviderError("sidecar unavailable")
    monkeypatch.setattr(ctx["service"], "retain_selected_option", fail_retention)
    selected = ctx["client"].post(
        f"/projects/{project_id}/ideas/{option_id}/disposition",
        json={"disposition": "select", "idempotency_key": "select-with-sidecar-failure"},
    )
    assert selected.status_code == 200
    projection = api._create_project_explore_read_service().read_projection(project_id)
    option = next(item for group in projection.option_sets for item in group.options if item.idea.activity_id == option_id)
    assert option.disposition.value == "select"
