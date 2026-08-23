from __future__ import annotations

from investigations import InvestigationEvidenceStore, InvestigationSessionStore

from .activity_store import ProjectActivityStore
from .checkpoint_proposal_store import CheckpointProposalStore
from .models import (
    PROJECT_KNOWLEDGE_SCHEMA_VERSION,
    CheckpointProposalStatus,
    ProjectActivity,
    ProjectActivityConfirmationStatus,
    ProjectActivitySourceType,
    ProjectActivityType,
    ProjectKnowledge,
    ProjectKnowledgeEvidence,
    ProjectKnowledgeRecord,
)
from .project_store import ProjectStore


EVIDENCE_LIMIT = 50
DECISION_LIMIT = 50
FINDING_LIMIT = 50
HISTORY_LIMIT = 100
RECENT_IMPORTANT_CHANGE_LIMIT = 10
ROADMAP_STATUSES = {"completed", "current", "upcoming", "deferred"}


class ProjectKnowledgeError(RuntimeError):
    pass


def _activity_record(activity: ProjectActivity, kind: str) -> ProjectKnowledgeRecord:
    return ProjectKnowledgeRecord(
        record_kind=kind,
        occurred_at_utc=activity.occurred_at_utc,
        summary=activity.summary,
        source_type=activity.source_type.value,
        confirmation_status=activity.confirmation_status.value,
        activity_id=activity.activity_id,
        metadata=activity.metadata,
    )


class ProjectKnowledgeReader:
    def __init__(self, *, project_store: ProjectStore, activity_store: ProjectActivityStore,
                 proposal_store: CheckpointProposalStore, session_store: InvestigationSessionStore,
                 evidence_store: InvestigationEvidenceStore):
        self.project_store = project_store
        self.activity_store = activity_store
        self.proposal_store = proposal_store
        self.session_store = session_store
        self.evidence_store = evidence_store

    def get_knowledge(self, project_id: str) -> ProjectKnowledge:
        self.project_store.load_project(project_id)
        activities = self.activity_store.list_activities(project_id)
        proposals = self.proposal_store.list_proposals(project_id)
        sessions = self.session_store.list_sessions_for_project(project_id)

        related_by_session: dict[str, list[str]] = {}
        for activity in activities:
            metadata = activity.metadata or {}
            session_id = metadata.get("investigation_session_id") or metadata.get("trust_session_id")
            if isinstance(session_id, str):
                related_by_session.setdefault(session_id, []).append(activity.activity_id)

        evidence: list[ProjectKnowledgeEvidence] = []
        for session in sessions:
            for item in self.evidence_store.list_evidence_for_analysis(session.session_id):
                evidence.append(ProjectKnowledgeEvidence(
                    origin="investigation_evidence", occurred_at_utc=item.created_at_utc,
                    summary=item.normalized_text or item.filename, source_type=item.source,
                    confirmation_status=item.validation_status.value, evidence_id=item.evidence_id,
                    investigation_session_id=session.session_id,
                    related_activity_ids=related_by_session.get(session.session_id, []),
                    reference=item.storage_ref,
                ))
        for activity in activities:
            if activity.activity_type == ProjectActivityType.OBSERVATION:
                evidence.append(ProjectKnowledgeEvidence(
                    origin="activity_observation", occurred_at_utc=activity.occurred_at_utc,
                    summary=activity.summary, source_type=activity.source_type.value,
                    confirmation_status=activity.confirmation_status.value,
                    activity_id=activity.activity_id,
                    investigation_session_id=(activity.metadata or {}).get("investigation_session_id") if isinstance((activity.metadata or {}).get("investigation_session_id"), str) else None,
                ))
        evidence.sort(key=lambda x: (x.occurred_at_utc, x.evidence_id or x.activity_id or ""), reverse=True)

        decisions = [_activity_record(a, "decision") for a in activities
                     if a.activity_type == ProjectActivityType.DECISION
                     and (a.source_type != ProjectActivitySourceType.AI
                          or a.confirmation_status == ProjectActivityConfirmationStatus.CONFIRMED)]
        applied_records = [ProjectKnowledgeRecord(
            record_kind="applied_checkpoint_proposal", occurred_at_utc=p.applied_at_utc,
            summary=p.reason, source_type="validated", confirmation_status="confirmed",
            proposal_id=p.proposal_id,
            metadata={"source_activity_ids": ",".join(p.source_activity_ids)},
        ) for p in proposals if p.status == CheckpointProposalStatus.APPLIED and p.applied_at_utc]
        decisions.extend(applied_records)
        decisions.sort(key=lambda x: (x.occurred_at_utc, x.activity_id or x.proposal_id or ""), reverse=True)

        findings = [_activity_record(a, "confirmed_finding") for a in activities
                    if a.activity_type in {ProjectActivityType.RESULT, ProjectActivityType.OBSERVATION}
                    and a.confirmation_status == ProjectActivityConfirmationStatus.CONFIRMED]
        findings.sort(key=lambda x: (x.occurred_at_utc, x.activity_id or ""), reverse=True)

        important = [_activity_record(a, "activity_change") for a in activities if self._is_important(a)]
        important.extend(applied_records)
        important.sort(key=lambda x: (x.occurred_at_utc, x.activity_id or x.proposal_id or ""), reverse=True)

        return ProjectKnowledge(
            schema_version=PROJECT_KNOWLEDGE_SCHEMA_VERSION, project_id=project_id,
            evidence_limit=EVIDENCE_LIMIT, decision_limit=DECISION_LIMIT, finding_limit=FINDING_LIMIT,
            history_limit=HISTORY_LIMIT, recent_important_change_limit=RECENT_IMPORTANT_CHANGE_LIMIT,
            evidence=evidence[:EVIDENCE_LIMIT], decisions=decisions[:DECISION_LIMIT],
            findings=findings[:FINDING_LIMIT], history=list(reversed(activities[-HISTORY_LIMIT:])),
            recent_important_changes=important[:RECENT_IMPORTANT_CHANGE_LIMIT],
        )

    @staticmethod
    def _is_important(activity: ProjectActivity) -> bool:
        metadata = activity.metadata or {}
        if activity.activity_type in {ProjectActivityType.MILESTONE, ProjectActivityType.DECISION, ProjectActivityType.BLOCKER}:
            return True
        if activity.activity_type == ProjectActivityType.RESULT:
            return True
        if metadata.get("trust_decision") in {"continue", "disagree", "more_evidence"}:
            return True
        return metadata.get("roadmap_status") in ROADMAP_STATUSES
