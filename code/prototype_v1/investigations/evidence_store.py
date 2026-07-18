from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .models import (
    InvestigationEvidence,
    InvestigationEvidenceCreateRequest,
    InvestigationEvidenceType,
    InvestigationEvidenceValidationStatus,
    InvestigationSession,
    InvestigationSessionStatus,
)
from .session_store import InvestigationSessionStore


EVIDENCE_SCHEMA_VERSION = "1.0"
EVIDENCE_MANIFEST_FILENAME = "_evidence_manifest.json"
DEFAULT_EVIDENCE_SOURCE = "backend"

MAX_IMAGE_UPLOAD_BYTES = 2_000_000
MAX_AUDIO_UPLOAD_BYTES = 2_000_000
UPLOAD_CHUNK_SIZE = 64 * 1024

_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
}
_AUDIO_MIME_TYPES = {
    "audio/mpeg",
    "audio/mp4",
    "audio/aac",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
}


class InvestigationEvidenceStoreError(RuntimeError):
    pass


class InvestigationEvidenceNotFound(InvestigationEvidenceStoreError):
    pass


class InvestigationEvidenceInvalidId(InvestigationEvidenceStoreError):
    pass


class InvestigationEvidenceStateError(InvestigationEvidenceStoreError):
    pass


class InvestigationEvidenceInvalidContentType(InvestigationEvidenceStoreError):
    pass


class InvestigationEvidenceManifestError(InvestigationEvidenceStoreError):
    pass


class InvestigationEvidenceSequenceState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = EVIDENCE_SCHEMA_VERSION
    next_sequence: int = Field(default=1, ge=1)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != EVIDENCE_SCHEMA_VERSION:
            raise ValueError("Unsupported evidence manifest schema_version.")
        return value


def _session_allows_evidence_mutation(session: InvestigationSession) -> bool:
    return session.status == InvestigationSessionStatus.COLLECTING


def _session_allows_evidence_list(session: InvestigationSession) -> bool:
    return session.status in {
        InvestigationSessionStatus.CREATED,
        InvestigationSessionStatus.COLLECTING,
        InvestigationSessionStatus.PAUSED,
        InvestigationSessionStatus.CANCELLED,
    }


def _normalize_uuid_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise InvestigationEvidenceInvalidId("Evidence ID is required.")

    try:
        parsed = UUID(text)
    except ValueError as exc:
        raise InvestigationEvidenceInvalidId("Evidence ID must be a valid UUID.") from exc

    return str(parsed)


def _sha256_hex(content: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(content)
    return digest.hexdigest()


def _safe_basename(filename: str) -> str:
    text = str(filename or "").strip().replace("\\", "/")
    if not text:
        raise ValueError("filename is required.")

    base = Path(text).name
    if base != text:
        raise ValueError("filename must be a safe basename.")
    if base in {".", ".."}:
        raise ValueError("filename is invalid.")
    if len(base) > 255:
        raise ValueError("filename is too long.")
    if any(part == "" for part in base.split("/")):
        raise ValueError("filename must not contain empty segments.")
    return base


def _normalize_storage_ref(storage_ref: str) -> str:
    text = str(storage_ref or "").strip().replace("\\", "/")
    if not text:
        raise ValueError("storage_ref is required.")
    if text.startswith("/") or re.match(r"^[a-zA-Z]:", text):
        raise ValueError("storage_ref must be relative.")
    if "//" in text:
        raise ValueError("storage_ref must not contain empty segments.")
    parts = text.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("storage_ref must not escape the workspace.")
    return text


def _relpath_under(base_dir: Path, relative_path: str) -> Path:
    candidate = (base_dir / relative_path).resolve(strict=False)
    resolved_base = base_dir.resolve(strict=False)
    if resolved_base not in candidate.parents and candidate != resolved_base:
        raise ValueError("storage_ref must remain within the session workspace.")
    return candidate


def _candidate_payload_ref(evidence_id: str, filename: str, evidence_type: InvestigationEvidenceType) -> str:
    safe_name = _safe_basename(filename)
    suffix = Path(safe_name).suffix.lower()
    if evidence_type == InvestigationEvidenceType.IMAGE and suffix not in {".png", ".jpg", ".jpeg"}:
        suffix = ".bin"
    if evidence_type == InvestigationEvidenceType.AUDIO and suffix not in {".mp3", ".m4a", ".aac", ".ogg", ".wav"}:
        suffix = ".bin"
    return f"evidence/payloads/{evidence_id}_{safe_name if suffix != '.bin' else Path(safe_name).stem + '.bin'}"


def _sanitize_media_type(value: str, evidence_type: InvestigationEvidenceType) -> str:
    mime_type = str(value or "").strip().lower()
    allowed = _IMAGE_MIME_TYPES if evidence_type == InvestigationEvidenceType.IMAGE else _AUDIO_MIME_TYPES
    if mime_type not in allowed:
        raise InvestigationEvidenceInvalidContentType("Unsupported media type.")
    return mime_type


class InvestigationEvidenceStore:
    def __init__(self, session_store: InvestigationSessionStore):
        self.session_store = session_store

    def _session_workspace_dir(self, session_id: str) -> Path:
        return self.session_store.session_workspace_dir(session_id)

    def _session_evidence_dir(self, session_id: str) -> Path:
        return self._session_workspace_dir(session_id) / "evidence"

    def _session_payload_dir(self, session_id: str) -> Path:
        return self._session_evidence_dir(session_id) / "payloads"

    def _manifest_path(self, session_id: str) -> Path:
        return self._session_evidence_dir(session_id) / EVIDENCE_MANIFEST_FILENAME

    def _session_corrupt_dir(self) -> Path:
        return self.session_store.corrupt_dir

    def _safe_record_payload_path(self, session_id: str, storage_ref: str) -> Path:
        workspace = self._session_workspace_dir(session_id)
        normalized = _normalize_storage_ref(storage_ref)
        candidate = _relpath_under(workspace, normalized)
        if candidate.is_dir():
            raise ValueError("storage_ref must reference a file.")
        return candidate

    def _safe_expected_payload_path(self, session_id: str, evidence_id: str, filename: str, evidence_type: InvestigationEvidenceType) -> tuple[str, Path]:
        ref = _candidate_payload_ref(evidence_id, filename, evidence_type)
        path = _relpath_under(self._session_workspace_dir(session_id), ref)
        return ref, path

    def _quarantine_file(self, path: Path, *, prefix: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self._session_corrupt_dir() / f"{prefix}_{stamp}_{uuid4().hex}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(str(path), str(target))
            return
        except OSError:
            pass

        try:
            shutil.copy2(str(path), str(target))
            path.unlink(missing_ok=True)
        except OSError:
            return

    def _read_json(self, path: Path) -> dict[str, object]:
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("JSON payload must be an object.")
        return parsed

    def _load_manifest_no_lock(self, session_id: str) -> InvestigationEvidenceSequenceState:
        path = self._manifest_path(session_id)
        if not path.exists() or not path.is_file():
            return InvestigationEvidenceSequenceState()

        try:
            parsed = self._read_json(path)
            return InvestigationEvidenceSequenceState.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            self._quarantine_file(path, prefix="evidence_manifest_corrupt")
            raise InvestigationEvidenceManifestError("Evidence manifest is unavailable.") from exc

    def _save_manifest_no_lock(self, session_id: str, manifest: InvestigationEvidenceSequenceState) -> None:
        path = self._manifest_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self.session_store.temp_dir),
                prefix="evidence-manifest.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2))
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)

            os.replace(str(temp_path), str(path))
        except OSError as exc:
            raise InvestigationEvidenceStoreError("Failed to persist evidence manifest.") from exc
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _load_evidence_from_path(self, path: Path, session_id: str) -> InvestigationEvidence:
        try:
            parsed = self._read_json(path)
            record = InvestigationEvidence.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            self._quarantine_file(path, prefix="evidence_record_corrupt")
            raise InvestigationEvidenceStoreError("Evidence data is malformed.") from exc

        try:
            expected_ref, expected_path = self._safe_expected_payload_path(session_id, record.evidence_id, record.filename, record.evidence_type)
            candidate_path = self._safe_record_payload_path(session_id, record.storage_ref)
            if candidate_path != expected_path or record.storage_ref != expected_ref:
                raise ValueError("storage_ref does not match the trusted evidence path.")
            if not candidate_path.exists() or not candidate_path.is_file():
                raise ValueError("Evidence payload is missing.")
        except ValueError as exc:
            self._quarantine_file(path, prefix="evidence_record_unsafe")
            raise InvestigationEvidenceStoreError("Evidence record is unsafe.") from exc

        return record

    def _list_evidence_unlocked(self, session_id: str) -> list[InvestigationEvidence]:
        evidence_dir = self._session_evidence_dir(session_id)
        if not evidence_dir.exists() or not evidence_dir.is_dir():
            return []

        items: list[InvestigationEvidence] = []
        for path in sorted(evidence_dir.glob("*.json")):
            if path.name == EVIDENCE_MANIFEST_FILENAME:
                continue
            try:
                items.append(self._load_evidence_from_path(path, session_id))
            except InvestigationEvidenceStoreError:
                continue

        items.sort(key=lambda item: (item.sequence_number, item.evidence_id))
        return items

    def list_evidence(self, session_id: str) -> list[InvestigationEvidence]:
        normalized = self.session_store.validate_session_id(session_id)

        def _list(session: InvestigationSession) -> list[InvestigationEvidence]:
            if not _session_allows_evidence_list(session):
                return []
            return self._list_evidence_unlocked(normalized)

        return self.session_store.run_with_session_lock(normalized, _list)

    def _validate_request(self, request: InvestigationEvidenceCreateRequest) -> InvestigationEvidenceCreateRequest:
        return InvestigationEvidenceCreateRequest.model_validate(request.model_dump(mode="python"))

    def _find_duplicate(self, session_id: str, evidence_type: InvestigationEvidenceType, content_hash: str) -> InvestigationEvidence | None:
        for item in self._list_evidence_unlocked(session_id):
            if item.evidence_type == evidence_type and item.content_hash == content_hash:
                return item
        return None

    def _build_record(
        self,
        *,
        session_id: str,
        evidence_id: str,
        sequence_number: int,
        evidence_type: InvestigationEvidenceType,
        request: InvestigationEvidenceCreateRequest,
        filename: str,
        mime_type: str,
        storage_ref: str,
        content_hash: str,
    ) -> InvestigationEvidence:
        return InvestigationEvidence(
            schema_version=EVIDENCE_SCHEMA_VERSION,
            evidence_id=evidence_id,
            session_id=session_id,
            evidence_type=evidence_type,
            created_at_utc=datetime.now(timezone.utc),
            validation_status=InvestigationEvidenceValidationStatus.ACCEPTED,
            sequence_number=sequence_number,
            client_timestamp_utc=request.client_timestamp_utc,
            filename=filename,
            mime_type=mime_type,
            storage_ref=storage_ref,
            content_hash=content_hash,
            width=request.width,
            height=request.height,
            duration_seconds=request.duration_seconds,
            normalized_text=request.normalized_text,
            metadata=request.metadata,
            source=request.source,
        )

    def upload_evidence(
        self,
        *,
        session_id: str,
        evidence_type: InvestigationEvidenceType,
        raw_bytes: bytes,
        mime_type: str,
        original_filename: str,
        request: InvestigationEvidenceCreateRequest,
    ) -> tuple[InvestigationEvidence, bool]:
        normalized = self.session_store.validate_session_id(session_id)
        if not raw_bytes:
            raise InvestigationEvidenceStoreError("Evidence payload is empty.")

        content_hash = _sha256_hex(raw_bytes)
        safe_filename = _safe_basename(original_filename or request.filename or "upload.bin")
        normalized_mime_type = _sanitize_media_type(mime_type or request.mime_type or "", evidence_type)
        normalized_request = self._validate_request(request)

        def _upload(session: InvestigationSession) -> tuple[InvestigationEvidence, bool]:
            if not _session_allows_evidence_mutation(session):
                raise InvestigationEvidenceStateError("Evidence can only be uploaded while collecting.")

            manifest = self._load_manifest_no_lock(normalized)
            duplicate = self._find_duplicate(normalized, evidence_type, content_hash)
            if duplicate is not None:
                return duplicate, False

            evidence_id = str(uuid4())
            sequence_number = manifest.next_sequence
            storage_ref, payload_path = self._safe_expected_payload_path(normalized, evidence_id, safe_filename, evidence_type)
            metadata_path = self._session_evidence_dir(normalized) / f"{evidence_id}.json"
            payload_path.parent.mkdir(parents=True, exist_ok=True)

            record = self._build_record(
                session_id=normalized,
                evidence_id=evidence_id,
                sequence_number=sequence_number,
                evidence_type=evidence_type,
                request=normalized_request,
                filename=safe_filename,
                mime_type=normalized_mime_type,
                storage_ref=storage_ref,
                content_hash=content_hash,
            )

            temp_payload: Path | None = None
            temp_metadata: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=str(self.session_store.temp_dir),
                    prefix=f"{evidence_id}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    handle.write(raw_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())
                    temp_payload = Path(handle.name)

                os.replace(str(temp_payload), str(payload_path))

                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=str(self.session_store.temp_dir),
                    prefix=f"{evidence_id}.meta.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2))
                    handle.flush()
                    os.fsync(handle.fileno())
                    temp_metadata = Path(handle.name)

                os.replace(str(temp_metadata), str(metadata_path))
                manifest.next_sequence = sequence_number + 1
                self._save_manifest_no_lock(normalized, manifest)
            except OSError as exc:
                try:
                    if payload_path.exists():
                        payload_path.unlink()
                except OSError:
                    pass
                try:
                    if metadata_path.exists():
                        metadata_path.unlink()
                except OSError:
                    pass
                raise InvestigationEvidenceStoreError("Failed to persist evidence.") from exc
            finally:
                for temp_path in (temp_payload, temp_metadata):
                    if temp_path and temp_path.exists():
                        try:
                            temp_path.unlink()
                        except OSError:
                            pass

            return record, True

        return self.session_store.run_with_session_lock(normalized, _upload)

    def delete_evidence(self, session_id: str, evidence_id: str) -> InvestigationEvidence:
        normalized_session_id = self.session_store.validate_session_id(session_id)
        normalized_evidence_id = _normalize_uuid_text(evidence_id)

        def _delete(session: InvestigationSession) -> InvestigationEvidence:
            if not _session_allows_evidence_mutation(session):
                raise InvestigationEvidenceStateError("Evidence can only be deleted while collecting.")

            metadata_path = self._session_evidence_dir(normalized_session_id) / f"{normalized_evidence_id}.json"
            if not metadata_path.exists() or not metadata_path.is_file():
                raise InvestigationEvidenceNotFound("Evidence does not exist.")

            try:
                record = self._load_evidence_from_path(metadata_path, normalized_session_id)
            except InvestigationEvidenceStoreError as exc:
                raise InvestigationEvidenceNotFound("Evidence does not exist.") from exc
            expected_ref, payload_path = self._safe_expected_payload_path(
                normalized_session_id,
                record.evidence_id,
                record.filename,
                record.evidence_type,
            )
            if record.storage_ref != expected_ref:
                self._quarantine_file(metadata_path, prefix="evidence_record_unsafe_delete")
                raise InvestigationEvidenceNotFound("Evidence does not exist.")

            if not payload_path.exists() or not payload_path.is_file():
                self._quarantine_file(metadata_path, prefix="evidence_record_missing_payload")
                raise InvestigationEvidenceNotFound("Evidence does not exist.")

            backup_path = self._session_corrupt_dir() / f"evidence_delete_{record.evidence_id}_{uuid4().hex}.bak"
            backup_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                os.replace(str(payload_path), str(backup_path))
            except OSError as exc:
                raise InvestigationEvidenceStoreError("Failed to delete evidence payload.") from exc

            try:
                metadata_path.unlink(missing_ok=True)
            except OSError as exc:
                try:
                    os.replace(str(backup_path), str(payload_path))
                except OSError:
                    pass
                raise InvestigationEvidenceStoreError("Failed to delete evidence metadata.") from exc

            try:
                backup_path.unlink(missing_ok=True)
            except OSError:
                pass

            return record

        return self.session_store.run_with_session_lock(normalized_session_id, _delete)
