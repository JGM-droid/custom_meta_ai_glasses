from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid5

from investigations import (
    MAX_IMAGE_UPLOAD_BYTES,
    InvestigationEvidence,
    InvestigationEvidenceStore,
    InvestigationEvidenceStoreError,
    InvestigationEvidenceType,
    InvestigationEvidenceValidationStatus,
    InvestigationSessionAnalysisRejected,
    InvestigationSessionStore,
    InvestigationSessionStoreError,
    InvestigationStoreError,
)

from .assistant_provider import (
    AssistantCapabilityIntent,
    AssistantContextTurn,
    AssistantImageInput,
    AssistantProvider,
    AssistantProviderError,
    AssistantRequest,
    AssistantReportedProgress,
    ReportedProgressOutcome,
)
from .conversation_store import ConversationIdempotencyConflict, ProjectConversationStore
from .project_context_retriever import ProjectContextRetriever
from .project_conversation import (
    ConversationExploreReferencePart,
    ConversationInvestigationReferencePart,
    ConversationProviderProvenance,
    ConversationEvidenceReferencePart,
    ConversationReadResponse,
    ConversationRole,
    ConversationSendRequest,
    ConversationSendResponse,
    ConversationTextPart,
    ConversationTurn,
    ConversationTurnStatus,
    ConversationVisualArtifactReferencePart,
    ProjectConversation,
)
from .activity_store import ProjectActivityStoreError
from .checkpoint_proposal_store import (
    CheckpointProposalRevisionConflict,
    CheckpointProposalStateError,
    CheckpointProposalStoreError,
)
from .investigation_trust import ProjectInvestigationTrustError, ProjectInvestigationTrustService
from .project_ai_result import ProjectAIResultPlanner, ProjectAIResultRoutingUnavailable
from .project_explore import (
    ProjectExploreError,
    ProjectExploreImageEvidence,
    ProjectExploreService,
)
from .project_store import ProjectStore, ProjectStoreError
from .project_troubleshoot import ProjectTextTroubleshootError
from .memory_extraction import ProjectMemoryExtractionError, ProjectMemoryExtractionService
from .memory_store import ProjectMemoryStore, ProjectMemoryStoreError
from .memory_retrieval import (
    MemoryRetrievalResult,
    ProjectMemoryRetrievalService,
    known_subject_hints,
    retrieve_memory_context,
)
from .project_current_state import ProjectCurrentStateService
from .visual_evidence import (
    VisualEvidenceContinuityError,
    VisualEvidenceContinuityService,
    _EVIDENCE_EXISTS_BUT_UNMATCHED_NOTICE,
    _NO_DESCRIPTION_PLACEHOLDER,
    is_visual_continuity_candidate,
    select_candidates,
)
from .models import (
    CheckpointProposalPatch,
    CheckpointProposalStatus,
    ProjectActivitySourceType,
    ProjectAIRoutingRequest,
    ProjectExploreRequest,
    ProjectMemoryCandidate,
    ProjectTrustDecisionRequest,
    ProjectTrustDecisionType,
)
from .visual_artifacts import (
    VisualArtifactCreateRequest,
    VisualArtifactError,
    VisualArtifactService,
    VisualArtifactStatus,
)


# Conversational Project Progression, Slice 1 (ADR-042/ADR-043): a proposed checkpoint patch may be
# auto-applied through the existing CheckpointProposal machinery, in the same request, only when it
# touches exclusively these narrative/working-state fields - never a "significant Project change"
# field (completed_summary, stopped_at, current_objective). This is documented as Slice 1
# IMPLEMENTATION POLICY, not a permanent product definition of "low consequence" - see
# docs/PROJECT_MEMORY_ARCHITECTURE.md. Investigation-originated CONTINUE proposals only ever
# populate next_action today, so this is currently the only field this policy needs to recognize;
# it is written as a real, general checkless allowlist so it stays correct if that ever changes.
_LOW_CONSEQUENCE_CHECKPOINT_FIELDS = frozenset({"current_work", "next_action", "discoveries_summary"})

logger = logging.getLogger(__name__)


MAX_PRIOR_CONVERSATION_TURNS = 8


class ConversationEvidenceUnavailable(RuntimeError):
    pass


class VisualArtifactBridgeError(VisualArtifactError):
    """Phase 3B: bridge-level resolution failure - no recent Explore result in this conversation to
    visualize, or the requested ordinal does not exist in it. Distinct from VisualArtifactService's
    own store/provider failures, but deliberately subclasses the same base VisualArtifactError so
    the conversation endpoint handles both with one categorized HTTP response, exactly like
    ProjectExploreError's single base-type handling for the Explore bridge."""


class ConversationInvestigationError(RuntimeError):
    """Phase 3C: uniform wrapper for any failure in the conversational Investigation bridge - the
    underlying session-based analyze pipeline, evidence-explanation backfill, or Path B text-only
    troubleshoot can each raise their own distinct exception type (InvestigationSessionAnalysisRejected,
    InvestigationEvidenceStoreError/InvestigationSessionStoreError, ProjectTextTroubleshootError,
    ProjectAIResultRoutingUnavailable) - this wraps all of them so the conversation endpoint maps
    exactly one exception type to one categorized HTTP response, exactly like
    VisualArtifactBridgeError/ProjectExploreError's own single-base-type handling."""


@dataclass(frozen=True)
class _PendingVisualDescriptionTarget:
    """Stage 3: one freshly-attached image this turn that has no durable description yet - gathered
    while resolving this turn's images (inside the project lock, cheap - no extra I/O beyond what
    _resolve_image_inputs already does), described AFTER the lock releases (a real, potentially
    slow provider call), exactly like Stage 2's shadow memory extraction."""

    session_id: str
    evidence_id: str
    media_type: str
    image_bytes: bytes


@dataclass(frozen=True)
class _VisualContinuityResolution:
    """Stage 3: the outcome of deterministic-then-AI visual Evidence retrieval for a text-only turn
    (no fresh evidence_refs). All fields default to "not applicable" - the common case for an
    ordinary non-visual turn, which must cost nothing beyond the cheap keyword gate."""

    image_override: AssistantImageInput | None = None
    visual_context: str | None = None
    tier: str | None = None
    evidence_id: str | None = None


class AssistantOrchestrator:
    def __init__(self, *, project_store: ProjectStore, conversation_store: ProjectConversationStore,
                 context_retriever: ProjectContextRetriever, provider: AssistantProvider,
                 session_store: InvestigationSessionStore | None = None,
                 evidence_store: InvestigationEvidenceStore | None = None,
                 explore_service: ProjectExploreService | None = None,
                 visual_artifact_service: VisualArtifactService | None = None,
                 ai_result_planner: ProjectAIResultPlanner | None = None,
                 investigation_trust_service: ProjectInvestigationTrustService | None = None,
                 memory_extraction_service: "ProjectMemoryExtractionService | None" = None,
                 memory_store: "ProjectMemoryStore | None" = None,
                 visual_evidence_service: "VisualEvidenceContinuityService | None" = None,
                 memory_retrieval_service: "ProjectMemoryRetrievalService | None" = None,
                 current_state_service: "ProjectCurrentStateService | None" = None):
        self.project_store = project_store
        self.conversation_store = conversation_store
        self.context_retriever = context_retriever
        self.provider = provider
        self.session_store = session_store
        self.evidence_store = evidence_store
        # Phase 3A/3B/3C: reuses the existing Explore/VisualArtifact/Investigation capabilities
        # as-is - never a second, parallel implementation of any of them. None (the default) means
        # that capability is never advertised to the provider and its tool-call can never be
        # produced - see _allowed_capability_intents.
        self.explore_service = explore_service
        self.visual_artifact_service = visual_artifact_service
        # Phase 3C: the SAME ProjectAIResultPlanner route()'s own TROUBLESHOOT dispatch uses -
        # reused via its dispatch_troubleshoot_for_conversation method, never a second Investigation
        # dispatch mechanism, and never route()'s own LLM intent-classification call (the
        # conversation's native tool-calling already decided this is a troubleshooting request).
        self.ai_result_planner = ai_result_planner
        # Conversational Project Progression, Slice 1: the SAME ProjectInvestigationTrustService the
        # legacy CONTINUE/DISAGREE/MORE EVIDENCE UI already calls - never a second trust-decision or
        # Checkpoint-mutation implementation. None (the default) means the progress-report tool is
        # never advertised and this bridge is a complete no-op - see
        # _find_eligible_investigation_target.
        self.investigation_trust_service = investigation_trust_service
        # Stage 2 (Integrated Persistent Memory Shadow Slice, ADR-063/064): writes structured
        # Project Memory after every eligible turn. Stage 4 (Real Conversation Integration) now
        # also READS it back via memory_retrieval_service/current_state_service below - extraction
        # itself is unchanged. None (the default) means no extraction at all, exactly like every
        # other optional capability here degrading to "not advertised/not run".
        self.memory_extraction_service = memory_extraction_service
        self.memory_store = memory_store
        # Stage 3 (Visual Evidence Continuity): also degrades to a complete no-op when None - no
        # description generation, no Tier 1/2 retrieval, existing image-attachment behavior
        # (evidence_refs on the current turn) is completely unaffected either way.
        self.visual_evidence_service = visual_evidence_service
        # Stage 4 (Real Conversation Integration): question-aware retrieval over the SAME canonical
        # Structured Project Memory (memory_store) - no second store. None means no AI-assisted
        # subject/continuation disambiguation call (deterministic subject/continuation matching
        # still works without it); the orchestrator degrades to no structured memory context at all
        # when memory_store itself is None. current_state_service defaults to a fresh instance with
        # no salience client (bounded deterministic fallback only) when not supplied - it is a pure,
        # stateless derivation service, never a second canonical state store.
        self.memory_retrieval_service = memory_retrieval_service
        self.current_state_service = current_state_service or ProjectCurrentStateService()

    def get_or_create(self, project_id: str) -> ConversationReadResponse:
        conversation = self.conversation_store.create_or_load(project_id)
        return self._read_response(conversation)

    def read(self, project_id: str) -> ConversationReadResponse:
        conversation = self.conversation_store.create_or_load(project_id)
        return self._read_response(conversation)

    def send(self, project_id: str, request: ConversationSendRequest) -> ConversationSendResponse:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        self.project_store.load_project(normalized_project_id)
        fingerprint_payload = {
            "text": request.text,
            "evidence_refs": [item.model_dump(mode="json") for item in request.evidence_refs],
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        with self.project_store._get_project_lock(normalized_project_id):
            conversation = self.conversation_store.create_or_load(normalized_project_id)
            user_id = str(uuid5(UUID(conversation.conversation_id), f"{request.idempotency_key}:user"))
            assistant_id = str(uuid5(UUID(conversation.conversation_id), f"{request.idempotency_key}:assistant"))
            existing_user = next((item for item in conversation.turns if item.turn_id == user_id), None)
            existing_assistant = next((item for item in conversation.turns if item.turn_id == assistant_id), None)
            if existing_user is not None:
                if existing_user.request_fingerprint != fingerprint:
                    raise ConversationIdempotencyConflict(
                        "idempotency_key was already used with different message content.")
                if existing_assistant is None:
                    raise ConversationIdempotencyConflict("Conversation exchange is incomplete.")
                if existing_assistant.status == ConversationTurnStatus.COMPLETED:
                    return ConversationSendResponse(
                        conversation_id=conversation.conversation_id,
                        project_id=normalized_project_id,
                        turns=[existing_user, existing_assistant],
                        reconstructed=True,
                    )
                image_inputs, pending_visual_descriptions = self._resolve_image_inputs(
                    normalized_project_id, request.evidence_refs)
                user_turn = existing_user
                assistant_turn = existing_assistant
            else:
                image_inputs, pending_visual_descriptions = self._resolve_image_inputs(
                    normalized_project_id, request.evidence_refs)
                now = datetime.now(timezone.utc)
                user_turn = ConversationTurn(
                    turn_id=user_id,
                    conversation_id=conversation.conversation_id,
                    project_id=normalized_project_id,
                    sequence_number=len(conversation.turns) + 1,
                    role=ConversationRole.USER,
                    status=ConversationTurnStatus.COMPLETED,
                    content_parts=[ConversationTextPart(text=request.text), *request.evidence_refs],
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=fingerprint,
                    created_at_utc=now,
                    completed_at_utc=now,
                )
                assistant_turn = ConversationTurn(
                    turn_id=assistant_id,
                    conversation_id=conversation.conversation_id,
                    project_id=normalized_project_id,
                    sequence_number=len(conversation.turns) + 2,
                    role=ConversationRole.ASSISTANT,
                    status=ConversationTurnStatus.PROCESSING,
                    content_parts=[ConversationTextPart(text="Response pending.")],
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=fingerprint,
                    created_at_utc=now,
                )
                conversation = conversation.model_copy(update={
                    "turns": [*conversation.turns, user_turn, assistant_turn],
                    "updated_at_utc": now,
                })
                self.conversation_store.save(conversation)

            prior_turns = self._bounded_prior_turns(conversation, before_sequence=user_turn.sequence_number)
            context_pack = self.context_retriever.get_context_for_question(
                normalized_project_id, request.text)
            allowed_intents = self._allowed_capability_intents()
            progress_target = self._find_eligible_investigation_target(
                normalized_project_id, conversation, before_sequence=user_turn.sequence_number)
            # Stage 3 (Visual Evidence Continuity): only ever considered when this turn has no
            # fresh evidence_refs of its own - a freshly-attached image is already handled by
            # image_inputs above and needs no retrieval. Never overrides a fresh attachment.
            visual_resolution = (
                self._resolve_visual_continuity(normalized_project_id, request.text)
                if not request.evidence_refs else _VisualContinuityResolution()
            )
            if visual_resolution.image_override is not None:
                image_inputs = (visual_resolution.image_override,)
            # Stage 4 (Real Conversation Integration): question-aware retrieval over the SAME
            # canonical Structured Project Memory Stage 2 already writes - never a second store,
            # never persisted here. Merged into the existing free-form project_context payload
            # dict, so no AssistantRequest/provider schema change was needed (unlike Stage 3's
            # visual_context, which answers a different question - "is there an image" - this is
            # plain additional bounded text).
            memory_result = self._resolve_memory_retrieval(
                normalized_project_id, request.text, conversation, prior_turns)
            project_context_payload = self._project_context_payload(context_pack)
            if memory_result.context_text:
                project_context_payload["structured_project_memory"] = memory_result.context_text
            provider_request = AssistantRequest(
                user_text=request.text,
                project_context=project_context_payload,
                prior_turns=prior_turns,
                images=image_inputs,
                allowed_capability_intents=allowed_intents,
                investigation_progress_eligible=progress_target is not None,
                visual_context=visual_resolution.visual_context,
            )
            try:
                result = self.provider.respond(provider_request)
            except AssistantProviderError as exc:
                self._fail_assistant_turn(
                    conversation, assistant_turn,
                    failure_category="provider_failure",
                    failure_message=str(exc),
                    user_facing_text="The assistant could not respond. Retry this message.",
                )
                raise

            if (result.capability_intent != AssistantCapabilityIntent.NONE
                    and result.capability_intent not in allowed_intents):
                # Provider-boundary contract violation: a conforming AssistantProvider must never
                # return a capability_intent that was not in allowed_capability_intents, which this
                # orchestrator only ever advertises when the matching service is configured (see
                # _allowed_capability_intents). Treated exactly like any other provider-contract
                # failure - never a silently empty completed turn, never a capability execution,
                # never a Project Memory mutation.
                exc = AssistantProviderError(
                    f"Assistant provider requested {result.capability_intent.value}, but that "
                    "capability is not available for this Project.")
                self._fail_assistant_turn(
                    conversation, assistant_turn,
                    failure_category="provider_failure",
                    failure_message=str(exc),
                    user_facing_text="The assistant could not respond. Retry this message.",
                )
                raise exc

            if result.capability_intent == AssistantCapabilityIntent.EXPLORE:
                try:
                    content_parts = self._run_explore_bridge(
                        normalized_project_id, request, image_inputs)
                except ProjectExploreError as exc:
                    self._fail_assistant_turn(
                        conversation, assistant_turn,
                        failure_category="explore_failure",
                        failure_message=str(exc),
                        user_facing_text="Could not generate ideas right now. Retry this message.",
                    )
                    raise
            elif result.capability_intent == AssistantCapabilityIntent.VISUALIZE_OPTION:
                try:
                    content_parts = self._run_visualize_bridge(
                        normalized_project_id, conversation, user_turn, request, result.visualize_option_ordinal)
                except VisualArtifactError as exc:
                    self._fail_assistant_turn(
                        conversation, assistant_turn,
                        failure_category="visualize_failure",
                        failure_message=str(exc),
                        user_facing_text="Could not create that visualization right now. Retry this message.",
                    )
                    raise
            elif result.capability_intent == AssistantCapabilityIntent.INVESTIGATE:
                try:
                    content_parts = self._run_investigate_bridge(normalized_project_id, request)
                except ConversationInvestigationError as exc:
                    self._fail_assistant_turn(
                        conversation, assistant_turn,
                        failure_category="investigate_failure",
                        failure_message=str(exc),
                        user_facing_text="Could not investigate this right now. Retry this message.",
                    )
                    raise
            else:
                content_parts = [ConversationTextPart(text=result.text)]

            # Conversational Project Progression, Slice 1: reported_progress is orthogonal to
            # capability_intent (see AssistantResponse), so this runs regardless of which branch
            # above executed - a turn may both confirm/correct the prior outstanding Investigation
            # claim AND independently trigger EXPLORE/VISUALIZE_OPTION/INVESTIGATE/NONE in the same
            # message, without a second model call: the SAME provider response already carried both
            # signals (OpenAI tool-calling already supports more than one tool_call per message).
            # progress_target was resolved BEFORE the branch above ran, from conversation state as
            # of the START of this turn - so it can never be the brand-new Investigation/Explore
            # result THIS turn's own primary capability just produced; the two are always distinct
            # targets. Still requires a real eligible target (never fires on an unrelated message,
            # silence, or topic change - see _find_eligible_investigation_target) and still fails
            # the whole turn honestly (retry-safe, like every other bridge failure) rather than
            # silently dropping either the primary capability's result or the progress update.
            if result.reported_progress is not None and progress_target is not None:
                try:
                    self._apply_reported_investigation_progress(
                        normalized_project_id, progress_target, result.reported_progress, request.text)
                except ConversationInvestigationError as exc:
                    self._fail_assistant_turn(
                        conversation, assistant_turn,
                        failure_category="investigate_failure",
                        failure_message=str(exc),
                        user_facing_text="Could not record that update right now. Retry this message.",
                    )
                    raise

            completed = assistant_turn.model_copy(update={
                "status": ConversationTurnStatus.COMPLETED,
                "content_parts": content_parts,
                "completed_at_utc": datetime.now(timezone.utc),
                "provider_provenance": ConversationProviderProvenance(
                    provider=result.provider, model=result.model, request_id=result.request_id,
                    visual_retrieval_tier=visual_resolution.tier,
                    visual_evidence_id=visual_resolution.evidence_id,
                    memory_retrieval_intent=memory_result.intent,
                    memory_retrieval_subject=memory_result.subject),
                "failure_category": None,
                "failure_message": None,
            })
            self._replace_turn(conversation, completed)
            response = ConversationSendResponse(
                conversation_id=conversation.conversation_id,
                project_id=normalized_project_id,
                turns=[user_turn, completed],
                reconstructed=False,
            )

        # Stage 2 (Integrated Persistent Memory Shadow Slice): deliberately OUTSIDE the project
        # lock above - this makes a real, potentially slow provider call, and the shadow store has
        # its own independent per-project lock (ProjectMemoryStore._get_project_lock), so it must
        # never hold the conversation lock while it runs. Fires after the real turn is already
        # durably saved; a shadow-path failure must never destroy or delay the real, already-
        # completed conversation response (see docs/PROJECT_MEMORY_ARCHITECTURE.md's Stage 2
        # shadow-mode boundary). Only the ORIGINAL user turn (not a reconstructed/idempotent
        # replay) is extracted from, so a retried duplicate send never double-writes memory.
        if self.memory_extraction_service is not None and self.memory_store is not None:
            self._run_shadow_memory_extraction(normalized_project_id, user_turn)

        # Stage 3 (Visual Evidence Continuity): same placement rationale as Stage 2 above - a real,
        # potentially slow provider call per pending image, run only after the real turn is already
        # durably saved and the project lock released. A description-generation failure must never
        # destroy the real conversation turn (see docs/PROJECT_MEMORY_ARCHITECTURE.md's Stage 3
        # failure-behavior requirement) - the original Evidence is always preserved regardless.
        if self.visual_evidence_service is not None and pending_visual_descriptions:
            self._run_shadow_visual_description_generation(pending_visual_descriptions)

        return response

    def _run_shadow_memory_extraction(self, project_id: str, user_turn: ConversationTurn) -> None:
        try:
            text = next(
                (p.text for p in user_turn.content_parts if isinstance(p, ConversationTextPart)), "")
            # Stage 5 repair (subject-identity stabilization): a bounded shortlist of this
            # Project's existing canonical subjects, so a naturally-worded update ("only got
            # halfway done") can be matched to the SAME real-world item as an earlier statement
            # ("I finished painting the wall") instead of silently forking a second, disconnected
            # identity - dogfooding found this happening even without adversarial phrasing.
            known_subjects = known_subject_hints(self.memory_store.list_records(project_id))
            candidates = self.memory_extraction_service.extract(text, known_subjects)
            for candidate in candidates:
                self.memory_store.write_candidate(
                    project_id, candidate,
                    source_type=ProjectActivitySourceType.USER,
                    source_turn_id=user_turn.turn_id,
                    occurred_at_utc=user_turn.created_at_utc,
                )
        except (ProjectMemoryExtractionError, ProjectMemoryStoreError) as exc:
            # Shadow-only: observable via logs, never raised into the real turn/response.
            logger.warning("Shadow memory extraction failed for project %s: %s", project_id, exc)

    def _run_shadow_visual_description_generation(
        self, targets: tuple[_PendingVisualDescriptionTarget, ...],
    ) -> None:
        for target in targets:
            try:
                result = self.visual_evidence_service.describe(
                    image_bytes=target.image_bytes, media_type=target.media_type)
                self.evidence_store.set_visual_description(
                    session_id=target.session_id, evidence_id=target.evidence_id,
                    description=result.description, scope=result.scope,
                    generated_at_utc=datetime.now(timezone.utc),
                )
            except (VisualEvidenceContinuityError, InvestigationEvidenceStoreError,
                    InvestigationSessionStoreError, ValueError) as exc:
                # Shadow-only: the original Evidence is untouched either way; observable via logs,
                # never raised into the real turn/response.
                logger.warning(
                    "Shadow visual description generation failed for evidence %s: %s",
                    target.evidence_id, exc)

    def _resolve_visual_continuity(self, project_id: str, question_text: str) -> _VisualContinuityResolution:
        """Deterministic-then-AI Tier 1/Tier 2 retrieval for a text-only turn. Returns a fully
        "not applicable" resolution (the cheap common case) whenever the service is unavailable, the
        cheap keyword gate does not match, no described Evidence candidates exist, or the AI
        selection call abstains/fails - never guesses, never raises into the real turn."""
        if (self.visual_evidence_service is None or self.session_store is None
                or self.evidence_store is None):
            return _VisualContinuityResolution()
        if not is_visual_continuity_candidate(question_text):
            return _VisualContinuityResolution()
        try:
            all_evidence = self._gather_project_evidence(project_id)
            candidates = select_candidates(all_evidence, question_text=question_text)
            if not candidates:
                return _VisualContinuityResolution()
            selection = self.visual_evidence_service.select(question_text=question_text, candidates=candidates)
        except (InvestigationSessionStoreError, InvestigationEvidenceStoreError) as exc:
            logger.warning("Visual evidence candidate gathering failed for project %s: %s", project_id, exc)
            return _VisualContinuityResolution()
        if selection is None:
            # Stage 5 repair: candidates was non-empty, so Evidence genuinely EXISTS for this
            # Project - the selection call just could not confidently match it to this specific
            # question. Stay honest about existence rather than silent (which previously let the
            # model conclude, and state, that no photo was ever provided at all - found during
            # Stage 5 dogfooding against a real photo that predates Stage 3's description
            # pipeline).
            return _VisualContinuityResolution(
                visual_context=_EVIDENCE_EXISTS_BUT_UNMATCHED_NOTICE, tier="not_found", evidence_id=None)

        if selection.tier == "original_required":
            try:
                evidence, payload_path = self.evidence_store.load_evidence_content(
                    session_id=selection.session_id, evidence_id=selection.evidence_id)
                size_bytes = payload_path.stat().st_size
                if 0 < size_bytes <= MAX_IMAGE_UPLOAD_BYTES:
                    return _VisualContinuityResolution(
                        image_override=AssistantImageInput(
                            evidence_id=evidence.evidence_id, media_type=evidence.mime_type,
                            image_bytes=payload_path.read_bytes(),
                        ),
                        tier="original_required", evidence_id=evidence.evidence_id,
                    )
            except (InvestigationSessionStoreError, InvestigationEvidenceStoreError, OSError):
                pass
            # Original pixels were judged necessary but are unavailable - fall back to an explicit
            # unavailability note, per the required failure behavior: state that the detail cannot
            # be verified rather than silently answering as if Tier 1 were sufficient or
            # fabricating the visual detail. A selected candidate with no real stored description
            # (only the placeholder) gets its own clearer wording, since claiming "only this stored
            # description is available" would be misleading when there was never a real one.
            note = (
                "This Project has Evidence indicating a photo exists, but neither a stored "
                "description nor the original image could be retrieved right now - say you cannot "
                "currently verify the image's contents, rather than guessing or denying a photo "
                "exists."
                if selection.description == _NO_DESCRIPTION_PLACEHOLDER else
                f"{selection.description} (Note: the original image for this Evidence could not "
                "be retrieved right now; only this stored description is available. If asked "
                "about a visual detail this description does not cover, say it cannot be "
                "verified from the stored description - do not guess.)"
            )
            return _VisualContinuityResolution(
                visual_context=note, tier="description_sufficient", evidence_id=selection.evidence_id,
            )
        return _VisualContinuityResolution(
            visual_context=selection.description,
            tier="description_sufficient", evidence_id=selection.evidence_id,
        )

    def _gather_project_evidence(self, project_id: str) -> list[InvestigationEvidence]:
        all_evidence: list[InvestigationEvidence] = []
        for session in self.session_store.list_sessions_for_project(project_id):
            all_evidence.extend(self.evidence_store.list_evidence_for_analysis(session.session_id))
        return all_evidence

    def _resolve_memory_retrieval(
        self, project_id: str, question_text: str, conversation: ProjectConversation,
        prior_turns: tuple[AssistantContextTurn, ...],
    ) -> MemoryRetrievalResult:
        """Stage 4: deterministic-first, question-aware retrieval over Structured Project Memory.
        Degrades to a fully "nothing relevant" result (never raises into the real turn) whenever no
        memory_store is configured, the store read fails, or nothing about the question resolves."""
        if self.memory_store is None:
            return MemoryRetrievalResult()
        try:
            records = self.memory_store.list_records(project_id)
        except ProjectMemoryStoreError as exc:
            logger.warning("Structured Project Memory retrieval failed for project %s: %s", project_id, exc)
            return MemoryRetrievalResult()

        prior_turns_text = "\n".join(f"{item.role}: {item.text}" for item in prior_turns[-3:])

        def _turn_text_lookup(turn_id: str) -> str | None:
            for item in conversation.turns:
                if item.turn_id == turn_id:
                    return next(
                        (part.text for part in item.content_parts if isinstance(part, ConversationTextPart)),
                        None,
                    )
            return None

        return retrieve_memory_context(
            project_id=project_id, records=records, question_text=question_text,
            prior_turns_text=prior_turns_text, current_state_service=self.current_state_service,
            selection_service=self.memory_retrieval_service, turn_text_lookup=_turn_text_lookup,
        )

    def _allowed_capability_intents(self) -> frozenset[AssistantCapabilityIntent]:
        intents: set[AssistantCapabilityIntent] = set()
        if self.explore_service is not None:
            intents.add(AssistantCapabilityIntent.EXPLORE)
        if self.visual_artifact_service is not None:
            intents.add(AssistantCapabilityIntent.VISUALIZE_OPTION)
        if self.ai_result_planner is not None:
            intents.add(AssistantCapabilityIntent.INVESTIGATE)
        return frozenset(intents)

    def _fail_assistant_turn(
        self,
        conversation: ProjectConversation,
        assistant_turn: ConversationTurn,
        *,
        failure_category: str,
        failure_message: str,
        user_facing_text: str,
    ) -> None:
        """Shared FAILED-turn persistence for every send() failure path (provider failure,
        provider-contract violation, Explore failure) - the caller always re-raises immediately
        after this returns, so this method's only job is to leave the conversation in the correct,
        already-established failure shape."""
        failed = assistant_turn.model_copy(update={
            "status": ConversationTurnStatus.FAILED,
            "content_parts": [ConversationTextPart(text=user_facing_text)],
            "completed_at_utc": datetime.now(timezone.utc),
            "provider_provenance": None,
            "failure_category": failure_category,
            "failure_message": failure_message,
        })
        self._replace_turn(conversation, failed)

    def _run_explore_bridge(
        self,
        project_id: str,
        request: ConversationSendRequest,
        image_inputs: tuple[AssistantImageInput, ...],
    ) -> list[ConversationTextPart | ConversationExploreReferencePart]:
        """Phase 3A bridge: reuses the existing Explore capability exactly as its own direct API
        caller does - same request type, same idempotent execute(), same INFERRED-only Activity
        writes (no canonical Project Memory mutation from generation alone). user_intent is always
        the conversation's own verbatim text, never a model-restated phrase, so a retry with the
        same idempotency_key produces the same ProjectExploreRequest fingerprint and reconstructs
        instead of conflicting or duplicating. image_inputs is the SAME evidence this method's
        caller already resolved for the plain conversation path - never a second evidence lookup.
        """
        explore_request = ProjectExploreRequest(
            user_intent=request.text,
            input_refs=[],
            idempotency_key=request.idempotency_key,
        )
        explore_image_evidence = tuple(
            ProjectExploreImageEvidence(
                evidence_id=item.evidence_id, media_type=item.media_type, image_bytes=item.image_bytes)
            for item in image_inputs
        )
        response = self.explore_service.execute(project_id, explore_request, image_evidence=explore_image_evidence)
        if response.option_set is None:
            info = response.information_request
            prompt = info.prompt if info else "Could you say a bit more about what you'd like ideas for?"
            return [ConversationTextPart(text=prompt)]
        return [
            ConversationTextPart(text=self._format_explore_reply(response.option_set)),
            ConversationExploreReferencePart(interaction_id=response.interaction_id),
        ]

    @staticmethod
    def _format_explore_reply(group) -> str:
        lines: list[str] = []
        if group.summary:
            lines.append(group.summary)
            lines.append("")
        for option in group.options:
            title = option.idea.summary
            blurb = f" — {option.summary}" if option.summary else ""
            lines.append(f"{option.ordinal}. {title}{blurb}")
        if group.recommended_ordinal and group.recommendation_reason:
            lines.append("")
            lines.append(f"Recommended: option {group.recommended_ordinal} — {group.recommendation_reason}")
        return "\n".join(lines).strip()

    def _run_visualize_bridge(
        self,
        project_id: str,
        conversation: ProjectConversation,
        user_turn: ConversationTurn,
        request: ConversationSendRequest,
        ordinal: int | None,
    ) -> list[ConversationTextPart | ConversationVisualArtifactReferencePart]:
        """Phase 3B bridge: reuses the existing VisualArtifact capability exactly as its own direct
        API caller does (prepare() then generate(), synchronously within this same request - a
        conversation turn already always resolves to a final COMPLETED/FAILED state within one
        request/response, so this does not introduce a new PROCESSING-then-poll shape). The option
        ordinal always comes from the model's own typed tool-call argument, never parsed from
        assistant prose. The Explore interaction it belongs to is always the most recently
        referenced one already in THIS conversation's own history, resolved from the application's
        own typed ConversationExploreReferencePart - never re-derived from prose, and never
        requiring the user to repeat the interaction id, the photo, or the original description.
        """
        if ordinal is None:
            raise VisualArtifactBridgeError("I couldn't tell which option to visualize.")
        reference = self._most_recent_explore_reference(conversation, before_sequence=user_turn.sequence_number)
        if reference is None:
            raise VisualArtifactBridgeError("There are no recent ideas in this conversation to visualize yet.")
        projection = self.explore_service.read_projection(project_id)
        group = next((item for item in projection.option_sets if item.interaction_id == reference.interaction_id), None)
        if group is None:
            raise VisualArtifactBridgeError("Those ideas are no longer available.")
        option = next((item for item in group.options if item.ordinal == ordinal), None)
        if option is None:
            raise VisualArtifactBridgeError(f"There's no option {ordinal} in that result.")
        create_request = VisualArtifactCreateRequest(idempotency_key=request.idempotency_key)
        artifact = self.visual_artifact_service.prepare(
            project_id, reference.interaction_id, option.idea.activity_id, create_request)
        if artifact.status != VisualArtifactStatus.READY:
            artifact = self.visual_artifact_service.generate(project_id, artifact.artifact_id)
        return [
            ConversationTextPart(text=f"Here's a visualization of option {ordinal}."),
            ConversationVisualArtifactReferencePart(
                project_ai_result_id=reference.interaction_id,
                option_id=option.idea.activity_id,
                artifact_id=artifact.artifact_id,
            ),
        ]

    @staticmethod
    def _most_recent_explore_reference(
        conversation: ProjectConversation, *, before_sequence: int,
    ) -> ConversationExploreReferencePart | None:
        candidates = [item for item in conversation.turns if item.sequence_number < before_sequence]
        for turn in reversed(candidates):
            for part in turn.content_parts:
                if isinstance(part, ConversationExploreReferencePart):
                    return part
        return None

    def _run_investigate_bridge(
        self, project_id: str, request: ConversationSendRequest,
    ) -> list[ConversationTextPart | ConversationInvestigationReferencePart]:
        """Phase 3C bridge: reuses the existing session-based Investigation pipeline exactly as
        ProjectAIResultPlanner.route()'s own TROUBLESHOOT dispatch does, via
        dispatch_troubleshoot_for_conversation - which only ever calls the session-based
        analyze_session_fn (_execute_investigation_session_analysis) for Path A and
        ProjectTextTroubleshootService for Path B. This bridge is structurally unable to reach the
        SEPARATE legacy multipart POST /investigations/analyze pipeline (investigations/service.py)
        - that pipeline is never imported, referenced, or callable from anywhere in this class.

        Evidence precedence (deterministic, never guesses across unrelated sessions):
          (A) Evidence already attached to THIS message takes explicit precedence - its own
              Investigation session is targeted directly, exactly as if the user had picked that
              session explicitly. Conversation-originated Evidence carries no explanation text (the
              explanation lives in the conversation message itself), so this backfills that one
              field on the SAME existing evidence record before dispatch - never a new session,
              evidence record, or association (see _ensure_evidence_explanation).
          (B) Otherwise, the SAME existing reusable-COLLECTING-session detection
              dispatch_troubleshoot_for_conversation already performs internally.
          (C) Otherwise, the SAME existing text-only fallback (Path B).
        """
        investigation_session_id: str | None = None
        if request.evidence_refs:
            reference = request.evidence_refs[0]
            investigation_session_id = reference.container_id
            self._ensure_evidence_explanation(reference, request.text)
        try:
            routing_request = ProjectAIRoutingRequest(
                user_request=request.text,
                investigation_session_id=investigation_session_id,
                idempotency_key=request.idempotency_key,
            )
            result = self.ai_result_planner.dispatch_troubleshoot_for_conversation(project_id, routing_request)
        except (InvestigationSessionAnalysisRejected, InvestigationEvidenceStoreError,
                InvestigationSessionStoreError, ProjectTextTroubleshootError,
                ProjectAIResultRoutingUnavailable) as exc:
            raise ConversationInvestigationError(str(exc)) from exc

        text = result.summary
        if result.hud_projection.next:
            text = f"{text}\n\nNext: {result.hud_projection.next}"
        if result.ephemeral or result.troubleshoot is None:
            # Path B: nothing durable was created - no reference to attach, exactly like
            # GENERAL_GUIDANCE's own ephemeral outputs.
            return [ConversationTextPart(text=text)]
        return [
            ConversationTextPart(text=text),
            ConversationInvestigationReferencePart(investigation_session_id=result.troubleshoot.session_id),
        ]

    def _find_eligible_investigation_target(
        self, project_id: str, conversation: ProjectConversation, *, before_sequence: int,
    ) -> str | None:
        """Conversational Project Progression, Slice 1: the ONLY thing that decides whether
        report_investigation_progress is even offered to the model this turn - a real target must
        already exist in THIS conversation's own persisted state, never a model judgment call. The
        target is the most recently INVESTIGATION_REFERENCE-d session in this conversation, and only
        while its trust state is still "awaiting_decision" (fresh - no decision yet) or
        "working_hypothesis" (a prior CONTINUE, still correctable per ADR-049's DISAGREE semantics -
        "Don't mark that complete" after an earlier confirmation is exactly this case). An
        already-DISAGREE'd or MORE-EVIDENCE'd target is out of Slice 1's bounded scope and is
        deliberately not re-offered here. If the most recent reference is not eligible, this does
        NOT fall back to an older one - "eligible target" means the most recent one, or none."""
        if self.investigation_trust_service is None:
            return None
        candidates = [item for item in conversation.turns if item.sequence_number < before_sequence]
        for turn in reversed(candidates):
            for part in turn.content_parts:
                if isinstance(part, ConversationInvestigationReferencePart):
                    try:
                        state = self.investigation_trust_service.get_state(
                            project_id, part.investigation_session_id)
                    except (ProjectInvestigationTrustError, InvestigationStoreError,
                            InvestigationSessionStoreError):
                        return None
                    if state.status in ("awaiting_decision", "working_hypothesis"):
                        return part.investigation_session_id
                    return None
        return None

    @staticmethod
    def _is_low_consequence_checkpoint_patch(patch: CheckpointProposalPatch) -> bool:
        return set(patch.to_update_fields()) <= _LOW_CONSEQUENCE_CHECKPOINT_FIELDS

    def _apply_reported_investigation_progress(
        self,
        project_id: str,
        investigation_session_id: str,
        reported: AssistantReportedProgress,
        user_text: str,
    ) -> None:
        """Conversational Project Progression, Slice 1 CONFIRMED path: record the outcome and, only
        for a low-consequence patch (Slice 1 implementation policy - see
        _LOW_CONSEQUENCE_CHECKPOINT_FIELDS), apply the resulting CheckpointProposal through the
        EXISTING apply mechanism in this same request - never a new mutation path. A
        significant-change patch is left PENDING, exactly like the legacy CONTINUE button today.

        CORRECTED path: never advances the rejected claim. Any PENDING proposal tied to the prior
        decision is rejected via the existing reject mechanism; an already-APPLIED prior proposal has
        no revert (forward correction only, not undo - see architecture review) and is left as durable
        history, consistent with never erasing historical Activities.

        Both paths reuse ProjectInvestigationTrustService.decide() verbatim - the exact same
        Activity/provenance/idempotency behavior the legacy CONTINUE/DISAGREE UI already relies on,
        so a retried conversational turn (same idempotency_key) converges exactly like a retried
        button click already does, and no second Activity/Proposal-creation implementation exists.
        """
        try:
            prior_state = self.investigation_trust_service.get_state(project_id, investigation_session_id)
        except (ProjectInvestigationTrustError, InvestigationStoreError,
                InvestigationSessionStoreError) as exc:
            raise ConversationInvestigationError(str(exc)) from exc

        decision_type = (
            ProjectTrustDecisionType.CONTINUE
            if reported.outcome == ReportedProgressOutcome.CONFIRMED
            else ProjectTrustDecisionType.DISAGREE
        )
        correction = user_text.strip()[:1000] or None
        try:
            response = self.investigation_trust_service.decide(
                project_id, investigation_session_id,
                ProjectTrustDecisionRequest(decision=decision_type, correction=correction),
            )
        except (ProjectInvestigationTrustError, InvestigationStoreError, InvestigationSessionStoreError,
                CheckpointProposalStoreError, ProjectActivityStoreError) as exc:
            raise ConversationInvestigationError(str(exc)) from exc

        if decision_type == ProjectTrustDecisionType.DISAGREE:
            if (prior_state.checkpoint_proposal_id is not None
                    and prior_state.checkpoint_proposal_status == CheckpointProposalStatus.PENDING):
                try:
                    self.investigation_trust_service.proposal_store.reject_proposal(
                        project_id, prior_state.checkpoint_proposal_id)
                except CheckpointProposalStoreError:
                    pass
            return

        proposal = response.checkpoint_proposal
        if proposal is None or proposal.status != CheckpointProposalStatus.PENDING:
            return
        if not self._is_low_consequence_checkpoint_patch(proposal.proposed_checkpoint_patch):
            # Significant Project change (ADR-042/ADR-043): stays PENDING, exactly like the legacy
            # CONTINUE button today. Slice 1's assistant reply is not yet specialized to ask a
            # confirming question for this case - see architecture review, "what remains
            # intentionally unimplemented."
            return
        try:
            self.investigation_trust_service.proposal_store.apply_proposal(project_id, proposal.proposal_id)
        except (CheckpointProposalRevisionConflict, CheckpointProposalStateError):
            # Already advanced by an earlier equivalent confirmation, or a sibling proposal with
            # identical content already applied (see CheckpointProposalStore's own reconciliation) -
            # the Project already reflects this outcome, so this is a benign no-op, never a
            # user-facing failure or a duplicate state advancement.
            pass

    def _ensure_evidence_explanation(
        self, reference: ConversationEvidenceReferencePart, explanation_text: str,
    ) -> None:
        """Phase 3C: conversation-originated Evidence is uploaded with no explanation text (the
        explanation lives in the conversation message itself - see
        ProjectConversationViewModel.stageAttachment), but the existing session-based analyze
        pipeline derives its explanation strictly from evidence.normalized_text
        (_normalize_session_explanation). This backfills that ONE field on the EXACT existing
        evidence record the conversation already references - never a new evidence record, never a
        new session, never new bytes - and only when it is still blank, so any pre-existing
        explanation (e.g. from a legacy Investigation capture) is preserved untouched. Failures here
        are swallowed deliberately: the downstream analyze call will then raise its own honest,
        already-categorized error (e.g. missing_explanation) rather than this pre-step introducing a
        second, redundant failure surface for the same underlying problem."""
        if self.evidence_store is None:
            return
        try:
            record = self.evidence_store.load_evidence_for_analysis(
                session_id=reference.container_id, evidence_id=reference.resource_id)
        except (InvestigationEvidenceStoreError, InvestigationSessionStoreError):
            return
        if str(record.normalized_text or "").strip():
            return
        try:
            self.evidence_store.set_evidence_explanation(
                session_id=reference.container_id, evidence_id=reference.resource_id,
                normalized_text=explanation_text)
        except (InvestigationEvidenceStoreError, InvestigationSessionStoreError):
            pass

    def _replace_turn(self, conversation: ProjectConversation, replacement: ConversationTurn) -> None:
        now = datetime.now(timezone.utc)
        updated = conversation.model_copy(update={
            "turns": [replacement if item.turn_id == replacement.turn_id else item for item in conversation.turns],
            "updated_at_utc": now,
        })
        self.conversation_store.save(updated)

    @staticmethod
    def _read_response(conversation: ProjectConversation) -> ConversationReadResponse:
        return ConversationReadResponse(
            conversation_id=conversation.conversation_id,
            project_id=conversation.project_id,
            turns=conversation.turns,
        )

    @staticmethod
    def _bounded_prior_turns(conversation: ProjectConversation, *, before_sequence: int) -> tuple[AssistantContextTurn, ...]:
        eligible = [
            item for item in conversation.turns
            if item.sequence_number < before_sequence and item.status == ConversationTurnStatus.COMPLETED
        ]
        selected = eligible[-MAX_PRIOR_CONVERSATION_TURNS:]
        return tuple(
            AssistantContextTurn(
                role=item.role.value.lower(),
                text=next(part.text for part in item.content_parts if isinstance(part, ConversationTextPart)),
            )
            for item in selected
        )

    def _resolve_image_inputs(
        self,
        project_id: str,
        references: list[ConversationEvidenceReferencePart],
    ) -> tuple[tuple[AssistantImageInput, ...], tuple[_PendingVisualDescriptionTarget, ...]]:
        if not references:
            return (), ()
        if self.session_store is None or self.evidence_store is None:
            raise ConversationEvidenceUnavailable("Conversation Evidence resolution is unavailable.")
        resolved: list[AssistantImageInput] = []
        # Stage 3 (Visual Evidence Continuity): freshly-attached Evidence with no durable description
        # yet is flagged here (no extra I/O - `evidence` is already loaded) and described AFTER this
        # method returns and the caller's project lock releases, since description generation is a
        # real, potentially slow provider call - see AssistantOrchestrator.send().
        pending_descriptions: list[_PendingVisualDescriptionTarget] = []
        try:
            for reference in references:
                session = self.session_store.load_session_for_project(project_id, reference.container_id)
                evidence, payload_path = self.evidence_store.load_evidence_content(
                    session_id=session.session_id,
                    evidence_id=reference.resource_id,
                )
                if evidence.evidence_type != InvestigationEvidenceType.IMAGE:
                    raise ConversationEvidenceUnavailable("Only image Evidence is supported in Phase 1B.")
                if evidence.validation_status not in {
                    InvestigationEvidenceValidationStatus.ACCEPTED,
                    InvestigationEvidenceValidationStatus.DUPLICATE_ACCEPTED,
                }:
                    raise ConversationEvidenceUnavailable("Evidence is not accepted for provider use.")
                size_bytes = payload_path.stat().st_size
                if size_bytes <= 0 or size_bytes > MAX_IMAGE_UPLOAD_BYTES:
                    raise ConversationEvidenceUnavailable("Evidence image size is unavailable or out of bounds.")
                image_bytes = payload_path.read_bytes()
                resolved.append(AssistantImageInput(
                    evidence_id=evidence.evidence_id,
                    media_type=evidence.mime_type,
                    image_bytes=image_bytes,
                ))
                if not evidence.visual_description:
                    pending_descriptions.append(_PendingVisualDescriptionTarget(
                        session_id=session.session_id, evidence_id=evidence.evidence_id,
                        media_type=evidence.mime_type, image_bytes=image_bytes,
                    ))
        except (InvestigationSessionStoreError, InvestigationEvidenceStoreError, OSError) as exc:
            raise ConversationEvidenceUnavailable(
                "Evidence does not exist or is unavailable for this Project.") from exc
        return tuple(resolved), tuple(pending_descriptions)
    @staticmethod
    def _project_context_payload(pack) -> dict[str, object]:
        return {
            "project": {
                "project_id": pack.project_id,
                "name": pack.project_name,
                "goal": pack.project_goal,
                "status": pack.project_status.value,
            },
            "checkpoint": {
                "current_objective": pack.current_objective,
                "current_work": pack.checkpoint.current_work,
                "next_action": pack.next_action,
                "blockers": pack.blockers,
            },
            "retrieval": {
                "contract": pack.selection.retrieval_contract,
                "selected_categories": pack.selection.selected_categories,
                "excluded_categories": pack.selection.excluded_categories,
                "activity_limit": pack.selection.recent_activity_limit,
                "investigation_limit": pack.selection.recent_investigation_limit,
            },
            "activities": [
                {
                    "activity_id": item.activity_id,
                    "type": item.activity_type.value,
                    "confirmation_status": item.confirmation_status.value,
                    "summary": item.summary,
                    "details": item.details,
                }
                for item in pack.selected_activities
            ],
            "investigations": [
                {
                    "session_id": item.session_id,
                    "status": item.status,
                    "diagnosis": item.diagnosis,
                    "required_next_action": item.required_next_action,
                }
                for item in pack.selected_investigations
            ],
        }
