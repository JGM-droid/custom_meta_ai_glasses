"""Memory Extraction (Stage 2 - shadow slice).

ProjectConversation turn -> Memory Extraction -> structured candidate(s) ->
deterministic application-side validation -> shadow ProjectMemoryStore write.

The model NEVER mutates canonical Project state directly - it only proposes
candidates (`ProjectMemoryCandidate`), which `ProjectMemoryExtractionService`
validates deterministically (schema, modality, scope defaulting) before
`ProjectMemoryStore.write_candidate` applies the supersession rule. One
bounded extraction call per eligible turn - no agent loop, no second call for
routing/classification.

System prompt design is deliberately conservative (extraction precision
matters far more than recall - see docs/PROJECT_MEMORY_ARCHITECTURE.md's
Stage 1/extraction falsification findings): abstain (return no candidates)
rather than guess a durable subject for an ambiguous reference, and never
promote a tentative/hypothetical/third-party statement to COMMITTED.
"""
from __future__ import annotations

import json
import logging

from .models import ProjectMemoryCandidate

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a conservative memory-extraction component for a persistent Project \
assistant. Given one user message, extract zero or more durable Project facts, constraints, \
preferences, decisions, or progress updates worth remembering across the whole Project's \
lifetime - not routine conversational filler, not questions, not the assistant's own text.

For each item, output:
- category: one of fact, constraint, preference, decision, progress
- scope: a short lowercase identifier for the Project area/workstream this belongs to (e.g. \
"living_room", "unit_412", "electrical") - use "overall" if the statement is not about a \
specific area
- subject: a short lowercase identifier for what this is about (e.g. "budget", "tv_stand", "rug")
- slot: a short lowercase identifier for which aspect of the subject this is (e.g. "amount", \
"disposition", "procurement") - use "value" if there is no meaningful further breakdown. \
IMPORTANT for a "replace/swap/change X for/to/with Y"-style statement about an item's fate: put \
the WHOLE outcome ("replace with warm wood", not just "warm wood") on that item's "disposition" \
slot - do not park it under a separate slot like "material"/"style" while leaving "disposition" \
stuck at an earlier, now-stale value ("keep"). A reader must be able to tell the item's current \
fate from the "disposition" slot alone, without cross-referencing another slot.
- value: the actual content, in your own concise words
- modality: exactly one of committed, tentative, historical, hypothetical, conditional, \
third_party
- progress_state: required ONLY when category is "progress" - one of planned, started, blocked, \
completed, abandoned, reopened. Omit entirely for every other category.
- is_blocker: true only if this describes something actively preventing other work from \
proceeding (e.g. a safety issue blocking an inspection). Default false.

Modality rules, be strict:
- committed: the user is stating their OWN current, direct, first-person intent or fact in \
plain declarative language ("my budget is $1,500", "we're keeping the couch", "I ordered the \
rug"). Only committed items are eligible to become durable current Project truth.
- tentative: hedged language ("I might", "maybe", "I'm not sure", "I think").
- historical: explicitly framed as past, no longer necessarily true now ("I used to have...", \
"we originally planned...").
- hypothetical: an "if" scenario or speculative aside not describing an actual decision.
- conditional: a decision contingent on something not yet known/true.
- third_party: someone other than the user is the source of the opinion/suggestion ("my \
friend thinks...", "John said...").

Never extract from third-party, hypothetical, or tentative language as if it were the user's \
own committed decision. Never extract anything from a plain question the user is asking you - \
a question restating known facts ("what was my budget again?") produces nothing, not a new \
fact. If a statement's subject is genuinely ambiguous (e.g. "I like that one better" referring \
to an unspecified prior option with no way to resolve which one from this message alone), \
extract nothing for it rather than guessing. This includes a PLURAL or anaphoric correction \
referring to more than one prior item at once (e.g. "those are both already done", "we don't \
need either of those anymore") when this single message alone does not make it unambiguous which \
specific subjects are meant - extract nothing rather than guessing which items the user means.

You may be given a bounded list of EXISTING KNOWN SUBJECTS already tracked for this Project, each \
shown as "scope/subject/slot: current value". If the new message clearly refers to the SAME \
real-world item, decision, or task as one of these - even if worded completely differently (e.g. \
"the wall" for "wall_painting", "the old server" for "server", "it" resolved from context) - reuse \
that EXACT scope, subject, and slot shown for it (e.g. "I finished painting the wall" then later \
"actually only got halfway done" are both updates to the SAME painting task, so both belong on that \
item's existing progress slot, not a new slot of your own choosing). This still only changes WHICH \
scope/subject/slot you write to - the value itself should still be your own concise wording of what \
the user actually said, exactly as you would write it with no hint at all. Only reuse an existing \
subject (and slot) when you are reasonably confident the new statement is about that SAME specific \
item or task, not merely the same general area or topic - a statement describing a DIFFERENT, \
additional task or issue in that area (even one that is related to or caused by the existing \
subject) must get its own new subject, never be folded into an existing one. This matters most for \
progress: an existing blocked/in-progress item must never be silently overwritten by a newer, \
unrelated follow-up task update that happens to share a general topic - if in doubt whether two \
statements describe the same task or two different ones, treat them as different (new subject) \
rather than merging them. If it is genuinely unclear whether a statement refers to an existing \
subject or a new one, or which of two existing subjects it means, do not force a match - fall back \
to your own best new scope/subject choice if the item itself is clearly identifiable, or extract \
nothing if the reference itself is ambiguous per the rule above. Never merge two genuinely \
different real-world items into one subject merely because they seem topically related.

Output ONLY a JSON object: {"candidates": [{"category": "...", "scope": "...", "subject": \
"...", "slot": "...", "value": "...", "modality": "...", "progress_state": "..." (omit if not \
progress), "is_blocker": false}, ...]} - use "candidates": [] if nothing qualifies."""


class ProjectMemoryExtractionError(RuntimeError):
    pass


class ProjectMemoryExtractionService:
    """One bounded real-provider call per eligible turn. Deliberately not a
    multi-step agent - a single JSON-mode chat completion, exactly like the
    falsification experiments that proved this approach."""

    def __init__(self, *, api_key: str, model: str = "gpt-4.1-mini",
                 timeout_seconds: float = 20.0, client_factory=None):
        if not str(api_key or "").strip():
            raise ProjectMemoryExtractionError("OPENAI_API_KEY is required for memory extraction.")
        if client_factory is None:
            try:
                from openai import OpenAI
            except Exception as exc:  # pragma: no cover
                raise ProjectMemoryExtractionError("OpenAI SDK is unavailable.") from exc
            client_factory = OpenAI
        self._client = client_factory(api_key=api_key.strip(), timeout=float(timeout_seconds))
        self._model = str(model or "gpt-4.1-mini").strip()

    def extract(
        self, user_text: str, known_subjects: list[tuple[str, str, str, str]] | None = None,
    ) -> list[ProjectMemoryCandidate]:
        """known_subjects, when given, is a bounded (scope, subject, slot, current_value) shortlist
        the caller already narrowed (see memory_retrieval.known_subject_hints) - a hint for the
        model to REUSE an existing identity (and its EXACT slot) for the same real-world item, never
        a mandate to merge unrelated ones. None/empty preserves the exact prior single-message
        prompt shape."""
        text = str(user_text or "").strip()
        if not text:
            return []
        if known_subjects:
            hint_lines = "\n".join(
                f"- {scope}/{subject}/{slot}: {value!r}" for scope, subject, slot, value in known_subjects)
            user_content = f"Existing known subjects for this Project:\n{hint_lines}\n\nUser message: {text}"
        else:
            user_content = text
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            raw = response.choices[0].message.content
        except Exception as exc:  # noqa: BLE001 - shadow path must never raise into the real turn
            raise ProjectMemoryExtractionError(f"Memory extraction call failed: {exc}") from exc

        try:
            parsed = json.loads(raw or "{}")
        except (TypeError, ValueError) as exc:
            raise ProjectMemoryExtractionError("Memory extraction returned invalid JSON.") from exc

        raw_candidates = parsed.get("candidates") if isinstance(parsed, dict) else None
        if not isinstance(raw_candidates, list):
            return []

        candidates: list[ProjectMemoryCandidate] = []
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            try:
                candidates.append(ProjectMemoryCandidate.model_validate(item))
            except Exception:  # noqa: BLE001 - one malformed candidate must not drop the rest
                logger.warning("Discarding one malformed memory extraction candidate: %r", item)
                continue
        return candidates
