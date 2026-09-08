from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from investigations import (
    InvestigationEvidenceStore,
    InvestigationEvidenceType,
    InvestigationEvidenceValidationStatus,
    InvestigationSessionStore,
)

from .project_explore import ProjectExploreService
from .project_store import ProjectStore


VISUAL_ARTIFACT_SCHEMA_VERSION = "1.0"
VISUAL_ARTIFACT_TTL_DAYS = 7
MAX_VISUAL_ARTIFACTS_PER_RESULT = 3


class VisualArtifactError(RuntimeError):
    pass


class VisualArtifactNotFound(VisualArtifactError):
    pass


class VisualArtifactConflict(VisualArtifactError):
    pass


class VisualArtifactProviderError(VisualArtifactError):
    pass


class VisualArtifactStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


class VisualArtifactRetention(str, Enum):
    EPHEMERAL = "EPHEMERAL"
    RETAINED = "RETAINED"


class VisualArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str = VISUAL_ARTIFACT_SCHEMA_VERSION
    artifact_id: str
    project_id: str
    project_ai_result_id: str
    option_id: str
    artifact_type: str = "OPTION_VISUALIZATION"
    status: VisualArtifactStatus
    source_evidence_ids: list[str] = Field(min_length=1, max_length=1)
    storage_ref: str | None = None
    mime_type: str | None = None
    provider: str | None = None
    provider_model: str | None = None
    provider_request_id: str | None = None
    prompt_fingerprint: str
    idempotency_key: str
    retention: VisualArtifactRetention = VisualArtifactRetention.EPHEMERAL
    created_at_utc: datetime
    completed_at_utc: datetime | None = None
    expires_at_utc: datetime | None = None
    failure_category: str | None = None


class VisualArtifactCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: str = Field(min_length=1, max_length=200)


@dataclass(frozen=True)
class VisualArtifactProviderResult:
    image_bytes: bytes
    mime_type: str
    provider: str
    model: str
    request_id: str | None = None


class VisualArtifactProvider(Protocol):
    def edit(self, *, source_bytes: bytes, source_filename: str, source_mime_type: str,
             prompt: str) -> VisualArtifactProviderResult: ...


class OpenAIVisualArtifactProvider:
    def __init__(self, *, api_key: str, model: str = "gpt-image-2", timeout_seconds: float = 60.0,
                 client_factory=None):
        if not str(api_key or "").strip():
            raise VisualArtifactProviderError("OPENAI_API_KEY is required for visualization.")
        if client_factory is None:
            try:
                from openai import OpenAI
            except Exception as exc:  # pragma: no cover
                raise VisualArtifactProviderError("OpenAI SDK is unavailable.") from exc
            client_factory = OpenAI
        self._api_key = api_key.strip()
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory

    def edit(self, *, source_bytes: bytes, source_filename: str, source_mime_type: str,
             prompt: str) -> VisualArtifactProviderResult:
        source = io.BytesIO(source_bytes)
        source.name = source_filename
        try:
            response = self._client_factory(api_key=self._api_key).images.edit(
                model=self._model,
                image=(source_filename, source, source_mime_type),
                prompt=prompt,
                n=1,
                quality="medium",
                size="1536x1024",
                output_format="webp",
                timeout=self._timeout_seconds,
            )
            item = response.data[0]
            encoded = getattr(item, "b64_json", None)
            if not encoded:
                raise ValueError("missing image data")
            return VisualArtifactProviderResult(
                image_bytes=base64.b64decode(encoded, validate=True),
                mime_type="image/webp",
                provider="openai",
                model=self._model,
                request_id=getattr(response, "id", None),
            )
        except Exception as exc:
            raise VisualArtifactProviderError("Image edit provider request failed.") from exc


class VisualArtifactStore:
    def __init__(self, project_store: ProjectStore):
        self.project_store = project_store
        self.root = project_store.root / "visual_artifacts"
        self.temp_dir = self.root / "temp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def _artifact_dir(self, project_id: str, artifact_id: str) -> Path:
        project = self.project_store.validate_project_id(project_id)
        try:
            artifact = str(UUID(str(artifact_id)))
        except ValueError as exc:
            raise VisualArtifactNotFound("Visual artifact does not exist.") from exc
        path = (self.root / project / artifact).resolve(strict=False)
        expected = (self.root / project).resolve(strict=False)
        if path.parent != expected:
            raise VisualArtifactNotFound("Visual artifact does not exist.")
        return path

    def _atomic_bytes(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.temp_dir, delete=False) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temp = Path(handle.name)
            os.replace(temp, path)
        except OSError as exc:
            raise VisualArtifactError("Visual artifact storage is unavailable.") from exc
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)

    def save(self, artifact: VisualArtifact, image_bytes: bytes | None = None) -> VisualArtifact:
        directory = self._artifact_dir(artifact.project_id, artifact.artifact_id)
        with self.project_store._get_project_lock(artifact.project_id):
            if image_bytes is not None:
                self._atomic_bytes(directory / "visualization.webp", image_bytes)
            self._atomic_bytes(
                directory / "artifact.json",
                artifact.model_dump_json(indent=2).encode("utf-8"),
            )
        return artifact

    def load(self, project_id: str, artifact_id: str) -> VisualArtifact:
        self.project_store.load_project(project_id)
        path = self._artifact_dir(project_id, artifact_id) / "artifact.json"
        try:
            artifact = VisualArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise VisualArtifactNotFound("Visual artifact does not exist.") from exc
        if artifact.project_id != self.project_store.validate_project_id(project_id):
            raise VisualArtifactNotFound("Visual artifact does not exist.")
        if (artifact.retention == VisualArtifactRetention.EPHEMERAL and
                artifact.expires_at_utc is not None and
                artifact.expires_at_utc <= datetime.now(timezone.utc)):
            raise VisualArtifactNotFound("Visual artifact has expired.")
        return artifact

    def content_path(self, project_id: str, artifact_id: str) -> tuple[VisualArtifact, Path]:
        artifact = self.load(project_id, artifact_id)
        if artifact.status != VisualArtifactStatus.READY or artifact.storage_ref != "visualization.webp":
            raise VisualArtifactNotFound("Visual artifact content is not ready.")
        path = self._artifact_dir(project_id, artifact_id) / artifact.storage_ref
        if not path.is_file():
            raise VisualArtifactNotFound("Visual artifact content is unavailable.")
        return artifact, path

    def list_for_result(self, project_id: str, result_id: str) -> list[VisualArtifact]:
        project_dir = self.root / self.project_store.validate_project_id(project_id)
        items: list[VisualArtifact] = []
        if project_dir.is_dir():
            for path in project_dir.glob("*/artifact.json"):
                try:
                    item = VisualArtifact.model_validate_json(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if item.project_ai_result_id == result_id:
                    items.append(item)
        return sorted(items, key=lambda item: (item.created_at_utc, item.artifact_id))

    def purge_expired_for_result(self, project_id: str, result_id: str,
                                 *, now: datetime | None = None) -> list[str]:
        cutoff = now or datetime.now(timezone.utc)
        removed: list[str] = []
        for item in self.list_for_result(project_id, result_id):
            if (item.retention != VisualArtifactRetention.EPHEMERAL or
                    item.expires_at_utc is None or item.expires_at_utc > cutoff):
                continue
            directory = self._artifact_dir(project_id, item.artifact_id)
            with self.project_store._get_project_lock(project_id):
                for filename in ("visualization.webp", "artifact.json"):
                    (directory / filename).unlink(missing_ok=True)
                try:
                    directory.rmdir()
                except OSError:
                    continue
            removed.append(item.artifact_id)
        return removed


class VisualArtifactService:
    def __init__(self, *, project_store: ProjectStore, explore_service: ProjectExploreService,
                 session_store: InvestigationSessionStore, evidence_store: InvestigationEvidenceStore,
                 artifact_store: VisualArtifactStore, provider: VisualArtifactProvider | None):
        self.project_store = project_store
        self.explore_service = explore_service
        self.session_store = session_store
        self.evidence_store = evidence_store
        self.artifact_store = artifact_store
        self.provider = provider

    def _resolve(self, project_id: str, result_id: str, option_id: str):
        project = self.project_store.validate_project_id(project_id)
        projection = self.explore_service.read_projection(project)
        group = next((item for item in projection.option_sets if item.interaction_id == result_id), None)
        if group is None or group.result_activity is None:
            raise VisualArtifactNotFound("Explore result does not exist for this Project.")
        option = next((item for item in group.options if item.idea.activity_id == option_id), None)
        if option is None:
            raise VisualArtifactNotFound("Explore option does not exist for this result.")
        evidence_ids = [item for item in str((group.result_activity.metadata or {}).get("evidence_refs") or "").split(",") if item]
        if not evidence_ids:
            raise VisualArtifactConflict("This Explore result has no source image evidence.")
        evidence_id = evidence_ids[0]
        for session in self.session_store.list_sessions_for_project(project):
            try:
                evidence, content_path = self.evidence_store.load_evidence_content(
                    session_id=session.session_id, evidence_id=evidence_id)
            except Exception:
                continue
            if (evidence.evidence_type == InvestigationEvidenceType.IMAGE and evidence.validation_status in {
                InvestigationEvidenceValidationStatus.ACCEPTED,
                InvestigationEvidenceValidationStatus.DUPLICATE_ACCEPTED,
            }):
                return project, group, option, evidence, content_path
        raise VisualArtifactNotFound("Source evidence does not exist for this Project.")

    @staticmethod
    def _prompt(group, option) -> str:
        observations = "; ".join(group.observations[:3])
        return (
            "Edit the supplied photograph to visualize this proposed change while preserving the recognizable "
            "room structure, camera viewpoint, walls, floor, windows, and unrelated objects. Produce a realistic "
            "concept illustration, not a different room. Do not add labels or text. "
            f"Selected option: {option.idea.summary}. Concept: {option.concept or option.summary}. "
            f"Proposed changes: {option.proposed_changes or option.summary}. Grounded observations: {observations}"
        )[:4000]

    def prepare(self, project_id: str, result_id: str, option_id: str,
                request: VisualArtifactCreateRequest) -> VisualArtifact:
        project, group, option, evidence, _ = self._resolve(project_id, result_id, option_id)
        prompt = self._prompt(group, option)
        artifact_id = str(uuid5(UUID(result_id), f"visual:{option_id}"))
        now = datetime.now(timezone.utc)
        self.artifact_store.purge_expired_for_result(project, result_id, now=now)
        try:
            existing = self.artifact_store.load(project, artifact_id)
            if existing.idempotency_key != request.idempotency_key:
                raise VisualArtifactConflict("This option already has a visualization request.")
            return existing
        except VisualArtifactNotFound:
            pass
        if len(self.artifact_store.list_for_result(project, result_id)) >= MAX_VISUAL_ARTIFACTS_PER_RESULT:
            raise VisualArtifactConflict("This Explore result already has the maximum number of visualizations.")
        return self.artifact_store.save(VisualArtifact(
            artifact_id=artifact_id,
            project_id=project,
            project_ai_result_id=result_id,
            option_id=option_id,
            status=VisualArtifactStatus.PENDING,
            source_evidence_ids=[evidence.evidence_id],
            prompt_fingerprint=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            idempotency_key=request.idempotency_key,
            created_at_utc=now,
            retention=(VisualArtifactRetention.RETAINED if getattr(option.disposition, "value", None) == "select"
                       else VisualArtifactRetention.EPHEMERAL),
            expires_at_utc=(None if getattr(option.disposition, "value", None) == "select"
                            else now + timedelta(days=VISUAL_ARTIFACT_TTL_DAYS)),
        ))

    def generate(self, project_id: str, artifact_id: str) -> VisualArtifact:
        with self.project_store._get_project_lock(project_id):
            artifact = self.artifact_store.load(project_id, artifact_id)
            if artifact.status == VisualArtifactStatus.READY:
                return artifact
            if self.provider is None:
                raise VisualArtifactProviderError("Visualization provider is unavailable.")
            project, group, option, evidence, content_path = self._resolve(
                project_id, artifact.project_ai_result_id, artifact.option_id)
            prompt = self._prompt(group, option)
            if hashlib.sha256(prompt.encode("utf-8")).hexdigest() != artifact.prompt_fingerprint:
                raise VisualArtifactConflict("Visualization prompt context changed.")
            try:
                result = self.provider.edit(
                    source_bytes=content_path.read_bytes(),
                    source_filename=evidence.filename,
                    source_mime_type=evidence.mime_type,
                    prompt=prompt,
                )
                ready = artifact.model_copy(update={
                    "status": VisualArtifactStatus.READY,
                    "storage_ref": "visualization.webp",
                    "mime_type": result.mime_type,
                    "provider": result.provider,
                    "provider_model": result.model,
                    "provider_request_id": result.request_id,
                    "completed_at_utc": datetime.now(timezone.utc),
                    "failure_category": None,
                })
                return self.artifact_store.save(ready, result.image_bytes)
            except Exception as exc:
                failed = artifact.model_copy(update={
                    "status": VisualArtifactStatus.FAILED,
                    "completed_at_utc": datetime.now(timezone.utc),
                    "failure_category": "provider_failure",
                })
                self.artifact_store.save(failed)
                if isinstance(exc, VisualArtifactError):
                    raise
                raise VisualArtifactProviderError("Visualization generation failed.") from exc

    def read(self, project_id: str, result_id: str, option_id: str, artifact_id: str) -> VisualArtifact:
        artifact = self.artifact_store.load(project_id, artifact_id)
        if artifact.project_ai_result_id != result_id or artifact.option_id != option_id:
            raise VisualArtifactNotFound("Visual artifact does not exist for this result option.")
        self._resolve(project_id, result_id, option_id)
        return artifact

    def source_content_path(self, project_id: str, result_id: str, option_id: str, artifact_id: str):
        artifact = self.read(project_id, result_id, option_id, artifact_id)
        _, _, _, evidence, path = self._resolve(project_id, result_id, option_id)
        if artifact.source_evidence_ids != [evidence.evidence_id]:
            raise VisualArtifactConflict("Visual artifact source provenance is inconsistent.")
        return evidence, path

    def retry(self, project_id: str, artifact_id: str, idempotency_key: str) -> VisualArtifact:
        artifact = self.artifact_store.load(project_id, artifact_id)
        if artifact.idempotency_key != idempotency_key:
            raise VisualArtifactConflict("Visualization idempotency key does not match.")
        if artifact.status == VisualArtifactStatus.READY:
            return artifact
        return self.generate(project_id, artifact_id)

    def retain(self, project_id: str, artifact_id: str) -> VisualArtifact:
        artifact = self.artifact_store.load(project_id, artifact_id)
        if artifact.status != VisualArtifactStatus.READY:
            raise VisualArtifactConflict("Only a ready visualization can be retained.")
        retained = [item for item in self.artifact_store.list_for_result(project_id, artifact.project_ai_result_id)
                    if item.retention == VisualArtifactRetention.RETAINED and item.artifact_id != artifact_id]
        if len(retained) >= MAX_VISUAL_ARTIFACTS_PER_RESULT:
            raise VisualArtifactConflict("This result already has the retained visualization limit.")
        return self.artifact_store.save(artifact.model_copy(update={
            "retention": VisualArtifactRetention.RETAINED,
            "expires_at_utc": None,
        }))

    def retain_selected_option(self, project_id: str, option_id: str) -> None:
        project = self.project_store.validate_project_id(project_id)
        project_dir = self.artifact_store.root / project
        if not project_dir.is_dir():
            return
        for manifest in project_dir.glob("*/artifact.json"):
            try:
                item = VisualArtifact.model_validate_json(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if item.option_id == option_id and item.status == VisualArtifactStatus.READY:
                self.retain(project, item.artifact_id)
