from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from investigations import InvestigationSessionStore, InvestigationStoreError, load_canonical_investigation_result

from .activity_store import ProjectActivityStore
from .checkpoint_proposal_store import CheckpointProposalStore
from .models import (
    PROJECT_TRUST_STATE_SCHEMA_VERSION,
    CheckpointProposal,
    CheckpointProposalCreateRequest,
    CheckpointProposalPatch,
    ProjectActivity,
    ProjectActivityConfirmationStatus,
    ProjectActivityCreateRequest,
    ProjectActivitySourceType,
    ProjectActivityType,
    ProjectInvestigationTrustState,
    ProjectTrustDecisionRequest,
    ProjectTrustDecisionResponse,
    ProjectTrustDecisionType,
)


TRUST_DECISION_METADATA_KEY = "trust_decision"


class ProjectInvestigationTrustError(RuntimeError):
    pass


class ProjectInvestigationTrustService:
    def __init__(self, *, activity_store: ProjectActivityStore, proposal_store: CheckpointProposalStore,
                 session_store: InvestigationSessionStore, canonical_result_root: Path):
        self.activity_store = activity_store
        self.proposal_store = proposal_store
        self.session_store = session_store
        self.canonical_result_root = canonical_result_root

    def _load_source(self, project_id: str, session_id: str):
        session = self.session_store.load_session_for_project(project_id, session_id)
        if not session.completed_result_id:
            raise ProjectInvestigationTrustError("Investigation has no completed result.")
        try:
            envelope = load_canonical_investigation_result(self.canonical_result_root, session.completed_result_id)
        except InvestigationStoreError as exc:
            raise ProjectInvestigationTrustError(
                "Investigation canonical result is unavailable; no trust decision can be reconstructed."
            ) from exc
        activities = self.activity_store.list_activities(project_id)
        source = next((a for a in activities if (a.metadata or {}).get("investigation_result_id") == session.completed_result_id
                       and a.source_type == ProjectActivitySourceType.AI), None)
        if source is None:
            raise ProjectInvestigationTrustError("Investigation result Activity is unavailable.")
        return session, envelope.retained_result, source, activities

    def decide(self, project_id: str, session_id: str, request: ProjectTrustDecisionRequest) -> ProjectTrustDecisionResponse:
        normalized_project_id = self.activity_store.project_store.validate_project_id(project_id)
        project_lock = self.activity_store.project_store._get_project_lock(normalized_project_id)
        with project_lock:
            session, retained, source, activities = self._load_source(normalized_project_id, session_id)
            if request.decision == ProjectTrustDecisionType.DISAGREE and not request.correction:
                details = "User disagreed with the AI hypothesis without providing a correction."
            else:
                details = request.correction

            decisions = [
                item for item in activities
                if (item.metadata or {}).get("trust_result_id") == session.completed_result_id
                and (item.metadata or {}).get(TRUST_DECISION_METADATA_KEY) in {decision.value for decision in ProjectTrustDecisionType}
            ]
            latest = decisions[-1] if decisions else None
            if (
                latest is not None
                and (latest.metadata or {}).get(TRUST_DECISION_METADATA_KEY) == request.decision.value
                and latest.details == details
            ):
                proposal = None
                if request.decision == ProjectTrustDecisionType.CONTINUE:
                    proposal = next(
                        (item for item in reversed(self.proposal_store.list_proposals(normalized_project_id))
                         if latest.activity_id in item.source_activity_ids),
                        None,
                    )
                    if proposal is None:
                        project = self.activity_store.project_store.load_project(normalized_project_id)
                        proposal = self.proposal_store.create_proposal(normalized_project_id, CheckpointProposalCreateRequest(
                            expected_project_revision=project.revision,
                            source_activity_ids=[source.activity_id, latest.activity_id],
                            proposed_checkpoint_patch=CheckpointProposalPatch(next_action=retained.required_next_action),
                            reason="User chose Continue on an AI working hypothesis; proposed next action still requires explicit apply.",
                        ))
                state = self.get_state(normalized_project_id, session_id)
                return ProjectTrustDecisionResponse(
                    trust_state=state,
                    decision_activity=latest,
                    checkpoint_proposal=proposal,
                )

            metadata: dict[str, str] = {
                TRUST_DECISION_METADATA_KEY: request.decision.value,
                "trust_session_id": session.session_id,
                "trust_result_id": session.completed_result_id,
                "source_activity_id": source.activity_id,
            }
            if request.decision == ProjectTrustDecisionType.MORE_EVIDENCE:
                follow_up = self.session_store.create_session(
                    project_id=normalized_project_id,
                    client_metadata={"continued_from_session_id": session.session_id, "continued_from_result_id": session.completed_result_id},
                )
                metadata["follow_up_session_id"] = follow_up.session_id
            activity = self.activity_store.create_activity(normalized_project_id, ProjectActivityCreateRequest(
                activity_type=ProjectActivityType.ACTION,
                source_type=ProjectActivitySourceType.USER,
                confirmation_status=ProjectActivityConfirmationStatus.REPORTED,
                summary=f"Investigation decision: {request.decision.value.replace('_', ' ')}",
                details=details,
                occurred_at_utc=datetime.now(timezone.utc),
                metadata=metadata,
            ))
            proposal: CheckpointProposal | None = None
            if request.decision == ProjectTrustDecisionType.CONTINUE:
                project = self.activity_store.project_store.load_project(normalized_project_id)
                proposal = self.proposal_store.create_proposal(normalized_project_id, CheckpointProposalCreateRequest(
                    expected_project_revision=project.revision,
                    source_activity_ids=[source.activity_id, activity.activity_id],
                    proposed_checkpoint_patch=CheckpointProposalPatch(next_action=retained.required_next_action),
                    reason="User chose Continue on an AI working hypothesis; proposed next action still requires explicit apply.",
                ))
            state = self.get_state(normalized_project_id, session_id)
            if proposal is not None:
                state = state.model_copy(update={"checkpoint_proposal_id": proposal.proposal_id, "checkpoint_proposal_status": proposal.status})
            return ProjectTrustDecisionResponse(trust_state=state, decision_activity=activity, checkpoint_proposal=proposal)

    def get_state(self, project_id: str, session_id: str) -> ProjectInvestigationTrustState:
        session, retained, _source, activities = self._load_source(project_id, session_id)
        decisions = [a for a in activities if (a.metadata or {}).get("trust_result_id") == session.completed_result_id
                     and (a.metadata or {}).get(TRUST_DECISION_METADATA_KEY) in {d.value for d in ProjectTrustDecisionType}]
        latest = decisions[-1] if decisions else None
        decision = ProjectTrustDecisionType((latest.metadata or {})[TRUST_DECISION_METADATA_KEY]) if latest else None
        statuses = {None: "awaiting_decision", ProjectTrustDecisionType.CONTINUE: "working_hypothesis",
                    ProjectTrustDecisionType.DISAGREE: "needs_reassessment", ProjectTrustDecisionType.MORE_EVIDENCE: "unresolved"}
        proposal = None
        if latest:
            proposals = self.proposal_store.list_proposals(project_id)
            proposal = next((p for p in reversed(proposals) if latest.activity_id in p.source_activity_ids), None)
        return ProjectInvestigationTrustState(
            schema_version=PROJECT_TRUST_STATE_SCHEMA_VERSION, project_id=project_id,
            investigation_session_id=session.session_id, investigation_result_id=session.completed_result_id,
            hypothesis=retained.diagnosis, recommended_next_action=retained.required_next_action,
            status=statuses[decision], user_decision=decision, user_correction=latest.details if latest else None,
            decision_activity_id=latest.activity_id if latest else None,
            decided_at_utc=latest.occurred_at_utc if latest else None,
            checkpoint_proposal_id=proposal.proposal_id if proposal else None,
            checkpoint_proposal_status=proposal.status if proposal else None,
            follow_up_investigation_session_id=(latest.metadata or {}).get("follow_up_session_id") if latest else None,
        )
