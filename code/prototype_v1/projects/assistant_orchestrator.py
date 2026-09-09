from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid5

from investigations import (
    MAX_IMAGE_UPLOAD_BYTES,
    InvestigationEvidenceStore,
    InvestigationEvidenceStoreError,
    InvestigationEvidenceType,
    InvestigationEvidenceValidationStatus,
    InvestigationSessionAnalysisRejected,
    InvestigationSessionStore,
    InvestigationSessionStoreError,
)

from .assistant_provider import (
    AssistantCapabilityIntent,
    AssistantContextTurn,
    AssistantImageInput,
    AssistantProvider,
    AssistantProviderError,
    AssistantRequest,
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
from .checkpoint_proposal_store import CheckpointProposalStoreError
from .project_ai_result import ProjectAIResultPlanner, ProjectAIResultRoutingUnavailable
from .project_explore import (
    ProjectExploreError,
    ProjectExploreImageEvidence,
    ProjectExploreService,
)
from .project_store import ProjectStore, ProjectStoreError
from .project_troubleshoot import ProjectTextTroubleshootError
from .models import ProjectAIRoutingRequest, ProjectExploreRequest
from .visual_artifacts import (
    VisualArtifactCreateRequest,
    VisualArtifactError,
    VisualArtifactService,
    VisualArtifactStatus,
)


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


class AssistantOrchestrator:
    def __init__(self, *, project_store: ProjectStore, conversation_store: ProjectConversationStore,
                 context_retriever: ProjectContextRetriever, provider: AssistantProvider,
                 session_store: InvestigationSessionStore | None = None,
                 evidence_store: InvestigationEvidenceStore | None = None,
                 explore_service: ProjectExploreService | None = None,
                 visual_artifact_service: VisualArtifactService | None = None,
                 ai_result_planner: ProjectAIResultPlanner | None = None):
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
                image_inputs = self._resolve_image_inputs(normalized_project_id, request.evidence_refs)
                user_turn = existing_user
                assistant_turn = existing_assistant
            else:
                image_inputs = self._resolve_image_inputs(normalized_project_id, request.evidence_refs)
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
            provider_request = AssistantRequest(
                user_text=request.text,
                project_context=self._project_context_payload(context_pack),
                prior_turns=prior_turns,
                images=image_inputs,
                allowed_capability_intents=allowed_intents,
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

            completed = assistant_turn.model_copy(update={
                "status": ConversationTurnStatus.COMPLETED,
                "content_parts": content_parts,
                "completed_at_utc": datetime.now(timezone.utc),
                "provider_provenance": ConversationProviderProvenance(
                    provider=result.provider, model=result.model, request_id=result.request_id),
                "failure_category": None,
                "failure_message": None,
            })
            self._replace_turn(conversation, completed)
            return ConversationSendResponse(
                conversation_id=conversation.conversation_id,
                project_id=normalized_project_id,
                turns=[user_turn, completed],
                reconstructed=False,
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
    ) -> tuple[AssistantImageInput, ...]:
        if not references:
            return ()
        if self.session_store is None or self.evidence_store is None:
            raise ConversationEvidenceUnavailable("Conversation Evidence resolution is unavailable.")
        resolved: list[AssistantImageInput] = []
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
                resolved.append(AssistantImageInput(
                    evidence_id=evidence.evidence_id,
                    media_type=evidence.mime_type,
                    image_bytes=payload_path.read_bytes(),
                ))
        except (InvestigationSessionStoreError, InvestigationEvidenceStoreError, OSError) as exc:
            raise ConversationEvidenceUnavailable(
                "Evidence does not exist or is unavailable for this Project.") from exc
        return tuple(resolved)
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
