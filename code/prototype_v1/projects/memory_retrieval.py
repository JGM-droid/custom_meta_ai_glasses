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
import re
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

_WORD_RE = re.compile(r"[a-z]+")


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(str(text or "").lower())


def _has_token_sequence(tokens: list[str], pattern: tuple) -> bool:
    """True if `tokens` contains every slot of `pattern`, IN ORDER, as a subsequence - each slot is
    either a single token or a tuple of acceptable alternative tokens for that position. Unlike
    literal substring matching, arbitrary other words (filler like "actually", "right now", a name)
    may appear before, between, or after the anchors without breaking the match - this is exactly
    what a fixed phrase list cannot tolerate (see the Stage 5 "is anything actually blocking me"
    regression this replaces). Order is still required, which keeps false-positive risk low: a
    two-or-more-word pattern only fires when its anchors appear in the SAME relative order a real
    instance of that phrasing would use, not merely somewhere in the same sentence."""
    pos = 0
    for slot in pattern:
        options = (slot,) if isinstance(slot, str) else slot
        matched_at = None
        for i in range(pos, len(tokens)):
            if tokens[i] in options:
                matched_at = i
                break
        if matched_at is None:
            return False
        pos = matched_at + 1
    return True


def _matches_any_pattern(text: str, patterns: tuple) -> bool:
    tokens = _tokenize(text)
    return any(_has_token_sequence(tokens, pattern) for pattern in patterns)


# Token-sequence patterns for a broad "continuation / current Project state" question - deliberately
# NOT a list of exact substrings, since natural phrasing routinely inserts filler words a literal
# match can't tolerate ("is anything blocking me" vs. "is anything ACTUALLY blocking me RIGHT NOW").
# Each pattern is a tuple of slots; a slot is one token or a tuple of acceptable alternatives; a
# pattern matches when its slots appear, in order, anywhere in the question. Kept as several narrow,
# multi-anchor patterns (mostly 2+ required words) rather than single common words, so this stays
# selective - a bare "what" or "did" is never enough on its own to trigger.
_CONTINUATION_TOKEN_PATTERNS = (
    # "is anything blocking", "any blockers", "am I stuck", "what's the holdup"
    (("blocking", "blocker", "blockers", "blocked", "stuck", "holdup", "holdups"),),
    ("holding", "up"),  # "what's holding this up"
    (("remain", "remains", "remaining"),),
    (("leave", "left"), "off"),  # "leave off" / "left off"
    ("where", "we"),  # "where are we", "where did we leave off"
    ("what", "next"),  # "what's next", "what should I do next"
    ("should", ("do", "focus")),  # "what should I do", "what should I focus on now"
    ("still", ("need", "needs", "needed", "open", "to", "going", "working", "todo")),
    (("completed", "complete", "finished", "finish", "done"), ("so", "far")),  # "completed so far"
    (("completed", "complete", "finished", "finish"),),  # bare "finished"/"completed" is unambiguous
)

# Same technique for historical framing ("originally", "why did that change") - preserved as its own
# distinct intent, not merged into continuation: a historical question wants the PAST record and an
# explanation of a change, a continuation question wants the CURRENT derived state.
_HISTORICAL_TOKEN_PATTERNS = (
    ("originally",),
    ("used", "to"),
    ("before", ("we", "the")),
    ("what", "did", "we", "decide"),
    ("why", ("did", "does", "is", "was")),
    ("what", "changed"),
    ("what", "was", "the", "original"),
    ("what", "original"),
)

_CATEGORY_KEYWORDS: dict[str, tuple[ProjectMemoryCategory, ...]] = {
    "constraint": (ProjectMemoryCategory.CONSTRAINT, ProjectMemoryCategory.PREFERENCE),
    "constraints": (ProjectMemoryCategory.CONSTRAINT, ProjectMemoryCategory.PREFERENCE),
    "preference": (ProjectMemoryCategory.CONSTRAINT, ProjectMemoryCategory.PREFERENCE),
    "preferences": (ProjectMemoryCategory.CONSTRAINT, ProjectMemoryCategory.PREFERENCE),
}


def is_continuation_question(text: str) -> bool:
    return _matches_any_pattern(text, _CONTINUATION_TOKEN_PATTERNS)


def is_historical_question(text: str) -> bool:
    return _matches_any_pattern(text, _HISTORICAL_TOKEN_PATTERNS)


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


_MAX_KNOWN_SUBJECT_HINTS = 20


def known_subject_hints(
    records: list[ProjectMemoryRecord], *, limit: int = _MAX_KNOWN_SUBJECT_HINTS,
) -> list[tuple[str, str, str, str]]:
    """Stage 5 repair (subject-identity stabilization): a bounded, most-recent-first list of
    (scope, subject, slot, current_value) hints for existing canonical subjects - handed to
    extraction so a new statement about the SAME real-world item, worded differently, can reuse the
    existing identity instead of silently forking a second, disconnected one (the exact failure
    dogfooding found: "accent_wall"/"wall_paint_color"/"wall_painting"/"paint_purchase" all
    describing one real-world paint job). The slot is included, not just scope/subject: a
    same-item update must land on the SAME slot to actually supersede/append correctly (a progress
    subject given a NEW slot name instead of its existing one silently creates a second,
    independently-"current" progress line for the same real-world task - e.g. an already-resolved
    blocker still showing as an active blocker under its old slot while a resolution sits, unseen,
    under a new one). Deliberately bounded like every other candidate list in this module - never
    the whole Project's memory, and this hands the model a shortlist to MATCH against, never a
    mandate to merge unrelated items."""
    committed = _current_committed(records)
    committed.sort(key=lambda r: r.occurred_at_utc, reverse=True)
    seen: list[tuple[str, str, str, str]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for record in committed:
        key = (record.scope, record.subject, record.slot)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        seen.append((record.scope, record.subject, record.slot, record.value))
        if len(seen) >= limit:
            break
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
historical state for one of these SPECIFIC LISTED subjects, or is a broad "where do things stand" \
continuation question. If the question clearly names or refers to a topic/item that is NOT among \
the listed subjects - even if the question's phrasing otherwise sounds exactly like a historical or \
current-state question ("didn't we originally decide X", "why did X change") - return \
applicable=false. NEVER select the closest-sounding, most-recent, or otherwise "least bad" listed \
subject as a stand-in for a topic that genuinely is not represented in the list; an unrelated \
subject (e.g. a budget record) must never be presented as if it answers a question about a \
completely different item (e.g. a TV stand) the list does not contain. False for anything else \
(small talk, an unrelated question, a new instruction, or a topic simply absent from the list).
- intent: "continuation" if this is a broad status/next-step/blocker question not about one \
specific subject; "current" if it asks what is presently true about one specific subject; \
"historical" if it asks what used to be true, why something changed, or what was originally \
decided about one specific subject.
- selected_subject_index: required (and must be a valid index) when intent is "current" or \
"historical" - use the recent conversation context to resolve pronouns/anaphora ("that", "it") to \
the right subject when possible, but only when the referent is actually identifiable from the \
question or recent conversation text - never guess a plausible-sounding subject with no textual \
basis. Omit or use null when intent is "continuation", or when you cannot confidently tell which \
subject is meant.

Never guess a specific subject when genuinely unclear, and never substitute an unrelated subject \
for one that is simply missing from the list - return applicable=false instead in both cases. \
Output ONLY a JSON object: {"applicable": true/false, "intent": \
"continuation"/"current"/"historical"/null, "selected_subject_index": <int or null>}."""

# Stage 5 repair: a question that clearly LOOKS like it wants durable Project history/current-state
# (matches the same historical-phrase heuristic used elsewhere) but for which nothing could be
# grounded - not silently omitted, because silence here is exactly what let the model fall back on
# its own unsupported inference and confidently invert a real decision (found during Stage 5
# dogfooding: a TV-stand question with no durable record produced a confident, backwards answer).
_NO_RELEVANT_MEMORY_NOTICE = (
    "NO_RELEVANT_MEMORY: No durable Structured Project Memory record was found specifically "
    "matching this question's topic. This does NOT mean the Project definitely never contained "
    "this information - it means no confirmed durable record currently covers it. Check the "
    "recent conversation above; if that does not clearly answer it either, say honestly that you "
    "do not have enough durable Project history to verify this confidently, rather than guessing "
    "or asserting a specific historical or current claim."
)


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


def _selection_is_grounded(selection: MemorySelection, question_text: str, prior_turns_text: str) -> bool:
    """Deterministic, generic post-hoc sanity check on the AI selection's subject choice - a real
    safety net (not topic-specific) against exactly the failure Stage 5 dogfooding found: the model
    selecting an unrelated known subject (e.g. "budget") for a question about a completely
    different, unknown topic (e.g. a TV stand) rather than abstaining. A continuation selection
    (subject=None) makes no specific-subject claim, so nothing to check. A subject selection is
    trusted only if its own name is actually findable in the current question, or in something the
    USER themselves said in the bounded recent conversation - never merely because it appears
    somewhere in an assistant's own reply. This distinction matters: an assistant recap/summary turn
    routinely lists many unrelated topics side by side (budget, TV stand, accent wall, ...), and a
    keyword's mere presence in that kind of list is not evidence the CURRENT question is about it -
    this is exactly how the real "budget substituted for a TV stand question" bug kept recurring
    even after this check first shipped. Legitimate anaphora ("why did that change" -> tv_stand)
    still passes, since a real referent was, by construction, raised by the user themselves
    somewhere in that same bounded text."""
    if selection.subject is None:
        return True
    keyword = selection.subject.replace("_", " ")
    if not keyword:
        return False
    if keyword in question_text.lower():
        return True
    user_said = "\n".join(
        line.split(":", 1)[1] for line in prior_turns_text.splitlines() if line.lower().startswith("user:")
    )
    return keyword in user_said.lower()


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
        if selection is not None and not _selection_is_grounded(selection, question_text, prior_turns_text):
            # The AI selected a subject with no textual basis in the question or recent
            # conversation - exactly the "unrelated record presented as evidence" failure found
            # during Stage 5 dogfooding. Discard it and fall through to the honesty-notice path
            # below, never trusting an ungrounded pick.
            logger.warning(
                "Discarding ungrounded memory selection (subject=%r not found in question/recent context).",
                selection.subject)
            selection = None
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
        # Stage 5 repair: nothing could be grounded for a question that looks like it wants durable
        # Project history - stay honest rather than silent, so the model does not quietly fall back
        # on its own unsupported inference (which previously produced a confident, backwards claim
        # about a real decision). Bounded and generic - never names the missing topic itself.
        if is_historical_question(question_text):
            return MemoryRetrievalResult(context_text=_NO_RELEVANT_MEMORY_NOTICE, intent="not_found", subject=None)

    return MemoryRetrievalResult()
