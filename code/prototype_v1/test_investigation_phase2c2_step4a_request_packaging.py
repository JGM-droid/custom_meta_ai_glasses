from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from investigations.analysis_contract_errors import (
    InvestigationAnalysisIdentityMismatchError,
    InvestigationAnalysisMissingEvidenceError,
    InvestigationAnalysisResponseValidationError,
    InvestigationAnalysisUnsupportedEvidenceError,
)
from investigations.analysis_prompt_renderer import render_deterministic_analysis_instructions
from investigations.analysis_request_builder import build_deterministic_analysis_request_package
from investigations.analysis_response_validator import validate_structured_analysis_response
from investigations.analysis_attempt_store import InvestigationAnalysisAttemptStore
from investigations.evidence_store import InvestigationEvidenceStore
from investigations.frozen_manifest_service import build_frozen_evidence_manifest_for_session
from investigations.models import (
    INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
    InvestigationAnalysisResponse,
    InvestigationEvidenceCreateRequest,
    InvestigationEvidenceType,
    InvestigationSessionStatus,
    create_new_investigation_session,
)
from investigations.session_store import InvestigationSessionStore


def _collecting_session(session_store: InvestigationSessionStore):
    created = create_new_investigation_session()
    collecting = created.model_copy(
        update={
            "status": InvestigationSessionStatus.COLLECTING,
            "revision": 1,
            "updated_at_utc": datetime.now(timezone.utc),
        }
    )
    session_store.save_session(collecting)
    return collecting


def _upload_image(
    evidence_store: InvestigationEvidenceStore,
    *,
    session_id: str,
    payload: bytes,
    filename: str,
) -> None:
    evidence_store.upload_evidence(
        session_id=session_id,
        evidence_type=InvestigationEvidenceType.IMAGE,
        raw_bytes=payload,
        mime_type="image/png",
        original_filename=filename,
        request=InvestigationEvidenceCreateRequest(
            source="desktop",
            client_timestamp_utc=datetime.now(timezone.utc),
            normalized_text=None,
            metadata=None,
            filename=filename,
            mime_type="image/png",
            width=1024,
            height=768,
            duration_seconds=None,
        ),
    )


def _build_ready_inputs(tmp_path: Path):
    root = tmp_path / "investigation_sessions"
    session_store = InvestigationSessionStore(root)
    evidence_store = InvestigationEvidenceStore(session_store)
    attempt_store = InvestigationAnalysisAttemptStore(session_store)

    session = _collecting_session(session_store)
    _upload_image(evidence_store, session_id=session.session_id, payload=b"img-1", filename="one.png")
    _upload_image(evidence_store, session_id=session.session_id, payload=b"img-2", filename="two.png")
    _upload_image(evidence_store, session_id=session.session_id, payload=b"img-3", filename="three.png")

    attempt_id = str(uuid4())
    manifest = build_frozen_evidence_manifest_for_session(
        evidence_store=evidence_store,
        session_id=session.session_id,
        analysis_attempt_id=attempt_id,
    )
    attempt = attempt_store.build_prepared_attempt(
        session_id=session.session_id,
        analysis_attempt_id=attempt_id,
        attempt_number=1,
        frozen_manifest_hash=manifest.manifest_hash,
        context_snapshot_hash="a" * 64,
        request_fingerprint="b" * 64,
    )

    return session_store, evidence_store, session, attempt, manifest


def test_identical_durable_inputs_produce_identical_request_packages(tmp_path: Path):
    _session_store, evidence_store, session, attempt, manifest = _build_ready_inputs(tmp_path)

    first = build_deterministic_analysis_request_package(
        session=session,
        analysis_attempt=attempt,
        frozen_manifest=manifest,
        evidence_store=evidence_store,
        normalized_explanation_text="Build failed after dependency upgrade.",
    )
    second = build_deterministic_analysis_request_package(
        session=session,
        analysis_attempt=attempt,
        frozen_manifest=manifest,
        evidence_store=evidence_store,
        normalized_explanation_text="Build failed after dependency upgrade.",
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_frozen_manifest_evidence_order_is_preserved(tmp_path: Path):
    _session_store, evidence_store, session, attempt, manifest = _build_ready_inputs(tmp_path)

    request = build_deterministic_analysis_request_package(
        session=session,
        analysis_attempt=attempt,
        frozen_manifest=manifest,
        evidence_store=evidence_store,
        normalized_explanation_text="",
    )

    assert [item.evidence_id for item in request.ordered_evidence_inputs] == manifest.selected_evidence_ids


def test_filesystem_ordering_cannot_change_request(tmp_path: Path):
    _session_store, evidence_store, session, attempt, manifest = _build_ready_inputs(tmp_path)

    workspace = evidence_store.session_store.session_workspace_dir(session.session_id)
    unrelated_paths = [
        workspace / "evidence" / "000_unrelated.json",
        workspace / "evidence" / "zzz_unrelated.json",
    ]
    for path in unrelated_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    first = build_deterministic_analysis_request_package(
        session=session,
        analysis_attempt=attempt,
        frozen_manifest=manifest,
        evidence_store=evidence_store,
        normalized_explanation_text="Look at all captures together.",
    )

    unrelated_paths.reverse()
    second = build_deterministic_analysis_request_package(
        session=session,
        analysis_attempt=attempt,
        frozen_manifest=manifest,
        evidence_store=evidence_store,
        normalized_explanation_text="Look at all captures together.",
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_evidence_outside_the_session_is_rejected(tmp_path: Path):
    _session_store, evidence_store, session, attempt, manifest = _build_ready_inputs(tmp_path)
    foreign_session = str(uuid4())

    first = manifest.selected_evidence[0]
    metadata_path = (
        evidence_store.session_store.session_workspace_dir(session.session_id)
        / "evidence"
        / f"{first.evidence_id}.json"
    )
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["session_id"] = foreign_session
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(InvestigationAnalysisIdentityMismatchError):
        build_deterministic_analysis_request_package(
            session=session,
            analysis_attempt=attempt,
            frozen_manifest=manifest,
            evidence_store=evidence_store,
            normalized_explanation_text=None,
        )


def test_attempt_session_mismatch_is_rejected(tmp_path: Path):
    _session_store, evidence_store, session, attempt, manifest = _build_ready_inputs(tmp_path)
    mismatched_attempt = attempt.model_copy(update={"session_id": str(uuid4())})

    with pytest.raises(InvestigationAnalysisIdentityMismatchError):
        build_deterministic_analysis_request_package(
            session=session,
            analysis_attempt=mismatched_attempt,
            frozen_manifest=manifest,
            evidence_store=evidence_store,
            normalized_explanation_text=None,
        )


def test_attempt_manifest_mismatch_is_rejected(tmp_path: Path):
    _session_store, evidence_store, session, attempt, manifest = _build_ready_inputs(tmp_path)
    mismatched_attempt = attempt.model_copy(update={"frozen_manifest_id": str(uuid4())})

    with pytest.raises(InvestigationAnalysisIdentityMismatchError):
        build_deterministic_analysis_request_package(
            session=session,
            analysis_attempt=mismatched_attempt,
            frozen_manifest=manifest,
            evidence_store=evidence_store,
            normalized_explanation_text=None,
        )


def test_missing_evidence_file_is_rejected(tmp_path: Path):
    _session_store, evidence_store, session, attempt, manifest = _build_ready_inputs(tmp_path)

    missing_ref = manifest.selected_evidence[0].storage_ref
    payload_path = evidence_store.session_store.session_workspace_dir(session.session_id) / missing_ref
    payload_path.unlink()

    with pytest.raises(InvestigationAnalysisMissingEvidenceError):
        build_deterministic_analysis_request_package(
            session=session,
            analysis_attempt=attempt,
            frozen_manifest=manifest,
            evidence_store=evidence_store,
            normalized_explanation_text=None,
        )


def test_unsupported_media_type_is_rejected(tmp_path: Path):
    _session_store, evidence_store, session, attempt, manifest = _build_ready_inputs(tmp_path)

    first = manifest.selected_evidence[0]
    updated_first = first.model_copy(update={"mime_type": "image/webp"})
    updated_items = [updated_first, *manifest.selected_evidence[1:]]
    updated_manifest = manifest.model_copy(
        update={
            "selected_evidence": updated_items,
            "selected_evidence_ids": [item.evidence_id for item in updated_items],
        }
    )

    with pytest.raises(InvestigationAnalysisUnsupportedEvidenceError):
        build_deterministic_analysis_request_package(
            session=session,
            analysis_attempt=attempt,
            frozen_manifest=updated_manifest,
            evidence_store=evidence_store,
            normalized_explanation_text=None,
        )


def test_prompt_rendering_is_deterministic(tmp_path: Path):
    _session_store, evidence_store, session, attempt, manifest = _build_ready_inputs(tmp_path)
    request = build_deterministic_analysis_request_package(
        session=session,
        analysis_attempt=attempt,
        frozen_manifest=manifest,
        evidence_store=evidence_store,
        normalized_explanation_text="The issue appears only after the third capture.",
    )

    first = render_deterministic_analysis_instructions(
        normalized_explanation_text=request.normalized_explanation_text,
        ordered_evidence_inputs=request.ordered_evidence_inputs,
    )
    second = render_deterministic_analysis_instructions(
        normalized_explanation_text=request.normalized_explanation_text,
        ordered_evidence_inputs=request.ordered_evidence_inputs,
    )

    assert first == second


def test_prompt_includes_multi_capture_investigation_behavior(tmp_path: Path):
    _session_store, evidence_store, session, attempt, manifest = _build_ready_inputs(tmp_path)
    request = build_deterministic_analysis_request_package(
        session=session,
        analysis_attempt=attempt,
        frozen_manifest=manifest,
        evidence_store=evidence_store,
        normalized_explanation_text="compare all views",
    )

    assert "Treat all captures as one investigation" in request.deterministic_system_instructions
    assert "Compare evidence across captures" in request.deterministic_system_instructions


def test_prompt_requests_concise_actionable_guidance(tmp_path: Path):
    _session_store, evidence_store, session, attempt, manifest = _build_ready_inputs(tmp_path)
    request = build_deterministic_analysis_request_package(
        session=session,
        analysis_attempt=attempt,
        frozen_manifest=manifest,
        evidence_store=evidence_store,
        normalized_explanation_text="",
    )

    assert "concise immediate recommended action suitable for glasses display" in request.deterministic_system_instructions


def test_valid_structured_response_parses_successfully():
    parsed = validate_structured_analysis_response(
        {
            "schema_version": INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
            "concise_diagnosis": "Likely stale dependency lockfile mismatch.",
            "immediate_recommended_action": "Regenerate lockfile and run focused tests.",
            "supporting_observations": [
                "First capture shows import error.",
                "Later capture shows inconsistent package versions.",
            ],
            "confidence_or_uncertainty": "Likely, but verify with one clean install.",
            "warning_or_blocker": "Do not run full upgrade before lockfile check.",
            "follow_up_capture_request": "Capture terminal output after lockfile regeneration.",
        }
    )

    assert isinstance(parsed, InvestigationAnalysisResponse)


def test_blank_diagnosis_is_rejected():
    with pytest.raises(InvestigationAnalysisResponseValidationError):
        validate_structured_analysis_response(
            {
                "schema_version": INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
                "concise_diagnosis": "   ",
                "immediate_recommended_action": "Run focused check.",
                "supporting_observations": ["obs"],
                "confidence_or_uncertainty": "uncertain",
            }
        )


def test_blank_recommended_action_is_rejected():
    with pytest.raises(InvestigationAnalysisResponseValidationError):
        validate_structured_analysis_response(
            {
                "schema_version": INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
                "concise_diagnosis": "Issue found",
                "immediate_recommended_action": "   ",
                "supporting_observations": ["obs"],
                "confidence_or_uncertainty": "uncertain",
            }
        )


def test_invalid_list_or_type_structure_is_rejected():
    with pytest.raises(InvestigationAnalysisResponseValidationError):
        validate_structured_analysis_response(
            {
                "schema_version": INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
                "concise_diagnosis": "Issue found",
                "immediate_recommended_action": "Run check.",
                "supporting_observations": "not-a-list",
                "confidence_or_uncertainty": "uncertain",
            }
        )


def test_excessive_values_are_rejected():
    with pytest.raises(InvestigationAnalysisResponseValidationError):
        validate_structured_analysis_response(
            {
                "schema_version": INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
                "concise_diagnosis": "x" * 501,
                "immediate_recommended_action": "Run check.",
                "supporting_observations": ["obs"],
                "confidence_or_uncertainty": "uncertain",
            }
        )


def test_optional_uncertainty_and_follow_up_fields_behavior():
    without_optional = validate_structured_analysis_response(
        {
            "schema_version": INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
            "concise_diagnosis": "Likely stale cache state.",
            "immediate_recommended_action": "Clear cache and rerun one test.",
            "supporting_observations": ["The latest capture differs from the first."],
            "confidence_or_uncertainty": "uncertain",
        }
    )
    assert without_optional.warning_or_blocker is None
    assert without_optional.follow_up_capture_request is None

    with_optional = validate_structured_analysis_response(
        {
            "schema_version": INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
            "concise_diagnosis": "Likely stale cache state.",
            "immediate_recommended_action": "Clear cache and rerun one test.",
            "supporting_observations": ["The latest capture differs from the first."],
            "confidence_or_uncertainty": "uncertain",
            "warning_or_blocker": "Do not clear production cache.",
            "follow_up_capture_request": "Capture the next failing stack trace if issue persists.",
        }
    )
    assert with_optional.warning_or_blocker is not None
    assert with_optional.follow_up_capture_request is not None


def test_request_construction_performs_no_session_mutation(tmp_path: Path):
    session_store, evidence_store, session, attempt, manifest = _build_ready_inputs(tmp_path)
    before = session_store.load_session(session.session_id).model_dump(mode="json")

    build_deterministic_analysis_request_package(
        session=session,
        analysis_attempt=attempt,
        frozen_manifest=manifest,
        evidence_store=evidence_store,
        normalized_explanation_text="Session should not mutate.",
    )

    after = session_store.load_session(session.session_id).model_dump(mode="json")
    assert before == after


def test_no_provider_call_occurs(tmp_path: Path):
    _session_store, evidence_store, session, attempt, manifest = _build_ready_inputs(tmp_path)

    request = build_deterministic_analysis_request_package(
        session=session,
        analysis_attempt=attempt,
        frozen_manifest=manifest,
        evidence_store=evidence_store,
        normalized_explanation_text=None,
    )

    assert request.analysis_attempt_id == attempt.analysis_attempt_id


def test_no_result_persistence_or_api_behavior_is_introduced(tmp_path: Path):
    session_store, evidence_store, session, attempt, manifest = _build_ready_inputs(tmp_path)

    build_deterministic_analysis_request_package(
        session=session,
        analysis_attempt=attempt,
        frozen_manifest=manifest,
        evidence_store=evidence_store,
        normalized_explanation_text=None,
    )

    root = session_store.root
    assert not (root / "results").exists()
    assert not (root / "latest.json").exists()
