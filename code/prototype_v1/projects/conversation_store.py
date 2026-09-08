from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid5

from pydantic import ValidationError

from .project_conversation import ProjectConversation
from .project_store import ProjectStore


class ConversationStoreError(RuntimeError):
    pass


class ConversationNotFound(ConversationStoreError):
    pass


class ConversationIdempotencyConflict(ConversationStoreError):
    pass


class ProjectConversationStore:
    """Application-owned V1 store: exactly one deterministic primary conversation per Project."""

    def __init__(self, project_store: ProjectStore):
        self.project_store = project_store
        self.root = project_store.root / "conversations"
        self.temp_dir = self.root / "temp"
        self.root.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def conversation_id_for(project_id: str) -> str:
        return str(uuid5(UUID(project_id), "primary-project-conversation-v1"))

    def _path(self, project_id: str) -> Path:
        normalized = self.project_store.validate_project_id(project_id)
        path = (self.root / normalized / "primary.json").resolve(strict=False)
        expected_parent = (self.root / normalized).resolve(strict=False)
        if path.parent != expected_parent:
            raise ConversationStoreError("Conversation path is invalid.")
        return path

    def load(self, project_id: str) -> ProjectConversation:
        normalized = self.project_store.validate_project_id(project_id)
        self.project_store.load_project(normalized)
        path = self._path(normalized)
        try:
            conversation = ProjectConversation.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConversationNotFound("Project conversation does not exist.") from exc
        except (OSError, ValidationError, ValueError) as exc:
            raise ConversationStoreError("Project conversation is unavailable or malformed.") from exc
        expected_id = self.conversation_id_for(normalized)
        if conversation.project_id != normalized or conversation.conversation_id != expected_id:
            raise ConversationStoreError("Project conversation identity mismatch.")
        return conversation

    def create_or_load(self, project_id: str) -> ProjectConversation:
        normalized = self.project_store.validate_project_id(project_id)
        self.project_store.load_project(normalized)
        with self.project_store._get_project_lock(normalized):
            try:
                return self.load(normalized)
            except ConversationNotFound:
                now = datetime.now(timezone.utc)
                conversation = ProjectConversation(
                    conversation_id=self.conversation_id_for(normalized),
                    project_id=normalized,
                    created_at_utc=now,
                    updated_at_utc=now,
                )
                return self.save(conversation)

    def save(self, conversation: ProjectConversation) -> ProjectConversation:
        normalized = self.project_store.validate_project_id(conversation.project_id)
        self.project_store.load_project(normalized)
        if conversation.conversation_id != self.conversation_id_for(normalized):
            raise ConversationStoreError("Only the primary Project conversation may be persisted.")
        path = self._path(normalized)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.temp_dir,
                prefix="conversation.", suffix=".tmp", delete=False,
            ) as handle:
                handle.write(conversation.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            os.replace(temp_path, path)
        except OSError as exc:
            raise ConversationStoreError("Failed to persist Project conversation.") from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return conversation

