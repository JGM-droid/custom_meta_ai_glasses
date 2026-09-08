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
    InvestigationSessionStore,
    InvestigationSessionStoreError,
)

from .assistant_provider import (
    AssistantContextTurn,
    AssistantImageInput,
    AssistantProvider,
    AssistantProviderError,
    AssistantRequest,
)
from .conversation_store import ConversationIdempotencyConflict, ProjectConversationStore
from .project_context_retriever import ProjectContextRetriever
from .project_conversation import (
    ConversationProviderProvenance,
    ConversationEvidenceReferencePart,
    ConversationReadResponse,
    ConversationRole,
    ConversationSendRequest,
    ConversationSendResponse,
    ConversationTextPart,
    ConversationTurn,
    ConversationTurnStatus,
    ProjectConversation,
)
from .project_store import ProjectStore


MAX_PRIOR_CONVERSATION_TURNS = 8


class ConversationEvidenceUnavailable(RuntimeError):
    pass


class AssistantOrchestrator:
    def __init__(self, *, project_store: ProjectStore, conversation_store: ProjectConversationStore,
                 context_retriever: ProjectContextRetriever, provider: AssistantProvider,
                 session_store: InvestigationSessionStore | None = None,
                 evidence_store: InvestigationEvidenceStore | None = None):
        self.project_store = project_store
        self.conversation_store = conversation_store
        self.context_retriever = context_retriever
        self.provider = provider
        self.session_store = session_store
        self.evidence_store = evidence_store

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
            provider_request = AssistantRequest(
                user_text=request.text,
                project_context=self._project_context_payload(context_pack),
                prior_turns=prior_turns,
                images=image_inputs,
            )
            try:
                result = self.provider.respond(provider_request)
            except AssistantProviderError as exc:
                failed = assistant_turn.model_copy(update={
                    "status": ConversationTurnStatus.FAILED,
                    "content_parts": [ConversationTextPart(text="The assistant could not respond. Retry this message.")],
                    "completed_at_utc": datetime.now(timezone.utc),
                    "provider_provenance": None,
                    "failure_category": "provider_failure",
                    "failure_message": str(exc),
                })
                self._replace_turn(conversation, failed)
                raise

            completed = assistant_turn.model_copy(update={
                "status": ConversationTurnStatus.COMPLETED,
                "content_parts": [ConversationTextPart(text=result.text)],
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
