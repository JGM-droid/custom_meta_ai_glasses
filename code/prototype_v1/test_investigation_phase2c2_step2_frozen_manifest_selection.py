from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investigations.evidence_store import InvestigationEvidenceStore
from investigations.frozen_manifest_service import (
    InvestigationFrozenManifestSelectionError,
    build_frozen_evidence_manifest,
    build_frozen_evidence_manifest_for_session,
)
from investigations.models import (
    InvestigationEvidence,
    InvestigationEvidenceCreateRequest,
    InvestigationEvidenceType,
    InvestigationEvidenceValidationStatus,
    InvestigationSessionStatus,
    create_new_investigation_session,
)
from investigations.session_store import InvestigationSessionStore


def _image_evidence(
    *,
    session_id: str,
    sequence_number: int,
    evidence_id: str | None = None,
    storage_ref: str | None = None,
    validation_status: InvestigationEvidenceValidationStatus = InvestigationEvidenceValidationStatus.ACCEPTED,
) -> InvestigationEvidence:
    evidence_uuid = evidence_id or str(uuid4())
    return InvestigationEvidence(
        schema_version="1.0",
        evidence_id=evidence_uuid,
        session_id=session_id,
        evidence_type=InvestigationEvidenceType.IMAGE,
        source="desktop",
        created_at_utc=datetime.now(timezone.utc),
        validation_status=validation_status,
        sequence_number=sequence_number,
        client_timestamp_utc=datetime.now(timezone.utc),
        filename=f"img_{sequence_number}.png",
        mime_type="image/png",
        storage_ref=storage_ref or f"evidence/payloads/{evidence_uuid}_img_{sequence_number}.png",
        content_hash="a" * 64,
        width=1280,
        height=720,
        metadata={"size_bytes": 100 + sequence_number},
    )


def _audio_evidence(*, session_id: str, sequence_number: int) -> InvestigationEvidence:
    evidence_uuid = str(uuid4())
    return InvestigationEvidence(
        schema_version="1.0",
        evidence_id=evidence_uuid,
        session_id=session_id,
        evidence_type=InvestigationEvidenceType.AUDIO,
        source="desktop",
        created_at_utc=datetime.now(timezone.utc),
        validation_status=InvestigationEvidenceValidationStatus.ACCEPTED,
        sequence_number=sequence_number,
        client_timestamp_utc=datetime.now(timezone.utc),
        filename=f"audio_{sequence_number}.wav",
        mime_type="audio/wav",
        storage_ref=f"evidence/payloads/{evidence_uuid}_audio_{sequence_number}.wav",
        content_hash="b" * 64,
        duration_seconds=1.5,
        metadata={"size_bytes": 300},
    )


def test_empty_eligible_evidence_raises_required_error():
    session_id = str(uuid4())
    with pytest.raises(InvestigationFrozenManifestSelectionError):
        build_frozen_evidence_manifest(
            session_id=session_id,
            analysis_attempt_id=str(uuid4()),
            evidence_records=[_audio_evidence(session_id=session_id, sequence_number=1)],
        )


def test_one_eligible_evidence_item_builds_manifest():
    session_id = str(uuid4())
    evidence = _image_evidence(session_id=session_id, sequence_number=1)

    manifest = build_frozen_evidence_manifest(
        session_id=session_id,
        analysis_attempt_id=str(uuid4()),
        evidence_records=[evidence],
    )

    assert manifest.evidence_count == 1
    assert manifest.selected_evidence_ids == [evidence.evidence_id]
    assert manifest.selected_evidence[0].selection_index == 0


def test_multiple_evidence_items_are_selected_deterministically_by_rule():
    session_id = str(uuid4())
    e1 = _image_evidence(session_id=session_id, sequence_number=10)
    e2 = _image_evidence(session_id=session_id, sequence_number=20)
    e3 = _image_evidence(session_id=session_id, sequence_number=30)
    e4 = _image_evidence(session_id=session_id, sequence_number=40)
    e5 = _image_evidence(session_id=session_id, sequence_number=50)

    manifest = build_frozen_evidence_manifest(
        session_id=session_id,
        analysis_attempt_id=str(uuid4()),
        evidence_records=[e1, e2, e3, e4, e5],
    )

    # Rule with max=3: earliest, evenly distributed middle, latest.
    assert manifest.selected_evidence_ids == [e1.evidence_id, e3.evidence_id, e5.evidence_id]
    assert [item.selection_index for item in manifest.selected_evidence] == [0, 1, 2]


def test_input_order_changes_do_not_change_manifest_order():
    session_id = str(uuid4())
    e1 = _image_evidence(session_id=session_id, sequence_number=1)
    e2 = _image_evidence(session_id=session_id, sequence_number=2)
    e3 = _image_evidence(session_id=session_id, sequence_number=3)
    e4 = _image_evidence(session_id=session_id, sequence_number=4)

    args = {
        "session_id": session_id,
        "analysis_attempt_id": str(uuid4()),
        "created_at_utc": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "manifest_id": str(uuid4()),
    }

    manifest_a = build_frozen_evidence_manifest(evidence_records=[e1, e2, e3, e4], **args)
    manifest_b = build_frozen_evidence_manifest(evidence_records=[e4, e2, e1, e3], **args)

    assert manifest_a.selected_evidence_ids == manifest_b.selected_evidence_ids


def test_selected_ids_and_count_match_item_order_and_size():
    session_id = str(uuid4())
    e1 = _image_evidence(session_id=session_id, sequence_number=1)
    e2 = _image_evidence(session_id=session_id, sequence_number=2)

    manifest = build_frozen_evidence_manifest(
        session_id=session_id,
        analysis_attempt_id=str(uuid4()),
        evidence_records=[e1, e2],
    )

    assert manifest.selected_evidence_ids == [item.evidence_id for item in manifest.selected_evidence]
    assert manifest.evidence_count == len(manifest.selected_evidence)


def test_duplicate_storage_ref_allowed_for_distinct_evidence_ids():
    session_id = str(uuid4())
    shared_ref = "evidence/payloads/shared.png"
    e1 = _image_evidence(session_id=session_id, sequence_number=1, storage_ref=shared_ref)
    e2 = _image_evidence(session_id=session_id, sequence_number=2, storage_ref=shared_ref)

    manifest = build_frozen_evidence_manifest(
        session_id=session_id,
        analysis_attempt_id=str(uuid4()),
        evidence_records=[e1, e2],
    )

    assert manifest.selected_evidence[0].storage_ref == shared_ref
    assert manifest.selected_evidence[1].storage_ref == shared_ref


def test_duplicate_evidence_ids_are_rejected():
    session_id = str(uuid4())
    duplicate_id = str(uuid4())
    e1 = _image_evidence(session_id=session_id, sequence_number=1, evidence_id=duplicate_id)
    e2 = _image_evidence(session_id=session_id, sequence_number=2, evidence_id=duplicate_id)

    with pytest.raises(InvestigationFrozenManifestSelectionError):
        build_frozen_evidence_manifest(
            session_id=session_id,
            analysis_attempt_id=str(uuid4()),
            evidence_records=[e1, e2],
        )


def test_different_session_evidence_is_rejected():
    session_id = str(uuid4())
    foreign_session_id = str(uuid4())
    local = _image_evidence(session_id=session_id, sequence_number=1)
    foreign = _image_evidence(session_id=foreign_session_id, sequence_number=2)

    with pytest.raises(InvestigationFrozenManifestSelectionError):
        build_frozen_evidence_manifest(
            session_id=session_id,
            analysis_attempt_id=str(uuid4()),
            evidence_records=[local, foreign],
        )


def test_ineligible_evidence_is_excluded():
    session_id = str(uuid4())
    image = _image_evidence(session_id=session_id, sequence_number=1)
    audio = _audio_evidence(session_id=session_id, sequence_number=2)
    invalid_status = _image_evidence(session_id=session_id, sequence_number=3).model_copy(
        update={"validation_status": "invalid"}
    )

    manifest = build_frozen_evidence_manifest(
        session_id=session_id,
        analysis_attempt_id=str(uuid4()),
        evidence_records=[audio, invalid_status, image],
    )

    assert manifest.selected_evidence_ids == [image.evidence_id]


def test_valid_nested_storage_path_is_accepted():
    session_id = str(uuid4())
    evidence = _image_evidence(
        session_id=session_id,
        sequence_number=1,
        storage_ref="evidence/session-a/image.jpg",
    )

    manifest = build_frozen_evidence_manifest(
        session_id=session_id,
        analysis_attempt_id=str(uuid4()),
        evidence_records=[evidence],
    )

    assert manifest.selected_evidence[0].storage_ref == "evidence/session-a/image.jpg"


def test_traversal_path_rejected_by_frozen_item_validation():
    session_id = str(uuid4())
    unsafe = _image_evidence(session_id=session_id, sequence_number=1).model_copy(
        update={"storage_ref": "../image.jpg"}
    )

    with pytest.raises(ValidationError):
        build_frozen_evidence_manifest(
            session_id=session_id,
            analysis_attempt_id=str(uuid4()),
            evidence_records=[unsafe],
        )


def test_source_evidence_objects_not_mutated():
    session_id = str(uuid4())
    e1 = _image_evidence(session_id=session_id, sequence_number=1)
    e2 = _image_evidence(session_id=session_id, sequence_number=2)
    before = [item.model_dump(mode="json") for item in [e1, e2]]

    build_frozen_evidence_manifest(
        session_id=session_id,
        analysis_attempt_id=str(uuid4()),
        evidence_records=[e1, e2],
    )

    after = [item.model_dump(mode="json") for item in [e1, e2]]
    assert before == after


def test_build_manifest_for_session_uses_store_evidence_without_persistence(tmp_path: Path):
    root = tmp_path / "investigation_sessions"
    session_store = InvestigationSessionStore(root)
    evidence_store = InvestigationEvidenceStore(session_store)

    session = create_new_investigation_session()
    collecting = session.model_copy(
        update={
            "status": InvestigationSessionStatus.COLLECTING,
            "revision": 1,
            "updated_at_utc": datetime.now(timezone.utc),
        }
    )
    session_store.save_session(collecting)

    for index, payload in enumerate([b"one", b"two", b"three", b"four"], start=1):
        record, created = evidence_store.upload_evidence(
            session_id=collecting.session_id,
            evidence_type=InvestigationEvidenceType.IMAGE,
            raw_bytes=payload,
            mime_type="image/png",
            original_filename=f"img_{index}.png",
            request=InvestigationEvidenceCreateRequest(
                source="desktop",
                client_timestamp_utc=datetime.now(timezone.utc),
                normalized_text=None,
                metadata=None,
                filename=f"img_{index}.png",
                mime_type="image/png",
                width=800,
                height=600,
                duration_seconds=None,
            ),
        )
        assert created is True
        assert record.sequence_number == index

    manifest = build_frozen_evidence_manifest_for_session(
        evidence_store=evidence_store,
        session_id=collecting.session_id,
        analysis_attempt_id=str(uuid4()),
    )

    assert manifest.evidence_count == 3
    assert [item.selection_index for item in manifest.selected_evidence] == [0, 1, 2]
    assert manifest.selected_evidence_ids == [item.evidence_id for item in manifest.selected_evidence]
