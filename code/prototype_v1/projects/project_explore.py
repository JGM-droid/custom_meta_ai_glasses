from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from typing import Protocol
from uuid import UUID, uuid5

from pydantic import ValidationError

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency fallback
    OpenAI = None  # type: ignore[assignment]

from .activity_store import ProjectActivityNotFound, ProjectActivityStore
from .checkpoint_proposal_store import CheckpointProposalStore
from .models import (
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
PROVIDER_RESULT_SCHEMA_VERSION = "1.0"


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


class OpenAIProjectExploreProvider:
    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 45.0, client_factory=OpenAI):
        if not str(api_key or "").strip():
            raise ProjectExploreProviderUnavailable("OPENAI_API_KEY is required for Explore execution.")
        self._api_key = api_key.strip()
        self._model = str(model or "gpt-4.1-mini").strip() or "gpt-4.1-mini"
        self._timeout_seconds = float(timeout_seconds)
        self._client_factory = client_factory

    def identity(self) -> ProjectExploreProviderIdentity:
        return ProjectExploreProviderIdentity(provider="openai", model=self._model, tool="chat.completions")

    def explore(self, context_pack: ProjectExploreContextPack) -> str:
        if self._client_factory is None:
            raise ProjectExploreProviderUnavailable("OpenAI SDK is unavailable.")
        schema = {
            "schema_version": PROVIDER_RESULT_SCHEMA_VERSION,
            "allowed_results": ["OPTION_SET", "INFORMATION_REQUEST"],
            "option_set": "Exactly three options with ordinals 1, 2, 3; fields title, summary, optional rationale/tradeoffs, source_refs.",
            "information_request": "title, prompt, requested_inputs, source_refs; no continuation key.",
            "rules": "Use only supplied source reference activity IDs. Do not prescribe mutations or device actions.",
        }
        client = self._client_factory(api_key=self._api_key)
        try:
            response = client.chat.completions.create(
                model=self._model,
                temperature=0.0,
                response_format={"type": "json_object"},
                timeout=self._timeout_seconds,
                messages=[
                    {"role": "system", "content": "Return only one strict JSON object matching the supplied Explore schema. Never invent project facts or source references."},
                    {"role": "user", "content": json.dumps({"schema": schema, "context_pack": context_pack.__dict__}, ensure_ascii=False, default=list)},
                ],
            )
        except Exception as exc:
            raise ProjectExploreProviderUnavailable("Explore provider request failed.") from exc
        return str(response.choices[0].message.content or "").strip()


def load_project_explore_model_name() -> str:
    return str(os.environ.get("PROJECT_EXPLORE_OPENAI_MODEL") or "gpt-4.1-mini").strip() or "gpt-4.1-mini"


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
    def _request_fingerprint(request: ProjectExploreRequest) -> str:
        canonical = json.dumps({"user_intent": request.user_intent, "input_refs": request.input_refs}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _option_details(option: ProjectExploreProviderOption) -> str:
        parts = [option.summary]
        if option.rationale:
            parts.append(f"Rationale: {option.rationale}")
        if option.tradeoffs:
            parts.append(f"Tradeoffs: {option.tradeoffs}")
        return "\n\n".join(parts)

    def _group_activities(self, project_id: str, interaction_id: str) -> list[ProjectActivity]:
        return [a for a in self.activity_store.list_activities(project_id)
                if a.activity_type == ProjectActivityType.IDEA
                and (a.metadata or {}).get("interaction_type") == INTERACTION_TYPE
                and (a.metadata or {}).get("interaction_id") == interaction_id]

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
    def _parse_result(raw: str | dict[str, object], allowed_refs: set[str]) -> ProjectExploreOptionSet | ProjectExploreInformationRequest:
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
                if [item.ordinal for item in result.options] != [1, 2, 3]:
                    raise ProjectExploreInvalidResult("OPTION_SET ordinals must be exactly 1, 2, 3 in order.")
                normalized_titles = [" ".join(item.title.lower().split()) for item in result.options]
                normalized_content = [" ".join((item.title + " " + item.summary).lower().split()) for item in result.options]
                if len(set(normalized_titles)) != 3 or len(set(normalized_content)) != 3:
                    raise ProjectExploreInvalidResult("OPTION_SET options must be distinct.")
                refs = result.source_refs + [ref for option in result.options for ref in option.source_refs]
            elif result_type == "INFORMATION_REQUEST":
                result = ProjectExploreInformationRequest.model_validate(parsed)
                refs = result.source_refs
            else:
                raise ProjectExploreInvalidResult("Unknown Explore result_type.")
        except ValidationError as exc:
            raise ProjectExploreInvalidResult("Explore provider result failed strict validation.") from exc
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
            existing = self._group_activities(normalized_project_id, interaction_id)
            if existing:
                stored_fingerprints = {(a.metadata or {}).get("request_fingerprint") for a in existing}
                if stored_fingerprints != {fingerprint}:
                    raise ProjectExploreIdempotencyConflict("idempotency_key was already used with a different request.")
                ordinals = [(a.metadata or {}).get("option_ordinal") for a in existing]
                if len(existing) > 3 or any(not isinstance(item, int) or item not in {1, 2, 3} for item in ordinals) or len(set(ordinals)) != len(ordinals):
                    raise ProjectExploreRecoveryConflict("Incomplete Explore options have invalid projection identities.")
                if self._is_complete_group(existing):
                    group = self._project_group(normalized_project_id, interaction_id, existing)
                    return ProjectExploreExecutionResponse(project_id=normalized_project_id, interaction_id=interaction_id,
                        result_type="OPTION_SET", suggestions_created=True, message="Three AI suggestions are available and remain unconfirmed.", option_set=group)

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
            if existing:
                context_fingerprints = {(a.metadata or {}).get("context_fingerprint") for a in existing}
                provider_identities = {(
                    (a.metadata or {}).get("provider"),
                    (a.metadata or {}).get("provider_model"),
                    (a.metadata or {}).get("provider_tool"),
                ) for a in existing}
                if context_fingerprints != {context_fingerprint} or provider_identities != {(
                    provider_identity.provider, provider_identity.model, provider_identity.tool
                )}:
                    raise ProjectExploreRecoveryConflict("Incomplete Explore options were created from a different execution context.")
            result = self._parse_result(self.provider.explore(context), {a["activity_id"] for a in context.input_activities} | {a["activity_id"] for a in context.relevant_context})
            if isinstance(result, ProjectExploreInformationRequest):
                if existing:
                    raise ProjectExploreRecoveryConflict("Incomplete Explore options could not be recovered from a non-option result.")
                return ProjectExploreExecutionResponse(project_id=normalized_project_id, interaction_id=None,
                    result_type="INFORMATION_REQUEST", suggestions_created=False,
                    message="More information is needed. No suggestions were created.", information_request=result)

            if existing:
                self._verify_matching_partial(existing, result)
            for option in result.options:
                result_item_id = str(uuid5(UUID(interaction_id), f"option:{option.ordinal}"))
                activity_id = str(uuid5(UUID(result_item_id), "idea"))
                refs_csv = ",".join(option.source_refs)
                request_activity = ProjectActivityCreateRequest(
                    activity_type=ProjectActivityType.IDEA,
                    source_type=ProjectActivitySourceType.AI,
                    confirmation_status=ProjectActivityConfirmationStatus.INFERRED,
                    summary=option.title,
                    details=self._option_details(option),
                    metadata={"idea_state": "captured", "interaction_id": interaction_id,
                              "interaction_type": INTERACTION_TYPE, "idempotency_key": request.idempotency_key,
                              "request_fingerprint": fingerprint, "result_item_id": result_item_id,
                              "option_ordinal": option.ordinal, "explore_group_size": 3,
                              "context_contract": EXPLORE_CONTEXT_CONTRACT,
                              "context_fingerprint": context_fingerprint,
                              "provider": provider_identity.provider, "provider_model": provider_identity.model,
                              "provider_tool": provider_identity.tool, "source_refs": refs_csv},
                )
                activity, created = self.activity_store.create_activity_with_id(normalized_project_id, activity_id, request_activity)
                if not created and not self._activity_matches_option(activity, option, fingerprint, interaction_id):
                    raise ProjectExploreRecoveryConflict("Existing Explore projection conflicts with the validated recovery result.")
            complete = self._group_activities(normalized_project_id, interaction_id)
            return ProjectExploreExecutionResponse(project_id=normalized_project_id, interaction_id=interaction_id,
                result_type="OPTION_SET", suggestions_created=True,
                message="Three AI suggestions were created and remain unconfirmed.",
                option_set=self._project_group(normalized_project_id, interaction_id, complete))

    @staticmethod
    def _is_complete_group(group: list[ProjectActivity]) -> bool:
        return len(group) == 3 and sorted((a.metadata or {}).get("option_ordinal") for a in group) == [1, 2, 3]

    def _activity_matches_option(self, activity: ProjectActivity, option: ProjectExploreProviderOption,
                                 fingerprint: str, interaction_id: str) -> bool:
        metadata = activity.metadata or {}
        return (activity.activity_type == ProjectActivityType.IDEA
                and activity.source_type == ProjectActivitySourceType.AI
                and activity.confirmation_status == ProjectActivityConfirmationStatus.INFERRED
                and activity.summary == option.title and activity.details == self._option_details(option)
                and metadata.get("interaction_id") == interaction_id
                and metadata.get("request_fingerprint") == fingerprint
                and metadata.get("option_ordinal") == option.ordinal
                and metadata.get("source_refs") == ",".join(option.source_refs))

    def _verify_matching_partial(self, existing: list[ProjectActivity], result: ProjectExploreOptionSet) -> None:
        by_ordinal = {option.ordinal: option for option in result.options}
        for activity in existing:
            ordinal = (activity.metadata or {}).get("option_ordinal")
            option = by_ordinal.get(ordinal) if isinstance(ordinal, int) else None
            fingerprint = str((activity.metadata or {}).get("request_fingerprint") or "")
            interaction_id = str((activity.metadata or {}).get("interaction_id") or "")
            if option is None or not self._activity_matches_option(activity, option, fingerprint, interaction_id):
                raise ProjectExploreRecoveryConflict("Validated recovery result diverges from existing Explore options.")

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
        groups: dict[str, list[ProjectActivity]] = {}
        for activity in activities:
            metadata = activity.metadata or {}
            if activity.activity_type == ProjectActivityType.IDEA and metadata.get("interaction_type") == INTERACTION_TYPE:
                groups.setdefault(str(metadata.get("interaction_id")), []).append(activity)
        complete = [(interaction_id, group) for interaction_id, group in groups.items() if self._is_complete_group(group)]
        projected = [self._project_group(normalized_project_id, interaction_id, group, activities=activities)
                     for interaction_id, group in complete]
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
        all_explore_idea_ids = {activity.activity_id for group in groups.values() for activity in group}
        pending = any(
            proposal.status.value == "pending"
            and bool(all_explore_idea_ids.intersection(proposal.source_activity_ids))
            for proposal in self.proposal_store.list_proposals(normalized_project_id)
        )
        has_incomplete = any(not self._is_complete_group(group) for group in groups.values())
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

    def _project_group(self, project_id: str, interaction_id: str, group: list[ProjectActivity],
                       *, activities: list[ProjectActivity] | None = None) -> ProjectExploreGroupView:
        all_activities = activities if activities is not None else self.activity_store.list_activities(project_id)
        decisions = [a for a in all_activities if a.activity_type == ProjectActivityType.DECISION
                     and (a.metadata or {}).get("explore_disposition") in {d.value for d in ProjectExploreDisposition}]
        roadmaps = {str((a.metadata or {}).get(PROMOTED_FROM_METADATA_KEY)): a for a in all_activities
                    if (a.metadata or {}).get(PROMOTED_FROM_METADATA_KEY)}
        proposals = self.proposal_store.list_proposals(project_id)
        options: list[ProjectExploreOptionView] = []
        for idea in sorted(group, key=lambda a: int((a.metadata or {}).get("option_ordinal", 0))):
            linked = [d for d in decisions if (d.metadata or {}).get("source_activity_id") == idea.activity_id]
            latest = max(linked, key=lambda d: (d.occurred_at_utc, d.created_at_utc, d.activity_id), default=None)
            related = [p for p in proposals if idea.activity_id in p.source_activity_ids]
            metadata = idea.metadata or {}
            options.append(ProjectExploreOptionView(idea=idea, interaction_id=interaction_id,
                result_item_id=str(metadata["result_item_id"]), ordinal=int(metadata["option_ordinal"]),
                disposition=ProjectExploreDisposition(str((latest.metadata or {})["explore_disposition"])) if latest else None,
                disposition_activity=latest, disposition_history=linked,
                promoted=idea.activity_id in roadmaps,
                roadmap_activity=roadmaps.get(idea.activity_id), related_proposals=related))
        first_metadata = group[0].metadata or {}
        return ProjectExploreGroupView(interaction_id=interaction_id,
            idempotency_key=str(first_metadata.get("idempotency_key") or ""), complete=self._is_complete_group(group), options=options)
