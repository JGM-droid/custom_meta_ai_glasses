from __future__ import annotations

import json
import os
import tempfile
from datetime import timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from .models import (
    INVESTIGATION_CANONICAL_RESULT_SCHEMA_VERSION,
    InvestigationCanonicalResultEnvelope,
    InvestigationRetainedResult,
)


class InvestigationStoreError(RuntimeError):
    pass


class InvestigationStoreNotFound(InvestigationStoreError):
    pass


class InvestigationStoreConflict(InvestigationStoreError):
    pass


def _atomic_write_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)

        os.replace(str(temp_path), str(path))
    except OSError as exc:
        raise InvestigationStoreError("Failed to persist investigation result.") from exc
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _canonical_store_root(latest_path: Path) -> Path:
    normalized = Path(latest_path)
    if normalized.name == "latest.json":
        return normalized.parent
    return normalized.parent / "investigations"


def _results_dir(store_root: Path) -> Path:
    return store_root / "results"


def _validate_result_id(result_id: str) -> str:
    text = str(result_id or "").strip()
    if not text:
        raise InvestigationStoreError("result_id is required.")
    try:
        parsed = UUID(text)
    except ValueError as exc:
        raise InvestigationStoreError("result_id must be a valid UUID.") from exc
    return str(parsed)


def _canonical_result_path(store_root: Path, result_id: str) -> Path:
    normalized = _validate_result_id(result_id)
    return _results_dir(store_root) / f"{normalized}.json"


def _serialize_canonical_result(envelope: InvestigationCanonicalResultEnvelope) -> str:
    return json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False, indent=2)


def _optional_uuid(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return str(UUID(text))
    except ValueError:
        return None


def _strict_optional_uuid(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        raise InvestigationStoreError(f"{field_name} must be a valid UUID when provided.")

    try:
        return str(UUID(text))
    except ValueError as exc:
        raise InvestigationStoreError(f"{field_name} must be a valid UUID when provided.") from exc


def _default_result_id(retained_result: InvestigationRetainedResult) -> str:
    seed = f"{retained_result.investigation_id}|{retained_result.completed_at_utc.astimezone(timezone.utc).isoformat()}"
    return str(uuid5(NAMESPACE_URL, seed))


def save_investigation_result_by_id(store_root: Path, envelope: InvestigationCanonicalResultEnvelope) -> None:
    root = Path(store_root)
    root.mkdir(parents=True, exist_ok=True)
    path = _canonical_result_path(root, envelope.result_id)
    payload = _serialize_canonical_result(envelope)

    if path.exists() and path.is_file():
        existing = load_investigation_result_by_id(root, envelope.result_id)
        existing_payload = _serialize_canonical_result(existing)
        if existing_payload == payload:
            return
        raise InvestigationStoreConflict("A different canonical result already exists for result_id.")

    _atomic_write_json(path, payload)


def load_investigation_result_by_id(store_root: Path, result_id: str) -> InvestigationCanonicalResultEnvelope:
    root = Path(store_root)
    path = _canonical_result_path(root, result_id)
    if not path.exists() or not path.is_file():
        raise InvestigationStoreNotFound("No canonical investigation result exists for result_id.")

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvestigationStoreError("Failed to read canonical investigation result.") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvestigationStoreError("Canonical investigation result is malformed JSON.") from exc

    try:
        return InvestigationCanonicalResultEnvelope.model_validate(parsed)
    except ValidationError as exc:
        raise InvestigationStoreError("Canonical investigation result has invalid schema.") from exc


def save_latest_investigation_result(path: Path, result: InvestigationRetainedResult) -> None:
    canonical_root = _canonical_store_root(path)
    canonical_result = InvestigationCanonicalResultEnvelope(
        schema_version=INVESTIGATION_CANONICAL_RESULT_SCHEMA_VERSION,
        result_id=_default_result_id(result),
        session_id=_optional_uuid(result.session_id),
        analysis_attempt_id=None,
        created_at_utc=result.completed_at_utc,
        retained_result=result,
        result_hash=None,
    )

    save_investigation_result_by_id(canonical_root, canonical_result)

    payload = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
    _atomic_write_json(path, payload)


def load_latest_investigation_result(path: Path) -> InvestigationRetainedResult:
    if not path.exists() or not path.is_file():
        raise InvestigationStoreNotFound("No retained investigation result exists.")

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvestigationStoreError("Failed to read retained investigation result.") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvestigationStoreError("Retained investigation result is malformed JSON.") from exc

    try:
        return InvestigationRetainedResult.model_validate(parsed)
    except ValidationError as exc:
        raise InvestigationStoreError("Retained investigation result has invalid schema.") from exc


def save_canonical_investigation_result(
    store_root: Path,
    *,
    result_id: str,
    retained_result: InvestigationRetainedResult,
    session_id: str | None = None,
    analysis_attempt_id: str | None = None,
    result_hash: str | None = None,
) -> InvestigationCanonicalResultEnvelope:
    envelope = InvestigationCanonicalResultEnvelope(
        schema_version=INVESTIGATION_CANONICAL_RESULT_SCHEMA_VERSION,
        result_id=_validate_result_id(result_id),
        session_id=_strict_optional_uuid(session_id, "session_id"),
        analysis_attempt_id=_strict_optional_uuid(analysis_attempt_id, "analysis_attempt_id"),
        created_at_utc=retained_result.completed_at_utc,
        retained_result=retained_result,
        result_hash=result_hash,
    )
    save_investigation_result_by_id(store_root, envelope)
    return envelope


def load_canonical_investigation_result(store_root: Path, result_id: str) -> InvestigationCanonicalResultEnvelope:
    return load_investigation_result_by_id(store_root, result_id)
