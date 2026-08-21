from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import Protocol

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional import fallback
    OpenAI = None  # type: ignore[assignment]

from .models import (
    ProjectContextQueryPack,
    ProjectGroundedAnswerReference,
    ProjectGroundedAnswerResponse,
)
from .project_context_retriever import ProjectContextRetriever

_DEFAULT_MODEL = "gpt-4.1-mini"
_DEFAULT_TIMEOUT_SECONDS = 45.0


class ProjectReasoningError(RuntimeError):
    pass


class ProjectReasoningProviderMissingApiKeyError(ProjectReasoningError):
    pass


@dataclass(frozen=True)
class ProjectReasoningRequest:
    question: str
    context_pack: ProjectContextQueryPack


@dataclass(frozen=True)
class ProjectReasoningResponse:
    answer: str
    insufficient_context: bool
    uncertainty_note: str | None
    grounding_status: str
    provider: str
    provider_model: str


class ProjectReasoningProvider(Protocol):
    def reason(self, request: ProjectReasoningRequest) -> ProjectReasoningResponse:
        ...


class OpenAIProjectReasoningProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        client_factory=OpenAI,
    ) -> None:
        normalized_key = str(api_key or "").strip()
        if not normalized_key:
            raise ProjectReasoningProviderMissingApiKeyError("OPENAI_API_KEY is required for project Q&A execution.")

        normalized_model = str(model or "").strip()
        if not normalized_model:
            normalized_model = _DEFAULT_MODEL

        self._api_key = normalized_key
        self._model = normalized_model
        self._timeout_seconds = float(timeout_seconds)
        self._client_factory = client_factory

    def reason(self, request: ProjectReasoningRequest) -> ProjectReasoningResponse:
        if self._client_factory is None:
            raise ProjectReasoningError("OpenAI SDK is unavailable.")

        context_payload = _build_reasoning_context_payload(request.context_pack)
        prompt_payload = {
            "question": request.question,
            "context_pack": context_payload,
            "instructions": {
                "grounding": "Answer using only the supplied context_pack.",
                "factuality": "Do not invent project state, events, or outcomes.",
                "evidence_status": "Distinguish confirmed/observed/reported/inferred evidence when relevant.",
                "insufficient_context": "If the context is insufficient, say so clearly.",
            },
            "response_schema": {
                "answer": "string",
                "insufficient_context": "boolean",
                "uncertainty_note": "string|null",
                "grounding_status": "grounded|insufficient_context|partial",
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
                        "You are a project assistant. Answer strictly from supplied project context. "
                        "Never fabricate events or state. "
                        "If context does not support the answer, state insufficient context. "
                        "Return only valid JSON matching response_schema."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt_payload, ensure_ascii=False),
                },
            ],
        )

        content = str(response.choices[0].message.content or "").strip()
        json_payload = _extract_json_object(content)
        if not json_payload:
            raise ProjectReasoningError("Project Q&A provider response did not contain a JSON object.")

        parsed = json.loads(json_payload)
        if not isinstance(parsed, dict):
            raise ProjectReasoningError("Project Q&A provider response must be a JSON object.")

        answer = str(parsed.get("answer") or "").strip()
        if not answer:
            raise ProjectReasoningError("Project Q&A provider response is missing answer.")

        insufficient_context = bool(parsed.get("insufficient_context", False))
        uncertainty_note_raw = parsed.get("uncertainty_note")
        uncertainty_note = str(uncertainty_note_raw).strip() if isinstance(uncertainty_note_raw, str) else None
        if uncertainty_note == "":
            uncertainty_note = None

        grounding_status = str(parsed.get("grounding_status") or "").strip().lower()
        if grounding_status not in {"grounded", "insufficient_context", "partial"}:
            grounding_status = "insufficient_context" if insufficient_context else "grounded"

        return ProjectReasoningResponse(
            answer=answer,
            insufficient_context=insufficient_context,
            uncertainty_note=uncertainty_note,
            grounding_status=grounding_status,
            provider="openai",
            provider_model=self._model,
        )


class ProjectQuestionAnsweringService:
    def __init__(self, *, context_retriever: ProjectContextRetriever, reasoning_provider: ProjectReasoningProvider) -> None:
        self._context_retriever = context_retriever
        self._reasoning_provider = reasoning_provider

    def ask(self, *, project_id: str, question: str) -> ProjectGroundedAnswerResponse:
        query_pack = self._context_retriever.get_context_for_question(project_id, question)
        reasoning_request = ProjectReasoningRequest(question=question, context_pack=query_pack)
        reasoning_response = self._reasoning_provider.reason(reasoning_request)

        return ProjectGroundedAnswerResponse(
            project_id=query_pack.project_id,
            project_name=query_pack.project_name,
            question=query_pack.question,
            question_class=query_pack.selection.detected_question_class,
            answer=reasoning_response.answer,
            grounding_status=reasoning_response.grounding_status,
            insufficient_context=reasoning_response.insufficient_context,
            uncertainty_note=reasoning_response.uncertainty_note,
            fallback_used=query_pack.selection.fallback_used,
            selected_context_summary=_build_selected_context_summary(query_pack),
            references=_build_references(query_pack),
            provider=reasoning_response.provider,
            provider_model=reasoning_response.provider_model,
            model_call_count=1,
        )


def load_project_qa_model_name() -> str:
    configured = (
        os.environ.get("PROJECT_QA_OPENAI_MODEL")
        or os.environ.get("INVESTIGATION_OPENAI_MODEL")
        or os.environ.get("OPENAI_VISION_MODEL")
        or _DEFAULT_MODEL
    )
    model = str(configured or "").strip()
    return model or _DEFAULT_MODEL


def load_project_qa_timeout_seconds() -> float:
    raw = str(os.environ.get("PROJECT_QA_OPENAI_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return _DEFAULT_TIMEOUT_SECONDS
    try:
        parsed = float(raw)
    except ValueError:
        return _DEFAULT_TIMEOUT_SECONDS
    if parsed <= 0:
        return _DEFAULT_TIMEOUT_SECONDS
    return parsed


def _extract_json_object(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\\s*```$", "", raw)

    if raw.startswith("{") and raw.endswith("}"):
        return raw

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start : end + 1]
    return ""


def _build_reasoning_context_payload(query_pack: ProjectContextQueryPack) -> dict[str, object]:
    return {
        "project": {
            "project_id": query_pack.project_id,
            "project_name": query_pack.project_name,
            "project_goal": query_pack.project_goal,
            "project_status": query_pack.project_status.value,
        },
        "checkpoint": {
            "current_objective": query_pack.current_objective,
            "blockers": query_pack.blockers,
            "next_action": query_pack.next_action,
            "completed_summary": query_pack.checkpoint.completed_summary,
            "discoveries_summary": query_pack.checkpoint.discoveries_summary,
            "current_work": query_pack.checkpoint.current_work,
        },
        "selection": {
            "question_class": query_pack.selection.detected_question_class,
            "selected_categories": query_pack.selection.selected_categories,
            "excluded_categories": query_pack.selection.excluded_categories,
            "fallback_used": query_pack.selection.fallback_used,
            "fallback_reason": query_pack.selection.fallback_reason,
            "matched_terms": query_pack.selection.matched_terms,
        },
        "selected_activities": [
            {
                "activity_id": item.activity_id,
                "activity_type": item.activity_type.value,
                "source_type": item.source_type.value,
                "confirmation_status": item.confirmation_status.value,
                "summary": item.summary,
                "details": item.details,
                "occurred_at_utc": item.occurred_at_utc.isoformat(),
            }
            for item in query_pack.selected_activities
        ],
        "selected_investigations": [
            {
                "session_id": item.session_id,
                "result_id": item.result_id,
                "status": item.status,
                "diagnosis": item.diagnosis,
                "required_next_action": item.required_next_action,
                "completed_at_utc": item.completed_at_utc.isoformat(),
            }
            for item in query_pack.selected_investigations
        ],
    }


def _build_selected_context_summary(query_pack: ProjectContextQueryPack) -> list[str]:
    return [
        f"question_class={query_pack.selection.detected_question_class}",
        f"selected_categories={','.join(query_pack.selection.selected_categories) if query_pack.selection.selected_categories else 'none'}",
        f"excluded_categories={','.join(query_pack.selection.excluded_categories) if query_pack.selection.excluded_categories else 'none'}",
        f"fallback_used={'yes' if query_pack.selection.fallback_used else 'no'}",
        f"selected_activities={len(query_pack.selected_activities)}",
        f"selected_investigations={len(query_pack.selected_investigations)}",
    ]


def _build_references(query_pack: ProjectContextQueryPack) -> list[ProjectGroundedAnswerReference]:
    references: list[ProjectGroundedAnswerReference] = []

    if query_pack.current_objective:
        references.append(
            ProjectGroundedAnswerReference(
                source_kind="checkpoint",
                source_id=None,
                summary=f"Current objective: {query_pack.current_objective}",
                evidence_status="reported",
            )
        )
    if query_pack.blockers:
        references.append(
            ProjectGroundedAnswerReference(
                source_kind="checkpoint",
                source_id=None,
                summary=f"Blockers: {query_pack.blockers}",
                evidence_status="reported",
            )
        )
    if query_pack.next_action:
        references.append(
            ProjectGroundedAnswerReference(
                source_kind="checkpoint",
                source_id=None,
                summary=f"Next action: {query_pack.next_action}",
                evidence_status="reported",
            )
        )

    for item in query_pack.selected_activities[:4]:
        detail = f" {item.details}" if item.details else ""
        references.append(
            ProjectGroundedAnswerReference(
                source_kind="activity",
                source_id=item.activity_id,
                summary=f"{item.summary}{detail}".strip(),
                evidence_status=item.confirmation_status.value,
            )
        )

    for item in query_pack.selected_investigations[:3]:
        references.append(
            ProjectGroundedAnswerReference(
                source_kind="investigation",
                source_id=item.session_id,
                summary=f"Diagnosis: {item.diagnosis} Action: {item.required_next_action}",
                evidence_status=item.status,
            )
        )

    return references
