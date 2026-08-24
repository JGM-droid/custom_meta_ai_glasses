from __future__ import annotations

from dataclasses import dataclass
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
QUESTION_CLASS_CONTINUITY = "continuity"
QUESTION_CLASS_STATUS = "status"
QUESTION_CLASS_NEXT_ACTION = "next_action"
QUESTION_CLASS_EVIDENCE_LOOKUP = "evidence_lookup"
RETRIEVAL_CONTRACT_ID = "e3_deterministic_contract_v1"
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

_CLASSIFICATION_TERMS = {
    QUESTION_CLASS_CONTINUITY: {
        "continue",
        "continuity",
        "leave",
        "left",
        "resume",
        "resuming",
        "off",
        "paused",
        "stopped",
        "pick",
        "pickup",
        "context",
    },
    QUESTION_CLASS_STATUS: {
        "status",
        "progress",
        "completed",
        "complete",
        "done",
        "finished",
        "shipped",
        "state",
    },
    QUESTION_CLASS_NEXT_ACTION: {
        "next",
        "action",
        "should",
        "todo",
        "prioritize",
        "priority",
        "proceed",
        "now",
        "step",
        "steps",
    },
    QUESTION_CLASS_EVIDENCE_LOOKUP: {
        "determine",
        "determined",
        "find",
        "found",
        "evidence",
        "observed",
        "observation",
        "why",
        "root",
        "cause",
        "about",
    },
}


@dataclass(frozen=True)
class _RetrievalContract:
    question_class: str
    required_categories: tuple[str, ...]
    optional_categories: tuple[str, ...]
    excluded_categories: tuple[str, ...]
    activity_limit: int
    investigation_limit: int


_CONTRACTS: dict[str, _RetrievalContract] = {
    QUESTION_CLASS_CONTINUITY: _RetrievalContract(
        question_class=QUESTION_CLASS_CONTINUITY,
        required_categories=("project_identity", "checkpoint", "blockers", "next_action"),
        optional_categories=("recent_activities",),
        excluded_categories=("recent_investigations", "deep_historical_evidence"),
        activity_limit=2,
        investigation_limit=0,
    ),
    QUESTION_CLASS_STATUS: _RetrievalContract(
        question_class=QUESTION_CLASS_STATUS,
        required_categories=("project_identity", "checkpoint"),
        optional_categories=("recent_activities",),
        excluded_categories=("recent_investigations", "deep_historical_evidence"),
        activity_limit=3,
        investigation_limit=0,
    ),
    QUESTION_CLASS_NEXT_ACTION: _RetrievalContract(
        question_class=QUESTION_CLASS_NEXT_ACTION,
        required_categories=("project_identity", "current_objective", "blockers", "next_action"),
        optional_categories=("recent_activities",),
        excluded_categories=("recent_investigations", "deep_historical_evidence"),
        activity_limit=2,
        investigation_limit=0,
    ),
    QUESTION_CLASS_EVIDENCE_LOOKUP: _RetrievalContract(
        question_class=QUESTION_CLASS_EVIDENCE_LOOKUP,
        required_categories=("project_identity", "checkpoint", "recent_activities", "recent_investigations"),
        optional_categories=("deeper_evidence_later_phase",),
        excluded_categories=("deep_historical_evidence",),
        activity_limit=DEFAULT_RECENT_ACTIVITY_LIMIT,
        investigation_limit=DEFAULT_RECENT_INVESTIGATION_LIMIT,
    ),
}

_QUESTION_CLASS_PRIORITY = (
    QUESTION_CLASS_NEXT_ACTION,
    QUESTION_CLASS_STATUS,
    QUESTION_CLASS_CONTINUITY,
    QUESTION_CLASS_EVIDENCE_LOOKUP,
)


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

    def get_explore_context_activities(
        self,
        project_id: str,
        input_refs: list[str],
        *,
        relevant_limit: int = 10,
    ) -> tuple[Project, list[ProjectActivity], list[ProjectActivity]]:
        """Deterministically select the bounded Explore context contract inputs."""
        project = self.project_store.load_project(project_id)
        explicit: list[ProjectActivity] = []
        for activity_id in input_refs:
            explicit.append(self.activity_store.load_activity(project_id, activity_id))

        explicit_ids = set(input_refs)
        relevant: list[ProjectActivity] = []
        for activity in reversed(self.activity_store.list_activities(project_id)):
            if activity.activity_id in explicit_ids:
                continue
            if activity.activity_type == ProjectActivityType.DECISION or (
                activity.activity_type in {
                    ProjectActivityType.OBSERVATION,
                    ProjectActivityType.NOTE,
                    ProjectActivityType.BLOCKER,
                }
                and activity.confirmation_status in {
                    ProjectActivityConfirmationStatus.CONFIRMED,
                    ProjectActivityConfirmationStatus.OBSERVED,
                    ProjectActivityConfirmationStatus.REPORTED,
                }
            ):
                relevant.append(activity)
            if len(relevant) == relevant_limit:
                break
        return project, explicit, relevant

    def get_context_for_question(self, project_id: str, question: str) -> ProjectContextQueryPack:
        base_context = self.get_context(project_id)
        normalized_question = str(question or "").strip()
        if not normalized_question:
            raise ProjectContextRetrieverError("Project context is unavailable.")

        question_terms = self._extract_terms(normalized_question)
        question_class = self._classify_question(normalized_question, question_terms)
        contract = _CONTRACTS[question_class]
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

        selected_activities = self._rank_activities(
            base_context.recent_activities,
            question_terms,
            fallback_used=fallback_used,
            limit=contract.activity_limit,
        )
        selected_investigations = self._rank_investigations(
            base_context.recent_investigations,
            question_terms,
            fallback_used=fallback_used,
            limit=contract.investigation_limit,
        )

        if "recent_activities" not in contract.required_categories and "recent_activities" not in contract.optional_categories:
            selected_activities = []

        if "recent_investigations" not in contract.required_categories and "recent_investigations" not in contract.optional_categories:
            selected_investigations = []

        if question_class == QUESTION_CLASS_NEXT_ACTION and fallback_used:
            selected_activities = []

        fallback_reason = None
        if fallback_used:
            fallback_reason = (
                "No lexical overlap with checkpoint hot-context terms; "
                "used deterministic bounded fallback within the selected contract."
            )

        matched_terms = sorted(
            question_terms.intersection(
                checkpoint_terms
                .union(*(self._extract_terms(item.summary + " " + (item.details or "")) for item in base_context.recent_activities))
                .union(*(self._extract_terms(item.diagnosis + " " + item.required_next_action) for item in base_context.recent_investigations))
            )
        )

        selected_categories: list[str] = ["project_identity", "checkpoint"]
        if base_context.current_objective:
            selected_categories.append("current_objective")
        if base_context.blockers:
            selected_categories.append("blockers")
        if base_context.next_action:
            selected_categories.append("next_action")
        if selected_activities:
            selected_categories.append("recent_activities")
        if selected_investigations:
            selected_categories.append("recent_investigations")

        category_inclusion_reasons = {
            "project_identity": "Required in all contracts to enforce explicit project namespace and continuity.",
            "checkpoint": "Required checkpoint context anchors deterministic retrieval.",
            "current_objective": "Included from checkpoint hot context for continuity and next-step clarity.",
            "blockers": "Included from checkpoint hot context to preserve constraint visibility.",
            "next_action": "Included from checkpoint hot context to preserve immediate action guidance.",
            "recent_activities": (
                "Included by contract for bounded supporting evidence and recency-ordered relevance."
                if selected_activities
                else "Not included because the contract excluded it or no useful fallback-safe support was selected."
            ),
            "recent_investigations": (
                "Included by contract for bounded investigation evidence summaries."
                if selected_investigations
                else "Not included because the contract excludes it by default for this question class."
            ),
            "deep_historical_evidence": "Excluded by default in E3 contracts to keep retrieval bounded and deterministic.",
            "deeper_evidence_later_phase": "Optional placeholder for a later phase; not retrieved in E3.",
        }

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
                detected_question_class=question_class,
                retrieval_contract=RETRIEVAL_CONTRACT_ID,
                matched_terms=matched_terms,
                required_categories=list(contract.required_categories),
                optional_categories=list(contract.optional_categories),
                excluded_categories=list(contract.excluded_categories),
                selected_categories=selected_categories,
                category_inclusion_reasons=category_inclusion_reasons,
                recent_activity_limit=contract.activity_limit,
                recent_investigation_limit=contract.investigation_limit,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            ),
            selected_activities=selected_activities,
            selected_investigations=selected_investigations,
        )

    def _classify_question(self, question: str, question_terms: set[str]) -> str:
        lowered_question = question.lower()

        if "should i" in lowered_question and "next" in lowered_question:
            return QUESTION_CLASS_NEXT_ACTION
        if "what should i do next" in lowered_question:
            return QUESTION_CLASS_NEXT_ACTION
        if "where did we leave off" in lowered_question:
            return QUESTION_CLASS_CONTINUITY

        scores: dict[str, int] = {}
        for question_class, class_terms in _CLASSIFICATION_TERMS.items():
            scores[question_class] = len(question_terms.intersection(class_terms))

        if "about" in lowered_question and (
            "determine" in lowered_question
            or "determined" in lowered_question
            or "find" in lowered_question
            or "found" in lowered_question
        ):
            return QUESTION_CLASS_EVIDENCE_LOOKUP

        best_score = max(scores.values()) if scores else 0
        if best_score <= 0:
            return QUESTION_CLASS_CONTINUITY

        best_classes = sorted(
            [question_class for question_class, score in scores.items() if score == best_score],
            key=lambda item: _QUESTION_CLASS_PRIORITY.index(item),
        )
        return best_classes[0]

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
        limit: int,
    ) -> list[ProjectActivity]:
        if limit <= 0:
            return []
        ranked = sorted(
            activities,
            key=lambda item: self._activity_rank_key(item, question_terms, fallback_used=fallback_used),
            reverse=True,
        )
        return ranked[:limit]

    def _rank_investigations(
        self,
        investigations: list[ProjectInvestigationSummary],
        question_terms: set[str],
        *,
        fallback_used: bool,
        limit: int,
    ) -> list[ProjectInvestigationSummary]:
        if limit <= 0:
            return []
        ranked = sorted(
            investigations,
            key=lambda item: self._investigation_rank_key(item, question_terms, fallback_used=fallback_used),
            reverse=True,
        )
        return ranked[:limit]

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
