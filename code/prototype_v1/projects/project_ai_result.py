from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol
from uuid import uuid4

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional import fallback
    OpenAI = None  # type: ignore[assignment]

from investigations import (
    InvestigationEvidenceStore,
    InvestigationEvidenceStoreError,
    InvestigationSessionAnalysisRejected,
    InvestigationSessionAnalyzeResponse,
    InvestigationSessionNotFound,
    InvestigationSessionStatus,
    InvestigationSessionStore,
    InvestigationSessionStoreError,
    InvestigationStoreError,
    build_desktop_projection,
    build_glasses_projection,
    investigation_stale_seconds,
    load_canonical_investigation_result,
)

from .models import (
    ProjectAIResult,
    ProjectAIResultHudProjection,
    ProjectAIResultRoutingDecision,
    ProjectAIResultType,
    ProjectAIRoutingRequest,
    ProjectContextPack,
    ProjectExploreGroupView,
    ProjectExploreRequest,
    ProjectGroundedAnswerResponse,
    ProjectTroubleshootTextResult,
)
from .project_context_retriever import ProjectContextRetriever
from .project_explore import ProjectExploreService
from .project_qa import ProjectQuestionAnsweringService
from .project_store import ProjectStore
from .project_troubleshoot import ProjectTextTroubleshootService


_MAX_GENERAL_GUIDANCE_HEADLINE_LENGTH = 280


class ProjectAIResultError(RuntimeError):
    pass


class ProjectAIResultTroubleshootNotFound(ProjectAIResultError):
    pass


class ProjectAIResultExplorePlanNotFound(ProjectAIResultError):
    pass


class ProjectAIResultRoutingUnavailable(ProjectAIResultError):
    """A technical Response Planner failure (provider error, timeout, invalid/unparseable
    structured output). ADR-060: this is always a retryable routing failure and must never be
    silently converted into a GENERAL_GUIDANCE result - the caller (api.py) maps this to a 503,
    the same "unavailable, retry" convention ProjectExploreProviderUnavailable already uses."""

    pass


@dataclass(frozen=True)
class ProjectAIResultClarificationNeeded:
    """A legitimate (non-error) Planner outcome: genuinely insufficient signal to pick a family
    confidently, so the Planner asks one concise clarifying question instead of guessing. Mirrors
    the existing ProjectExploreExecutionResponse.information_request pattern (a None/absent
    ProjectAIResult is not itself an error there either) rather than introducing a new error type
    for something that is not a failure."""

    project_id: str
    clarifying_question: str
    brief_reason: str


def _truncate(text: str, max_length: int) -> str:
    text = str(text or "").strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


_RESPONSE_ROUTER_DEFAULT_MODEL = "gpt-4.1-mini"
_RESPONSE_ROUTER_DEFAULT_TIMEOUT_SECONDS = 20.0
_RESPONSE_ROUTER_ALLOWED_FAMILIES = {"TROUBLESHOOT", "EXPLORE_PLAN", "GENERAL_GUIDANCE"}


class ProjectResponseRoutingProvider(Protocol):
    def classify(self, context_payload: dict[str, object]) -> ProjectAIResultRoutingDecision:
        ...


class OpenAIProjectResponseRoutingProvider:
    """ADR-060 Response Planner classifier: one small structured-output call selecting exactly
    one of TROUBLESHOOT | EXPLORE_PLAN | GENERAL_GUIDANCE (or asking one clarifying question),
    reusing the same pattern OpenAIProjectReasoningProvider (project_qa.py) already establishes -
    temperature 0, JSON-object response format, one call, no chain-of-thought. The prompt payload
    is deliberately small (bounded Context Pack fields only - see
    ProjectAIResultPlanner._build_routing_context_payload) and contains no raw image bytes."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = _RESPONSE_ROUTER_DEFAULT_TIMEOUT_SECONDS,
        client_factory=OpenAI,
    ) -> None:
        normalized_key = str(api_key or "").strip()
        if not normalized_key:
            raise ProjectAIResultRoutingUnavailable("OPENAI_API_KEY is required for response routing.")

        normalized_model = str(model or "").strip() or _RESPONSE_ROUTER_DEFAULT_MODEL
        self._api_key = normalized_key
        self._model = normalized_model
        self._timeout_seconds = float(timeout_seconds)
        self._client_factory = client_factory
        # Cost/latency observability only (ADR-060) - never read by classify()'s own logic.
        self.last_usage: dict[str, int] | None = None

    def classify(self, context_payload: dict[str, object]) -> ProjectAIResultRoutingDecision:
        if self._client_factory is None:
            raise ProjectAIResultRoutingUnavailable("OpenAI SDK is unavailable.")

        prompt_payload = {
            "context_pack": context_payload,
            "allowed_response_families": sorted(_RESPONSE_ROUTER_ALLOWED_FAMILIES),
            "instructions": {
                "task": (
                    "Choose exactly one response_family for this Project request, using only the "
                    "supplied context_pack and current_request."
                ),
                "TROUBLESHOOT": "The request describes something malfunctioning, broken, or behaving unexpectedly that needs a diagnosis.",
                "EXPLORE_PLAN": "The request asks for design/planning ideas, options, or directions to choose between.",
                "GENERAL_GUIDANCE": "The request is a general question, follow-up, or explanation that does not need a diagnosis or a set of options - e.g. asking why a prior AI suggestion was made.",
                # ADR-060 hardening: the original single "ambiguous between families" framing let
                # the model treat a genuinely empty request (no named problem, evidence, decision,
                # or question) as if it still had to pick one of the three - it would guess
                # (unstably, across repeated identical calls) rather than ask. This names a SECOND,
                # distinct trigger for needs_clarification that does not depend on family ambiguity
                # at all, and says explicitly not to let "one of the three must be chosen" force a
                # guess.
                "when_to_clarify": (
                    "Set needs_clarification=true (and omit response_family) in EITHER of two "
                    "distinct cases: (1) the request is genuinely ambiguous between two or more "
                    "families even after reading context_pack, or (2) current_request itself is too "
                    "generic to establish ANY meaningful response need - it names no problem, no "
                    "evidence, no decision, and no specific question, even if the Project itself is "
                    "well described. A short generic phrase such as 'help me', 'what should I do?', "
                    "'what about this?', or 'can you help me with this?' is NOT enough signal by "
                    "itself, no matter how much Project context exists - do not select a family "
                    "merely because one of the three must otherwise be chosen. When genuinely "
                    "unsure, ask exactly one concise clarifying_question rather than guessing."
                ),
                "when_not_to_clarify": (
                    "Do not ask for clarification when current_request already gives enough signal - "
                    "a described problem/symptom (-> TROUBLESHOOT), a request for options/directions/"
                    "ideas (-> EXPLORE_PLAN), or a specific question about existing state/reasoning/"
                    "status (-> GENERAL_GUIDANCE). Clarification should be the rare exception, not a "
                    "default, and must never be used merely to hedge."
                ),
                "grounding": "Do not invent Project state. Use only context_pack and current_request.",
                "examples": [
                    {
                        "current_request": "Can you help me with this?",
                        "why_this_answer": "Names no problem, evidence, decision, or specific question - generic willingness to help is not enough signal, even inside a well-described Project.",
                        "expected_decision": {
                            "response_family": None, "needs_clarification": True,
                            "clarifying_question": "What would you like help with - a specific problem, some design ideas, or a question about where things stand?",
                        },
                    },
                    {
                        "current_request": "What would you change about this room? Give me some ideas.",
                        "why_this_answer": "Specifically asks for design/planning options - enough signal to route directly.",
                        "expected_decision": {"response_family": "EXPLORE_PLAN", "needs_clarification": False},
                    },
                ],
            },
            "response_schema": {
                "response_family": "TROUBLESHOOT|EXPLORE_PLAN|GENERAL_GUIDANCE|null",
                "confidence": "number between 0 and 1",
                "brief_reason": "short string",
                "needs_clarification": "boolean",
                "clarifying_question": "string|null",
            },
        }

        client = self._client_factory(api_key=self._api_key)
        response = client.chat.completions.create(
            model=self._model,
            temperature=0.0,
            response_format={"type": "json_object"},
            timeout=self._timeout_seconds,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a routing classifier for a project assistant. You choose exactly one "
                        "response contract for the application to execute - you never answer the "
                        "request yourself and never invent Project state. Return only valid JSON "
                        "matching response_schema."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)},
            ],
        )

        usage = getattr(response, "usage", None)
        if usage is not None:
            self.last_usage = {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(usage, "total_tokens", 0) or 0,
            }

        content = str(response.choices[0].message.content or "").strip()
        json_payload = _extract_routing_json_object(content)
        if not json_payload:
            raise ProjectAIResultRoutingUnavailable("Response routing provider did not return a JSON object.")

        try:
            parsed = json.loads(json_payload)
        except (TypeError, ValueError) as exc:
            raise ProjectAIResultRoutingUnavailable("Response routing provider returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise ProjectAIResultRoutingUnavailable("Response routing provider response must be a JSON object.")

        try:
            return ProjectAIResultRoutingDecision.model_validate(parsed)
        except Exception as exc:  # ValidationError and any other malformed-shape failure
            raise ProjectAIResultRoutingUnavailable("Response routing provider returned an invalid routing decision.") from exc


def _extract_routing_json_object(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    if raw.startswith("{") and raw.endswith("}"):
        return raw
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start : end + 1]
    return ""


def load_project_response_router_model_name() -> str:
    configured = os.environ.get("PROJECT_RESPONSE_ROUTER_OPENAI_MODEL") or _RESPONSE_ROUTER_DEFAULT_MODEL
    return str(configured or "").strip() or _RESPONSE_ROUTER_DEFAULT_MODEL


def load_project_response_router_timeout_seconds() -> float:
    raw = str(os.environ.get("PROJECT_RESPONSE_ROUTER_OPENAI_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return _RESPONSE_ROUTER_DEFAULT_TIMEOUT_SECONDS
    try:
        parsed = float(raw)
    except ValueError:
        return _RESPONSE_ROUTER_DEFAULT_TIMEOUT_SECONDS
    return parsed if parsed > 0 else _RESPONSE_ROUTER_DEFAULT_TIMEOUT_SECONDS


class ProjectAIResultPlanner:
    """The Response Planner: ProjectAIResult composition over the three approved response
    families, dispatched either explicitly (create_explore_plan/read_troubleshoot/
    create_general_guidance - unchanged, still used by the existing explicit /ai-results/*
    endpoints) or via bounded intent inference (route() - ADR-060).

    Owns no Project Memory, retrieval, or trust of its own. ADR-060 amends ADR-059's original
    dispatch rule ("explicit service dispatch, not autonomous intent classification" -
    docs/PROJECT_INTERACTION_FOUNDATION.md's Project Guidance Engine Boundary): physical Room
    Redesign acceptance testing showed that rule forced the user to understand internal response
    families. route() infers the family from a bounded Context Pack and the current request
    instead - it still only SELECTS one of the same three application-approved contracts below
    and never executes a mutation itself.
    """

    def __init__(self, *, project_store: ProjectStore, explore_service: ProjectExploreService,
                 qa_service: ProjectQuestionAnsweringService, session_store: InvestigationSessionStore,
                 investigation_store_root: Path,
                 context_retriever: ProjectContextRetriever | None = None,
                 evidence_store: InvestigationEvidenceStore | None = None,
                 routing_provider: ProjectResponseRoutingProvider | None = None,
                 analyze_session_fn: Callable[[str, int | None], InvestigationSessionAnalyzeResponse] | None = None,
                 text_troubleshoot_service: ProjectTextTroubleshootService | None = None):
        self.project_store = project_store
        self.explore_service = explore_service
        self.qa_service = qa_service
        self.session_store = session_store
        # route()-only dependencies. Optional here so existing direct construction/tests that only
        # exercise the explicit create_explore_plan/read_troubleshoot/create_general_guidance
        # methods are unaffected; route() itself raises clearly if any is missing.
        self.context_retriever = context_retriever
        self.evidence_store = evidence_store
        self.routing_provider = routing_provider
        self.analyze_session_fn = analyze_session_fn
        # ADR-060 Path B (route()'s TROUBLESHOOT dispatch only, when no usable Investigation
        # evidence exists yet) - see _dispatch_troubleshoot/_dispatch_text_only_troubleshoot.
        self.text_troubleshoot_service = text_troubleshoot_service
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

    # --- ADR-060: bounded intent inference (one unified entrypoint) ---

    def route(
        self, project_id: str, request: ProjectAIRoutingRequest
    ) -> ProjectAIResult | ProjectAIResultClarificationNeeded:
        """Infers exactly one of TROUBLESHOOT | EXPLORE_PLAN | GENERAL_GUIDANCE from a bounded
        Context Pack + the current request, then dispatches to the SAME existing family methods
        explicit dispatch already uses (create_explore_plan's service call, read_troubleshoot,
        create_general_guidance) - see class doc. Never mutates canonical Project state itself;
        the routing decision that drives dispatch is discarded once this method returns.

        Raises ProjectAIResultRoutingUnavailable on any technical classifier failure - ADR-060
        requires this be a retryable failure, never a silent GENERAL_GUIDANCE substitution.
        Returns ProjectAIResultClarificationNeeded (not an error) when the Planner is genuinely
        uncertain and asks one concise clarifying question instead of guessing.
        """
        if self.context_retriever is None or self.routing_provider is None:
            raise ProjectAIResultRoutingUnavailable("Response routing is not configured.")

        normalized_project_id = self.project_store.validate_project_id(project_id)

        session_snapshot: dict[str, object] | None = None
        if request.investigation_session_id is not None:
            # Raises InvestigationSessionNotFound (mapped to 404 by the caller) for a session
            # belonging to a different Project - the same existing project-scoped loader every
            # other Investigation-reading endpoint already uses, so isolation is inherited, not
            # reimplemented.
            session = self.session_store.load_session_for_project(normalized_project_id, request.investigation_session_id)
            evidence_count = 0
            if self.evidence_store is not None:
                try:
                    evidence_count = len(self.evidence_store.list_evidence_for_analysis(session.session_id))
                except InvestigationEvidenceStoreError:
                    evidence_count = 0
            session_snapshot = {
                "status": session.status.value,
                "evidence_count": evidence_count,
            }

        context_pack = self.context_retriever.get_context(normalized_project_id)
        context_payload = self._build_routing_context_payload(
            context_pack=context_pack,
            user_request=request.user_request,
            session_snapshot=session_snapshot,
        )
        decision = self.routing_provider.classify(context_payload)

        if decision.needs_clarification:
            return ProjectAIResultClarificationNeeded(
                project_id=normalized_project_id,
                clarifying_question=decision.clarifying_question or "Could you share a bit more detail?",
                brief_reason=decision.brief_reason,
            )

        if decision.response_family == ProjectAIResultType.EXPLORE_PLAN:
            explore_request = ProjectExploreRequest(
                user_intent=request.user_request,
                input_refs=[],
                idempotency_key=request.idempotency_key,
            )
            response = self.explore_service.execute(normalized_project_id, explore_request)
            if response.option_set is None:
                info = response.information_request
                return ProjectAIResultClarificationNeeded(
                    project_id=normalized_project_id,
                    clarifying_question=(info.prompt if info else "More information is needed to suggest design/planning options."),
                    brief_reason="EXPLORE_PLAN needs more information before options can be produced.",
                )
            return self._compose_explore_plan(normalized_project_id, response.option_set)

        if decision.response_family == ProjectAIResultType.GENERAL_GUIDANCE:
            return self.create_general_guidance(normalized_project_id, request.user_request)

        if decision.response_family == ProjectAIResultType.TROUBLESHOOT:
            return self._dispatch_troubleshoot(normalized_project_id, request)

        raise ProjectAIResultRoutingUnavailable("Response routing selected an unsupported response family.")

    def _dispatch_troubleshoot(self, project_id: str, request: ProjectAIRoutingRequest) -> ProjectAIResult:
        """ADR-060 (2026-09-04 architecture decision): TROUBLESHOOT is a response family, not a
        synonym for "has an Investigation session." Investigation's evidence-rich session/
        evidence/orchestrator pipeline (Path A) is the specialized path used when usable evidence
        already exists; it is never a prerequisite for TROUBLESHOOT itself. When it does not exist
        yet, Path B answers from Project context + the current request alone - never by
        fabricating evidence, never by creating a session solely to satisfy this dispatch, and
        never by silently switching to a different response family.

        Contract correction (2026-09-04): an explicitly supplied investigation_session_id is
        NEVER silently ignored in favor of Path B, regardless of that session's state. The caller
        named this exact session; its actual state governs the response - success through Path A,
        or the SAME existing state/conflict error analyze_session_fn already raises for
        ANALYZING/FINALIZING/CANCELLED/not-yet-collecting sessions. Path B is reachable only when
        no investigation_session_id was supplied at all.
        """
        if request.investigation_session_id is not None:
            # Isolation inherited from the existing project-scoped loader, same as elsewhere.
            # Always dispatches through Path A - see contract correction above.
            session = self.session_store.load_session_for_project(project_id, request.investigation_session_id)
            if self.analyze_session_fn is None:
                raise ProjectAIResultRoutingUnavailable("TROUBLESHOOT dispatch is not configured.")
            self.analyze_session_fn(session.session_id, None)
            return self.read_troubleshoot(project_id, session.session_id)

        # No explicit session: reuse a usable evidence-backed COLLECTING session for this Project
        # if one exists; otherwise run Path B. Never creates a session merely to satisfy this
        # dispatch.
        candidates = self.session_store.list_sessions_for_project(project_id)
        reusable = next(
            (item for item in candidates if item.status == InvestigationSessionStatus.COLLECTING and self._session_has_usable_evidence(item)),
            None,
        )
        if reusable is not None:
            # Path A: evidence-backed - reuse the existing, unchanged diagnostic pipeline exactly
            # as the explicit /investigation-sessions/{id}/analyze route already does.
            if self.analyze_session_fn is None:
                raise ProjectAIResultRoutingUnavailable("TROUBLESHOOT dispatch is not configured.")
            self.analyze_session_fn(reusable.session_id, None)
            return self.read_troubleshoot(project_id, reusable.session_id)

        # Path B: no usable Investigation evidence/session for this request - text/context-
        # grounded TROUBLESHOOT. No session was created and no evidence was fabricated to reach
        # this point.
        return self._dispatch_text_only_troubleshoot(project_id, request)

    def _session_has_usable_evidence(self, session) -> bool:
        """True exactly when Path A (the existing Investigation pipeline) can meaningfully run:
        the session already has a completed result, or is COLLECTING with at least one evidence
        record carrying explanation text (the same underlying signal
        api._normalize_session_explanation checks - this is a cheap existence predicate for
        ROUTE SELECTION only, not a reimplementation of that function; the real check still runs
        inside analyze_session_fn on the Path A branch)."""
        if session.completed_result_id:
            return True
        if session.status != InvestigationSessionStatus.COLLECTING:
            return False
        if self.evidence_store is None:
            return False
        try:
            records = self.evidence_store.list_evidence_for_analysis(session.session_id)
        except InvestigationEvidenceStoreError:
            return False
        return any(str(getattr(item, "normalized_text", "") or "").strip() for item in records)

    def _dispatch_text_only_troubleshoot(self, project_id: str, request: ProjectAIRoutingRequest) -> ProjectAIResult:
        if self.text_troubleshoot_service is None:
            raise ProjectAIResultRoutingUnavailable("Text-only TROUBLESHOOT execution is not configured.")

        response = self.text_troubleshoot_service.diagnose(project_id=project_id, user_request=request.user_request)
        return ProjectAIResult(
            result_id=str(uuid4()),
            project_id=project_id,
            result_type=ProjectAIResultType.TROUBLESHOOT,
            summary=response.diagnosis,
            hud_projection=ProjectAIResultHudProjection(
                headline=_truncate(response.diagnosis, _MAX_GENERAL_GUIDANCE_HEADLINE_LENGTH),
                next=_truncate(response.recommended_next_action, _MAX_GENERAL_GUIDANCE_HEADLINE_LENGTH),
                uncertainty_flag=response.uncertain,
            ),
            evidence_refs=[],
            suggested_project_updates=False,
            # Nothing durable was created (no session, no Activity) - this can never be
            # reconstructed after a reload, so it is ephemeral exactly like GENERAL_GUIDANCE,
            # and remains inferred/unconfirmed with no trust-decision mechanism of its own.
            ephemeral=True,
            troubleshoot_text=ProjectTroubleshootTextResult(
                diagnosis=response.diagnosis,
                recommended_next_action=response.recommended_next_action,
                uncertain=response.uncertain,
            ),
        )

    def _build_routing_context_payload(
        self,
        *,
        context_pack: ProjectContextPack,
        user_request: str,
        session_snapshot: dict[str, object] | None,
    ) -> dict[str, object]:
        """Deliberately small (ADR-060): Project identity/goal, current checkpoint, a bounded
        window of recent activities/investigations the existing ProjectContextRetriever already
        assembles, evidence presence/count for the supplied session (if any), and the current
        request text only. No full Project dump, no chat-transcript store, no raw image bytes."""
        return {
            "project": {
                "project_id": context_pack.project_id,
                "project_name": context_pack.project_name,
                "project_goal": context_pack.project_goal,
            },
            "checkpoint": {
                "current_objective": context_pack.current_objective,
                "blockers": context_pack.blockers,
                "next_action": context_pack.next_action,
            },
            "recent_activities": [
                {
                    "activity_type": item.activity_type.value,
                    "summary": item.summary,
                    "occurred_at_utc": item.occurred_at_utc.isoformat(),
                }
                for item in context_pack.recent_activities[:10]
            ],
            "recent_investigations": [
                {
                    "status": item.status,
                    "diagnosis": item.diagnosis,
                    "required_next_action": item.required_next_action,
                    "completed_at_utc": item.completed_at_utc.isoformat(),
                }
                for item in context_pack.recent_investigations[:5]
            ],
            "current_investigation_session": session_snapshot,
            "current_request": user_request,
        }
