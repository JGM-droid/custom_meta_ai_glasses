from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class AssistantProviderError(RuntimeError):
    pass


class AssistantCapabilityIntent(str, Enum):
    """Phase 3B/3C: the small, closed set of application-owned capabilities a provider may hand
    back control for, via native tool-calling, instead of answering in plain text. Two real
    capabilities (Explore, then VisualArtifact) originally justified this abstraction over a bag of
    one-off booleans; INVESTIGATE (Phase 3C) is the third, exactly as anticipated. This is
    deliberately NOT a generic capability registry/plugin system - it is a closed enum with exactly
    the capabilities that exist today, and growing it stays a one-line addition only when a real
    capability justifies it."""

    NONE = "NONE"
    EXPLORE = "EXPLORE"
    VISUALIZE_OPTION = "VISUALIZE_OPTION"
    INVESTIGATE = "INVESTIGATE"


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
    # Phase 3A/3B: only ever contains a capability the caller has a real service wired in for (see
    # AssistantOrchestrator._allowed_capability_intents). The provider must never advertise a tool
    # for a capability the orchestrator cannot actually fulfill.
    allowed_capability_intents: frozenset[AssistantCapabilityIntent] = frozenset()


@dataclass(frozen=True)
class AssistantResponse:
    text: str
    provider: str
    model: str
    request_id: str | None = None
    # Phase 3A/3B: set when the model itself judged (via the SAME chat.completions call, native
    # OpenAI tool-calling - never a second classification call and never keyword matching) that the
    # user wants one of the bounded capabilities above rather than an ordinary answer. The
    # orchestrator always derives the capability's own inputs from its own conversation-owned state
    # (Explore: the conversation's own verbatim user_text; Visualize: the conversation's own most
    # recent Explore reference) rather than a model-restated phrase, so idempotent retries stay
    # stable even though this comes from a fresh (non-deterministic-in-principle) model call each time.
    capability_intent: AssistantCapabilityIntent = AssistantCapabilityIntent.NONE
    # Only meaningful when capability_intent == VISUALIZE_OPTION: the 1-based option ordinal the
    # model extracted from the user's own text and the recently-presented options already in its
    # context - a typed tool-call argument, never parsed from assistant prose by the application.
    visualize_option_ordinal: int | None = None


_PROPOSE_IDEAS_TOOL_NAME = "propose_project_ideas"
_PROPOSE_IDEAS_TOOL = {
    "type": "function",
    "function": {
        "name": _PROPOSE_IDEAS_TOOL_NAME,
        "description": (
            "Call this when the user is asking for NEW creative options, alternatives, or ideas about "
            "their Project - for example choosing a replacement, redesigning something, comparing "
            "approaches, or brainstorming what to do next. Do not call this for ordinary questions, "
            "status updates, or requests that do not need a set of alternative ideas. Do NOT call this "
            "when the user is simply asking which of the steps/options already given earlier in this "
            "conversation (for example by investigate_project_issue's guidance) to try first or next, "
            "or asking how to carry out one of those steps - that is continuing an existing answer, "
            "not requesting new brainstorming, and should be answered as normal text instead."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

_VISUALIZE_OPTION_TOOL_NAME = "visualize_project_option"
_VISUALIZE_OPTION_TOOL = {
    "type": "function",
    "function": {
        "name": _VISUALIZE_OPTION_TOOL_NAME,
        "description": (
            "Call this ONLY when the user explicitly asks to see, visualize, or generate an image of "
            "one specific numbered option that was already presented - for example 'show me what "
            "option 3 would look like', 'visualize that in my room', 'can you generate an image of "
            "that', 'show me the replacement'. Do NOT call this for ordinary discussion, questions, "
            "or opinions about an option (for example 'tell me more about option 3', 'why do you "
            "recommend option 2', 'would that give me more storage') - answer those as normal text "
            "instead. Only call this when the user's own words clearly ask to see/visualize/generate "
            "an image, not merely because options were recently discussed. Call it immediately the "
            "first time the request is already this explicit - never ask the user to confirm first, "
            "and never reply with plain text saying you will generate/prepare/visualize it instead of "
            "actually calling this tool right now."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ordinal": {
                    "type": "integer",
                    "enum": [1, 2, 3],
                    "description": (
                        "The 1-based ordinal of the option the user wants visualized, exactly as it "
                        "was numbered when it was presented."
                    ),
                },
            },
            "required": ["ordinal"],
        },
    },
}

_INVESTIGATE_TOOL_NAME = "investigate_project_issue"
_INVESTIGATE_TOOL = {
    "type": "function",
    "function": {
        "name": _INVESTIGATE_TOOL_NAME,
        "description": (
            "Call this when the user is trying to actually diagnose or troubleshoot a problem - "
            "determine WHY something is failing, broken, or behaving incorrectly, identify an "
            "underlying cause, test a hypothesis, or work through an unresolved problem - and "
            "answering depends on looking at the attached/current visual Evidence. Do NOT call this "
            "for ordinary cleaning, restoration, or how-to requests that do not ask you to diagnose a "
            "cause - wanting to know how to clean, whiten, refresh, or otherwise fix the appearance "
            "of something is an ordinary how-to request, not a diagnosis, even when the thing is "
            "visibly dirty, damaged, or discolored; answer those directly in plain text with the "
            "how-to/cleaning/restoration steps instead of calling this tool. Examples that SHOULD "
            "call this: 'why isn't this working', 'what's wrong with this', 'my AC isn't cooling, "
            "help me diagnose what's wrong', 'this outlet stopped working, help me troubleshoot it', "
            "'my computer won't boot, here's the error, help me figure out what's wrong', 'my plant "
            "keeps getting brown leaves even though I'm watering it, help me figure out why', 'this "
            "bike chain used to be smooth, why does it look like this now and what caused it'. Do "
            "NOT call this for ordinary descriptive, curiosity, or how-to questions that are not "
            "asking you to determine a cause (for example 'what is this', 'what color is this', 'how "
            "should I clean these shoes', 'how can I make these shoes white again', 'summarize what "
            "you see', 'what brand does this look like', 'explain how this works') - answer those as "
            "normal text instead, including giving cleaning/restoration/how-to steps directly. Call "
            "it immediately the first time the request is already this explicit - never ask the user "
            "to confirm first, and never reply with plain text saying you will investigate/diagnose "
            "it instead of actually calling this tool right now."
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
                "response": (
                    "Reply naturally as the Project assistant for ordinary conversation, or call the "
                    "appropriate available tool immediately when the user's message already clearly "
                    "matches one - never narrate or promise that action in text instead of calling it."
                ),
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
                    {"role": "system", "content": self._system_message(request.allowed_capability_intents)},
                    {"role": "user", "content": current_content},
                ],
            }
            tools: list[dict[str, object]] = []
            if AssistantCapabilityIntent.EXPLORE in request.allowed_capability_intents:
                tools.append(_PROPOSE_IDEAS_TOOL)
            if AssistantCapabilityIntent.VISUALIZE_OPTION in request.allowed_capability_intents:
                tools.append(_VISUALIZE_OPTION_TOOL)
            if AssistantCapabilityIntent.INVESTIGATE in request.allowed_capability_intents:
                tools.append(_INVESTIGATE_TOOL)
            if tools:
                create_kwargs["tools"] = tools
            response = self._client_factory(api_key=self._api_key).chat.completions.create(**create_kwargs)
            message = response.choices[0].message
            request_id = str(getattr(response, "id", "") or "") or None
            tool_calls = getattr(message, "tool_calls", None) or []

            def _call_named(name: str):
                return next(
                    (call for call in tool_calls if getattr(getattr(call, "function", None), "name", None) == name),
                    None,
                )

            if _call_named(_PROPOSE_IDEAS_TOOL_NAME) is not None:
                return AssistantResponse(
                    text="", provider="openai", model=self._model, request_id=request_id,
                    capability_intent=AssistantCapabilityIntent.EXPLORE,
                )
            visualize_call = _call_named(_VISUALIZE_OPTION_TOOL_NAME)
            if visualize_call is not None:
                ordinal = self._parse_visualize_ordinal(visualize_call)
                return AssistantResponse(
                    text="", provider="openai", model=self._model, request_id=request_id,
                    capability_intent=AssistantCapabilityIntent.VISUALIZE_OPTION,
                    visualize_option_ordinal=ordinal,
                )
            if _call_named(_INVESTIGATE_TOOL_NAME) is not None:
                return AssistantResponse(
                    text="", provider="openai", model=self._model, request_id=request_id,
                    capability_intent=AssistantCapabilityIntent.INVESTIGATE,
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

    @staticmethod
    def _system_message(allowed_capability_intents: frozenset[AssistantCapabilityIntent]) -> str:
        """Root-cause repair (real-acceptance-test failure, Phase 3B): the previous system message
        unconditionally said "Return a natural text reply", and the JSON payload's own
        instructions.response echoed the same text-only framing - both actively worked against the
        tool descriptions below them, which is why a real model answered an already-explicit
        visualize request with prose (and then falsely claimed to be "preparing"/"proceeding")
        instead of calling visualize_project_option. This builds an explicit, capability-aware
        instruction that (a) tells the model each currently-available tool exists and must be called
        immediately - not narrated, not gated behind a confirmation question - whenever the user's own
        words already clearly match it, and (b) forbids describing an action as happening/about to
        happen unless the matching tool is actually being called in this exact response. Deliberately
        prose/instruction-only: this is prompt engineering inside the OpenAI adapter, not application-
        side keyword routing - the typed capability_intent the model returns is still the only thing
        the orchestrator ever acts on.
        """
        lines = [
            "You are a persistent Project assistant. The application supplies continuity.",
            "Use only the bounded context supplied for Project facts; never invent Project state.",
        ]
        if AssistantCapabilityIntent.EXPLORE in allowed_capability_intents:
            lines.append(
                "If the user is asking for NEW creative options, alternatives, or ideas about their "
                "Project, call propose_project_ideas in this exact response instead of listing "
                "options yourself in text. Do not call it when the user is instead asking which of "
                "the steps/options you already gave earlier in this conversation to try first or "
                "next, or how to carry one of them out - that is continuing your existing answer, not "
                "a request for new brainstorming, so just answer in plain text using the prior "
                "conversation."
            )
        if AssistantCapabilityIntent.VISUALIZE_OPTION in allowed_capability_intents:
            lines.append(
                "If the user explicitly asks to see, visualize, or generate an image of a specific "
                "already-presented option, call visualize_project_option in this exact response with "
                "that option's ordinal - immediately, the first time they ask. Never ask them to "
                "confirm first, and never reply with text claiming you are generating, preparing, "
                "starting, or about to create the visualization instead of actually calling the tool."
            )
        if AssistantCapabilityIntent.INVESTIGATE in allowed_capability_intents:
            lines.append(
                "If the user is trying to actually diagnose or troubleshoot a problem - determine WHY "
                "something is failing, broken, or behaving incorrectly, identify an underlying cause, "
                "or work through an unresolved problem - and that depends on the attached/current "
                "visual Evidence, call investigate_project_issue in this exact response, immediately, "
                "the first time they ask. Never ask them to confirm first, and never reply with text "
                "claiming you are investigating or diagnosing it instead of actually calling the "
                "tool. Do not call it for ordinary cleaning, restoration, or how-to requests that do "
                "not ask you to diagnose a cause - wanting to know how to clean, whiten, refresh, or "
                "otherwise fix the appearance of something is an ordinary how-to request, not a "
                "diagnosis, even when the thing is visibly dirty, damaged, or discolored; answer "
                "those directly in plain text with the how-to/cleaning/restoration steps. Also do not "
                "call it for ordinary descriptive or curiosity questions (for example what something "
                "is, what color it is, or what it looks like). If the user is instead asking which "
                "step you already gave to try first or next, or how to carry one out, that continues "
                "your existing answer - reply in plain text using the prior conversation instead of "
                "calling the tool again unless a new problem or new Evidence is involved."
            )
        lines.append(
            "For everything else, reply naturally and concisely in text. Never describe yourself as "
            "performing, starting, or about to perform an action (generating, preparing, creating, "
            "proceeding, visualizing, etc.) unless you are calling the matching tool in this exact "
            "response - if you are not calling a tool, you are only talking, not acting."
        )
        return " ".join(lines)

    @staticmethod
    def _parse_visualize_ordinal(call) -> int:
        try:
            arguments = json.loads(getattr(getattr(call, "function", None), "arguments", None) or "{}")
            ordinal = int(arguments["ordinal"])
        except (TypeError, ValueError, KeyError) as exc:
            raise AssistantProviderError("Visualize tool call did not include a valid option ordinal.") from exc
        if ordinal not in (1, 2, 3):
            raise AssistantProviderError("Visualize tool call ordinal was out of range.")
        return ordinal
