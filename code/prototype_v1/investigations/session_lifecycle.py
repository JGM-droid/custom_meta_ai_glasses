from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .models import InvestigationSession, InvestigationSessionStatus


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
