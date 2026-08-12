from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError

from .activity_store import ProjectActivityNotFound, ProjectActivityStore
from .models import (
    CHECKPOINT_PROPOSAL_SCHEMA_VERSION,
    CheckpointProposal,
    CheckpointProposalCreateRequest,
    CheckpointProposalPatch,
    CheckpointProposalStatus,
    Project,
    ProjectCheckpoint,
)
from .project_store import ProjectInvalidId, ProjectNotFound, ProjectRevisionConflict, ProjectStore, ProjectStoreError


class CheckpointProposalStoreError(RuntimeError):
    pass


class CheckpointProposalNotFound(CheckpointProposalStoreError):
    pass


class CheckpointProposalInvalidId(CheckpointProposalStoreError):
    pass


class CheckpointProposalStateError(CheckpointProposalStoreError):
    pass


class CheckpointProposalRevisionConflict(CheckpointProposalStoreError):
    pass


class CheckpointProposalForeignActivityReference(CheckpointProposalStoreError):
    pass


class CheckpointProposalStore:
    def __init__(self, root: Path, project_store: ProjectStore, activity_store: ProjectActivityStore):
        self.root = root
        self.project_store = project_store
        self.activity_store = activity_store
        self.proposals_root = self.root / "checkpoint_proposals"
        self.corrupt_dir = self.root / "corrupt"
        self.temp_dir = self.root / "temp"

        self.proposals_root.mkdir(parents=True, exist_ok=True)
        self.corrupt_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def validate_proposal_id(proposal_id: str) -> str:
        text = str(proposal_id or "").strip()
        if not text:
            raise CheckpointProposalInvalidId("proposal_id is required.")
        try:
            parsed = UUID(text)
        except ValueError as exc:
            raise CheckpointProposalInvalidId("proposal_id must be a valid UUID.") from exc
        return str(parsed)

    def _proposal_dir(self, project_id: str) -> Path:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        return self.proposals_root / normalized_project_id

    def _proposal_path(self, project_id: str, proposal_id: str) -> Path:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        normalized_proposal_id = self.validate_proposal_id(proposal_id)
        return self._proposal_dir(normalized_project_id) / f"{normalized_proposal_id}.json"

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
            raise CheckpointProposalStoreError("Failed to persist checkpoint proposal data.") from exc
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
            raise CheckpointProposalStoreError("Checkpoint proposal data could not be read.") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._quarantine_file(path, prefix="checkpoint_proposal_corrupt")
            raise CheckpointProposalStoreError("Checkpoint proposal data is malformed.") from exc

        if not isinstance(parsed, dict):
            self._quarantine_file(path, prefix="checkpoint_proposal_corrupt")
            raise CheckpointProposalStoreError("Checkpoint proposal data has invalid shape.")

        return parsed

    def _load_proposal_from_path(self, project_id: str, path: Path) -> CheckpointProposal:
        parsed = self._load_json_object(path)
        try:
            proposal = CheckpointProposal.model_validate(parsed)
        except ValidationError as exc:
            self._quarantine_file(path, prefix="checkpoint_proposal_corrupt")
            raise CheckpointProposalStoreError("Checkpoint proposal data has invalid schema.") from exc

        if proposal.schema_version != CHECKPOINT_PROPOSAL_SCHEMA_VERSION:
            self._quarantine_file(path, prefix="checkpoint_proposal_corrupt")
            raise CheckpointProposalStoreError("Checkpoint proposal data has unsupported schema version.")

        if proposal.project_id != project_id:
            self._quarantine_file(path, prefix="checkpoint_proposal_corrupt")
            raise CheckpointProposalStoreError("Checkpoint proposal ownership mismatch detected.")

        expected_name = f"{proposal.proposal_id}.json"
        if path.name != expected_name:
            self._quarantine_file(path, prefix="checkpoint_proposal_corrupt")
            raise CheckpointProposalStoreError("Checkpoint proposal identity mismatch detected.")

        return proposal

    def _save_proposal_no_lock(self, proposal: CheckpointProposal) -> None:
        normalized_project_id = self.project_store.validate_project_id(proposal.project_id)
        normalized_proposal_id = self.validate_proposal_id(proposal.proposal_id)
        path = self._proposal_path(normalized_project_id, normalized_proposal_id)
        payload = json.dumps(proposal.model_dump(mode="json"), ensure_ascii=False, indent=2)
        self._atomic_write_json(path, payload)

    def _load_proposal_no_lock(self, project_id: str, proposal_id: str) -> CheckpointProposal:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        normalized_proposal_id = self.validate_proposal_id(proposal_id)
        path = self._proposal_path(normalized_project_id, normalized_proposal_id)
        if not path.exists() or not path.is_file():
            raise CheckpointProposalNotFound("Checkpoint proposal does not exist.")
        return self._load_proposal_from_path(normalized_project_id, path)

    def _apply_patch_to_checkpoint(self, checkpoint: ProjectCheckpoint, patch: CheckpointProposalPatch) -> ProjectCheckpoint:
        checkpoint_dict = checkpoint.model_dump(mode="python")
        for key, value in patch.to_update_fields().items():
            checkpoint_dict[key] = value
        return ProjectCheckpoint.model_validate(checkpoint_dict)

    def _project_matches_patch(self, project: Project, patch: CheckpointProposalPatch) -> bool:
        checkpoint_data = project.checkpoint.model_dump(mode="python")
        for key, value in patch.to_update_fields().items():
            if checkpoint_data.get(key) != value:
                return False
        return True

    def _validate_source_activities(self, project_id: str, source_activity_ids: list[str]) -> None:
        for activity_id in source_activity_ids:
            try:
                self.activity_store.load_activity(project_id, activity_id)
            except ProjectActivityNotFound as exc:
                raise CheckpointProposalForeignActivityReference(
                    "source_activity_ids must reference activities owned by the project."
                ) from exc
            except (ProjectStoreError, ProjectInvalidId) as exc:
                raise CheckpointProposalStoreError(str(exc)) from exc

    def create_proposal(self, project_id: str, request: CheckpointProposalCreateRequest) -> CheckpointProposal:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        project_lock = self.project_store._get_project_lock(normalized_project_id)

        with project_lock:
            project = self.project_store._load_project_no_lock(normalized_project_id)

            if request.expected_project_revision != project.revision:
                raise CheckpointProposalRevisionConflict(
                    "expected_project_revision does not match the current project revision."
                )

            self._validate_source_activities(normalized_project_id, request.source_activity_ids)

            proposal = CheckpointProposal.build_new(
                proposal_id=str(uuid4()),
                project_id=normalized_project_id,
                base_project_revision=project.revision,
                source_activity_ids=request.source_activity_ids,
                proposed_checkpoint_patch=request.proposed_checkpoint_patch,
                reason=request.reason,
                created_at_utc=datetime.now(timezone.utc),
            )
            self._save_proposal_no_lock(proposal)
            return proposal

    def load_proposal(self, project_id: str, proposal_id: str) -> CheckpointProposal:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        self.project_store.load_project(normalized_project_id)
        project_lock = self.project_store._get_project_lock(normalized_project_id)
        with project_lock:
            return self._load_proposal_no_lock(normalized_project_id, proposal_id)

    def list_proposals(self, project_id: str) -> list[CheckpointProposal]:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        self.project_store.load_project(normalized_project_id)
        project_lock = self.project_store._get_project_lock(normalized_project_id)

        with project_lock:
            proposal_dir = self._proposal_dir(normalized_project_id)
            if not proposal_dir.exists() or not proposal_dir.is_dir():
                return []

            proposals: list[CheckpointProposal] = []
            for path in sorted(proposal_dir.glob("*.json")):
                proposals.append(self._load_proposal_from_path(normalized_project_id, path))

            proposals.sort(key=lambda item: (item.created_at_utc, item.proposal_id))
            return proposals

    def apply_proposal(self, project_id: str, proposal_id: str) -> CheckpointProposal:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        normalized_proposal_id = self.validate_proposal_id(proposal_id)
        project_lock = self.project_store._get_project_lock(normalized_project_id)

        with project_lock:
            project = self.project_store._load_project_no_lock(normalized_project_id)
            proposal = self._load_proposal_no_lock(normalized_project_id, normalized_proposal_id)

            if proposal.status != CheckpointProposalStatus.PENDING:
                raise CheckpointProposalStateError("Only pending proposals can be applied.")

            self._validate_source_activities(normalized_project_id, proposal.source_activity_ids)

            if project.revision != proposal.base_project_revision:
                if (
                    project.revision == proposal.base_project_revision + 1
                    and self._project_matches_patch(project, proposal.proposed_checkpoint_patch)
                ):
                    reconciled = proposal.model_copy(
                        update={
                            "status": CheckpointProposalStatus.APPLIED,
                            "applied_at_utc": datetime.now(timezone.utc),
                            "rejected_at_utc": None,
                        }
                    )
                    self._save_proposal_no_lock(reconciled)
                    return reconciled
                raise CheckpointProposalRevisionConflict(
                    "proposal base_project_revision does not match the current project revision."
                )

            now = datetime.now(timezone.utc)
            updated_checkpoint = self._apply_patch_to_checkpoint(project.checkpoint, proposal.proposed_checkpoint_patch)
            updated_project = project.model_copy(
                update={
                    "checkpoint": updated_checkpoint,
                    "revision": project.revision + 1,
                    "updated_at_utc": now,
                }
            )

            self.project_store._save_project_no_lock(updated_project)

            updated_proposal = proposal.model_copy(
                update={
                    "status": CheckpointProposalStatus.APPLIED,
                    "applied_at_utc": now,
                    "rejected_at_utc": None,
                }
            )
            self._save_proposal_no_lock(updated_proposal)
            return updated_proposal

    def reject_proposal(self, project_id: str, proposal_id: str) -> CheckpointProposal:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        normalized_proposal_id = self.validate_proposal_id(proposal_id)
        project_lock = self.project_store._get_project_lock(normalized_project_id)

        with project_lock:
            self.project_store._load_project_no_lock(normalized_project_id)
            proposal = self._load_proposal_no_lock(normalized_project_id, normalized_proposal_id)

            if proposal.status != CheckpointProposalStatus.PENDING:
                raise CheckpointProposalStateError("Only pending proposals can be rejected.")

            updated = proposal.model_copy(
                update={
                    "status": CheckpointProposalStatus.REJECTED,
                    "applied_at_utc": None,
                    "rejected_at_utc": datetime.now(timezone.utc),
                }
            )
            self._save_proposal_no_lock(updated)
            return updated
