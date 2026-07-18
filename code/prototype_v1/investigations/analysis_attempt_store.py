from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError

from .models import (
    INVESTIGATION_ANALYSIS_ATTEMPT_SCHEMA_VERSION,
    InvestigationAnalysisAttempt,
    InvestigationAnalysisAttemptStatus,
    InvestigationSession,
)
from .session_store import InvestigationSessionStore


class InvestigationAnalysisAttemptStoreError(RuntimeError):
    pass


class InvestigationAnalysisAttemptNotFound(InvestigationAnalysisAttemptStoreError):
    pass


class InvestigationAnalysisAttemptConflict(InvestigationAnalysisAttemptStoreError):
    pass


class InvestigationAnalysisAttemptOwnershipError(InvestigationAnalysisAttemptStoreError):
    pass


@dataclass(frozen=True)
class InvestigationAttemptOwnershipResult:
    session: InvestigationSession
    attempt: InvestigationAnalysisAttempt
    created_attempt: bool
    updated_session: bool
    reconciliation_action: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_write_json(path: Path, payload: str, *, temp_dir: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(temp_dir),
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
        raise InvestigationAnalysisAttemptStoreError("Failed to persist analysis attempt.") from exc
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


class InvestigationAnalysisAttemptStore:
    def __init__(self, session_store: InvestigationSessionStore):
        self.session_store = session_store

    @staticmethod
    def _validate_attempt_id(analysis_attempt_id: str) -> str:
        text = str(analysis_attempt_id or "").strip()
        if not text:
            raise InvestigationAnalysisAttemptStoreError("analysis_attempt_id is required.")
        try:
            return str(UUID(text))
        except ValueError as exc:
            raise InvestigationAnalysisAttemptStoreError("analysis_attempt_id must be a valid UUID.") from exc

    def _finalization_dir(self, session_id: str) -> Path:
        return self.session_store.session_workspace_dir(session_id) / "finalization"

    def _attempts_dir(self, session_id: str) -> Path:
        return self._finalization_dir(session_id) / "analysis_attempts"

    def _frozen_manifest_path(self, session_id: str) -> Path:
        return self._finalization_dir(session_id) / "frozen_manifest.json"

    def _attempt_path(self, session_id: str, analysis_attempt_id: str) -> Path:
        normalized_session_id = self.session_store.validate_session_id(session_id)
        normalized_attempt_id = self._validate_attempt_id(analysis_attempt_id)
        return self._attempts_dir(normalized_session_id) / f"{normalized_attempt_id}.json"

    def _find_foreign_attempt_session(self, *, analysis_attempt_id: str, excluded_session_id: str) -> str | None:
        normalized_attempt_id = self._validate_attempt_id(analysis_attempt_id)
        normalized_excluded = self.session_store.validate_session_id(excluded_session_id)

        pattern = f"*/finalization/analysis_attempts/{normalized_attempt_id}.json"
        for candidate in self.session_store.root.glob(pattern):
            session_dir = candidate.parents[2]
            candidate_session_id = session_dir.name
            try:
                normalized_candidate = self.session_store.validate_session_id(candidate_session_id)
            except Exception:
                continue
            if normalized_candidate != normalized_excluded and candidate.is_file():
                return normalized_candidate
        return None

    def _serialize_attempt(self, attempt: InvestigationAnalysisAttempt) -> str:
        return json.dumps(attempt.model_dump(mode="json"), ensure_ascii=False, indent=2)

    def _load_attempt_from_path(self, path: Path) -> InvestigationAnalysisAttempt:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise InvestigationAnalysisAttemptStoreError("Failed to read analysis attempt.") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InvestigationAnalysisAttemptStoreError("Analysis attempt is malformed JSON.") from exc

        try:
            return InvestigationAnalysisAttempt.model_validate(parsed)
        except ValidationError as exc:
            raise InvestigationAnalysisAttemptStoreError("Analysis attempt has invalid schema.") from exc

    def build_prepared_attempt(
        self,
        *,
        session_id: str,
        frozen_manifest_hash: str,
        context_snapshot_hash: str,
        request_fingerprint: str,
        analysis_attempt_id: str | None = None,
        attempt_number: int = 1,
        created_at_utc: datetime | None = None,
    ) -> InvestigationAnalysisAttempt:
        normalized_session_id = self.session_store.validate_session_id(session_id)
        attempt_id = self._validate_attempt_id(analysis_attempt_id or str(uuid4()))

        return InvestigationAnalysisAttempt(
            schema_version=INVESTIGATION_ANALYSIS_ATTEMPT_SCHEMA_VERSION,
            analysis_attempt_id=attempt_id,
            session_id=normalized_session_id,
            attempt_number=attempt_number,
            status=InvestigationAnalysisAttemptStatus.PREPARED,
            frozen_manifest_hash=frozen_manifest_hash,
            context_snapshot_hash=context_snapshot_hash,
            request_fingerprint=request_fingerprint,
            created_at_utc=created_at_utc or _utc_now(),
            started_at_utc=None,
            completed_at_utc=None,
            failed_at_utc=None,
            failure_metadata=None,
            safe_error_category=None,
            safe_error_message=None,
            frozen_manifest_id=None,
            structured_analysis=None,
            rendered_prompt=None,
            prompt_renderer_version=None,
            latency_metadata=None,
            canonical_result_id=None,
            provider_request_id=None,
            recovery_state=None,
            retryable=True,
        )

    def save_attempt(self, attempt: InvestigationAnalysisAttempt) -> bool:
        normalized_session_id = self.session_store.validate_session_id(attempt.session_id)
        normalized_attempt_id = self._validate_attempt_id(attempt.analysis_attempt_id)

        foreign_session_id = self._find_foreign_attempt_session(
            analysis_attempt_id=normalized_attempt_id,
            excluded_session_id=normalized_session_id,
        )
        if foreign_session_id is not None:
            raise InvestigationAnalysisAttemptConflict(
                "analysis_attempt_id already belongs to a different session."
            )

        path = self._attempt_path(normalized_session_id, normalized_attempt_id)
        payload = self._serialize_attempt(attempt)

        if path.exists() and path.is_file():
            existing = self._load_attempt_from_path(path)
            if existing.session_id != normalized_session_id:
                raise InvestigationAnalysisAttemptConflict("Attempt file session_id does not match the target session.")
            existing_payload = self._serialize_attempt(existing)
            if existing_payload == payload:
                return False
            raise InvestigationAnalysisAttemptConflict(
                "A different analysis attempt already exists for analysis_attempt_id."
            )

        _atomic_write_json(path, payload, temp_dir=self.session_store.temp_dir)
        return True

    def load_attempt(self, *, session_id: str, analysis_attempt_id: str) -> InvestigationAnalysisAttempt:
        normalized_session_id = self.session_store.validate_session_id(session_id)
        normalized_attempt_id = self._validate_attempt_id(analysis_attempt_id)

        path = self._attempt_path(normalized_session_id, normalized_attempt_id)
        if not path.exists() or not path.is_file():
            raise InvestigationAnalysisAttemptNotFound("Analysis attempt does not exist.")

        attempt = self._load_attempt_from_path(path)
        if attempt.session_id != normalized_session_id:
            raise InvestigationAnalysisAttemptConflict("Attempt session_id does not match requested session.")
        return attempt

    def try_load_attempt(self, *, session_id: str, analysis_attempt_id: str) -> InvestigationAnalysisAttempt | None:
        try:
            return self.load_attempt(session_id=session_id, analysis_attempt_id=analysis_attempt_id)
        except InvestigationAnalysisAttemptNotFound:
            return None

    def list_attempts(self, *, session_id: str) -> list[InvestigationAnalysisAttempt]:
        normalized_session_id = self.session_store.validate_session_id(session_id)
        attempts_dir = self._attempts_dir(normalized_session_id)
        if not attempts_dir.exists() or not attempts_dir.is_dir():
            return []

        attempts: list[InvestigationAnalysisAttempt] = []
        for path in sorted(attempts_dir.glob("*.json")):
            attempt = self._load_attempt_from_path(path)
            if attempt.session_id != normalized_session_id:
                raise InvestigationAnalysisAttemptConflict(
                    "Attempt file is stored under a different session directory."
                )
            attempts.append(attempt)

        attempts.sort(key=lambda item: (item.attempt_number, item.created_at_utc, item.analysis_attempt_id))
        return attempts

    def _next_attempt_number_unlocked(self, *, session_id: str) -> int:
        attempts = self.list_attempts(session_id=session_id)
        if not attempts:
            return 1
        return max(item.attempt_number for item in attempts) + 1

    def _prepare_durable_attempt_outside_lock(
        self,
        *,
        session_id: str,
        proposed_attempt: InvestigationAnalysisAttempt,
    ) -> tuple[InvestigationAnalysisAttempt, bool]:
        normalized_session_id = self.session_store.validate_session_id(session_id)

        if proposed_attempt.session_id != normalized_session_id:
            raise InvestigationAnalysisAttemptConflict("session_id and proposed attempt session_id must match.")
        if proposed_attempt.status != InvestigationAnalysisAttemptStatus.PREPARED:
            raise InvestigationAnalysisAttemptOwnershipError("Only prepared attempts can acquire ownership.")

        foreign_session_id = self._find_foreign_attempt_session(
            analysis_attempt_id=proposed_attempt.analysis_attempt_id,
            excluded_session_id=normalized_session_id,
        )
        if foreign_session_id is not None:
            raise InvestigationAnalysisAttemptConflict("analysis_attempt_id belongs to another session.")

        existing_attempt = self.try_load_attempt(
            session_id=normalized_session_id,
            analysis_attempt_id=proposed_attempt.analysis_attempt_id,
        )
        if existing_attempt is not None:
            if self._serialize_attempt(existing_attempt) != self._serialize_attempt(proposed_attempt):
                raise InvestigationAnalysisAttemptConflict(
                    "analysis_attempt_id already exists with different data."
                )
            return existing_attempt, False

        next_attempt_number = self._next_attempt_number_unlocked(session_id=normalized_session_id)
        durable_attempt = proposed_attempt.model_copy(update={"attempt_number": next_attempt_number})
        created = self.save_attempt(durable_attempt)
        if not created:
            return durable_attempt, False
        return durable_attempt, True

    def establish_attempt_ownership(
        self,
        *,
        session_id: str,
        proposed_attempt: InvestigationAnalysisAttempt,
        expected_revision: int | None,
    ) -> InvestigationAttemptOwnershipResult:
        normalized_session_id = self.session_store.validate_session_id(session_id)
        durable_attempt, created_attempt = self._prepare_durable_attempt_outside_lock(
            session_id=normalized_session_id,
            proposed_attempt=proposed_attempt,
        )
        has_frozen_manifest = self._frozen_manifest_path(normalized_session_id).exists()

        outcome: dict[str, object] = {
            "attempt": durable_attempt,
            "created_attempt": created_attempt,
            "reconciliation_action": "none",
        }

        def _mutator(session: InvestigationSession) -> tuple[InvestigationSession, bool]:
            if expected_revision is not None and expected_revision != session.revision:
                raise InvestigationAnalysisAttemptOwnershipError(
                    "expected_revision does not match the current session revision."
                )

            selected_attempt = durable_attempt
            existing_active_id = session.active_analysis_attempt_id
            action = "none"

            if selected_attempt.session_id != normalized_session_id:
                raise InvestigationAnalysisAttemptConflict("Durable attempt session_id mismatch.")

            if selected_attempt.status != InvestigationAnalysisAttemptStatus.PREPARED:
                raise InvestigationAnalysisAttemptOwnershipError("Durable attempt must remain in prepared status.")

            if existing_active_id and existing_active_id != selected_attempt.analysis_attempt_id:
                raise InvestigationAnalysisAttemptConflict("A different active analysis attempt already exists.")

            requires_pointer_update = (
                session.active_analysis_attempt_id != selected_attempt.analysis_attempt_id
                or session.latest_analysis_attempt_id != selected_attempt.analysis_attempt_id
                or session.current_analysis_attempt_id != selected_attempt.analysis_attempt_id
            )

            if not requires_pointer_update:
                outcome["reconciliation_action"] = "attempt_rehydrated_without_session_mutation" if created_attempt else "reuse_existing_attempt"
                return session, False

            now = _utc_now()
            updated = session.model_copy(
                update={
                    "active_analysis_attempt_id": selected_attempt.analysis_attempt_id,
                    "latest_analysis_attempt_id": selected_attempt.analysis_attempt_id,
                    "current_analysis_attempt_id": selected_attempt.analysis_attempt_id,
                    "revision": session.revision + 1,
                    "updated_at_utc": now,
                }
            )

            if existing_active_id is None and created_attempt:
                action = "claim_new_attempt"
            elif existing_active_id is None and not created_attempt:
                action = "link_existing_attempt"
            elif existing_active_id == selected_attempt.analysis_attempt_id and created_attempt:
                action = "reconcile_missing_attempt_record"
            elif existing_active_id == selected_attempt.analysis_attempt_id:
                action = "reconcile_missing_latest_pointer"

            # If a frozen manifest exists but no attempt ownership was durable yet, link deterministically.
            if has_frozen_manifest and existing_active_id is None:
                action = "reconcile_from_frozen_manifest_state"

            outcome["reconciliation_action"] = action
            return updated, True

        updated_session = self.session_store.mutate_session(normalized_session_id, _mutator)
        selected_attempt = durable_attempt

        return InvestigationAttemptOwnershipResult(
            session=updated_session,
            attempt=selected_attempt,
            created_attempt=bool(outcome["created_attempt"]),
            updated_session=updated_session.active_analysis_attempt_id == selected_attempt.analysis_attempt_id
            and updated_session.latest_analysis_attempt_id == selected_attempt.analysis_attempt_id
            and updated_session.current_analysis_attempt_id == selected_attempt.analysis_attempt_id,
            reconciliation_action=str(outcome["reconciliation_action"]),
        )
