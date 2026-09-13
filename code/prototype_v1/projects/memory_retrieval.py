"""Stage 4 - Real Conversation Integration: question-aware retrieval over Stage 2's Structured
Project Memory (and Stage 1's Current Project State derivation), feeding normal ProjectConversation
turns. This is the seam that makes Stage 2/3 actually improve normal answers - Stage 2 remains the
one canonical Structured Project Memory substrate; Current Project State remains derived, never
persisted. Nothing here creates a second memory store, a second current-state store, or a competing
Context system - it only decides WHICH already-canonical records are relevant to THIS question and
renders them as a small, clearly-labeled bounded text block.

Deterministic-first, exactly like every prior stage: a continuation-style question always uses the
already-proven ProjectCurrentStateService global derivation (no new AI call beyond whatever that
service itself needs). A subject-specific question first tries an unambiguous deterministic keyword
match against known current subjects/categories; only when that is ambiguous or absent does one
bounded AI selection call decide which subject (if any) the question refers to and whether it wants
current or historical framing - the same "deterministic filter, AI selects among survivors" pattern
proven in Stages 1-3, never a canonical-truth decision by the model.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

from .models import (
    ProjectCurrentState,
    ProjectMemoryCategory,
    ProjectMemoryModality,
    ProjectMemoryRecord,
    ProjectMemoryStatus,
)
from .project_current_state import ProjectCurrentStateService

logger = logging.getLogger(__name__)

_MAX_SUBJECT_CANDIDATES = 12
_MAX_HISTORY_EVENTS = 8

_CONTINUATION_PHRASES = (
    "leave off", "left off", "what's next", "whats next", "what should i do next",
    "still need", "still needs", "still needed", "remain", "remains", "remaining",
    "where are we", "is anything blocking", "blocking the project", "what's blocking",
    "what have i completed", "what have we completed", "completed so far",
    "what should i do", "what needs to be done", "still to do",
)

_HISTORICAL_PHRASES = (
    "originally", "used to", "before we", "before the", "what did we decide",
    "why did", "why does", "why is", "what changed", "what was the original",
    "did we used to",
)

_CATEGORY_KEYWORDS: dict[str, tuple[ProjectMemoryCategory, ...]] = {
    "constraint": (ProjectMemoryCategory.CONSTRAINT, ProjectMemoryCategory.PREFERENCE),
    "constraints": (ProjectMemoryCategory.CONSTRAINT, ProjectMemoryCategory.PREFERENCE),
    "preference": (ProjectMemoryCategory.CONSTRAINT, ProjectMemoryCategory.PREFERENCE),
    "preferences": (ProjectMemoryCategory.CONSTRAINT, ProjectMemoryCategory.PREFERENCE),
}


def is_continuation_question(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(phrase in lowered for phrase in _CONTINUATION_PHRASES)


def is_historical_question(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(phrase in lowered for phrase in _HISTORICAL_PHRASES)


def _current_committed(records: list[ProjectMemoryRecord]) -> list[ProjectMemoryRecord]:
    return [r for r in records if r.status == ProjectMemoryStatus.CURRENT
            and r.modality == ProjectMemoryModality.COMMITTED]


def known_current_subjects(records: list[ProjectMemoryRecord]) -> list[tuple[str, str]]:
    """Distinct (scope, subject) pairs with at least one CURRENT+COMMITTED record - the bounded
    index a subject-specific question is matched against, deterministically or via AI selection."""
    seen: list[tuple[str, str]] = []
    seen_set: set[tuple[str, str]] = set()
    for record in _current_committed(records):
        key = (record.scope, record.subject)
        if key not in seen_set:
            seen_set.add(key)
            seen.append(key)
    return seen


def deterministic_subject_match(question_text: str, subjects: list[tuple[str, str]]) -> tuple[str, str] | None:
    """Only ever returns a match when it is UNAMBIGUOUS - a subject keyword appearing in exactly
    one (scope, subject) pair. Any ambiguity (the same subject name in two scopes, or none at all)
    falls through to the AI selection step rather than guessing."""
    lowered = str(question_text or "").lower()
    matches = [(scope, subject) for scope, subject in subjects if subject.replace("_", " ") in lowered]
    if len(matches) == 1:
        return matches[0]
    return None


def category_keyword_match(question_text: str) -> tuple[ProjectMemoryCategory, ...] | None:
    lowered = str(question_text or "").lower()
    for keyword, categories in _CATEGORY_KEYWORDS.items():
        if keyword in lowered:
            return categories
    return None


def _format_record(record: ProjectMemoryRecord) -> str:
    state = f" ({record.progress_state.value})" if record.progress_state else ""
    return f"[{record.scope}] {record.subject}/{record.slot}{state}: {record.value}"


_MAX_CATEGORY_RECORDS = 15


def render_category_context(records: list[ProjectMemoryRecord], categories: tuple[ProjectMemoryCategory, ...]) -> str | None:
    matching = [r for r in _current_committed(records) if r.category in categories]
    if not matching:
        return None
    # Bounded like every other rendering path here - most-recent first, capped - so a Project that
    # accumulates many constraints/preferences over time cannot make this payload grow unbounded.
    matching = sorted(matching, key=lambda r: r.occurred_at_utc, reverse=True)[:_MAX_CATEGORY_RECORDS]
    lines = [_format_record(r) for r in matching]
    return "CURRENT (confirmed):\n" + "\n".join(f"- {line}" for line in lines)


def render_subject_context(
    records: list[ProjectMemoryRecord], scope: str, subject: str, *, historical: bool,
    turn_text_lookup: Callable[[str], str | None] | None = None,
) -> str | None:
    subject_records = [r for r in records if r.scope == scope and r.subject == subject]
    if not subject_records:
        return None
    current = [r for r in subject_records if r.status == ProjectMemoryStatus.CURRENT
               and r.modality == ProjectMemoryModality.COMMITTED]
    if not historical:
        if not current:
            return None
        lines = [_format_record(r) for r in current]
        return "CURRENT (confirmed):\n" + "\n".join(f"- {line}" for line in lines)

    # The TRUE oldest record is identified BEFORE any truncation, and always shown - truncating
    # first (e.g. a naive `sorted(...)[-N:]`) can silently drop the actual original event for a
    # subject with many historical entries and mislabel a later event as "ORIGINAL", which is a
    # factually wrong answer to "what did we originally decide" (found during Stage 4 review).
    full_chain = sorted(subject_records, key=lambda r: r.occurred_at_utc)
    original_record = full_chain[0]
    recent_window = full_chain[-_MAX_HISTORY_EVENTS:]
    if original_record not in recent_window:
        omitted = len(full_chain) - len(recent_window) - 1
        displayed = [original_record]
        if omitted > 0:
            displayed.append(None)  # marker for an "N events omitted" line
        displayed.extend(recent_window)
    else:
        displayed = list(recent_window)

    def _label(record: ProjectMemoryRecord) -> str:
        # Only a CURRENT **and COMMITTED** record is the genuinely-still-true entry - a tentative/
        # hypothetical/third-party record can independently sit at status=CURRENT (Stage 2 never
        # supersedes a non-committed record), and must never share the "CURRENT" label with it or a
        # reader could treat an unconfirmed aside as equally authoritative (found during Stage 4
        # review: a tentative record chronologically mixed with a committed one both showed
        # "CURRENT / most recent" here before this fix).
        if record.status == ProjectMemoryStatus.CURRENT and record.modality == ProjectMemoryModality.COMMITTED:
            return "CURRENT / most recent"
        if record is original_record:
            return "ORIGINAL - later superseded" if record.status == ProjectMemoryStatus.SUPERSEDED else "ORIGINAL"
        if record.status == ProjectMemoryStatus.CURRENT:
            return "NOT SUPERSEDED, BUT NOT CONFIRMED - a separate aside, not the committed decision"
        return "superseded"

    lines = []
    for record in displayed:
        if record is None:
            lines.append(f"... ({omitted} earlier event(s) omitted) ...")
            continue
        modality_note = "" if record.modality == ProjectMemoryModality.COMMITTED else f" [{record.modality.value}, not confirmed]"
        entry = f"{_format_record(record)} - {_label(record)}{modality_note}"
        if turn_text_lookup is not None and record.source_turn_id:
            original_text = turn_text_lookup(record.source_turn_id)
            if original_text:
                entry += f' (said: "{original_text}")'
        lines.append(entry)
    # HISTORY is listed FIRST and CURRENT last for a historical question - deliberately, so a
    # question like "what did we ORIGINALLY decide" is not answered from whichever block a model
    # reads first; the entry explicitly labeled "ORIGINAL" is always the first real entry in this
    # list, and it is always the TRUE oldest event for this subject, never a truncation artifact.
    header = ("HISTORY for this subject, oldest to newest (the entry labeled ORIGINAL is what was "
              "first decided; only an entry labeled CURRENT / most recent is still true now - "
              "anything else, including an entry marked NOT CONFIRMED, is not current Project truth):")
    current_block = ("\n\nCURRENT (confirmed, still true now):\n" + "\n".join(f"- {_format_record(r)}" for r in current)
                      if current else "\n\nCURRENT: none - this decision has no committed current value.")
    return header + "\n" + "\n".join(f"- {line}" for line in lines) + current_block


def render_continuation_context(state: ProjectCurrentState) -> str:
    lines: list[str] = []
    if state.global_blockers:
        lines.append("BLOCKERS:\n" + "\n".join(f"- {b}" for b in state.global_blockers))
    if state.scope_summaries:
        lines.append("ACTIVE SCOPES:\n" + "\n".join(state.scope_summaries))
    if state.resolved_scope_count:
        lines.append(f"({state.resolved_scope_count} scope(s) fully resolved/completed, omitted for brevity)")
    if state.recent_changes:
        # These are prior/superseded values (or reopened progress), NOT current truth - the current
        # value for the same subject, if relevant, is already covered by ACTIVE SCOPES/DETAIL above.
        # Explicitly labeled here because the bare strings alone (found during Stage 4 review) read
        # as plain current facts and could otherwise be misinterpreted - a real run produced a
        # confusing sentence implying an old, already-superseded decision was still pending.
        lines.append("RECENT CHANGES (prior values that were since superseded/updated - NOT current truth):\n"
                      + "\n".join(f"- {c}" for c in state.recent_changes))
    for scope_name, detail in state.scope_detail.items():
        block = []
        if detail.active_progress:
            block.append("in progress: " + "; ".join(detail.active_progress))
        if detail.pending_decisions:
            block.append("pending follow-up: " + "; ".join(detail.pending_decisions))
        if detail.recently_completed:
            block.append("recently completed: " + "; ".join(detail.recently_completed))
        if block:
            lines.append(f"DETAIL [{scope_name}]: " + " | ".join(block))
    if not lines:
        return "No active Project state recorded yet."
    return "\n\n".join(lines)


_SELECTION_SYSTEM_PROMPT = """You are a conservative Structured-Project-Memory retrieval component \
for a persistent Project assistant. Given the user's current question, a little recent conversation \
context, and a bounded list of subjects the Project currently has committed information about \
(each with an index, scope, and a short current-value hint), decide:

- applicable: true only if the question is plausibly asking about the Project's current or \
historical state for one of these specific subjects, or is a broad "where do things stand" \
continuation question. False for anything else (small talk, an unrelated question, a new \
instruction).
- intent: "continuation" if this is a broad status/next-step/blocker question not about one \
specific subject; "current" if it asks what is presently true about one specific subject; \
"historical" if it asks what used to be true, why something changed, or what was originally \
decided about one specific subject.
- selected_subject_index: required (and must be a valid index) when intent is "current" or \
"historical" - use the recent conversation context to resolve pronouns/anaphora ("that", "it") to \
the right subject when possible. Omit or use null when intent is "continuation", or when you \
cannot confidently tell which subject is meant.

Never guess a specific subject when genuinely unclear - return applicable=false instead. Output \
ONLY a JSON object: {"applicable": true/false, "intent": "continuation"/"current"/"historical"/null, \
"selected_subject_index": <int or null>}."""


class ProjectMemoryRetrievalError(RuntimeError):
    pass


class ProjectMemoryRetrievalService:
    """One bounded real-provider call, only when deterministic subject/continuation matching could
    not confidently resolve the question on its own."""

    def __init__(self, *, api_key: str, model: str = "gpt-4.1-mini",
                 timeout_seconds: float = 20.0, client_factory=None):
        if not str(api_key or "").strip():
            raise ProjectMemoryRetrievalError("OPENAI_API_KEY is required for memory retrieval.")
        if client_factory is None:
            try:
                from openai import OpenAI
            except Exception as exc:  # pragma: no cover
                raise ProjectMemoryRetrievalError("OpenAI SDK is unavailable.") from exc
            client_factory = OpenAI
        self._client = client_factory(api_key=api_key.strip(), timeout=float(timeout_seconds))
        self._model = str(model or "gpt-4.1-mini").strip()

    def select(
        self, *, question_text: str, prior_turns_text: str, subjects: list[tuple[str, str]],
        records: list[ProjectMemoryRecord],
    ) -> "MemorySelection | None":
        if not subjects:
            return None
        bounded = subjects[:_MAX_SUBJECT_CANDIDATES]
        lines = []
        for index, (scope, subject) in enumerate(bounded):
            current = [r for r in records if r.scope == scope and r.subject == subject
                       and r.status == ProjectMemoryStatus.CURRENT and r.modality == ProjectMemoryModality.COMMITTED]
            hint = current[0].value if current else "(no current value)"
            lines.append(f"{index}: scope={scope}, subject={subject}, current_value={hint!r}")
        numbered = "\n".join(lines)
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SELECTION_SYSTEM_PROMPT},
                    {"role": "user", "content": (
                        f"Recent conversation:\n{prior_turns_text or '(none)'}\n\n"
                        f"Current question: {question_text}\n\nKnown subjects:\n{numbered}")},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            parsed = json.loads(response.choices[0].message.content or "{}")
        except Exception:  # noqa: BLE001 - retrieval failure must degrade, never raise into the turn
            logger.warning("Project memory retrieval selection failed; proceeding without structured memory context.")
            return None

        if not isinstance(parsed, dict) or not parsed.get("applicable"):
            return None
        intent = parsed.get("intent")
        if intent not in ("continuation", "current", "historical"):
            return None
        if intent == "continuation":
            return MemorySelection(intent="continuation", scope=None, subject=None)
        index = parsed.get("selected_subject_index")
        if not isinstance(index, int) or not (0 <= index < len(bounded)):
            return None
        scope, subject = bounded[index]
        return MemorySelection(intent=intent, scope=scope, subject=subject)


@dataclass(frozen=True)
class MemorySelection:
    intent: str  # "continuation" | "current" | "historical"
    scope: str | None
    subject: str | None


@dataclass(frozen=True)
class MemoryRetrievalResult:
    context_text: str | None = None
    intent: str | None = None
    subject: str | None = None


def retrieve_memory_context(
    *, project_id: str, records: list[ProjectMemoryRecord], question_text: str,
    prior_turns_text: str = "", current_state_service: ProjectCurrentStateService | None = None,
    selection_service: ProjectMemoryRetrievalService | None = None,
    turn_text_lookup: Callable[[str], str | None] | None = None,
) -> MemoryRetrievalResult:
    """Main entry point: deterministic-first question-aware retrieval over Structured Project
    Memory. Returns a fully "nothing relevant" result (cheap, no calls) whenever the Project has no
    current committed memory yet, or nothing about the question resolves confidently."""
    if not _current_committed(records):
        return MemoryRetrievalResult()

    category_match = category_keyword_match(question_text)
    if category_match is not None:
        text = render_category_context(records, category_match)
        if text is not None:
            return MemoryRetrievalResult(context_text=text, intent="current", subject=None)

    subjects = known_current_subjects(records)
    subject_match = deterministic_subject_match(question_text, subjects)
    if subject_match is not None:
        scope, subject = subject_match
        historical = is_historical_question(question_text)
        text = render_subject_context(records, scope, subject, historical=historical, turn_text_lookup=turn_text_lookup)
        if text is not None:
            return MemoryRetrievalResult(context_text=text, intent="historical" if historical else "current", subject=subject)

    if is_continuation_question(question_text) and current_state_service is not None:
        state = current_state_service.get_current_state(project_id, records)
        return MemoryRetrievalResult(context_text=render_continuation_context(state), intent="continuation", subject=None)

    if selection_service is not None:
        selection = selection_service.select(
            question_text=question_text, prior_turns_text=prior_turns_text, subjects=subjects, records=records)
        if selection is not None:
            if selection.intent == "continuation" and current_state_service is not None:
                state = current_state_service.get_current_state(project_id, records)
                return MemoryRetrievalResult(context_text=render_continuation_context(state), intent="continuation", subject=None)
            if selection.scope is not None and selection.subject is not None:
                text = render_subject_context(
                    records, selection.scope, selection.subject,
                    historical=selection.intent == "historical", turn_text_lookup=turn_text_lookup)
                if text is not None:
                    return MemoryRetrievalResult(context_text=text, intent=selection.intent, subject=selection.subject)

    return MemoryRetrievalResult()
