from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

from pydantic import ValidationError

from .models import InvestigationSession, create_new_investigation_session


class InvestigationSessionStoreError(RuntimeError):
    pass


class InvestigationSessionNotFound(InvestigationSessionStoreError):
    pass


class InvestigationSessionInvalidId(InvestigationSessionStoreError):
    pass


class InvestigationSessionStore:
    def __init__(self, root: Path):
        self.root = root
        self.sessions_dir = self.root / "sessions"
        self.corrupt_dir = self.root / "corrupt"
        self.archive_dir = self.root / "archive"
        self.temp_dir = self.root / "temp"

        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.corrupt_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self._lock_guard = threading.Lock()
        self._session_locks: dict[str, threading.Lock] = {}

    def _get_session_lock(self, session_id: str) -> threading.Lock:
        with self._lock_guard:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._session_locks[session_id] = lock
            return lock

    @staticmethod
    def validate_session_id(session_id: str) -> str:
        text = str(session_id or "").strip()
        if not text:
            raise InvestigationSessionInvalidId("Session ID is required.")

        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise InvestigationSessionInvalidId("Session ID must be a valid UUID.") from exc

        return str(parsed)

    def _session_path(self, session_id: str) -> Path:
        normalized = self.validate_session_id(session_id)
        return self.sessions_dir / f"{normalized}.json"

    def _quarantine_malformed_file(self, path: Path) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_name = f"session_corrupt_{stamp}_{uuid4().hex}.json"
        target = self.corrupt_dir / safe_name
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

    def _load_session_no_lock(self, normalized_session_id: str) -> InvestigationSession:
        path = self.sessions_dir / f"{normalized_session_id}.json"
        if not path.exists() or not path.is_file():
            raise InvestigationSessionNotFound("Session does not exist.")

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise InvestigationSessionStoreError("Session data could not be read.") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._quarantine_malformed_file(path)
            raise InvestigationSessionStoreError("Session data is malformed.") from exc

        try:
            return InvestigationSession.model_validate(parsed)
        except ValidationError as exc:
            self._quarantine_malformed_file(path)
            raise InvestigationSessionStoreError("Session data has invalid schema.") from exc

    def load_session(self, session_id: str) -> InvestigationSession:
        normalized = self.validate_session_id(session_id)
        return self._load_session_no_lock(normalized)

    def _validate_existing_file_before_write(self, session_path: Path) -> None:
        if not session_path.exists() or not session_path.is_file():
            return

        try:
            raw = session_path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            InvestigationSession.model_validate(parsed)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            self._quarantine_malformed_file(session_path)
            raise InvestigationSessionStoreError("Existing session file is malformed and was quarantined.") from exc

    def _save_session_no_lock(self, session: InvestigationSession) -> None:
        normalized = self.validate_session_id(session.session_id)
        payload = session.model_dump(mode="json")
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)

        session_path = self.sessions_dir / f"{normalized}.json"
        self._validate_existing_file_before_write(session_path)

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self.temp_dir),
                prefix=f"{normalized}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)

            os.replace(str(temp_path), str(session_path))
        except OSError as exc:
            raise InvestigationSessionStoreError("Failed to persist session.") from exc
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def create_session(
        self,
        *,
        client_metadata: dict[str, str | int | float | bool | None] | None = None,
    ) -> InvestigationSession:
        session = create_new_investigation_session(client_metadata=client_metadata)
        self.save_session(session)
        return session

    def save_session(self, session: InvestigationSession) -> None:
        normalized = self.validate_session_id(session.session_id)
        lock = self._get_session_lock(normalized)
        with lock:
            self._save_session_no_lock(session)

    def mutate_session(
        self,
        session_id: str,
        mutator: Callable[[InvestigationSession], tuple[InvestigationSession, bool]],
    ) -> InvestigationSession:
        normalized = self.validate_session_id(session_id)
        lock = self._get_session_lock(normalized)
        with lock:
            current = self._load_session_no_lock(normalized)
            updated, changed = mutator(current)
            if changed:
                self._save_session_no_lock(updated)
                return updated
            return current
