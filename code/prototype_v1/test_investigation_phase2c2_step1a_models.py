from __future__ import annotations

import inspect
import sys
from datetime import timedelta
from datetime import datetime, timezone
from types import ModuleType
from typing import Any, get_args, get_origin
from uuid import uuid4

import investigations.models as investigations_models
import pytest
from pydantic import ValidationError

from investigations.models import (
    INVESTIGATION_ANALYSIS_ATTEMPT_SCHEMA_VERSION,
    INVESTIGATION_FROZEN_EVIDENCE_MANIFEST_SCHEMA_VERSION,
    INVESTIGATION_LATENCY_METADATA_SCHEMA_VERSION,
    INVESTIGATION_STRUCTURED_ANALYSIS_SCHEMA_VERSION,
    InvestigationAnalysisAttempt,
    InvestigationAnalysisAttemptStatus,
    InvestigationAttemptFailureMetadata,
    InvestigationEvidenceType,
    InvestigationFrozenEvidenceItem,
    InvestigationFrozenEvidenceManifest,
    InvestigationLatencyMetadata,
    InvestigationStructuredAnalysis,
)


def _frozen_item(*, evidence_id: str | None = None, storage_ref: str = "evidence/payloads/one.png", selection_index: int = 0) -> InvestigationFrozenEvidenceItem:
    return InvestigationFrozenEvidenceItem(
        evidence_id=evidence_id or str(uuid4()),
        session_id=str(uuid4()),
        storage_ref=storage_ref,
        evidence_type=InvestigationEvidenceType.IMAGE,
        mime_type="image/png",
        captured_at_utc=datetime.now(timezone.utc),
        content_hash="a" * 64,
        size_bytes=123,
        selection_index=selection_index,
    )


def _manifest_with_items(items: list[InvestigationFrozenEvidenceItem]) -> InvestigationFrozenEvidenceManifest:
    session_id = str(uuid4())
    normalized_items = [
        item.model_copy(update={"session_id": session_id, "selection_index": idx})
        for idx, item in enumerate(items)
    ]
    return InvestigationFrozenEvidenceManifest(
        schema_version=INVESTIGATION_FROZEN_EVIDENCE_MANIFEST_SCHEMA_VERSION,
        manifest_id=str(uuid4()),
        session_id=session_id,
        analysis_attempt_id=str(uuid4()),
        created_at_utc=datetime.now(timezone.utc),
        selection_policy_version="1.0",
        selected_evidence=normalized_items,
        selected_evidence_ids=[item.evidence_id for item in normalized_items],
        evidence_count=len(normalized_items),
        manifest_hash="b" * 64,
    )


def _structured_analysis() -> InvestigationStructuredAnalysis:
    return InvestigationStructuredAnalysis(
        schema_version=INVESTIGATION_STRUCTURED_ANALYSIS_SCHEMA_VERSION,
        observed_evidence=["Editor shows failing test output"],
        likely_issue="Invalid UUID input is not handled in one path.",
        confidence_or_uncertainty="Likely but not fully certain; verify with focused regression.",
        recommended_checks=["Inspect UUID parsing in result persistence.", "Run the phase2c1 focused test file."],
        recommended_changes=["Harden optional UUID validation."],
        relevant_safe_filenames=["code/prototype_v1/investigations/result_store.py"],
        limitations=["No runtime trace was included in this input."],
    )


def _latency_partial() -> InvestigationLatencyMetadata:
    return InvestigationLatencyMetadata(
        schema_version=INVESTIGATION_LATENCY_METADATA_SCHEMA_VERSION,
        device_picture_to_prompt_ms=None,
        backend_picture_to_prompt_ms=1200,
        capture_acknowledged_utc=None,
        evidence_ready_utc=None,
        context_collection_started_utc=None,
        context_collection_completed_utc=None,
        provider_request_started_utc=None,
        provider_response_completed_utc=None,
        result_persisted_utc=None,
        prompt_available_utc=None,
        backend_request_accepted_utc=datetime.now(timezone.utc),
        client_capture_acknowledged_utc=None,
        client_request_started_utc=None,
        evidence_preparation_ms=120,
        context_collection_ms=None,
        provider_round_trip_ms=None,
        result_processing_ms=80,
    )


def _attempt_payload() -> dict[str, object]:
    return {
        "schema_version": INVESTIGATION_ANALYSIS_ATTEMPT_SCHEMA_VERSION,
        "analysis_attempt_id": str(uuid4()),
        "session_id": str(uuid4()),
        "attempt_number": 1,
        "status": InvestigationAnalysisAttemptStatus.PREPARED.value,
        "frozen_manifest_hash": "c" * 64,
        "context_snapshot_hash": "d" * 64,
        "request_fingerprint": "e" * 64,
        "created_at_utc": datetime.now(timezone.utc),
        "started_at_utc": None,
        "completed_at_utc": None,
        "failed_at_utc": None,
        "failure_metadata": None,
        "safe_error_category": None,
        "safe_error_message": None,
        "frozen_manifest_id": str(uuid4()),
        "structured_analysis": _structured_analysis().model_dump(mode="json"),
        "rendered_prompt": "Use Copilot to inspect UUID validation in result persistence.",
        "prompt_renderer_version": "1.0",
        "latency_metadata": _latency_partial().model_dump(mode="json"),
        "canonical_result_id": None,
        "provider_request_id": None,
        "recovery_state": None,
        "retryable": False,
    }


def test_frozen_evidence_item_valid_construction():
    item = _frozen_item()
    assert item.evidence_type == InvestigationEvidenceType.IMAGE
    assert item.storage_ref.startswith("evidence/")


def test_frozen_manifest_valid_with_one_image():
    manifest = _manifest_with_items([_frozen_item(selection_index=0)])
    assert manifest.evidence_count == 1


def test_frozen_manifest_valid_with_two_images():
    manifest = _manifest_with_items([
        _frozen_item(selection_index=0),
        _frozen_item(selection_index=1, storage_ref="evidence/payloads/two.png"),
    ])
    assert manifest.evidence_count == 2


def test_frozen_manifest_valid_with_three_images():
    manifest = _manifest_with_items([
        _frozen_item(selection_index=0),
        _frozen_item(selection_index=1, storage_ref="evidence/payloads/two.png"),
        _frozen_item(selection_index=2, storage_ref="evidence/payloads/three.png"),
    ])
    assert manifest.evidence_count == 3


def test_frozen_manifest_rejects_zero_images():
    with pytest.raises(ValidationError):
        _manifest_with_items([])


def test_frozen_manifest_rejects_more_than_three_images():
    with pytest.raises(ValidationError):
        _manifest_with_items([
            _frozen_item(selection_index=0, storage_ref="evidence/payloads/one.png"),
            _frozen_item(selection_index=1, storage_ref="evidence/payloads/two.png"),
            _frozen_item(selection_index=2, storage_ref="evidence/payloads/three.png"),
            _frozen_item(selection_index=3, storage_ref="evidence/payloads/four.png"),
        ])


def test_frozen_manifest_rejects_duplicate_evidence_identifiers():
    duplicate_id = str(uuid4())
    with pytest.raises(ValidationError):
        _manifest_with_items([
            _frozen_item(evidence_id=duplicate_id, selection_index=0, storage_ref="evidence/payloads/one.png"),
            _frozen_item(evidence_id=duplicate_id, selection_index=1, storage_ref="evidence/payloads/two.png"),
        ])


def test_frozen_manifest_allows_duplicate_paths_for_distinct_evidence_ids():
    manifest = _manifest_with_items([
        _frozen_item(selection_index=0, storage_ref="evidence/payloads/same.png"),
        _frozen_item(selection_index=1, storage_ref="evidence/payloads/same.png"),
    ])
    assert manifest.evidence_count == 2
    assert manifest.selected_evidence[0].evidence_id != manifest.selected_evidence[1].evidence_id
    assert manifest.selected_evidence[0].storage_ref == manifest.selected_evidence[1].storage_ref


def test_manifest_round_trip_serialization():
    manifest = _manifest_with_items([
        _frozen_item(selection_index=0),
        _frozen_item(selection_index=1, storage_ref="evidence/payloads/two.png"),
    ])
    payload = manifest.model_dump(mode="json")
    loaded = InvestigationFrozenEvidenceManifest.model_validate(payload)
    assert loaded.model_dump(mode="json") == payload


def test_structured_analysis_round_trip_serialization():
    structured = _structured_analysis()
    payload = structured.model_dump(mode="json")
    loaded = InvestigationStructuredAnalysis.model_validate(payload)
    assert loaded.model_dump(mode="json") == payload


def test_latency_metadata_with_partial_nullable_timings():
    metadata = _latency_partial()
    assert metadata.device_picture_to_prompt_ms is None
    assert metadata.context_collection_ms is None
    assert metadata.backend_picture_to_prompt_ms == 1200


def test_latency_metadata_full_stage_markers_and_round_trip():
    now = datetime.now(timezone.utc)
    metadata = InvestigationLatencyMetadata(
        schema_version=INVESTIGATION_LATENCY_METADATA_SCHEMA_VERSION,
        device_picture_to_prompt_ms=1500,
        backend_picture_to_prompt_ms=1300,
        capture_acknowledged_utc=now,
        evidence_ready_utc=now,
        context_collection_started_utc=now,
        context_collection_completed_utc=now,
        provider_request_started_utc=now,
        provider_response_completed_utc=now,
        result_persisted_utc=now,
        prompt_available_utc=now,
        backend_request_accepted_utc=now,
        client_capture_acknowledged_utc=now,
        client_request_started_utc=now,
        evidence_preparation_ms=100,
        context_collection_ms=200,
        provider_round_trip_ms=300,
        result_processing_ms=400,
    )
    payload = metadata.model_dump(mode="json")
    loaded = InvestigationLatencyMetadata.model_validate(payload)
    assert loaded.model_dump(mode="json") == payload


def test_latency_metadata_normalizes_timezone_aware_values_to_utc():
    plus_two = timezone(timedelta(hours=2))
    metadata = InvestigationLatencyMetadata(
        schema_version=INVESTIGATION_LATENCY_METADATA_SCHEMA_VERSION,
        capture_acknowledged_utc=datetime(2026, 1, 1, 12, 0, tzinfo=plus_two),
        evidence_preparation_ms=10,
    )
    assert metadata.capture_acknowledged_utc is not None
    assert metadata.capture_acknowledged_utc.tzinfo == timezone.utc
    assert metadata.capture_acknowledged_utc.hour == 10


def test_latency_metadata_rejects_naive_timestamps():
    with pytest.raises(ValidationError):
        InvestigationLatencyMetadata(
            schema_version=INVESTIGATION_LATENCY_METADATA_SCHEMA_VERSION,
            capture_acknowledged_utc=datetime(2026, 1, 1, 12, 0),
        )


def test_latency_metadata_rejects_negative_durations():
    with pytest.raises(ValidationError):
        InvestigationLatencyMetadata(
            schema_version=INVESTIGATION_LATENCY_METADATA_SCHEMA_VERSION,
            evidence_preparation_ms=-1,
        )


def test_latency_metadata_all_missing_values_is_valid():
    metadata = InvestigationLatencyMetadata(
        schema_version=INVESTIGATION_LATENCY_METADATA_SCHEMA_VERSION,
    )
    assert metadata.device_picture_to_prompt_ms is None
    assert metadata.prompt_available_utc is None


def test_analysis_attempt_round_trip_serialization():
    payload = _attempt_payload()
    attempt = InvestigationAnalysisAttempt.model_validate(payload)
    serialized = attempt.model_dump(mode="json")
    loaded = InvestigationAnalysisAttempt.model_validate(serialized)
    assert loaded.model_dump(mode="json") == serialized


def test_new_nullable_attempt_fields_default_safely():
    payload = _attempt_payload()
    payload.pop("failed_at_utc")
    payload.pop("safe_error_category")
    payload.pop("safe_error_message")
    payload.pop("frozen_manifest_id")
    payload.pop("structured_analysis")
    payload.pop("rendered_prompt")
    payload.pop("prompt_renderer_version")
    payload.pop("latency_metadata")

    attempt = InvestigationAnalysisAttempt.model_validate(payload)
    assert attempt.failed_at_utc is None
    assert attempt.safe_error_category is None
    assert attempt.safe_error_message is None
    assert attempt.frozen_manifest_id is None
    assert attempt.structured_analysis is None
    assert attempt.rendered_prompt is None
    assert attempt.prompt_renderer_version is None
    assert attempt.latency_metadata is None


def test_workflow_stage_does_not_exist_on_attempt_model():
    payload = _attempt_payload()
    payload["workflow_stage"] = "preparing"
    with pytest.raises(ValidationError):
        InvestigationAnalysisAttempt.model_validate(payload)


def _annotation_contains_provider_sdk_type(annotation: Any) -> bool:
    provider_prefixes = ("openai",)

    origin = get_origin(annotation)
    if origin is not None:
        return any(_annotation_contains_provider_sdk_type(arg) for arg in get_args(annotation))

    if inspect.isclass(annotation):
        module_name = getattr(annotation, "__module__", "")
        return any(module_name.startswith(prefix) for prefix in provider_prefixes)

    return False


def test_model_layer_public_contract_has_no_concrete_provider_sdk_types():
    provider_prefixes = ("openai",)

    model_classes = [
        cls
        for _, cls in inspect.getmembers(investigations_models, inspect.isclass)
        if cls.__module__ == investigations_models.__name__ and hasattr(cls, "model_fields")
    ]

    assert model_classes
    for model_cls in model_classes:
        for field_info in model_cls.model_fields.values():
            annotation = field_info.annotation
            assert not _annotation_contains_provider_sdk_type(annotation)

    for _, value in vars(investigations_models).items():
        if isinstance(value, ModuleType):
            module_name = getattr(value, "__name__", "")
            assert not any(module_name.startswith(prefix) for prefix in provider_prefixes)

    assert investigations_models.__name__ in sys.modules


def test_absolute_paths_are_rejected_for_frozen_item_and_structured_filenames():
    with pytest.raises(ValidationError):
        InvestigationFrozenEvidenceItem(
            evidence_id=str(uuid4()),
            session_id=str(uuid4()),
            storage_ref="C:/absolute/path.png",
            evidence_type=InvestigationEvidenceType.IMAGE,
            mime_type="image/png",
            captured_at_utc=datetime.now(timezone.utc),
            content_hash="f" * 64,
            size_bytes=50,
            selection_index=0,
        )

    with pytest.raises(ValidationError):
        InvestigationStructuredAnalysis(
            schema_version=INVESTIGATION_STRUCTURED_ANALYSIS_SCHEMA_VERSION,
            observed_evidence=["obs"],
            likely_issue="issue",
            confidence_or_uncertainty="uncertain",
            recommended_checks=["check"],
            recommended_changes=[],
            relevant_safe_filenames=["/absolute/path.py"],
            limitations=[],
        )


def test_traversal_paths_are_rejected_for_frozen_item_and_structured_filenames():
    with pytest.raises(ValidationError):
        InvestigationFrozenEvidenceItem(
            evidence_id=str(uuid4()),
            session_id=str(uuid4()),
            storage_ref="../image.jpg",
            evidence_type=InvestigationEvidenceType.IMAGE,
            mime_type="image/jpeg",
            captured_at_utc=datetime.now(timezone.utc),
            content_hash="f" * 64,
            size_bytes=50,
            selection_index=0,
        )

    with pytest.raises(ValidationError):
        InvestigationFrozenEvidenceItem(
            evidence_id=str(uuid4()),
            session_id=str(uuid4()),
            storage_ref="folder/../../image.jpg",
            evidence_type=InvestigationEvidenceType.IMAGE,
            mime_type="image/jpeg",
            captured_at_utc=datetime.now(timezone.utc),
            content_hash="f" * 64,
            size_bytes=50,
            selection_index=0,
        )

    with pytest.raises(ValidationError):
        InvestigationStructuredAnalysis(
            schema_version=INVESTIGATION_STRUCTURED_ANALYSIS_SCHEMA_VERSION,
            observed_evidence=["obs"],
            likely_issue="issue",
            confidence_or_uncertainty="uncertain",
            recommended_checks=["check"],
            recommended_changes=[],
            relevant_safe_filenames=["../image.jpg"],
            limitations=[],
        )

    with pytest.raises(ValidationError):
        InvestigationStructuredAnalysis(
            schema_version=INVESTIGATION_STRUCTURED_ANALYSIS_SCHEMA_VERSION,
            observed_evidence=["obs"],
            likely_issue="issue",
            confidence_or_uncertainty="uncertain",
            recommended_checks=["check"],
            recommended_changes=[],
            relevant_safe_filenames=["folder/../../image.jpg"],
            limitations=[],
        )


def test_valid_nested_relative_paths_are_accepted():
    item = InvestigationFrozenEvidenceItem(
        evidence_id=str(uuid4()),
        session_id=str(uuid4()),
        storage_ref="evidence/session-a/image.jpg",
        evidence_type=InvestigationEvidenceType.IMAGE,
        mime_type="image/jpeg",
        captured_at_utc=datetime.now(timezone.utc),
        content_hash="f" * 64,
        size_bytes=50,
        selection_index=0,
    )
    assert item.storage_ref == "evidence/session-a/image.jpg"

    structured = InvestigationStructuredAnalysis(
        schema_version=INVESTIGATION_STRUCTURED_ANALYSIS_SCHEMA_VERSION,
        observed_evidence=["obs"],
        likely_issue="issue",
        confidence_or_uncertainty="uncertain",
        recommended_checks=["check"],
        recommended_changes=[],
        relevant_safe_filenames=["evidence/session-a/image.jpg"],
        limitations=[],
    )
    assert structured.relevant_safe_filenames == ["evidence/session-a/image.jpg"]


def test_failed_attempt_allows_failed_at_and_safe_error_metadata():
    payload = _attempt_payload()
    payload["status"] = InvestigationAnalysisAttemptStatus.FAILED_PRE_CALL.value
    payload["failed_at_utc"] = datetime.now(timezone.utc)
    payload["failure_metadata"] = InvestigationAttemptFailureMetadata(
        category="validation_error",
        safe_message="Evidence missing.",
        retryable=True,
    ).model_dump(mode="json")
    payload["safe_error_category"] = "validation_error"
    payload["safe_error_message"] = "Evidence missing."

    attempt = InvestigationAnalysisAttempt.model_validate(payload)
    assert attempt.failed_at_utc is not None
