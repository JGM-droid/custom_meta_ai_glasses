from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError

from .models import (
    PROJECT_ACTIVITY_SCHEMA_VERSION,
    ProjectActivity,
    ProjectActivityCreateRequest,
)
from .project_store import ProjectNotFound, ProjectStore, ProjectStoreError


class ProjectActivityStoreError(RuntimeError):
    pass


class ProjectActivityNotFound(ProjectActivityStoreError):
    pass


class ProjectActivityInvalidId(ProjectActivityStoreError):
    pass


class ProjectActivityStore:
    def __init__(self, root: Path, project_store: ProjectStore):
        self.root = root
        self.project_store = project_store
        self.activities_root = self.root / "activities"
        self.corrupt_dir = self.root / "corrupt"
        self.temp_dir = self.root / "temp"

        self.activities_root.mkdir(parents=True, exist_ok=True)
        self.corrupt_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self._lock_guard = threading.Lock()
        self._project_locks: dict[str, threading.Lock] = {}

    def _get_project_lock(self, project_id: str) -> threading.Lock:
        with self._lock_guard:
            lock = self._project_locks.get(project_id)
            if lock is None:
                lock = threading.Lock()
                self._project_locks[project_id] = lock
            return lock

    @staticmethod
    def validate_activity_id(activity_id: str) -> str:
        text = str(activity_id or "").strip()
        if not text:
            raise ProjectActivityInvalidId("Activity ID is required.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ProjectActivityInvalidId("Activity ID must be a valid UUID.") from exc
        return str(parsed)

    def _ensure_project_exists(self, project_id: str) -> str:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        self.project_store.load_project(normalized_project_id)
        return normalized_project_id

    def _project_activity_dir(self, project_id: str) -> Path:
        normalized = self.project_store.validate_project_id(project_id)
        return self.activities_root / normalized

    def _activity_path(self, project_id: str, activity_id: str) -> Path:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        normalized_activity_id = self.validate_activity_id(activity_id)
        return self._project_activity_dir(normalized_project_id) / f"{normalized_activity_id}.json"

    def _quarantine_file(self, path: Path, *, prefix: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.corrupt_dir / f"{prefix}_{stamp}_{uuid4().hex}.json"
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

    def _atomic_write_json(self, path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self.temp_dir),
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
            raise ProjectActivityStoreError("Failed to persist activity data.") from exc
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _load_json_object(self, path: Path) -> dict[str, object]:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProjectActivityStoreError("Activity data could not be read.") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._quarantine_file(path, prefix="activity_corrupt")
            raise ProjectActivityStoreError("Activity data is malformed.") from exc

        if not isinstance(parsed, dict):
            self._quarantine_file(path, prefix="activity_corrupt")
            raise ProjectActivityStoreError("Activity data has invalid shape.")

        return parsed

    def _load_activity_from_path(self, project_id: str, path: Path) -> ProjectActivity:
        parsed = self._load_json_object(path)
        try:
            activity = ProjectActivity.model_validate(parsed)
        except ValidationError as exc:
            self._quarantine_file(path, prefix="activity_corrupt")
            raise ProjectActivityStoreError("Activity data has invalid schema.") from exc

        if activity.schema_version != PROJECT_ACTIVITY_SCHEMA_VERSION:
            self._quarantine_file(path, prefix="activity_corrupt")
            raise ProjectActivityStoreError("Activity data has unsupported schema version.")

        if activity.project_id != project_id:
            self._quarantine_file(path, prefix="activity_corrupt")
            raise ProjectActivityStoreError("Activity ownership mismatch detected.")

        expected_name = f"{activity.activity_id}.json"
        if path.name != expected_name:
            self._quarantine_file(path, prefix="activity_corrupt")
            raise ProjectActivityStoreError("Activity identity mismatch detected.")

        return activity

    def _load_all_activities_no_lock(self, project_id: str) -> list[ProjectActivity]:
        activity_dir = self._project_activity_dir(project_id)
        if not activity_dir.exists() or not activity_dir.is_dir():
            return []

        activities: list[ProjectActivity] = []
        for path in sorted(activity_dir.glob("*.json")):
            activities.append(self._load_activity_from_path(project_id, path))
        return activities

    @staticmethod
    def _investigation_reference_from_metadata(
        metadata: dict[str, str | int | float | bool | None] | None,
    ) -> tuple[str, str] | None:
        if not metadata:
            return None

        session_value = metadata.get("investigation_session_id")
        result_value = metadata.get("investigation_result_id")
        if session_value is None or result_value is None:
            return None

        session_text = str(session_value).strip()
        result_text = str(result_value).strip()
        if not session_text or not result_text:
            return None

        try:
            normalized_session_id = str(UUID(session_text))
            normalized_result_id = str(UUID(result_text))
        except ValueError:
            return None

        return normalized_session_id, normalized_result_id

    def create_activity(self, project_id: str, request: ProjectActivityCreateRequest) -> ProjectActivity:
        normalized_project_id = self._ensure_project_exists(project_id)

        lock = self._get_project_lock(normalized_project_id)
        with lock:
            reference = self._investigation_reference_from_metadata(request.metadata)
            if reference is not None:
                for existing in self._load_all_activities_no_lock(normalized_project_id):
                    existing_reference = self._investigation_reference_from_metadata(existing.metadata)
                    if existing_reference == reference:
                        return existing

            now = datetime.now(timezone.utc)
            occurred_at = request.occurred_at_utc or now
            if occurred_at.tzinfo is None:
                raise ProjectActivityStoreError("occurred_at_utc must be timezone-aware UTC.")
            occurred_at = occurred_at.astimezone(timezone.utc)

            activity = ProjectActivity(
                schema_version=PROJECT_ACTIVITY_SCHEMA_VERSION,
                activity_id=str(uuid4()),
                project_id=normalized_project_id,
                activity_type=request.activity_type,
                source_type=request.source_type,
                confirmation_status=request.confirmation_status,
                summary=request.summary,
                details=request.details,
                occurred_at_utc=occurred_at,
                created_at_utc=now,
                metadata=request.metadata,
            )

            path = self._activity_path(normalized_project_id, activity.activity_id)
            payload = json.dumps(activity.model_dump(mode="json"), ensure_ascii=False, indent=2)
            self._atomic_write_json(path, payload)
            return activity

    def create_activity_with_id(
        self,
        project_id: str,
        activity_id: str,
        request: ProjectActivityCreateRequest,
    ) -> tuple[ProjectActivity, bool]:
        """Create an application-identified Activity, converging on an existing record.

        This is intentionally a single-process/file-store primitive. Callers own the
        semantic identity and must validate an existing record before treating it as
        equivalent.
        """
        normalized_project_id = self._ensure_project_exists(project_id)
        normalized_activity_id = self.validate_activity_id(activity_id)
        lock = self._get_project_lock(normalized_project_id)
        with lock:
            path = self._activity_path(normalized_project_id, normalized_activity_id)
            if path.exists() and path.is_file():
                return self._load_activity_from_path(normalized_project_id, path), False

            now = datetime.now(timezone.utc)
            occurred_at = request.occurred_at_utc or now
            if occurred_at.tzinfo is None:
                raise ProjectActivityStoreError("occurred_at_utc must be timezone-aware UTC.")
            activity = ProjectActivity(
                schema_version=PROJECT_ACTIVITY_SCHEMA_VERSION,
                activity_id=normalized_activity_id,
                project_id=normalized_project_id,
                activity_type=request.activity_type,
                source_type=request.source_type,
                confirmation_status=request.confirmation_status,
                summary=request.summary,
                details=request.details,
                occurred_at_utc=occurred_at.astimezone(timezone.utc),
                created_at_utc=now,
                metadata=request.metadata,
            )
            payload = json.dumps(activity.model_dump(mode="json"), ensure_ascii=False, indent=2)
            self._atomic_write_json(path, payload)
            return activity, True

    def load_activity(self, project_id: str, activity_id: str) -> ProjectActivity:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        normalized_activity_id = self.validate_activity_id(activity_id)

        self.project_store.load_project(normalized_project_id)

        lock = self._get_project_lock(normalized_project_id)
        with lock:
            path = self._activity_path(normalized_project_id, normalized_activity_id)
            if not path.exists() or not path.is_file():
                raise ProjectActivityNotFound("Activity does not exist.")
            return self._load_activity_from_path(normalized_project_id, path)

    def list_activities(self, project_id: str) -> list[ProjectActivity]:
        normalized_project_id = self.project_store.validate_project_id(project_id)

        self.project_store.load_project(normalized_project_id)

        lock = self._get_project_lock(normalized_project_id)
        with lock:
            activities = self._load_all_activities_no_lock(normalized_project_id)

            activities.sort(key=lambda item: (item.occurred_at_utc, item.created_at_utc, item.activity_id))
            return activities
