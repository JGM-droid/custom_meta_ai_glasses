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


@dataclass(frozen=True)
class AssistantResponse:
    text: str
    provider: str
    model: str
    request_id: str | None = None


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
            response = self._client_factory(api_key=self._api_key).chat.completions.create(
                model=self._model,
                temperature=0.0,
                timeout=self._timeout_seconds,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a persistent Project assistant. The application supplies continuity. "
                            "Use only the bounded context supplied for Project facts. Return a natural text reply."
                        ),
                    },
                    {"role": "user", "content": current_content},
                ],
            )
            text = str(response.choices[0].message.content or "").strip()
            if not text:
                raise ValueError("missing assistant text")
            return AssistantResponse(
                text=text,
                provider="openai",
                model=self._model,
                request_id=str(getattr(response, "id", "") or "") or None,
            )
        except Exception as exc:
            if isinstance(exc, AssistantProviderError):
                raise
            raise AssistantProviderError("Conversation provider request failed.") from exc
