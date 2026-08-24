from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid5

from .activity_store import ProjectActivityNotFound, ProjectActivityStore
from .checkpoint_proposal_store import CheckpointProposalNotFound, CheckpointProposalStore
from .models import (
    CheckpointProposal,
    CheckpointProposalCreateRequest,
    CheckpointProposalPatch,
    ProjectActivity,
    ProjectActivityConfirmationStatus,
    ProjectActivityCreateRequest,
    ProjectActivitySourceType,
    ProjectActivityType,
    ProjectProgressCheckpointPatch,
    ProjectProgressPreview,
    ProjectProgressRequest,
    ProjectProgressResponse,
)
from .project_store import ProjectRevisionConflict, ProjectStore


class ProjectProgressError(RuntimeError):
    pass


class ProjectProgressIdempotencyConflict(ProjectProgressError):
    pass


class ProjectProgressRecoveryConflict(ProjectProgressError):
    pass


class ProjectProgressService:
    INTERACTION_TYPE = "record_progress"
    PROPOSAL_REASON = "Recorded progress suggested a Project update."

    def __init__(
        self,
        project_store: ProjectStore,
        activity_store: ProjectActivityStore,
        proposal_store: CheckpointProposalStore,
    ) -> None:
        self.project_store = project_store
        self.activity_store = activity_store
        self.proposal_store = proposal_store

    @staticmethod
    def _fingerprint(request: ProjectProgressRequest) -> str:
        payload = request.model_dump(mode="json", exclude_none=True)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _ids(project_id: str, key: str) -> tuple[str, str, str]:
        interaction_id = str(uuid5(UUID(project_id), f"record-progress:{key}"))
        return (
            interaction_id,
            str(uuid5(UUID(interaction_id), "activity")),
            str(uuid5(UUID(interaction_id), "proposal")),
        )

    @staticmethod
    def _effective_patch(project, requested: ProjectProgressCheckpointPatch | None) -> ProjectProgressCheckpointPatch | None:
        if requested is None:
            return None
        changed = {
            key: value
            for key, value in requested.to_update_fields().items()
            if getattr(project.checkpoint, key) != value
        }
        return ProjectProgressCheckpointPatch(**changed) if changed else None

    def preview(self, project_id: str, request: ProjectProgressRequest) -> ProjectProgressPreview:
        project = self.project_store.load_project(project_id)
        if request.expected_project_revision != project.revision:
            raise ProjectRevisionConflict("expected_project_revision does not match the current project revision.")
        effective = self._effective_patch(project, request.checkpoint_patch)
        return ProjectProgressPreview(
            project_id=project.project_id,
            idempotency_key=request.idempotency_key,
            summary=request.summary,
            details=request.details,
            base_project_revision=project.revision,
            effective_checkpoint_patch=effective,
            proposal_required=effective is not None,
        )

    def save(self, project_id: str, request: ProjectProgressRequest) -> ProjectProgressResponse:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        fingerprint = self._fingerprint(request)
        interaction_id, activity_id, proposal_id = self._ids(normalized_project_id, request.idempotency_key)
        project_lock = self.project_store._get_project_lock(normalized_project_id)

        with project_lock:
            project = self.project_store._load_project_no_lock(normalized_project_id)
            existing_activity: ProjectActivity | None = None
            try:
                existing_activity = self.activity_store.load_activity(normalized_project_id, activity_id)
            except ProjectActivityNotFound:
                pass

            reconstructed = existing_activity is not None
            if existing_activity is not None:
                metadata = existing_activity.metadata or {}
                if metadata.get("request_fingerprint") != fingerprint:
                    raise ProjectProgressIdempotencyConflict(
                        "idempotency_key was already used with different progress content."
                    )
                base_revision = int(metadata.get("base_project_revision", -1))
                proposal_required = bool(metadata.get("proposal_required", False))
                effective = None
                activity = existing_activity
            else:
                if request.expected_project_revision != project.revision:
                    raise ProjectRevisionConflict(
                        "expected_project_revision does not match the current project revision."
                    )
                effective = self._effective_patch(project, request.checkpoint_patch)
                proposal_required = effective is not None
                base_revision = project.revision
                activity, _ = self.activity_store.create_activity_with_id(
                    normalized_project_id,
                    activity_id,
                    ProjectActivityCreateRequest(
                        activity_type=ProjectActivityType.NOTE,
                        source_type=ProjectActivitySourceType.USER,
                        confirmation_status=ProjectActivityConfirmationStatus.REPORTED,
                        summary=request.summary,
                        details=request.details,
                        metadata={
                            "interaction_type": self.INTERACTION_TYPE,
                            "interaction_id": interaction_id,
                            "idempotency_key": request.idempotency_key,
                            "request_fingerprint": fingerprint,
                            "base_project_revision": base_revision,
                            "proposal_required": proposal_required,
                        },
                    ),
                )

            proposal: CheckpointProposal | None = None
            if proposal_required:
                try:
                    proposal = self.proposal_store.load_proposal(normalized_project_id, proposal_id)
                except CheckpointProposalNotFound:
                    if project.revision != base_revision:
                        raise ProjectProgressRecoveryConflict(
                            "Progress was recorded, but the Project changed before its proposal could be recovered."
                        )
                    effective = self._effective_patch(project, request.checkpoint_patch)
                    if effective is None:
                        raise ProjectProgressRecoveryConflict(
                            "Stored progress requires a proposal, but its checkpoint change cannot be reconstructed."
                        )
                    proposal, _ = self.proposal_store.create_proposal_with_id(
                        normalized_project_id,
                        proposal_id,
                        CheckpointProposalCreateRequest(
                            expected_project_revision=base_revision,
                            source_activity_ids=[activity.activity_id],
                            proposed_checkpoint_patch=CheckpointProposalPatch(**effective.to_update_fields()),
                            reason=self.PROPOSAL_REASON,
                        ),
                    )
                if effective is None:
                    proposal_fields = proposal.proposed_checkpoint_patch.to_update_fields()
                    effective = ProjectProgressCheckpointPatch(
                        **{
                            key: value
                            for key, value in proposal_fields.items()
                            if key in {"current_work", "blockers", "next_action"}
                        }
                    )
                expected_patch = effective.to_update_fields()
                if (
                    proposal.project_id != normalized_project_id
                    or proposal.base_project_revision != base_revision
                    or proposal.source_activity_ids != [activity.activity_id]
                    or proposal.proposed_checkpoint_patch.to_update_fields() != expected_patch
                    or proposal.reason != self.PROPOSAL_REASON
                ):
                    raise ProjectProgressRecoveryConflict("Stored progress proposal conflicts with this request.")

            return ProjectProgressResponse(
                project_id=normalized_project_id,
                idempotency_key=request.idempotency_key,
                summary=activity.summary,
                details=activity.details,
                base_project_revision=base_revision,
                effective_checkpoint_patch=effective,
                proposal_required=proposal_required,
                activity=activity,
                proposal=proposal,
                reconstructed=reconstructed,
            )
