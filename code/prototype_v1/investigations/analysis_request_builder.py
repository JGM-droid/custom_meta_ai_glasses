from __future__ import annotations

from pathlib import Path

from .analysis_contract_errors import (
    InvestigationAnalysisIdentityMismatchError,
    InvestigationAnalysisMissingEvidenceError,
    InvestigationAnalysisRequestBuildError,
    InvestigationAnalysisUnsupportedEvidenceError,
)
from .analysis_prompt_renderer import render_deterministic_analysis_instructions
from .evidence_store import InvestigationEvidenceNotFound, InvestigationEvidenceStore, InvestigationEvidenceStoreError
from .models import (
    INVESTIGATION_ANALYSIS_REQUEST_PACKAGE_SCHEMA_VERSION,
    InvestigationAnalysisAttempt,
    InvestigationAnalysisEvidenceAttachment,
    InvestigationAnalysisRequestPackage,
    InvestigationEvidenceType,
    InvestigationFrozenEvidenceItem,
    InvestigationFrozenEvidenceManifest,
    InvestigationSession,
    SUPPORTED_ANALYSIS_REQUEST_IMAGE_MIME_TYPES,
)


def _normalize_optional_explanation_text(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > 1000:
        raise InvestigationAnalysisRequestBuildError("normalized_explanation_text exceeds the allowed length.")
    return text


def _safe_payload_path(*, session_workspace: Path, storage_ref: str) -> Path:
    normalized = str(storage_ref or "").strip().replace("\\", "/")
    if not normalized:
        raise InvestigationAnalysisMissingEvidenceError("storage_ref is required.")
    if normalized.startswith("/"):
        raise InvestigationAnalysisMissingEvidenceError("storage_ref must be relative.")

    candidate = (session_workspace / normalized).resolve(strict=False)
    workspace_resolved = session_workspace.resolve(strict=False)
    if workspace_resolved not in candidate.parents and candidate != workspace_resolved:
        raise InvestigationAnalysisMissingEvidenceError("storage_ref escapes the session workspace.")
    return candidate


def _validate_session_attempt_manifest_alignment(
    *,
    session: InvestigationSession,
    analysis_attempt: InvestigationAnalysisAttempt,
    frozen_manifest: InvestigationFrozenEvidenceManifest,
) -> None:
    if analysis_attempt.session_id != session.session_id:
        raise InvestigationAnalysisIdentityMismatchError("analysis_attempt.session_id does not match session.session_id.")
    if frozen_manifest.session_id != session.session_id:
        raise InvestigationAnalysisIdentityMismatchError("frozen_manifest.session_id does not match session.session_id.")
    if frozen_manifest.analysis_attempt_id != analysis_attempt.analysis_attempt_id:
        raise InvestigationAnalysisIdentityMismatchError(
            "frozen_manifest.analysis_attempt_id does not match analysis_attempt.analysis_attempt_id."
        )
    if analysis_attempt.frozen_manifest_hash != frozen_manifest.manifest_hash:
        raise InvestigationAnalysisIdentityMismatchError(
            "analysis_attempt.frozen_manifest_hash does not match frozen_manifest.manifest_hash."
        )
    if analysis_attempt.frozen_manifest_id and analysis_attempt.frozen_manifest_id != frozen_manifest.manifest_id:
        raise InvestigationAnalysisIdentityMismatchError(
            "analysis_attempt.frozen_manifest_id does not match frozen_manifest.manifest_id."
        )


def _build_attachment(
    *,
    session: InvestigationSession,
    frozen_item: InvestigationFrozenEvidenceItem,
    evidence_store: InvestigationEvidenceStore,
) -> InvestigationAnalysisEvidenceAttachment:
    if frozen_item.session_id != session.session_id:
        raise InvestigationAnalysisIdentityMismatchError("Frozen evidence item session_id does not match session.")
    if frozen_item.evidence_type != InvestigationEvidenceType.IMAGE:
        raise InvestigationAnalysisUnsupportedEvidenceError("Only image evidence is supported for analysis packaging.")
    if frozen_item.mime_type not in SUPPORTED_ANALYSIS_REQUEST_IMAGE_MIME_TYPES:
        raise InvestigationAnalysisUnsupportedEvidenceError("Frozen evidence mime_type is unsupported.")

    session_workspace = evidence_store.session_store.session_workspace_dir(session.session_id)
    payload_path = _safe_payload_path(session_workspace=session_workspace, storage_ref=frozen_item.storage_ref)
    if not payload_path.exists() or not payload_path.is_file():
        raise InvestigationAnalysisMissingEvidenceError(
            f"Evidence payload file is missing for evidence_id={frozen_item.evidence_id}."
        )

    try:
        evidence_record = evidence_store.load_evidence_for_analysis(
            session_id=session.session_id,
            evidence_id=frozen_item.evidence_id,
        )
    except InvestigationEvidenceNotFound as exc:
        raise InvestigationAnalysisMissingEvidenceError(
            f"Missing evidence for evidence_id={frozen_item.evidence_id}."
        ) from exc
    except InvestigationEvidenceStoreError as exc:
        raise InvestigationAnalysisRequestBuildError("Failed to resolve evidence record.") from exc

    if evidence_record.session_id != session.session_id:
        raise InvestigationAnalysisIdentityMismatchError("Resolved evidence record belongs to a different session.")
    if evidence_record.storage_ref != frozen_item.storage_ref:
        raise InvestigationAnalysisIdentityMismatchError(
            "Resolved evidence storage_ref does not match frozen manifest storage_ref."
        )
    if evidence_record.mime_type != frozen_item.mime_type:
        raise InvestigationAnalysisIdentityMismatchError(
            "Resolved evidence mime_type does not match frozen manifest mime_type."
        )

    metadata: dict[str, str] = {
        "filename": evidence_record.filename,
        "source": evidence_record.source,
    }

    return InvestigationAnalysisEvidenceAttachment(
        evidence_id=frozen_item.evidence_id,
        capture_timestamp_utc=frozen_item.captured_at_utc,
        media_type=frozen_item.mime_type,
        storage_ref=frozen_item.storage_ref,
        evidence_metadata=metadata,
    )


def build_deterministic_analysis_request_package(
    *,
    session: InvestigationSession,
    analysis_attempt: InvestigationAnalysisAttempt,
    frozen_manifest: InvestigationFrozenEvidenceManifest,
    evidence_store: InvestigationEvidenceStore,
    normalized_explanation_text: str | None,
) -> InvestigationAnalysisRequestPackage:
    _validate_session_attempt_manifest_alignment(
        session=session,
        analysis_attempt=analysis_attempt,
        frozen_manifest=frozen_manifest,
    )

    ordered_attachments: list[InvestigationAnalysisEvidenceAttachment] = []
    for frozen_item in frozen_manifest.selected_evidence:
        ordered_attachments.append(
            _build_attachment(
                session=session,
                frozen_item=frozen_item,
                evidence_store=evidence_store,
            )
        )

    system_instructions, context_instructions = render_deterministic_analysis_instructions(
        normalized_explanation_text=normalized_explanation_text,
        ordered_evidence_inputs=ordered_attachments,
    )

    return InvestigationAnalysisRequestPackage(
        schema_version=INVESTIGATION_ANALYSIS_REQUEST_PACKAGE_SCHEMA_VERSION,
        session_id=session.session_id,
        analysis_attempt_id=analysis_attempt.analysis_attempt_id,
        attempt_number=analysis_attempt.attempt_number,
        frozen_manifest_id=frozen_manifest.manifest_id,
        frozen_manifest_hash=frozen_manifest.manifest_hash,
        normalized_explanation_text=_normalize_optional_explanation_text(normalized_explanation_text),
        deterministic_system_instructions=system_instructions,
        deterministic_context_instructions=context_instructions,
        ordered_evidence_inputs=ordered_attachments,
    )
