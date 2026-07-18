from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from .evidence_store import InvestigationEvidenceStore
from .models import (
    INVESTIGATION_FROZEN_EVIDENCE_MANIFEST_SCHEMA_VERSION,
    InvestigationEvidence,
    InvestigationEvidenceType,
    InvestigationEvidenceValidationStatus,
    InvestigationFrozenEvidenceItem,
    InvestigationFrozenEvidenceManifest,
)

_DEFAULT_PROVIDER_MAX_IMAGES = 3
_DEFAULT_SELECTION_POLICY_VERSION = "1.0"


class InvestigationFrozenManifestSelectionError(RuntimeError):
    pass


def _canonical_selected_subset_hash(
    *,
    schema_version: str,
    session_id: str,
    analysis_attempt_id: str,
    selection_policy_version: str,
    selected_items: list[InvestigationFrozenEvidenceItem],
) -> str:
    payload = {
        "schema_version": schema_version,
        "session_id": session_id,
        "analysis_attempt_id": analysis_attempt_id,
        "selection_policy_version": selection_policy_version,
        "selected_evidence": [
            {
                "evidence_id": item.evidence_id,
                "session_id": item.session_id,
                "storage_ref": item.storage_ref,
                "evidence_type": item.evidence_type.value,
                "mime_type": item.mime_type,
                "captured_at_utc": item.captured_at_utc.isoformat() if item.captured_at_utc else None,
                "content_hash": item.content_hash,
                "size_bytes": item.size_bytes,
                "selection_index": item.selection_index,
            }
            for item in selected_items
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _deterministic_subset(eligible: list[InvestigationEvidence], max_selected_images: int) -> list[InvestigationEvidence]:
    if len(eligible) <= max_selected_images:
        return eligible

    if max_selected_images <= 1:
        return [eligible[0]]

    earliest = eligible[0]
    latest = eligible[-1]
    intermediate = eligible[1:-1]
    slots = max_selected_images - 2

    if slots <= 0:
        return [earliest, latest]

    if slots >= len(intermediate):
        selected_intermediate = intermediate
    else:
        selected_intermediate = []
        total_span = len(eligible) - 1
        for index in range(slots):
            # Spread picks across interior sequence using stable integer buckets.
            absolute_index = ((index + 1) * total_span) // (slots + 1)
            absolute_index = max(1, min(len(eligible) - 2, absolute_index))
            selected_intermediate.append(eligible[absolute_index])

    selected: list[InvestigationEvidence] = [earliest, *selected_intermediate, latest]
    # Defensive de-dupe for any accidental overlap in computed interior picks.
    deduped: list[InvestigationEvidence] = []
    seen_ids: set[str] = set()
    for evidence in selected:
        if evidence.evidence_id in seen_ids:
            continue
        seen_ids.add(evidence.evidence_id)
        deduped.append(evidence)

    deduped.sort(key=lambda item: (item.sequence_number, item.evidence_id))
    return deduped[:max_selected_images]


def build_frozen_evidence_manifest(
    *,
    session_id: str,
    analysis_attempt_id: str,
    evidence_records: list[InvestigationEvidence],
    size_bytes_by_evidence_id: dict[str, int] | None = None,
    max_selected_images: int = _DEFAULT_PROVIDER_MAX_IMAGES,
    created_at_utc: datetime | None = None,
    manifest_id: str | None = None,
    selection_policy_version: str = _DEFAULT_SELECTION_POLICY_VERSION,
) -> InvestigationFrozenEvidenceManifest:
    if max_selected_images <= 0:
        raise InvestigationFrozenManifestSelectionError("max_selected_images must be >= 1.")
    if max_selected_images > _DEFAULT_PROVIDER_MAX_IMAGES:
        raise InvestigationFrozenManifestSelectionError(
            f"max_selected_images cannot exceed {_DEFAULT_PROVIDER_MAX_IMAGES} for this phase."
        )

    eligible_images: list[InvestigationEvidence] = []
    for evidence in evidence_records:
        if evidence.evidence_type != InvestigationEvidenceType.IMAGE:
            continue
        if evidence.validation_status not in {
            InvestigationEvidenceValidationStatus.ACCEPTED,
            InvestigationEvidenceValidationStatus.DUPLICATE_ACCEPTED,
        }:
            continue
        if evidence.session_id != session_id:
            raise InvestigationFrozenManifestSelectionError(
                "Eligible evidence contains a different session_id."
            )
        eligible_images.append(evidence)

    if not eligible_images:
        raise InvestigationFrozenManifestSelectionError("At least one accepted image evidence item is required.")

    ordered = sorted(eligible_images, key=lambda item: (item.sequence_number, item.evidence_id))

    seen_ids: set[str] = set()
    for evidence in ordered:
        if evidence.evidence_id in seen_ids:
            raise InvestigationFrozenManifestSelectionError("Duplicate evidence_id values are not allowed.")
        seen_ids.add(evidence.evidence_id)

    selected = _deterministic_subset(ordered, max_selected_images=max_selected_images)

    size_lookup = size_bytes_by_evidence_id or {}

    selected_items: list[InvestigationFrozenEvidenceItem] = []
    for index, evidence in enumerate(selected):
        if evidence.evidence_id in size_lookup:
            size_bytes = size_lookup[evidence.evidence_id]
        else:
            size_bytes = _extract_size_from_metadata(evidence)

        selected_items.append(
            InvestigationFrozenEvidenceItem(
                evidence_id=evidence.evidence_id,
                session_id=evidence.session_id,
                storage_ref=evidence.storage_ref,
                evidence_type=evidence.evidence_type,
                mime_type=evidence.mime_type,
                captured_at_utc=evidence.client_timestamp_utc,
                content_hash=(
                    evidence.content_hash
                    if evidence.content_hash
                    else (_raise_missing_content_hash(evidence.evidence_id))
                ),
                size_bytes=size_bytes,
                selection_index=index,
            )
        )

    manifest_hash = _canonical_selected_subset_hash(
        schema_version=INVESTIGATION_FROZEN_EVIDENCE_MANIFEST_SCHEMA_VERSION,
        session_id=session_id,
        analysis_attempt_id=analysis_attempt_id,
        selection_policy_version=selection_policy_version,
        selected_items=selected_items,
    )

    return InvestigationFrozenEvidenceManifest(
        schema_version=INVESTIGATION_FROZEN_EVIDENCE_MANIFEST_SCHEMA_VERSION,
        manifest_id=manifest_id or str(uuid4()),
        session_id=session_id,
        analysis_attempt_id=analysis_attempt_id,
        created_at_utc=created_at_utc or datetime.now(timezone.utc),
        selection_policy_version=selection_policy_version,
        selected_evidence=selected_items,
        selected_evidence_ids=[item.evidence_id for item in selected_items],
        evidence_count=len(selected_items),
        manifest_hash=manifest_hash,
    )


def build_frozen_evidence_manifest_for_session(
    *,
    evidence_store: InvestigationEvidenceStore,
    session_id: str,
    analysis_attempt_id: str,
    max_selected_images: int = _DEFAULT_PROVIDER_MAX_IMAGES,
    created_at_utc: datetime | None = None,
    manifest_id: str | None = None,
    selection_policy_version: str = _DEFAULT_SELECTION_POLICY_VERSION,
) -> InvestigationFrozenEvidenceManifest:
    evidence_records = evidence_store.list_evidence(session_id)
    size_bytes_by_evidence_id = _size_lookup_from_store_records(
        evidence_store=evidence_store,
        session_id=session_id,
        evidence_records=evidence_records,
    )
    return build_frozen_evidence_manifest(
        session_id=session_id,
        analysis_attempt_id=analysis_attempt_id,
        evidence_records=evidence_records,
        size_bytes_by_evidence_id=size_bytes_by_evidence_id,
        max_selected_images=max_selected_images,
        created_at_utc=created_at_utc,
        manifest_id=manifest_id,
        selection_policy_version=selection_policy_version,
    )


def _extract_size_from_metadata(evidence: InvestigationEvidence) -> int:
    if isinstance(evidence.metadata, dict):
        size_value = evidence.metadata.get("size_bytes")
        if isinstance(size_value, int) and size_value > 0:
            return size_value
    raise InvestigationFrozenManifestSelectionError(
        f"Missing size_bytes for evidence_id={evidence.evidence_id}."
    )


def _raise_missing_content_hash(evidence_id: str) -> str:
    raise InvestigationFrozenManifestSelectionError(
        f"Missing content_hash for evidence_id={evidence_id}."
    )


def _size_lookup_from_store_records(
    *,
    evidence_store: InvestigationEvidenceStore,
    session_id: str,
    evidence_records: list[InvestigationEvidence],
) -> dict[str, int]:
    workspace = evidence_store.session_store.session_workspace_dir(session_id)
    lookup: dict[str, int] = {}
    for evidence in evidence_records:
        payload_path = (workspace / evidence.storage_ref).resolve(strict=False)
        workspace_resolved = workspace.resolve(strict=False)
        if workspace_resolved not in payload_path.parents and payload_path != workspace_resolved:
            raise InvestigationFrozenManifestSelectionError(
                f"Unsafe storage_ref for evidence_id={evidence.evidence_id}."
            )
        if not payload_path.exists() or not payload_path.is_file():
            raise InvestigationFrozenManifestSelectionError(
                f"Payload missing for evidence_id={evidence.evidence_id}."
            )
        size_value = payload_path.stat().st_size
        if size_value <= 0:
            raise InvestigationFrozenManifestSelectionError(
                f"Payload size invalid for evidence_id={evidence.evidence_id}."
            )
        lookup[evidence.evidence_id] = size_value
    return lookup
