"""ADR-060 Path B: text/context-grounded TROUBLESHOOT execution.

Architecture decision (2026-09-04): TROUBLESHOOT is a response family, not a
synonym for "has an Investigation session." Investigation's evidence-rich
session/evidence/orchestrator pipeline is the SPECIALIZED path used when
usable evidence already exists (see ProjectAIResultPlanner._dispatch_
troubleshoot's Path A). This module is the DISTINCT, lighter path used when
it does not - a natural text-only diagnostic question grounded in Project
context + the current request, never in fabricated evidence.

Deliberately mirrors ProjectQuestionAnsweringService/OpenAIProjectReasoningProvider's
shape (project_qa.py) exactly - context retrieval + one structured-output call,
no persistence of its own - rather than touching anything under investigations/
(session store, evidence store, orchestrator, frozen manifests). No Investigation
session is read, created, or required by this module.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Protocol

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional import fallback
    OpenAI = None  # type: ignore[assignment]

from .models import ProjectContextPack
from .project_context_retriever import ProjectContextRetriever

_DEFAULT_MODEL = "gpt-4.1-mini"
_DEFAULT_TIMEOUT_SECONDS = 30.0


class ProjectTextTroubleshootError(RuntimeError):
    pass


class ProjectTextTroubleshootProviderMissingApiKeyError(ProjectTextTroubleshootError):
    pass


@dataclass(frozen=True)
class ProjectTextTroubleshootResponse:
    diagnosis: str
    recommended_next_action: str
    uncertain: bool
    provider: str
    provider_model: str


class ProjectTextTroubleshootProvider(Protocol):
    def diagnose(self, *, user_request: str, context_pack: ProjectContextPack) -> ProjectTextTroubleshootResponse:
        ...


class OpenAIProjectTextTroubleshootProvider:
    """One small structured-output call - temperature 0, JSON-object response format - producing
    a diagnosis-shaped answer instead of a general Q&A answer. Never fabricates a specific cause
    it cannot support from the supplied context; sets uncertain=true instead."""

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
            raise ProjectTextTroubleshootProviderMissingApiKeyError(
                "OPENAI_API_KEY is required for text-only troubleshoot execution."
            )
        self._api_key = normalized_key
        self._model = str(model or "").strip() or _DEFAULT_MODEL
        self._timeout_seconds = float(timeout_seconds)
        self._client_factory = client_factory
        # Cost/latency observability only - never read by diagnose()'s own logic.
        self.last_usage: dict[str, int] | None = None

    def diagnose(self, *, user_request: str, context_pack: ProjectContextPack) -> ProjectTextTroubleshootResponse:
        if self._client_factory is None:
            raise ProjectTextTroubleshootError("OpenAI SDK is unavailable.")

        prompt_payload = {
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
                {"activity_type": item.activity_type.value, "summary": item.summary, "occurred_at_utc": item.occurred_at_utc.isoformat()}
                for item in context_pack.recent_activities[:10]
            ],
            "recent_investigations": [
                {"status": item.status, "diagnosis": item.diagnosis, "required_next_action": item.required_next_action,
                 "completed_at_utc": item.completed_at_utc.isoformat()}
                for item in context_pack.recent_investigations[:5]
            ],
            "current_request": user_request,
            "instructions": {
                "task": (
                    "Provide a best-effort diagnosis and exactly one concrete next action for this "
                    "troubleshooting request, using only the supplied Project context and "
                    "current_request. No photos or captured evidence are available for this request."
                ),
                "honesty": (
                    "If the request lacks enough detail for a specific diagnosis, give the most "
                    "useful general next step (e.g. what to check or observe first) and set "
                    "uncertain=true. Never invent a specific cause you cannot support from the "
                    "given context - a plausible-sounding but unsupported guess is worse than an "
                    "honest, general first step."
                ),
                "grounding": "Do not invent Project state beyond what is supplied.",
            },
            "response_schema": {
                "diagnosis": "string",
                "recommended_next_action": "string",
                "uncertain": "boolean",
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
                        "You are a troubleshooting assistant helping with a real-world project. You "
                        "give a best-effort diagnosis and one next action from the supplied context "
                        "only - you never fabricate specifics you cannot support, and you say so via "
                        "uncertain=true when the request is under-specified. Return only valid JSON "
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
        json_payload = _extract_json_object(content)
        if not json_payload:
            raise ProjectTextTroubleshootError("Text-only troubleshoot provider did not return a JSON object.")

        try:
            parsed = json.loads(json_payload)
        except (TypeError, ValueError) as exc:
            raise ProjectTextTroubleshootError("Text-only troubleshoot provider returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise ProjectTextTroubleshootError("Text-only troubleshoot provider response must be a JSON object.")

        diagnosis = str(parsed.get("diagnosis") or "").strip()
        recommended_next_action = str(parsed.get("recommended_next_action") or "").strip()
        if not diagnosis or not recommended_next_action:
            raise ProjectTextTroubleshootError("Text-only troubleshoot provider response is missing required fields.")

        return ProjectTextTroubleshootResponse(
            diagnosis=diagnosis,
            recommended_next_action=recommended_next_action,
            uncertain=bool(parsed.get("uncertain", False)),
            provider="openai",
            provider_model=self._model,
        )


class ProjectTextTroubleshootService:
    """Thin service boundary matching ProjectQuestionAnsweringService's shape (project_qa.py) -
    owns context retrieval + provider dispatch only, no persistence of its own."""

    def __init__(self, *, context_retriever: ProjectContextRetriever, provider: ProjectTextTroubleshootProvider) -> None:
        self._context_retriever = context_retriever
        self._provider = provider

    def diagnose(self, *, project_id: str, user_request: str) -> ProjectTextTroubleshootResponse:
        context_pack = self._context_retriever.get_context(project_id)
        return self._provider.diagnose(user_request=user_request, context_pack=context_pack)


def _extract_json_object(text: str) -> str:
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


def load_project_text_troubleshoot_model_name() -> str:
    configured = os.environ.get("PROJECT_TEXT_TROUBLESHOOT_OPENAI_MODEL") or _DEFAULT_MODEL
    return str(configured or "").strip() or _DEFAULT_MODEL


def load_project_text_troubleshoot_timeout_seconds() -> float:
    raw = str(os.environ.get("PROJECT_TEXT_TROUBLESHOOT_OPENAI_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return _DEFAULT_TIMEOUT_SECONDS
    try:
        parsed = float(raw)
    except ValueError:
        return _DEFAULT_TIMEOUT_SECONDS
    return parsed if parsed > 0 else _DEFAULT_TIMEOUT_SECONDS
