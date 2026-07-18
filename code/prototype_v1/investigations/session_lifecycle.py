from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from .models import InvestigationSession, InvestigationSessionErrorMetadata, InvestigationSessionStatus


@dataclass
class InvestigationSessionLifecycleError(RuntimeError):
    category: str
    message: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_expected_revision(session: InvestigationSession, expected_revision: int | None) -> None:
    if expected_revision is None:
        return
    if expected_revision != session.revision:
        raise InvestigationSessionLifecycleError(
            category="revision_conflict",
            message="expected_revision does not match the current session revision.",
        )


def _normalize_uuid_or_error(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise InvestigationSessionLifecycleError(
            category="validation_error",
            message=f"{field_name} is required.",
        )
    try:
        return str(UUID(text))
    except ValueError as exc:
        raise InvestigationSessionLifecycleError(
            category="validation_error",
            message=f"{field_name} must be a valid UUID.",
        ) from exc


def apply_pause_transition(
    session: InvestigationSession,
    *,
    expected_revision: int | None,
) -> tuple[InvestigationSession, bool]:
    _validate_expected_revision(session, expected_revision)

    if session.status in {InvestigationSessionStatus.CREATED, InvestigationSessionStatus.COLLECTING}:
        now = _utc_now()
        updated = session.model_copy(
            update={
                "status": InvestigationSessionStatus.PAUSED,
                "revision": session.revision + 1,
                "updated_at_utc": now,
                "paused_at_utc": now,
            }
        )
        return updated, True

    if session.status == InvestigationSessionStatus.PAUSED:
        return session, False

    raise InvestigationSessionLifecycleError(
        category="invalid_state_transition",
        message="Session cannot be paused from the current state.",
    )


def apply_resume_transition(
    session: InvestigationSession,
    *,
    expected_revision: int | None,
) -> tuple[InvestigationSession, bool]:
    _validate_expected_revision(session, expected_revision)

    if session.status == InvestigationSessionStatus.PAUSED:
        now = _utc_now()
        updated = session.model_copy(
            update={
                "status": InvestigationSessionStatus.COLLECTING,
                "revision": session.revision + 1,
                "updated_at_utc": now,
            }
        )
        return updated, True

    if session.status == InvestigationSessionStatus.COLLECTING:
        return session, False

    raise InvestigationSessionLifecycleError(
        category="invalid_state_transition",
        message="Session cannot be resumed from the current state.",
    )


def apply_start_transition(
    session: InvestigationSession,
    *,
    expected_revision: int | None,
) -> tuple[InvestigationSession, bool]:
    _validate_expected_revision(session, expected_revision)

    if session.status == InvestigationSessionStatus.CREATED:
        now = _utc_now()
        updated = session.model_copy(
            update={
                "status": InvestigationSessionStatus.COLLECTING,
                "revision": session.revision + 1,
                "updated_at_utc": now,
            }
        )
        return updated, True

    if session.status == InvestigationSessionStatus.COLLECTING:
        return session, False

    raise InvestigationSessionLifecycleError(
        category="invalid_state_transition",
        message="Session cannot be started from the current state.",
    )


def apply_cancel_transition(
    session: InvestigationSession,
    *,
    expected_revision: int | None,
) -> tuple[InvestigationSession, bool]:
    _validate_expected_revision(session, expected_revision)

    if session.status in {
        InvestigationSessionStatus.CREATED,
        InvestigationSessionStatus.COLLECTING,
        InvestigationSessionStatus.PAUSED,
    }:
        now = _utc_now()
        updated = session.model_copy(
            update={
                "status": InvestigationSessionStatus.CANCELLED,
                "revision": session.revision + 1,
                "updated_at_utc": now,
                "cancelled_at_utc": now,
            }
        )
        return updated, True

    if session.status == InvestigationSessionStatus.CANCELLED:
        return session, False

    raise InvestigationSessionLifecycleError(
        category="invalid_state_transition",
        message="Session cannot be cancelled from the current state.",
    )


def apply_finalize_transition(
    session: InvestigationSession,
    *,
    expected_revision: int | None,
) -> tuple[InvestigationSession, bool]:
    _validate_expected_revision(session, expected_revision)

    if session.status == InvestigationSessionStatus.COLLECTING:
        now = _utc_now()
        updated = session.model_copy(
            update={
                "status": InvestigationSessionStatus.FINALIZING,
                "revision": session.revision + 1,
                "updated_at_utc": now,
            }
        )
        return updated, True

    if session.status == InvestigationSessionStatus.FINALIZING:
        return session, False

    raise InvestigationSessionLifecycleError(
        category="invalid_state_transition",
        message="Session cannot transition to finalizing from the current state.",
    )


def apply_analysis_started_transition(
    session: InvestigationSession,
    *,
    expected_revision: int | None,
) -> tuple[InvestigationSession, bool]:
    _validate_expected_revision(session, expected_revision)

    if session.status == InvestigationSessionStatus.FINALIZING:
        now = _utc_now()
        updated = session.model_copy(
            update={
                "status": InvestigationSessionStatus.ANALYZING,
                "revision": session.revision + 1,
                "updated_at_utc": now,
            }
        )
        return updated, True

    if session.status == InvestigationSessionStatus.ANALYZING:
        return session, False

    raise InvestigationSessionLifecycleError(
        category="invalid_state_transition",
        message="Session cannot transition to analyzing from the current state.",
    )


def apply_complete_transition(
    session: InvestigationSession,
    *,
    expected_revision: int | None,
    completed_result_id: str,
) -> tuple[InvestigationSession, bool]:
    _validate_expected_revision(session, expected_revision)
    normalized_result_id = _normalize_uuid_or_error(completed_result_id, "completed_result_id")

    if session.status == InvestigationSessionStatus.ANALYZING:
        now = _utc_now()
        updated = session.model_copy(
            update={
                "status": InvestigationSessionStatus.COMPLETED,
                "completed_result_id": normalized_result_id,
                "revision": session.revision + 1,
                "updated_at_utc": now,
            }
        )
        return updated, True

    if session.status == InvestigationSessionStatus.COMPLETED and session.completed_result_id == normalized_result_id:
        return session, False

    raise InvestigationSessionLifecycleError(
        category="invalid_state_transition",
        message="Session cannot transition to completed from the current state.",
    )


def apply_fail_transition(
    session: InvestigationSession,
    *,
    expected_revision: int | None,
    error_category: str,
    safe_message: str,
    retryable: bool,
) -> tuple[InvestigationSession, bool]:
    _validate_expected_revision(session, expected_revision)

    if session.status in {InvestigationSessionStatus.COMPLETED, InvestigationSessionStatus.CANCELLED}:
        raise InvestigationSessionLifecycleError(
            category="invalid_state_transition",
            message="Terminal sessions cannot transition to failed.",
        )

    if session.status in {InvestigationSessionStatus.FINALIZING, InvestigationSessionStatus.ANALYZING}:
        now = _utc_now()
        error = InvestigationSessionErrorMetadata(
            error_category=error_category,
            retryable=retryable,
            occurred_at_utc=now,
            safe_message=safe_message,
        )
        updated = session.model_copy(
            update={
                "status": InvestigationSessionStatus.FAILED,
                "last_error": error,
                "revision": session.revision + 1,
                "updated_at_utc": now,
            }
        )
        return updated, True

    if session.status == InvestigationSessionStatus.FAILED:
        return session, False

    raise InvestigationSessionLifecycleError(
        category="invalid_state_transition",
        message="Session cannot transition to failed from the current state.",
    )
