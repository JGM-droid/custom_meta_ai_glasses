from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Protocol


class AssistantProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssistantContextTurn:
    role: str
    text: str


@dataclass(frozen=True)
class AssistantImageInput:
    evidence_id: str
    media_type: str
    image_bytes: bytes


@dataclass(frozen=True)
class AssistantRequest:
    user_text: str
    project_context: dict[str, object]
    prior_turns: tuple[AssistantContextTurn, ...]
    images: tuple[AssistantImageInput, ...] = ()
    # Phase 3A: only true when the caller has a real Explore capability wired in (see
    # AssistantOrchestrator._create_assistant_orchestrator's explore_service). The provider must
    # never advertise a tool the orchestrator cannot actually fulfill.
    allow_explore_intent: bool = False


@dataclass(frozen=True)
class AssistantResponse:
    text: str
    provider: str
    model: str
    request_id: str | None = None
    # Phase 3A: true when the model itself judged (via the SAME chat.completions call, native
    # OpenAI tool-calling - never a second classification call and never keyword matching) that the
    # user is asking for creative options/ideas rather than an ordinary question. The tool carries
    # no arguments - the orchestrator always uses the conversation's own verbatim user_text as the
    # Explore intent, never a model-restated paraphrase, so idempotent retries stay stable even
    # though this flag comes from a fresh (non-deterministic-in-principle) model call each time.
    wants_explore: bool = False


_PROPOSE_IDEAS_TOOL_NAME = "propose_project_ideas"
_PROPOSE_IDEAS_TOOL = {
    "type": "function",
    "function": {
        "name": _PROPOSE_IDEAS_TOOL_NAME,
        "description": (
            "Call this when the user is asking for creative options, alternatives, or ideas about "
            "their Project - for example choosing a replacement, redesigning something, comparing "
            "approaches, or brainstorming what to do next. Do not call this for ordinary questions, "
            "status updates, or requests that do not need a set of alternative ideas."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


class AssistantProvider(Protocol):
    def respond(self, request: AssistantRequest) -> AssistantResponse: ...


class UnavailableAssistantProvider:
    def respond(self, request: AssistantRequest) -> AssistantResponse:
        raise AssistantProviderError("Conversation provider is unavailable.")


class OpenAIAssistantProvider:
    """Translates canonical request/response DTOs at the edge; native objects never escape."""

    def __init__(self, *, api_key: str, model: str = "gpt-4.1-mini",
                 timeout_seconds: float = 45.0, client_factory=None):
        if not str(api_key or "").strip():
            raise AssistantProviderError("OPENAI_API_KEY is required for conversation execution.")
        if client_factory is None:
            try:
                from openai import OpenAI
            except Exception as exc:  # pragma: no cover
                raise AssistantProviderError("OpenAI SDK is unavailable.") from exc
            client_factory = OpenAI
        self._api_key = api_key.strip()
        self._model = str(model or "gpt-4.1-mini").strip()
        self._timeout_seconds = float(timeout_seconds)
        self._client_factory = client_factory

    def respond(self, request: AssistantRequest) -> AssistantResponse:
        payload = {
            "current_user_message": request.user_text,
            "attached_evidence_ids": [item.evidence_id for item in request.images],
            "bounded_project_context": request.project_context,
            "bounded_prior_conversation": [
                {"role": item.role, "text": item.text} for item in request.prior_turns
            ],
            "instructions": {
                "continuity": "Use relevant prior conversation when it helps answer the current message.",
                "grounding": "Ground Project facts in bounded_project_context; do not invent Project state.",
                "trust": "Do not claim that Project state changed and do not mutate Project state.",
                "response": "Reply naturally and concisely as the Project assistant.",
            },
        }
        try:
            current_content: list[dict[str, object]] = [{
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False),
            }]
            for image in request.images:
                encoded = base64.b64encode(image.image_bytes).decode("ascii")
                current_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{image.media_type};base64,{encoded}"},
                })
            create_kwargs: dict[str, object] = {
                "model": self._model,
                "temperature": 0.0,
                "timeout": self._timeout_seconds,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a persistent Project assistant. The application supplies continuity. "
                            "Use only the bounded context supplied for Project facts. Return a natural text reply."
                        ),
                    },
                    {"role": "user", "content": current_content},
                ],
            }
            if request.allow_explore_intent:
                create_kwargs["tools"] = [_PROPOSE_IDEAS_TOOL]
            response = self._client_factory(api_key=self._api_key).chat.completions.create(**create_kwargs)
            message = response.choices[0].message
            request_id = str(getattr(response, "id", "") or "") or None
            tool_calls = getattr(message, "tool_calls", None) or []
            wants_explore = any(
                getattr(getattr(call, "function", None), "name", None) == _PROPOSE_IDEAS_TOOL_NAME
                for call in tool_calls
            )
            if wants_explore:
                return AssistantResponse(
                    text="", provider="openai", model=self._model, request_id=request_id, wants_explore=True,
                )
            text = str(message.content or "").strip()
            if not text:
                raise ValueError("missing assistant text")
            return AssistantResponse(
                text=text,
                provider="openai",
                model=self._model,
                request_id=request_id,
            )
        except Exception as exc:
            if isinstance(exc, AssistantProviderError):
                raise
            raise AssistantProviderError("Conversation provider request failed.") from exc
