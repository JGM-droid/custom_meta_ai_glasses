from __future__ import annotations

from pathlib import Path
import re

from investigations import (
    InvestigationSessionStatus,
    InvestigationSessionStore,
    InvestigationSessionStoreError,
    InvestigationStoreError,
    load_canonical_investigation_result,
)

from .activity_store import ProjectActivityStore, ProjectActivityStoreError
from .models import (
    PROJECT_CONTEXT_PACK_SCHEMA_VERSION,
    PROJECT_CONTEXT_QUERY_PACK_SCHEMA_VERSION,
    ProjectActivity,
    ProjectActivityConfirmationStatus,
    ProjectActivitySourceType,
    ProjectActivityType,
    ProjectContextPack,
    ProjectContextQueryPack,
    ProjectContextSelectionMetadata,
    ProjectInvestigationSummary,
)
from .project_store import ProjectNotFound, ProjectStore, ProjectStoreError

DEFAULT_RECENT_ACTIVITY_LIMIT = 5
DEFAULT_RECENT_INVESTIGATION_LIMIT = 3
_STOPWORDS = {
    "about",
    "after",
    "before",
    "did",
    "does",
    "from",
    "had",
    "have",
    "into",
    "leave",
    "left",
    "off",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
}


class ProjectContextRetrieverError(RuntimeError):
    pass


class ProjectContextRetriever:
    def __init__(
        self,
        *,
        project_store: ProjectStore,
        activity_store: ProjectActivityStore,
        session_store: InvestigationSessionStore,
        investigation_store_root: Path,
        recent_activity_limit: int = DEFAULT_RECENT_ACTIVITY_LIMIT,
        recent_investigation_limit: int = DEFAULT_RECENT_INVESTIGATION_LIMIT,
    ) -> None:
        self.project_store = project_store
        self.activity_store = activity_store
        self.session_store = session_store
        self.investigation_store_root = Path(investigation_store_root)
        self.recent_activity_limit = recent_activity_limit
        self.recent_investigation_limit = recent_investigation_limit

    def get_context(self, project_id: str) -> ProjectContextPack:
        try:
            project = self.project_store.load_project(project_id)
            all_activities = self.activity_store.list_activities(project_id)
            sessions = self.session_store.list_sessions_for_project(project_id)
        except ProjectNotFound:
            raise
        except (ProjectStoreError, ProjectActivityStoreError, InvestigationSessionStoreError) as exc:
            raise ProjectContextRetrieverError("Project context is unavailable.") from exc

        recent_activities = list(reversed(all_activities[-self.recent_activity_limit :]))
        recent_investigations = self._recent_investigations(sessions)

        return ProjectContextPack(
            schema_version=PROJECT_CONTEXT_PACK_SCHEMA_VERSION,
            project_id=project.project_id,
            project_name=project.name,
            project_goal=project.goal,
            project_status=project.status,
            checkpoint=project.checkpoint,
            current_objective=project.checkpoint.current_objective,
            blockers=project.checkpoint.blockers,
            next_action=project.checkpoint.next_action,
            recent_activity_limit=self.recent_activity_limit,
            recent_investigation_limit=self.recent_investigation_limit,
            recent_activities=recent_activities,
            recent_investigations=recent_investigations,
        )

    def get_context_for_question(self, project_id: str, question: str) -> ProjectContextQueryPack:
        base_context = self.get_context(project_id)
        normalized_question = str(question or "").strip()
        if not normalized_question:
            raise ProjectContextRetrieverError("Project context is unavailable.")

        question_terms = self._extract_terms(normalized_question)
        checkpoint_terms = self._extract_terms(
            " ".join(
                part
                for part in [
                    base_context.current_objective or "",
                    base_context.blockers or "",
                    base_context.next_action or "",
                    base_context.checkpoint.completed_summary or "",
                    base_context.checkpoint.discoveries_summary or "",
                    base_context.checkpoint.current_work or "",
                ]
                if part
            )
        )
        fallback_used = len(question_terms.intersection(checkpoint_terms)) == 0

        selected_activities = self._rank_activities(base_context.recent_activities, question_terms, fallback_used=fallback_used)
        selected_investigations = self._rank_investigations(base_context.recent_investigations, question_terms, fallback_used=fallback_used)

        matched_terms = sorted(
            question_terms.intersection(
                checkpoint_terms
                .union(*(self._extract_terms(item.summary + " " + (item.details or "")) for item in base_context.recent_activities))
                .union(*(self._extract_terms(item.diagnosis + " " + item.required_next_action) for item in base_context.recent_investigations))
            )
        )

        return ProjectContextQueryPack(
            schema_version=PROJECT_CONTEXT_QUERY_PACK_SCHEMA_VERSION,
            project_id=base_context.project_id,
            project_name=base_context.project_name,
            project_goal=base_context.project_goal,
            project_status=base_context.project_status,
            question=normalized_question,
            checkpoint=base_context.checkpoint,
            current_objective=base_context.current_objective,
            blockers=base_context.blockers,
            next_action=base_context.next_action,
            selection=ProjectContextSelectionMetadata(
                strategy="deterministic_keyword_overlap_recency",
                matched_terms=matched_terms,
                recent_activity_limit=self.recent_activity_limit,
                recent_investigation_limit=self.recent_investigation_limit,
                fallback_used=fallback_used,
            ),
            selected_activities=selected_activities,
            selected_investigations=selected_investigations,
        )

    def _recent_investigations(self, sessions) -> list[ProjectInvestigationSummary]:
        summaries: list[ProjectInvestigationSummary] = []
        for session in sessions:
            if session.status != InvestigationSessionStatus.COMPLETED:
                continue
            if not session.completed_result_id:
                continue
            try:
                retained = load_canonical_investigation_result(
                    self.investigation_store_root,
                    session.completed_result_id,
                ).retained_result
            except InvestigationStoreError as exc:
                raise ProjectContextRetrieverError("Project context is unavailable.") from exc

            if retained.session_id != session.session_id:
                raise ProjectContextRetrieverError("Project context is unavailable.")

            summaries.append(
                ProjectInvestigationSummary(
                    session_id=session.session_id,
                    result_id=session.completed_result_id,
                    investigation_id=retained.investigation_id,
                    status=retained.status.value,
                    diagnosis=retained.diagnosis,
                    required_next_action=retained.required_next_action,
                    completed_at_utc=retained.completed_at_utc,
                )
            )

        summaries.sort(
            key=lambda item: (item.completed_at_utc, item.session_id, item.result_id),
            reverse=True,
        )
        return summaries[: self.recent_investigation_limit]

    @staticmethod
    def _extract_terms(text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if len(token) >= 3 and token not in _STOPWORDS
        }

    def _rank_activities(
        self,
        activities: list[ProjectActivity],
        question_terms: set[str],
        *,
        fallback_used: bool,
    ) -> list[ProjectActivity]:
        ranked = sorted(
            activities,
            key=lambda item: self._activity_rank_key(item, question_terms, fallback_used=fallback_used),
            reverse=True,
        )
        return ranked[: self.recent_activity_limit]

    def _rank_investigations(
        self,
        investigations: list[ProjectInvestigationSummary],
        question_terms: set[str],
        *,
        fallback_used: bool,
    ) -> list[ProjectInvestigationSummary]:
        ranked = sorted(
            investigations,
            key=lambda item: self._investigation_rank_key(item, question_terms, fallback_used=fallback_used),
            reverse=True,
        )
        return ranked[: self.recent_investigation_limit]

    def _activity_rank_key(
        self,
        activity: ProjectActivity,
        question_terms: set[str],
        *,
        fallback_used: bool,
    ) -> tuple[int, int, int, int, object, object, str]:
        content_terms = self._extract_terms(activity.summary + " " + (activity.details or ""))
        overlap = len(question_terms.intersection(content_terms)) if question_terms else 0
        type_score = {
            ProjectActivityType.RESULT: 3,
            ProjectActivityType.OBSERVATION: 2,
            ProjectActivityType.BLOCKER: 2,
            ProjectActivityType.NOTE: 1,
            ProjectActivityType.ACTION: 1,
            ProjectActivityType.DECISION: 1,
            ProjectActivityType.MILESTONE: 0,
        }.get(activity.activity_type, 0)
        source_score = {
            ProjectActivitySourceType.USER: 2,
            ProjectActivitySourceType.SYSTEM: 1,
            ProjectActivitySourceType.AI: 0,
        }.get(activity.source_type, 0)
        confirmation_score = {
            ProjectActivityConfirmationStatus.CONFIRMED: 3,
            ProjectActivityConfirmationStatus.OBSERVED: 2,
            ProjectActivityConfirmationStatus.REPORTED: 1,
            ProjectActivityConfirmationStatus.INFERRED: 0,
        }.get(activity.confirmation_status, 0)
        if fallback_used:
            overlap = 0
        return (
            overlap,
            type_score,
            source_score,
            confirmation_score,
            activity.occurred_at_utc,
            activity.created_at_utc,
            activity.activity_id,
        )

    def _investigation_rank_key(
        self,
        investigation: ProjectInvestigationSummary,
        question_terms: set[str],
        *,
        fallback_used: bool,
    ) -> tuple[int, object, str, str]:
        content_terms = self._extract_terms(investigation.diagnosis + " " + investigation.required_next_action)
        overlap = len(question_terms.intersection(content_terms)) if question_terms else 0
        if fallback_used:
            overlap = 0
        return (
            overlap,
            investigation.completed_at_utc,
            investigation.session_id,
            investigation.result_id,
        )
