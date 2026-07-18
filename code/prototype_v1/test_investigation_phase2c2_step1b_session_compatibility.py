from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investigations.models import (
    INVESTIGATION_SESSION_SCHEMA_VERSION,
    InvestigationSession,
    InvestigationSessionStatus,
    create_new_investigation_session,
)
from investigations.session_store import InvestigationSessionStore


def _base_session_payload(*, status: InvestigationSessionStatus = InvestigationSessionStatus.COLLECTING) -> dict[str, object]:
    return {
        "schema_version": INVESTIGATION_SESSION_SCHEMA_VERSION,
        "session_id": str(uuid4()),
        "status": status.value,
        "revision": 3,
        "created_at_utc": datetime.now(timezone.utc),
        "updated_at_utc": datetime.now(timezone.utc),
        "paused_at_utc": None,
        "cancelled_at_utc": None,
        "client_metadata": {"source": "desktop"},
        "current_analysis_attempt_id": None,
        "completed_result_id": None,
        "last_error": None,
    }


def test_new_session_defaults_step1b_fields_to_none():
    session = create_new_investigation_session()
    assert session.active_analysis_attempt_id is None
    assert session.latest_analysis_attempt_id is None


def test_step1b_optional_fields_accept_and_normalize_uuid_values():
    active = str(uuid4()).upper()
    latest = str(uuid4()).upper()
    payload = _base_session_payload()
    payload["active_analysis_attempt_id"] = active
    payload["latest_analysis_attempt_id"] = latest

    session = InvestigationSession.model_validate(payload)
    assert session.active_analysis_attempt_id == str(UUID(active))
    assert session.latest_analysis_attempt_id == str(UUID(latest))


def test_step1b_optional_fields_reject_blank_and_invalid_values():
    payload = _base_session_payload()
    payload["active_analysis_attempt_id"] = "   "
    with pytest.raises(ValidationError):
        InvestigationSession.model_validate(payload)

    payload = _base_session_payload()
    payload["latest_analysis_attempt_id"] = "not-a-uuid"
    with pytest.raises(ValidationError):
        InvestigationSession.model_validate(payload)


def test_session_round_trip_with_active_analysis_attempt_id():
    payload = _base_session_payload()
    payload["active_analysis_attempt_id"] = str(uuid4())
    session = InvestigationSession.model_validate(payload)

    dumped = session.model_dump(mode="json")
    loaded = InvestigationSession.model_validate(dumped)

    assert loaded.active_analysis_attempt_id == session.active_analysis_attempt_id
    assert loaded.latest_analysis_attempt_id is None


def test_session_round_trip_with_latest_analysis_attempt_id():
    payload = _base_session_payload()
    payload["latest_analysis_attempt_id"] = str(uuid4())
    session = InvestigationSession.model_validate(payload)

    dumped = session.model_dump(mode="json")
    loaded = InvestigationSession.model_validate(dumped)

    assert loaded.active_analysis_attempt_id is None
    assert loaded.latest_analysis_attempt_id == session.latest_analysis_attempt_id


def test_session_round_trip_with_both_step1b_fields_populated():
    payload = _base_session_payload()
    payload["active_analysis_attempt_id"] = str(uuid4())
    payload["latest_analysis_attempt_id"] = str(uuid4())
    session = InvestigationSession.model_validate(payload)

    dumped = session.model_dump(mode="json")
    loaded = InvestigationSession.model_validate(dumped)

    assert loaded.active_analysis_attempt_id == session.active_analysis_attempt_id
    assert loaded.latest_analysis_attempt_id == session.latest_analysis_attempt_id


def test_older_session_payload_missing_step1b_fields_loads_with_defaults():
    payload = _base_session_payload(status=InvestigationSessionStatus.PAUSED)

    session = InvestigationSession.model_validate(payload)
    assert session.active_analysis_attempt_id is None
    assert session.latest_analysis_attempt_id is None
    assert session.status == InvestigationSessionStatus.PAUSED
    assert session.revision == 3


def test_store_save_reload_preserves_older_session_payload_semantics(tmp_path: Path):
    root = tmp_path / "investigation_sessions"
    store = InvestigationSessionStore(root)

    payload = _base_session_payload(status=InvestigationSessionStatus.COLLECTING)
    session_id = str(payload["session_id"])
    session_path = root / "sessions" / f"{session_id}.json"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps(payload, default=str), encoding="utf-8")

    loaded = store.load_session(session_id)
    assert loaded.active_analysis_attempt_id is None
    assert loaded.latest_analysis_attempt_id is None
    assert loaded.status == InvestigationSessionStatus.COLLECTING
    assert loaded.revision == 3

    store.save_session(loaded)
    reloaded = store.load_session(session_id)

    assert reloaded.active_analysis_attempt_id is None
    assert reloaded.latest_analysis_attempt_id is None
    assert reloaded.session_id == loaded.session_id
    assert reloaded.status == loaded.status
    assert reloaded.revision == loaded.revision
    assert reloaded.client_metadata == loaded.client_metadata


def test_legacy_current_analysis_attempt_id_remains_supported():
    payload = _base_session_payload()
    payload["current_analysis_attempt_id"] = str(uuid4())

    session = InvestigationSession.model_validate(payload)
    assert session.current_analysis_attempt_id is not None
    assert session.active_analysis_attempt_id is None
    assert session.latest_analysis_attempt_id is None
