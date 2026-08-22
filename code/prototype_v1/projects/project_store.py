from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar
from uuid import UUID, uuid4

from pydantic import ValidationError

from .models import (
    ACTIVE_PROJECT_POINTER_SCHEMA_VERSION,
    ActiveProjectPointer,
    Project,
    ProjectCheckpoint,
    ProjectStatus,
    create_new_project,
)


class ProjectStoreError(RuntimeError):
    pass


class ProjectNotFound(ProjectStoreError):
    pass


class ProjectInvalidId(ProjectStoreError):
    pass


class ProjectRevisionConflict(ProjectStoreError):
    pass


class ActiveProjectNotSet(ProjectStoreError):
    pass


T = TypeVar("T")


class ProjectStore:
    def __init__(self, root: Path):
        self.root = root
        self.projects_dir = self.root / "projects"
        self.active_project_path = self.root / "active_project.json"
        self.corrupt_dir = self.root / "corrupt"
        self.archive_dir = self.root / "archive"
        self.temp_dir = self.root / "temp"

        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.corrupt_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self._global_lock = threading.Lock()
        self._project_locks: dict[str, threading.Lock] = {}

    def _get_project_lock(self, project_id: str) -> threading.Lock:
        with self._global_lock:
            lock = self._project_locks.get(project_id)
            if lock is None:
                lock = threading.Lock()
                self._project_locks[project_id] = lock
            return lock

    @staticmethod
    def validate_project_id(project_id: str) -> str:
        text = str(project_id or "").strip()
        if not text:
            raise ProjectInvalidId("Project ID is required.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise ProjectInvalidId("Project ID must be a valid UUID.") from exc
        return str(parsed)

    def _project_path(self, project_id: str) -> Path:
        normalized = self.validate_project_id(project_id)
        return self.projects_dir / f"{normalized}.json"

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
            raise ProjectStoreError("Failed to persist project data.") from exc
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
            raise ProjectStoreError("Project data could not be read.") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._quarantine_file(path, prefix="project_corrupt")
            raise ProjectStoreError("Project data is malformed.") from exc

        if not isinstance(parsed, dict):
            self._quarantine_file(path, prefix="project_corrupt")
            raise ProjectStoreError("Project data has invalid shape.")

        return parsed

    def _load_project_no_lock(self, normalized_project_id: str) -> Project:
        path = self._project_path(normalized_project_id)
        if not path.exists() or not path.is_file():
            raise ProjectNotFound("Project does not exist.")

        parsed = self._load_json_object(path)
        try:
            project = Project.model_validate(parsed)
        except ValidationError as exc:
            self._quarantine_file(path, prefix="project_corrupt")
            raise ProjectStoreError("Project data has invalid schema.") from exc

        if project.project_id != normalized_project_id:
            self._quarantine_file(path, prefix="project_corrupt")
            raise ProjectStoreError("Project identity mismatch detected.")

        return project

    def load_project(self, project_id: str) -> Project:
        normalized = self.validate_project_id(project_id)
        return self._load_project_no_lock(normalized)

    def _validate_existing_project_file_before_write(self, project_path: Path, expected_project_id: str) -> None:
        if not project_path.exists() or not project_path.is_file():
            return

        parsed = self._load_json_object(project_path)
        try:
            project = Project.model_validate(parsed)
        except ValidationError as exc:
            self._quarantine_file(project_path, prefix="project_corrupt")
            raise ProjectStoreError("Existing project file is malformed and was quarantined.") from exc

        if project.project_id != expected_project_id:
            self._quarantine_file(project_path, prefix="project_corrupt")
            raise ProjectStoreError("Existing project file identity mismatch.")

    def _save_project_no_lock(self, project: Project) -> None:
        normalized = self.validate_project_id(project.project_id)
        path = self._project_path(normalized)
        self._validate_existing_project_file_before_write(path, normalized)
        payload = json.dumps(project.model_dump(mode="json"), ensure_ascii=False, indent=2)
        self._atomic_write_json(path, payload)

    def save_project(self, project: Project) -> None:
        normalized = self.validate_project_id(project.project_id)
        lock = self._get_project_lock(normalized)
        with lock:
            self._save_project_no_lock(project)

    def create_project(
        self,
        *,
        name: str,
        goal: str,
        status: ProjectStatus = ProjectStatus.ACTIVE,
        checkpoint: ProjectCheckpoint | None = None,
    ) -> Project:
        project = create_new_project(name=name, goal=goal, status=status, checkpoint=checkpoint)
        self.save_project(project)
        return project

    def list_projects(self) -> list[Project]:
        projects: list[Project] = []
        for path in sorted(self.projects_dir.glob("*.json")):
            project_id = path.stem
            try:
                normalized = self.validate_project_id(project_id)
                projects.append(self._load_project_no_lock(normalized))
            except ProjectInvalidId:
                self._quarantine_file(path, prefix="project_corrupt")
                raise ProjectStoreError("Project storage contains invalid project identifiers.")

        projects.sort(key=lambda item: (item.updated_at_utc, item.project_id), reverse=True)
        return projects

    def mutate_project(
        self,
        project_id: str,
        *,
        expected_revision: int | None,
        mutator: Callable[[Project], tuple[Project, bool]],
    ) -> Project:
        normalized = self.validate_project_id(project_id)
        lock = self._get_project_lock(normalized)
        with lock:
            current = self._load_project_no_lock(normalized)
            if expected_revision is not None and expected_revision != current.revision:
                raise ProjectRevisionConflict("expected_revision does not match the current project revision.")

            updated, changed = mutator(current)
            if updated.project_id != normalized:
                raise ProjectStoreError("Mutator changed project identity.")

            if not changed:
                return current

            self._save_project_no_lock(updated)
            return updated

    def set_active_project(self, project_id: str) -> ActiveProjectPointer:
        normalized = self.validate_project_id(project_id)
        # Ensure the project exists and is valid before persisting active pointer.
        self.load_project(normalized)

        pointer = ActiveProjectPointer(
            schema_version=ACTIVE_PROJECT_POINTER_SCHEMA_VERSION,
            active_project_id=normalized,
            updated_at_utc=datetime.now(timezone.utc),
        )
        payload = json.dumps(pointer.model_dump(mode="json"), ensure_ascii=False, indent=2)
        self._atomic_write_json(self.active_project_path, payload)
        return pointer

    def clear_active_project(self) -> None:
        # Clearing is deleting the pointer file, not writing an empty/null
        # pointer - ActiveProjectPointer.active_project_id is required and
        # non-empty by schema, and the "no active project" state is already
        # exactly what _load_active_pointer/get_active_project_id report
        # when this file does not exist (ActiveProjectNotSet). Idempotent:
        # clearing when nothing is active is not an error.
        self.active_project_path.unlink(missing_ok=True)

    def _load_active_pointer(self) -> ActiveProjectPointer:
        if not self.active_project_path.exists() or not self.active_project_path.is_file():
            raise ActiveProjectNotSet("No active project is currently selected.")

        parsed = self._load_json_object(self.active_project_path)
        try:
            return ActiveProjectPointer.model_validate(parsed)
        except ValidationError as exc:
            self._quarantine_file(self.active_project_path, prefix="active_project_corrupt")
            raise ProjectStoreError("Active project pointer is malformed.") from exc

    def get_active_project_id(self) -> str:
        pointer = self._load_active_pointer()
        return pointer.active_project_id

    def get_active_project(self) -> Project:
        active_project_id = self.get_active_project_id()
        return self.load_project(active_project_id)
