from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from typing import Literal, Protocol
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency fallback
    OpenAI = None  # type: ignore[assignment]

from .activity_store import ProjectActivityNotFound, ProjectActivityStore
from .checkpoint_proposal_store import CheckpointProposalStore
from .models import (
    ExplorePlanEstimatedCost,
    ProjectActivity,
    ProjectActivityConfirmationStatus,
    ProjectActivityCreateRequest,
    ProjectActivitySourceType,
    ProjectActivityType,
    ProjectExploreDisposition,
    ProjectExploreDispositionRequest,
    ProjectExploreDispositionResponse,
    ProjectExploreExecutionResponse,
    ProjectExploreGroupView,
    ProjectExploreInformationRequest,
    ProjectExploreOptionSet,
    ProjectExploreOptionView,
    ProjectExploreProviderOption,
    ProjectExploreReadProjection,
    ProjectExploreRequest,
)
from .project_ideas import PROMOTED_FROM_METADATA_KEY
from .project_context_retriever import ProjectContextRetriever
from .project_store import ProjectStore


EXPLORE_CONTEXT_CONTRACT = "explore_option_generation_v1"
EXPLORE_OPTION_COUNT = 3
INTERACTION_TYPE = "explore"
PROVIDER_RESULT_SCHEMA_VERSION = "1.1"

# Reserved Unicode Private Use Area codepoint. Unlike ASCII separator control
# characters (\x1c-\x1f), this survives Pydantic's str_strip_whitespace
# normalization (str.strip() treats \x1f as whitespace and would silently
# eat a trailing empty field). Never produced by validated provider text
# (rejected by the model layer); used to losslessly encode multiple bounded
# text fields into one Activity.summary/details string, so canonical
# reconstruction after restart never depends on parsing free-form prose.
_FIELD_DELIMITER = ""


class ProjectExploreError(RuntimeError):
    pass


class ProjectExploreProviderUnavailable(ProjectExploreError):
    pass


class ProjectExploreInvalidResult(ProjectExploreError):
    pass


class ProjectExploreIdempotencyConflict(ProjectExploreError):
    pass


class ProjectExploreRecoveryConflict(ProjectExploreError):
    pass


class ProjectExploreForeignReference(ProjectExploreError):
    pass


class ProjectExploreIdeaNotFound(ProjectExploreError):
    pass


@dataclass(frozen=True)
class ProjectExploreContextPack:
    contract_id: str
    project_id: str
    project_name: str
    project_goal: str
    project_revision: int
    checkpoint: dict[str, object]
    user_intent: str
    input_activities: tuple[dict[str, object], ...]
    relevant_context: tuple[dict[str, object], ...]


class ProjectExploreProvider(Protocol):
    def identity(self) -> "ProjectExploreProviderIdentity":
        ...

    def explore(self, context_pack: ProjectExploreContextPack) -> str | dict[str, object]:
        ...


@dataclass(frozen=True)
class ProjectExploreProviderIdentity:
    provider: str
    model: str
    tool: str


class _ProjectExploreProviderResponse(BaseModel):
    """Union-free transport wrapper accepted by Responses Structured Outputs.

    The API rejects a discriminated Pydantic union here because its generated
    ``oneOf`` is not supported in this response-format position. Nullable,
    named payload slots keep the transport schema compatible while this
    validator preserves the same strict two-result domain boundary.
    """

    model_config = ConfigDict(extra="forbid")

    result_type: Literal["OPTION_SET", "INFORMATION_REQUEST"]
    option_set: ProjectExploreOptionSet | None
    information_request: ProjectExploreInformationRequest | None

    @model_validator(mode="after")
    def _validate_selected_payload(self) -> "_ProjectExploreProviderResponse":
        if self.result_type == "OPTION_SET" and self.option_set is not None and self.information_request is None:
            return self
        if self.result_type == "INFORMATION_REQUEST" and self.information_request is not None and self.option_set is None:
            return self
        raise ValueError("Exactly the payload selected by result_type must be present.")

    def selected_result(self) -> ProjectExploreOptionSet | ProjectExploreInformationRequest:
        if self.result_type == "OPTION_SET" and self.option_set is not None:
            return self.option_set
        if self.result_type == "INFORMATION_REQUEST" and self.information_request is not None:
            return self.information_request
        raise ProjectExploreInvalidResult("Explore provider returned an inconsistent structured result.")


def _response_contains_refusal(response: object) -> bool:
    outputs = getattr(response, "output", None)
    if not isinstance(outputs, list):
        return False
    for output in outputs:
        if getattr(output, "type", None) != "message":
            continue
        content_items = getattr(output, "content", None)
        if not isinstance(content_items, list):
            continue
        for item in content_items:
            if getattr(item, "type", None) == "refusal":
                return True
    return False


class OpenAIProjectExploreProvider:
    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 45.0, client_factory=OpenAI):
        if not str(api_key or "").strip():
            raise ProjectExploreProviderUnavailable("OPENAI_API_KEY is required for Explore execution.")
        self._api_key = api_key.strip()
        self._model = str(model or "gpt-4.1-mini").strip() or "gpt-4.1-mini"
        self._timeout_seconds = float(timeout_seconds)
        self._client_factory = client_factory

    def identity(self) -> ProjectExploreProviderIdentity:
        return ProjectExploreProviderIdentity(provider="openai", model=self._model, tool="responses.parse")

    def explore(self, context_pack: ProjectExploreContextPack) -> ProjectExploreOptionSet | ProjectExploreInformationRequest:
        if self._client_factory is None:
            raise ProjectExploreProviderUnavailable("OpenAI SDK is unavailable.")
        instructions = (
            "You are a Project-scoped Explore assistant. Return one wrapper with result_type and EXACTLY "
            "one matching payload: option_set for OPTION_SET, or information_request for INFORMATION_REQUEST. "
            "Set the unused payload to null. Never invent Project facts or source "
            "references; use only supplied source reference activity IDs. Do not prescribe mutations or "
            "device actions. An OPTION_SET must contain exactly three distinct, meaningfully different "
            "options (ordinals 1, 2, 3), grounded observations, one recommended option with a reason, and "
            "concrete next steps."
        )
        client = self._client_factory(api_key=self._api_key)
        try:
            response = client.responses.parse(
                model=self._model,
                instructions=instructions,
                input=[{
                    "role": "user",
                    "content": [{
                        "type": "input_text",
                        "text": json.dumps({"context_pack": context_pack.__dict__}, ensure_ascii=False, default=list),
                    }],
                }],
                text_format=_ProjectExploreProviderResponse,
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            raise ProjectExploreProviderUnavailable("Explore provider request failed.") from exc

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            if _response_contains_refusal(response):
                raise ProjectExploreInvalidResult("Explore provider refused the request.")
            raise ProjectExploreInvalidResult("Explore provider did not return a structured OPTION_SET or INFORMATION_REQUEST result.")
        return parsed.selected_result()


def load_project_explore_model_name() -> str:
    return str(os.environ.get("PROJECT_EXPLORE_OPENAI_MODEL") or "gpt-4.1-mini").strip() or "gpt-4.1-mini"


def _encode_option_details(option: ProjectExploreProviderOption) -> str:
    """Losslessly encode option.summary/rationale/tradeoffs/concept/proposed_changes.

    Canonical reconstruction source for these five fields - not a
    human-readable-only rendering. See ProjectExploreProviderOption's
    reserved-delimiter field validator, which guarantees this join is
    unambiguous to split back apart.
    """
    parts = [option.summary, option.rationale or "", option.tradeoffs or "", option.concept or "", option.proposed_changes or ""]
    return _FIELD_DELIMITER.join(parts)


def _decode_option_details(details: str | None) -> dict[str, str | None]:
    parts = (details or "").split(_FIELD_DELIMITER)
    parts = (parts + [""] * 5)[:5]
    summary, rationale, tradeoffs, concept, proposed_changes = parts
    return {
        "summary": summary,
        "rationale": rationale or None,
        "tradeoffs": tradeoffs or None,
        "concept": concept or None,
        "proposed_changes": proposed_changes or None,
    }


def _encode_estimated_cost(cost: ExplorePlanEstimatedCost | None) -> str | None:
    """Encode as one flat delimited scalar Activity metadata value - never nested JSON."""
    if cost is None:
        return None
    min_text = "" if cost.min_amount is None else repr(cost.min_amount)
    max_text = "" if cost.max_amount is None else repr(cost.max_amount)
    return "|".join([cost.currency, min_text, max_text, cost.qualifier or ""])


def _decode_estimated_cost(raw: object) -> ExplorePlanEstimatedCost | None:
    if not isinstance(raw, str) or not raw:
        return None
    parts = (raw.split("|") + ["", "", "", ""])[:4]
    currency, min_text, max_text, qualifier = parts
    try:
        return ExplorePlanEstimatedCost(
            currency=currency,
            min_amount=float(min_text) if min_text else None,
            max_amount=float(max_text) if max_text else None,
            qualifier=qualifier or None,
        )
    except (ValidationError, ValueError):
        return None


def _encode_text_list(items: list[str]) -> str:
    return _FIELD_DELIMITER.join(items)


def _decode_text_list(raw: object) -> list[str]:
    if not isinstance(raw, str) or not raw:
        return []
    return [item for item in raw.split(_FIELD_DELIMITER) if item]


def _encode_result_details(result: ProjectExploreOptionSet) -> str:
    return json.dumps(
        {
            "summary": result.summary,
            "recommendation_reason": result.recommendation_reason,
            "observations": result.observations,
            "next_steps": result.next_steps,
            "follow_up_questions": result.follow_up_questions,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_result_details(details: str | None, metadata: dict[str, object]) -> dict[str, object]:
    try:
        parsed = json.loads(details or "")
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return {
            "summary": str(parsed.get("summary") or ""),
            "recommendation_reason": str(parsed.get("recommendation_reason") or ""),
            "observations": list(parsed.get("observations") or []),
            "next_steps": list(parsed.get("next_steps") or []),
            "follow_up_questions": list(parsed.get("follow_up_questions") or []),
        }
    legacy = ((details or "").split(_FIELD_DELIMITER) + ["", ""])[:2]
    return {
        "summary": legacy[0],
        "recommendation_reason": legacy[1],
        "observations": _decode_text_list(metadata.get("observations")),
        "next_steps": _decode_text_list(metadata.get("next_steps")),
        "follow_up_questions": _decode_text_list(metadata.get("follow_up_questions")),
    }


class ProjectExploreService:
    def __init__(self, *, project_store: ProjectStore, activity_store: ProjectActivityStore,
                 proposal_store: CheckpointProposalStore, context_retriever: ProjectContextRetriever,
                 provider: ProjectExploreProvider | None):
        self.project_store = project_store
        self.activity_store = activity_store
        self.proposal_store = proposal_store
        self.context_retriever = context_retriever
        self.provider = provider

    @staticmethod
    def _interaction_id(project_id: str, idempotency_key: str) -> str:
        return str(uuid5(UUID(project_id), f"explore:{idempotency_key}"))

    @staticmethod
    def _result_activity_id(interaction_id: str) -> str:
        return str(uuid5(UUID(interaction_id), "result"))

    @staticmethod
    def _request_fingerprint(request: ProjectExploreRequest) -> str:
        canonical = json.dumps({"user_intent": request.user_intent, "input_refs": request.input_refs}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_canonical_ai_explore_component(activity: ProjectActivity) -> bool:
        """Only canonical inferred AI output may reconstruct an Explore result.

        Interaction metadata is correlation data, not provenance.  User/reported or otherwise
        non-AI Activities can legitimately carry arbitrary metadata through the generic Activity
        API, so they must never be trusted as Explore-plan components merely because those keys
        resemble an Explore interaction.
        """
        return (
            activity.source_type == ProjectActivitySourceType.AI
            and activity.confirmation_status == ProjectActivityConfirmationStatus.INFERRED
        )

    def _group_activities(self, project_id: str, interaction_id: str) -> tuple[list[ProjectActivity], ProjectActivity | None]:
        """Every Activity belonging to one Explore interaction: the (<=3) option Ideas and the whole-result RESULT Activity, if written."""
        all_activities = self.activity_store.list_activities(project_id)
        ideas = [a for a in all_activities if self._is_canonical_ai_explore_component(a)
                 and a.activity_type == ProjectActivityType.IDEA
                 and (a.metadata or {}).get("interaction_type") == INTERACTION_TYPE
                 and (a.metadata or {}).get("interaction_id") == interaction_id]
        result_activity = next((a for a in all_activities if self._is_canonical_ai_explore_component(a)
                                and a.activity_type == ProjectActivityType.RESULT
                                and (a.metadata or {}).get("interaction_type") == INTERACTION_TYPE
                                and (a.metadata or {}).get("interaction_id") == interaction_id), None)
        return ideas, result_activity

    def _build_context(self, project_id: str, request: ProjectExploreRequest) -> ProjectExploreContextPack:
        try:
            project, explicit, relevant = self.context_retriever.get_explore_context_activities(
                project_id, request.input_refs, relevant_limit=10
            )
        except ProjectActivityNotFound as exc:
            raise ProjectExploreForeignReference("input_refs must belong to the target Project.") from exc

        def bounded(activity: ProjectActivity) -> dict[str, object]:
            item: dict[str, object] = {
                "activity_id": activity.activity_id,
                "activity_type": activity.activity_type.value,
                "source_type": activity.source_type.value,
                "confirmation_status": activity.confirmation_status.value,
                "summary": activity.summary,
                "details": activity.details,
            }
            metadata = activity.metadata or {}
            source_activity_id = metadata.get("source_activity_id")
            if (activity.activity_type == ProjectActivityType.DECISION
                    and metadata.get("interaction_type") == INTERACTION_TYPE
                    and isinstance(source_activity_id, str)):
                try:
                    linked = self.activity_store.load_activity(project_id, source_activity_id)
                except ProjectActivityNotFound:
                    linked = None
                if (linked is not None and linked.activity_type == ProjectActivityType.IDEA
                        and (linked.metadata or {}).get("interaction_type") == INTERACTION_TYPE):
                    item["linked_idea"] = {"activity_id": linked.activity_id, "title": linked.summary}
            return item

        return ProjectExploreContextPack(
            contract_id=EXPLORE_CONTEXT_CONTRACT,
            project_id=project.project_id,
            project_name=project.name,
            project_goal=project.goal,
            project_revision=project.revision,
            checkpoint=project.checkpoint.model_dump(mode="json"),
            user_intent=request.user_intent,
            input_activities=tuple(bounded(item) for item in explicit),
            relevant_context=tuple(bounded(item) for item in relevant),
        )

    @staticmethod
    def _parse_result(raw: str | dict[str, object] | ProjectExploreOptionSet | ProjectExploreInformationRequest,
                       allowed_refs: set[str]) -> ProjectExploreOptionSet | ProjectExploreInformationRequest:
        if isinstance(raw, (ProjectExploreOptionSet, ProjectExploreInformationRequest)):
            result: ProjectExploreOptionSet | ProjectExploreInformationRequest = raw
        else:
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError as exc:
                raise ProjectExploreInvalidResult("Explore provider returned malformed JSON.") from exc
            if not isinstance(parsed, dict):
                raise ProjectExploreInvalidResult("Explore provider result must be one JSON object.")
            result_type = parsed.get("result_type")
            try:
                if result_type == "OPTION_SET":
                    result = ProjectExploreOptionSet.model_validate(parsed)
                elif result_type == "INFORMATION_REQUEST":
                    result = ProjectExploreInformationRequest.model_validate(parsed)
                else:
                    raise ProjectExploreInvalidResult("Unknown Explore result_type.")
            except ValidationError as exc:
                raise ProjectExploreInvalidResult("Explore provider result failed strict validation.") from exc

        if isinstance(result, ProjectExploreOptionSet):
            if [item.ordinal for item in result.options] != [1, 2, 3]:
                raise ProjectExploreInvalidResult("OPTION_SET ordinals must be exactly 1, 2, 3 in order.")
            normalized_titles = [" ".join(item.title.lower().split()) for item in result.options]
            normalized_content = [" ".join((item.title + " " + item.summary).lower().split()) for item in result.options]
            if len(set(normalized_titles)) != 3 or len(set(normalized_content)) != 3:
                raise ProjectExploreInvalidResult("OPTION_SET options must be distinct.")
            if len(_encode_result_details(result)) > 3000:
                raise ProjectExploreInvalidResult("OPTION_SET rich result exceeds the canonical Activity details limit.")
            refs = result.source_refs + [ref for option in result.options for ref in option.source_refs]
        else:
            refs = result.source_refs

        if any(ref not in allowed_refs for ref in refs):
            raise ProjectExploreInvalidResult("Explore provider invented or used a foreign source reference.")
        return result

    def execute(self, project_id: str, request: ProjectExploreRequest) -> ProjectExploreExecutionResponse:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        interaction_id = self._interaction_id(normalized_project_id, request.idempotency_key)
        fingerprint = self._request_fingerprint(request)
        lock = self.project_store._get_project_lock(normalized_project_id)
        with lock:
            self.project_store.load_project(normalized_project_id)
            existing_ideas, existing_result = self._group_activities(normalized_project_id, interaction_id)
            if existing_ideas or existing_result:
                stored_fingerprints = {(a.metadata or {}).get("request_fingerprint") for a in existing_ideas + ([existing_result] if existing_result else [])}
                if stored_fingerprints != {fingerprint}:
                    raise ProjectExploreIdempotencyConflict("idempotency_key was already used with a different request.")
                ordinals = [(a.metadata or {}).get("option_ordinal") for a in existing_ideas]
                if len(existing_ideas) > 3 or any(not isinstance(item, int) or item not in {1, 2, 3} for item in ordinals) or len(set(ordinals)) != len(ordinals):
                    raise ProjectExploreRecoveryConflict("Incomplete Explore options have invalid projection identities.")
                if self._is_complete_group(existing_ideas, existing_result):
                    group = self._project_group(normalized_project_id, interaction_id, existing_ideas, existing_result)
                    return ProjectExploreExecutionResponse(project_id=normalized_project_id, interaction_id=interaction_id,
                        result_type="OPTION_SET", suggestions_created=True, message="An AI plan with three options is available and remains unconfirmed.", option_set=group)

            context = self._build_context(normalized_project_id, request)
            if self.provider is None:
                raise ProjectExploreProviderUnavailable("Explore provider is unavailable.")
            provider_identity = self.provider.identity()
            if any(not str(value or "").strip() or len(str(value)) > 128 for value in (
                provider_identity.provider, provider_identity.model, provider_identity.tool
            )):
                raise ProjectExploreProviderUnavailable("Explore provider identity is invalid.")
            context_fingerprint = hashlib.sha256(json.dumps(context.__dict__, sort_keys=True,
                separators=(",", ":"), ensure_ascii=False, default=list).encode("utf-8")).hexdigest()
            if existing_ideas or existing_result:
                existing_all = existing_ideas + ([existing_result] if existing_result else [])
                context_fingerprints = {(a.metadata or {}).get("context_fingerprint") for a in existing_all}
                provider_identities = {(
                    (a.metadata or {}).get("provider"),
                    (a.metadata or {}).get("provider_model"),
                    (a.metadata or {}).get("provider_tool"),
                ) for a in existing_all}
                if context_fingerprints != {context_fingerprint} or provider_identities != {(
                    provider_identity.provider, provider_identity.model, provider_identity.tool
                )}:
                    raise ProjectExploreRecoveryConflict("Incomplete Explore options were created from a different execution context.")

            allowed_refs = {a["activity_id"] for a in context.input_activities} | {a["activity_id"] for a in context.relevant_context}
            result = self._parse_result(self.provider.explore(context), allowed_refs)
            if isinstance(result, ProjectExploreInformationRequest):
                if existing_ideas or existing_result:
                    raise ProjectExploreRecoveryConflict("Incomplete Explore options could not be recovered from a non-option result.")
                return ProjectExploreExecutionResponse(project_id=normalized_project_id, interaction_id=None,
                    result_type="INFORMATION_REQUEST", suggestions_created=False,
                    message="More information is needed. No suggestions were created.", information_request=result)

            if existing_ideas:
                self._verify_matching_partial(existing_ideas, result)
            if existing_result is not None:
                self._verify_matching_result(existing_result, result, fingerprint, interaction_id)

            recommended_result_item_id = str(uuid5(UUID(interaction_id), f"option:{result.recommended_ordinal}"))
            for option in result.options:
                result_item_id = str(uuid5(UUID(interaction_id), f"option:{option.ordinal}"))
                activity_id = str(uuid5(UUID(result_item_id), "idea"))
                refs_csv = ",".join(option.source_refs)
                cost_encoded = _encode_estimated_cost(option.estimated_cost)
                metadata = {"idea_state": "captured", "interaction_id": interaction_id,
                            "interaction_type": INTERACTION_TYPE, "idempotency_key": request.idempotency_key,
                            "request_fingerprint": fingerprint, "result_item_id": result_item_id,
                            "option_ordinal": option.ordinal, "explore_group_size": 3,
                            "context_contract": EXPLORE_CONTEXT_CONTRACT,
                            "context_fingerprint": context_fingerprint,
                            "provider": provider_identity.provider, "provider_model": provider_identity.model,
                            "provider_tool": provider_identity.tool, "source_refs": refs_csv}
                if cost_encoded is not None:
                    metadata["estimated_cost"] = cost_encoded
                request_activity = ProjectActivityCreateRequest(
                    activity_type=ProjectActivityType.IDEA,
                    source_type=ProjectActivitySourceType.AI,
                    confirmation_status=ProjectActivityConfirmationStatus.INFERRED,
                    summary=option.title,
                    details=_encode_option_details(option),
                    metadata=metadata,
                )
                activity, created = self.activity_store.create_activity_with_id(normalized_project_id, activity_id, request_activity)
                if not created and not self._activity_matches_option(activity, option, fingerprint, interaction_id):
                    raise ProjectExploreRecoveryConflict("Existing Explore projection conflicts with the validated recovery result.")

            result_activity_id = self._result_activity_id(interaction_id)
            result_request = self._build_result_activity_request(
                result=result, interaction_id=interaction_id, idempotency_key=request.idempotency_key,
                fingerprint=fingerprint, context_fingerprint=context_fingerprint,
                provider_identity=provider_identity, recommended_result_item_id=recommended_result_item_id,
            )
            result_activity, result_created = self.activity_store.create_activity_with_id(
                normalized_project_id, result_activity_id, result_request)
            if not result_created and not self._result_activity_matches(result_activity, result, fingerprint, interaction_id):
                raise ProjectExploreRecoveryConflict("Existing Explore result projection conflicts with the validated recovery result.")

            complete_ideas, complete_result = self._group_activities(normalized_project_id, interaction_id)
            return ProjectExploreExecutionResponse(project_id=normalized_project_id, interaction_id=interaction_id,
                result_type="OPTION_SET", suggestions_created=True,
                message="An AI plan with three options was created and remains unconfirmed.",
                option_set=self._project_group(normalized_project_id, interaction_id, complete_ideas, complete_result))

    @staticmethod
    def _is_complete_group(ideas: list[ProjectActivity], result_activity: ProjectActivity | None) -> bool:
        return (len(ideas) == 3 and sorted((a.metadata or {}).get("option_ordinal") for a in ideas) == [1, 2, 3]
                and result_activity is not None)

    def _activity_matches_option(self, activity: ProjectActivity, option: ProjectExploreProviderOption,
                                 fingerprint: str, interaction_id: str) -> bool:
        metadata = activity.metadata or {}
        return (activity.activity_type == ProjectActivityType.IDEA
                and activity.source_type == ProjectActivitySourceType.AI
                and activity.confirmation_status == ProjectActivityConfirmationStatus.INFERRED
                and activity.summary == option.title and activity.details == _encode_option_details(option)
                and metadata.get("interaction_id") == interaction_id
                and metadata.get("request_fingerprint") == fingerprint
                and metadata.get("option_ordinal") == option.ordinal
                and metadata.get("source_refs") == ",".join(option.source_refs)
                and metadata.get("estimated_cost") == _encode_estimated_cost(option.estimated_cost))

    def _build_result_activity_request(self, *, result: ProjectExploreOptionSet, interaction_id: str, idempotency_key: str,
                                       fingerprint: str, context_fingerprint: str,
                                       provider_identity: "ProjectExploreProviderIdentity",
                                       recommended_result_item_id: str) -> ProjectActivityCreateRequest:
        metadata: dict[str, str | int | float | bool | None] = {
            "interaction_id": interaction_id, "interaction_type": INTERACTION_TYPE,
            "idempotency_key": idempotency_key, "request_fingerprint": fingerprint,
            "context_contract": EXPLORE_CONTEXT_CONTRACT, "context_fingerprint": context_fingerprint,
            "provider": provider_identity.provider, "provider_model": provider_identity.model,
            "provider_tool": provider_identity.tool,
            "recommended_ordinal": result.recommended_ordinal,
            "recommended_result_item_id": recommended_result_item_id,
        }
        return ProjectActivityCreateRequest(
            activity_type=ProjectActivityType.RESULT,
            source_type=ProjectActivitySourceType.AI,
            confirmation_status=ProjectActivityConfirmationStatus.INFERRED,
            summary=result.title,
            details=_encode_result_details(result),
            metadata=metadata,
        )

    def _result_activity_matches(self, activity: ProjectActivity, result: ProjectExploreOptionSet,
                                 fingerprint: str, interaction_id: str) -> bool:
        metadata = activity.metadata or {}
        expected_details = _encode_result_details(result)
        return (activity.activity_type == ProjectActivityType.RESULT
                and activity.source_type == ProjectActivitySourceType.AI
                and activity.confirmation_status == ProjectActivityConfirmationStatus.INFERRED
                and activity.summary == result.title and activity.details == expected_details
                and metadata.get("interaction_id") == interaction_id
                and metadata.get("request_fingerprint") == fingerprint
                and metadata.get("recommended_ordinal") == result.recommended_ordinal)

    def _verify_matching_partial(self, existing: list[ProjectActivity], result: ProjectExploreOptionSet) -> None:
        by_ordinal = {option.ordinal: option for option in result.options}
        for activity in existing:
            ordinal = (activity.metadata or {}).get("option_ordinal")
            option = by_ordinal.get(ordinal) if isinstance(ordinal, int) else None
            fingerprint = str((activity.metadata or {}).get("request_fingerprint") or "")
            interaction_id = str((activity.metadata or {}).get("interaction_id") or "")
            if option is None or not self._activity_matches_option(activity, option, fingerprint, interaction_id):
                raise ProjectExploreRecoveryConflict("Validated recovery result diverges from existing Explore options.")

    def _verify_matching_result(self, existing_result: ProjectActivity, result: ProjectExploreOptionSet,
                                fingerprint: str, interaction_id: str) -> None:
        if not self._result_activity_matches(existing_result, result, fingerprint, interaction_id):
            raise ProjectExploreRecoveryConflict("Validated recovery result diverges from the existing Explore result projection.")

    def disposition(self, project_id: str, idea_activity_id: str,
                    request: ProjectExploreDispositionRequest) -> ProjectExploreDispositionResponse:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        lock = self.project_store._get_project_lock(normalized_project_id)
        with lock:
            try:
                idea = self.activity_store.load_activity(normalized_project_id, idea_activity_id)
            except ProjectActivityNotFound as exc:
                raise ProjectExploreIdeaNotFound("Explore Idea does not exist.") from exc
            metadata = idea.metadata or {}
            if idea.activity_type != ProjectActivityType.IDEA or metadata.get("interaction_type") != INTERACTION_TYPE:
                raise ProjectExploreIdeaNotFound("Explore Idea does not exist.")
            fingerprint = hashlib.sha256(request.disposition.value.encode("utf-8")).hexdigest()
            decision_id = str(uuid5(UUID(idea.activity_id), f"disposition:{request.idempotency_key}"))
            decision, created = self.activity_store.create_activity_with_id(normalized_project_id, decision_id,
                ProjectActivityCreateRequest(activity_type=ProjectActivityType.DECISION,
                    source_type=ProjectActivitySourceType.USER,
                    confirmation_status=ProjectActivityConfirmationStatus.REPORTED,
                    summary={ProjectExploreDisposition.KEEP: "Keep for consideration", ProjectExploreDisposition.DISMISS: "Dismiss suggestion", ProjectExploreDisposition.SELECT: "Choose as preferred direction"}[request.disposition],
                    details="This records a user disposition only; it does not change canonical Project state.",
                    metadata={"interaction_type": INTERACTION_TYPE, "interaction_id": metadata["interaction_id"],
                              "source_activity_id": idea.activity_id, "explore_disposition": request.disposition.value,
                              "idempotency_key": request.idempotency_key, "request_fingerprint": fingerprint}))
            if not created and (decision.metadata or {}).get("request_fingerprint") != fingerprint:
                raise ProjectExploreIdempotencyConflict("idempotency_key was already used with a different disposition.")
            return ProjectExploreDispositionResponse(idea=idea, decision_activity=decision, created=created,
                                                       projection=self.read_projection(normalized_project_id))

    def read_projection(self, project_id: str) -> ProjectExploreReadProjection:
        normalized_project_id = self.project_store.validate_project_id(project_id)
        project = self.project_store.load_project(normalized_project_id)
        activities = self.activity_store.list_activities(normalized_project_id)
        idea_groups: dict[str, list[ProjectActivity]] = {}
        result_activities: dict[str, ProjectActivity] = {}
        for activity in activities:
            metadata = activity.metadata or {}
            if (metadata.get("interaction_type") != INTERACTION_TYPE
                    or not self._is_canonical_ai_explore_component(activity)):
                continue
            interaction_id = str(metadata.get("interaction_id"))
            if activity.activity_type == ProjectActivityType.IDEA:
                idea_groups.setdefault(interaction_id, []).append(activity)
            elif activity.activity_type == ProjectActivityType.RESULT:
                result_activities[interaction_id] = activity
        interaction_ids = set(idea_groups) | set(result_activities)
        complete = [
            (interaction_id, idea_groups.get(interaction_id, []), result_activities.get(interaction_id))
            for interaction_id in interaction_ids
            if self._is_complete_group(idea_groups.get(interaction_id, []), result_activities.get(interaction_id))
        ]
        projected = [self._project_group(normalized_project_id, interaction_id, ideas, result, activities=activities)
                     for interaction_id, ideas, result in complete]
        projected.sort(key=lambda group: max(option.idea.created_at_utc for option in group.options))
        options_by_idea_id = {option.idea.activity_id: option for group in projected for option in group.options}
        disposition_stream = [activity for activity in activities
                              if activity.activity_type == ProjectActivityType.DECISION
                              and (activity.metadata or {}).get("explore_disposition") in {
                                  disposition.value for disposition in ProjectExploreDisposition
                              }
                              and (activity.metadata or {}).get("source_activity_id") in options_by_idea_id]
        order_key = lambda item: (item.occurred_at_utc, item.created_at_utc, item.activity_id)
        latest_select = max(
            (item for item in disposition_stream
             if (item.metadata or {}).get("explore_disposition") == ProjectExploreDisposition.SELECT.value),
            key=order_key,
            default=None,
        )
        preferred = None
        if latest_select is not None:
            selected_idea_id = str((latest_select.metadata or {}).get("source_activity_id"))
            later_selected_idea_disposition = max(
                (item for item in disposition_stream
                 if (item.metadata or {}).get("source_activity_id") == selected_idea_id
                 and order_key(item) > order_key(latest_select)),
                key=order_key,
                default=None,
            )
            if later_selected_idea_disposition is None or (
                later_selected_idea_disposition.metadata or {}
            ).get("explore_disposition") == ProjectExploreDisposition.SELECT.value:
                preferred = options_by_idea_id.get(selected_idea_id)
        all_explore_idea_ids = {activity.activity_id for group in idea_groups.values() for activity in group}
        pending = any(
            proposal.status.value == "pending"
            and bool(all_explore_idea_ids.intersection(proposal.source_activity_ids))
            for proposal in self.proposal_store.list_proposals(normalized_project_id)
        )
        has_incomplete = any(
            not self._is_complete_group(idea_groups.get(interaction_id, []), result_activities.get(interaction_id))
            for interaction_id in interaction_ids
        )
        if pending:
            next_action = "Review the pending suggested Project change."
        elif has_incomplete:
            next_action = "Retry Explore to recover the interrupted suggestion set."
        elif preferred:
            next_action = "Preferred direction recorded. Create or review a suggested Project change when ready."
        elif projected:
            next_action = "Review the AI suggestions and choose what to keep, dismiss, or prefer."
        else:
            next_action = "Start Explore to generate Project-scoped suggestions."
        return ProjectExploreReadProjection(project_id=normalized_project_id, option_sets=projected,
            preferred_direction=preferred, canonical_checkpoint=project.checkpoint,
            project_revision=project.revision, next_action=next_action)

    def _project_group(self, project_id: str, interaction_id: str, ideas: list[ProjectActivity],
                       result_activity: ProjectActivity | None,
                       *, activities: list[ProjectActivity] | None = None) -> ProjectExploreGroupView:
        all_activities = activities if activities is not None else self.activity_store.list_activities(project_id)
        decisions = [a for a in all_activities if a.activity_type == ProjectActivityType.DECISION
                     and (a.metadata or {}).get("explore_disposition") in {d.value for d in ProjectExploreDisposition}]
        roadmaps = {str((a.metadata or {}).get(PROMOTED_FROM_METADATA_KEY)): a for a in all_activities
                    if (a.metadata or {}).get(PROMOTED_FROM_METADATA_KEY)}
        proposals = self.proposal_store.list_proposals(project_id)
        result_metadata = (result_activity.metadata or {}) if result_activity else {}
        recommended_result_item_id = result_metadata.get("recommended_result_item_id")
        options: list[ProjectExploreOptionView] = []
        for idea in sorted(ideas, key=lambda a: int((a.metadata or {}).get("option_ordinal", 0))):
            linked = [d for d in decisions if (d.metadata or {}).get("source_activity_id") == idea.activity_id]
            latest = max(linked, key=lambda d: (d.occurred_at_utc, d.created_at_utc, d.activity_id), default=None)
            related = [p for p in proposals if idea.activity_id in p.source_activity_ids]
            metadata = idea.metadata or {}
            decoded = _decode_option_details(idea.details)
            options.append(ProjectExploreOptionView(idea=idea, interaction_id=interaction_id,
                result_item_id=str(metadata["result_item_id"]), ordinal=int(metadata["option_ordinal"]),
                disposition=ProjectExploreDisposition(str((latest.metadata or {})["explore_disposition"])) if latest else None,
                disposition_activity=latest, disposition_history=linked,
                promoted=idea.activity_id in roadmaps,
                roadmap_activity=roadmaps.get(idea.activity_id), related_proposals=related,
                concept=decoded["concept"], proposed_changes=decoded["proposed_changes"],
                estimated_cost=_decode_estimated_cost(metadata.get("estimated_cost")),
                recommended=metadata.get("result_item_id") == recommended_result_item_id))
        complete = self._is_complete_group(ideas, result_activity)
        first_metadata = (ideas[0].metadata or {}) if ideas else result_metadata
        if result_activity is not None:
            decoded_result = _decode_result_details(result_activity.details, result_metadata)
            result_summary = str(decoded_result["summary"])
            recommendation_reason = str(decoded_result["recommendation_reason"])
            recommended_ordinal = result_metadata.get("recommended_ordinal")
            return ProjectExploreGroupView(interaction_id=interaction_id,
                idempotency_key=str(first_metadata.get("idempotency_key") or ""), complete=complete, options=options,
                title=result_activity.summary, summary=result_summary or None,
                observations=decoded_result["observations"],
                recommended_ordinal=recommended_ordinal if isinstance(recommended_ordinal, int) else None,
                recommendation_reason=recommendation_reason or None,
                next_steps=decoded_result["next_steps"],
                follow_up_questions=decoded_result["follow_up_questions"],
                result_activity=result_activity)
        return ProjectExploreGroupView(interaction_id=interaction_id,
            idempotency_key=str(first_metadata.get("idempotency_key") or ""), complete=complete, options=options)
