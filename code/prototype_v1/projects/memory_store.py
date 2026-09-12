"""Structured Project Memory store (Stage 2 - Integrated Persistent Memory
Shadow Slice, ADR-063/064).

SHADOW ONLY: this store is populated alongside normal ProjectConversation
turns but is not yet consumed as the authoritative context source for
production conversation (that is Stage 4). See
docs/PROJECT_MEMORY_ARCHITECTURE.md's "Stage 1 Result" and "Editable Project
Workspace Requirement" sections for the design this store implements.

Follows the exact persistence pattern already established by
`ProjectActivityStore`: one file per record, atomic tempfile+os.replace
writes, corruption quarantine, per-project locking. Deliberately not a new
storage technology.
"""
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
    DEFAULT_MEMORY_SCOPE,
    PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
    ProjectMemoryCandidate,
    ProjectMemoryModality,
    ProjectMemoryRecord,
    ProjectMemoryStatus,
)
from .project_store import ProjectStore


class ProjectMemoryStoreError(RuntimeError):
    pass


class ProjectMemoryStore:
    def __init__(self, root: Path, project_store: ProjectStore):
        self.root = root
        self.project_store = project_store
        self.memory_root = self.root / "memory"
        self.corrupt_dir = self.root / "corrupt"
        self.temp_dir = self.root / "temp"

        self.memory_root.mkdir(parents=True, exist_ok=True)
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

    def _project_memory_dir(self, project_id: str) -> Path:
        normalized = self.project_store.validate_project_id(project_id)
        return self.memory_root / normalized

    def _record_path(self, project_id: str, memory_id: str) -> Path:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        return self._project_memory_dir(normalized_project_id) / f"{memory_id}.json"

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
                mode="w", encoding="utf-8", dir=str(self.temp_dir),
                prefix=f"{path.name}.", suffix=".tmp", delete=False,
            ) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            os.replace(str(temp_path), str(path))
        except OSError as exc:
            raise ProjectMemoryStoreError("Failed to persist memory record.") from exc
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _load_record_from_path(self, project_id: str, path: Path) -> ProjectMemoryRecord:
        try:
            raw = path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            self._quarantine_file(path, prefix="memory_corrupt")
            raise ProjectMemoryStoreError("Memory record data is malformed.") from exc

        try:
            record = ProjectMemoryRecord.model_validate(parsed)
        except ValidationError as exc:
            self._quarantine_file(path, prefix="memory_corrupt")
            raise ProjectMemoryStoreError("Memory record has invalid schema.") from exc

        if record.project_id != project_id:
            self._quarantine_file(path, prefix="memory_corrupt")
            raise ProjectMemoryStoreError("Memory record ownership mismatch detected.")
        if path.name != f"{record.memory_id}.json":
            self._quarantine_file(path, prefix="memory_corrupt")
            raise ProjectMemoryStoreError("Memory record identity mismatch detected.")
        return record

    def _load_all_no_lock(self, project_id: str) -> list[ProjectMemoryRecord]:
        memory_dir = self._project_memory_dir(project_id)
        if not memory_dir.exists() or not memory_dir.is_dir():
            return []
        records: list[ProjectMemoryRecord] = []
        for path in sorted(memory_dir.glob("*.json")):
            records.append(self._load_record_from_path(project_id, path))
        return records

    def _current_committed(
        self, records: list[ProjectMemoryRecord], scope: str, subject: str, slot: str,
    ) -> ProjectMemoryRecord | None:
        matches = [
            r for r in records
            if r.scope == scope and r.subject == subject and r.slot == slot
            and r.status == ProjectMemoryStatus.CURRENT and r.modality == ProjectMemoryModality.COMMITTED
        ]
        return matches[-1] if matches else None

    def write_candidate(
        self,
        project_id: str,
        candidate: ProjectMemoryCandidate,
        *,
        source_type,
        source_turn_id: str | None,
        occurred_at_utc: datetime | None = None,
    ) -> ProjectMemoryRecord:
        """Deterministic write path. Supersession is modality-aware: only a
        COMMITTED fact/constraint/preference/decision can supersede a prior
        CURRENT+COMMITTED record under the same (scope, subject, slot) -
        never a tentative/hypothetical/third_party/historical one, and never
        a progress record (progress is append-only; see current_progress_projection
        in project_current_state.py for its derived-latest-event view)."""
        normalized_project_id = self.project_store.validate_project_id(project_id)
        self.project_store.load_project(normalized_project_id)

        lock = self._get_project_lock(normalized_project_id)
        with lock:
            existing = self._load_all_no_lock(normalized_project_id)
            now = datetime.now(timezone.utc)
            occurred_at = (occurred_at_utc or now)
            if occurred_at.tzinfo is None:
                raise ProjectMemoryStoreError("occurred_at_utc must be timezone-aware UTC.")
            occurred_at = occurred_at.astimezone(timezone.utc)

            memory_id = str(uuid4())
            can_supersede = (
                candidate.modality == ProjectMemoryModality.COMMITTED
                and candidate.category.value != "progress"
            )
            prior = None
            if can_supersede:
                prior = self._current_committed(existing, candidate.scope, candidate.subject, candidate.slot)

            record = ProjectMemoryRecord(
                schema_version=PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
                memory_id=memory_id,
                project_id=normalized_project_id,
                category=candidate.category,
                scope=candidate.scope or DEFAULT_MEMORY_SCOPE,
                subject=candidate.subject,
                slot=candidate.slot,
                value=candidate.value,
                modality=candidate.modality,
                status=ProjectMemoryStatus.CURRENT,
                progress_state=candidate.progress_state,
                is_blocker=candidate.is_blocker,
                superseded_by=None,
                source_type=source_type,
                source_turn_id=source_turn_id,
                occurred_at_utc=occurred_at,
                created_at_utc=now,
            )
            path = self._record_path(normalized_project_id, memory_id)
            payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2)
            self._atomic_write_json(path, payload)

            if prior is not None:
                updated_prior = prior.model_copy(update={
                    "status": ProjectMemoryStatus.SUPERSEDED,
                    "superseded_by": memory_id,
                })
                prior_path = self._record_path(normalized_project_id, prior.memory_id)
                prior_payload = json.dumps(updated_prior.model_dump(mode="json"), ensure_ascii=False, indent=2)
                self._atomic_write_json(prior_path, prior_payload)

            return record

    def list_records(self, project_id: str) -> list[ProjectMemoryRecord]:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        self.project_store.load_project(normalized_project_id)
        lock = self._get_project_lock(normalized_project_id)
        with lock:
            records = self._load_all_no_lock(normalized_project_id)
            records.sort(key=lambda r: (r.occurred_at_utc, r.created_at_utc, r.memory_id))
            return records
