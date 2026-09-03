from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from investigations import (
    InvestigationSessionNotFound,
    InvestigationSessionStore,
    InvestigationStoreError,
    build_desktop_projection,
    build_glasses_projection,
    investigation_stale_seconds,
    load_canonical_investigation_result,
)

from .models import (
    ProjectAIResult,
    ProjectAIResultHudProjection,
    ProjectAIResultType,
    ProjectExploreGroupView,
    ProjectExploreRequest,
    ProjectGroundedAnswerResponse,
)
from .project_explore import ProjectExploreService
from .project_qa import ProjectQuestionAnsweringService
from .project_store import ProjectStore


_MAX_GENERAL_GUIDANCE_HEADLINE_LENGTH = 280


class ProjectAIResultError(RuntimeError):
    pass


class ProjectAIResultTroubleshootNotFound(ProjectAIResultError):
    pass


class ProjectAIResultExplorePlanNotFound(ProjectAIResultError):
    pass


def _truncate(text: str, max_length: int) -> str:
    text = str(text or "").strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


class ProjectAIResultPlanner:
    """The Response Planner: explicit dispatch + ProjectAIResult composition.

    Owns no Project Memory, retrieval, or trust of its own - it selects,
    from an explicit client-declared interaction_type, exactly one of the
    three existing/evolved domain services below and wraps whichever typed
    response comes back in the shared presentation envelope. Matches
    docs/PROJECT_INTERACTION_FOUNDATION.md's Project Guidance Engine
    Boundary: "Initial routing should be explicit service dispatch, not
    autonomous intent classification."
    """

    def __init__(self, *, project_store: ProjectStore, explore_service: ProjectExploreService,
                 qa_service: ProjectQuestionAnsweringService, session_store: InvestigationSessionStore,
                 investigation_store_root: Path):
        self.project_store = project_store
        self.explore_service = explore_service
        self.qa_service = qa_service
        self.session_store = session_store
        self.investigation_store_root = investigation_store_root

    # --- EXPLORE_PLAN: create (dispatches to the evolved Explore service) ---

    def create_explore_plan(self, project_id: str, request: ProjectExploreRequest) -> ProjectAIResult | None:
        """Returns None when the provider asked for more information (INFORMATION_REQUEST) -
        callers should surface the ProjectExploreExecutionResponse.information_request as-is;
        there is no ProjectAIResult to compose without a durable interaction_id yet."""
        normalized_project_id = self.project_store.validate_project_id(project_id)
        response = self.explore_service.execute(normalized_project_id, request)
        if response.option_set is None:
            return None
        return self._compose_explore_plan(normalized_project_id, response.option_set)

    def read_explore_plan(self, project_id: str, interaction_id: str) -> ProjectAIResult:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        projection = self.explore_service.read_projection(normalized_project_id)
        group = next((item for item in projection.option_sets if item.interaction_id == interaction_id), None)
        if group is None:
            raise ProjectAIResultExplorePlanNotFound("Explore plan does not exist for this Project.")
        return self._compose_explore_plan(normalized_project_id, group)

    def _compose_explore_plan(self, project_id: str, group: ProjectExploreGroupView) -> ProjectAIResult:
        recommended = next((option for option in group.options if option.recommended), None)
        headline_source = (recommended.idea.summary if recommended else group.title) or "AI plan ready"
        evidence_refs: list[str] = []
        for option in group.options:
            refs_csv = str((option.idea.metadata or {}).get("source_refs") or "")
            evidence_refs.extend(ref for ref in refs_csv.split(",") if ref)
        return ProjectAIResult(
            result_id=group.interaction_id,
            project_id=project_id,
            result_type=ProjectAIResultType.EXPLORE_PLAN,
            summary=group.summary or headline_source,
            hud_projection=ProjectAIResultHudProjection(
                headline=_truncate(f"AI plan ready. Recommends {headline_source}.", _MAX_GENERAL_GUIDANCE_HEADLINE_LENGTH),
                next=_truncate(group.next_steps[0], _MAX_GENERAL_GUIDANCE_HEADLINE_LENGTH) if group.next_steps else None,
                uncertainty_flag=not group.complete,
            ),
            evidence_refs=sorted(set(evidence_refs)),
            suggested_project_updates=bool(group.options and any(option.related_proposals for option in group.options)),
            explore_plan=group,
        )

    # --- TROUBLESHOOT: read-only composition over the existing, unchanged Investigation result ---

    def read_troubleshoot(self, project_id: str, session_id: str) -> ProjectAIResult:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        try:
            session = self.session_store.load_session_for_project(normalized_project_id, session_id)
        except InvestigationSessionNotFound as exc:
            raise ProjectAIResultTroubleshootNotFound("Investigation does not exist for this Project.") from exc
        if not session.completed_result_id:
            raise ProjectAIResultTroubleshootNotFound("Investigation has no completed result.")
        try:
            envelope = load_canonical_investigation_result(self.investigation_store_root, session.completed_result_id)
        except InvestigationStoreError as exc:
            raise ProjectAIResultTroubleshootNotFound("Investigation canonical result is unavailable.") from exc

        retained = envelope.retained_result
        stale_seconds = investigation_stale_seconds()
        desktop = build_desktop_projection(retained, stale_seconds=stale_seconds)
        glasses = build_glasses_projection(retained, stale_seconds=stale_seconds)
        return ProjectAIResult(
            result_id=session.completed_result_id,
            project_id=normalized_project_id,
            result_type=ProjectAIResultType.TROUBLESHOOT,
            summary=retained.diagnosis,
            hud_projection=ProjectAIResultHudProjection(
                headline=glasses.diagnosis_short,
                next=glasses.required_next_action_short,
                uncertainty_flag=glasses.uncertainty_flag,
            ),
            evidence_refs=list(retained.image_order),
            suggested_project_updates=False,
            troubleshoot=desktop,
        )

    # --- GENERAL_GUIDANCE: thin envelope adapter over the existing, unchanged, ephemeral /ask ---

    def create_general_guidance(self, project_id: str, question: str) -> ProjectAIResult:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        answer = self.qa_service.ask(project_id=normalized_project_id, question=question)
        return self._compose_general_guidance(normalized_project_id, answer)

    def _compose_general_guidance(self, project_id: str, answer: ProjectGroundedAnswerResponse) -> ProjectAIResult:
        evidence_refs = [item.source_id for item in answer.references if item.source_id]
        return ProjectAIResult(
            result_id=str(uuid4()),
            project_id=project_id,
            result_type=ProjectAIResultType.GENERAL_GUIDANCE,
            summary=answer.answer,
            hud_projection=ProjectAIResultHudProjection(
                headline=_truncate(answer.answer, _MAX_GENERAL_GUIDANCE_HEADLINE_LENGTH),
                next=None,
                uncertainty_flag=answer.insufficient_context,
            ),
            evidence_refs=evidence_refs,
            suggested_project_updates=False,
            ephemeral=True,
            general_guidance=answer,
        )
