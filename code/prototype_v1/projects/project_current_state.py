"""Current Project State (Stage 2 - shadow slice).

DERIVED, never canonical: every function here reads ProjectMemoryRecord and
computes a bounded projection - nothing here is itself persisted. See
docs/PROJECT_MEMORY_ARCHITECTURE.md's "Stage 1 Result" for the proven design
this module implements verbatim: deterministic eligibility/blocker/resolved-
area handling first, AI salience selection only for choosing which non-
blocked active scopes to expand for a GLOBAL ("where did we leave off"-style)
view. A specific scope request never needs the AI step - deterministic
lookup is sufficient and was already proven correct for topic-specific
questions in the prior falsification gate.
"""
from __future__ import annotations

import json
import logging

from .models import (
    PROJECT_CURRENT_STATE_SCHEMA_VERSION,
    ProjectCurrentState,
    ProjectMemoryCategory,
    ProjectMemoryModality,
    ProjectMemoryProgressState,
    ProjectMemoryRecord,
    ProjectMemoryStatus,
    ProjectScopeState,
)

logger = logging.getLogger(__name__)

_ACTIVE_PROGRESS_STATES = {
    ProjectMemoryProgressState.PLANNED, ProjectMemoryProgressState.STARTED,
    ProjectMemoryProgressState.BLOCKED, ProjectMemoryProgressState.REOPENED,
}
_TERMINAL_PROGRESS_STATES = {ProjectMemoryProgressState.COMPLETED, ProjectMemoryProgressState.ABANDONED}
_RECENT_CHANGES_LIMIT = 10
_RECENTLY_COMPLETED_LIMIT = 5
# Below this many non-blocked active scopes, skip the AI call entirely and
# include them all - the salience step exists to choose among many
# candidates, not to second-guess a small, already-bounded set.
_SALIENCE_CALL_THRESHOLD = 8


def _committed(records: list[ProjectMemoryRecord]) -> list[ProjectMemoryRecord]:
    return [r for r in records if r.modality == ProjectMemoryModality.COMMITTED]


def _current_facts_constraints(records: list[ProjectMemoryRecord], scope: str) -> list[ProjectMemoryRecord]:
    return [r for r in _committed(records) if r.scope == scope and r.status == ProjectMemoryStatus.CURRENT
            and r.category in (ProjectMemoryCategory.FACT, ProjectMemoryCategory.CONSTRAINT,
                               ProjectMemoryCategory.PREFERENCE)]


def _current_decisions(records: list[ProjectMemoryRecord], scope: str) -> list[ProjectMemoryRecord]:
    return [r for r in _committed(records) if r.scope == scope and r.status == ProjectMemoryStatus.CURRENT
            and r.category == ProjectMemoryCategory.DECISION]


def _progress_projection(records: list[ProjectMemoryRecord], scope: str) -> list[ProjectMemoryRecord]:
    """Latest progress event per (scope, subject, slot) - progress is
    append-only, never superseded; "current" progress is always the most
    recent event, derived here, not stored as a separate flag."""
    seen: dict[tuple[str, str, str], ProjectMemoryRecord] = {}
    for r in sorted(records, key=lambda r: r.occurred_at_utc):
        if r.category == ProjectMemoryCategory.PROGRESS and r.scope == scope:
            seen[(r.scope, r.subject, r.slot)] = r
    return list(seen.values())


def _open_blockers(records: list[ProjectMemoryRecord], scope: str | None) -> list[ProjectMemoryRecord]:
    scopes = {scope} if scope else _known_scopes(records)
    result = []
    for s in scopes:
        for r in _progress_projection(records, s):
            if r.is_blocker and r.progress_state not in _TERMINAL_PROGRESS_STATES:
                result.append(r)
    return result


def _active_progress(records: list[ProjectMemoryRecord], scope: str) -> list[ProjectMemoryRecord]:
    return [r for r in _progress_projection(records, scope) if r.progress_state in _ACTIVE_PROGRESS_STATES]


def _pending_decisions(records: list[ProjectMemoryRecord], scope: str) -> list[ProjectMemoryRecord]:
    """A committed decision with no progress record tracking follow-through
    at all in this scope - a decision made but never operationalized. Known
    heuristic limit (recorded, not silently hidden): a decision whose value
    contains "keep"/"no change" is assumed to need no follow-up action."""
    decisions = _current_decisions(records, scope)
    tracked_subjects = {(r.scope, r.subject) for r in records if r.category == ProjectMemoryCategory.PROGRESS}
    return [d for d in decisions if (d.scope, d.subject) not in tracked_subjects
            and "keep" not in d.value.lower() and "no change" not in d.value.lower()]


def _recently_completed(records: list[ProjectMemoryRecord], scope: str) -> list[ProjectMemoryRecord]:
    completed = [r for r in _progress_projection(records, scope)
                 if r.progress_state == ProjectMemoryProgressState.COMPLETED]
    return sorted(completed, key=lambda r: r.occurred_at_utc, reverse=True)[:_RECENTLY_COMPLETED_LIMIT]


def _recent_changes(records: list[ProjectMemoryRecord], scope: str | None) -> list[ProjectMemoryRecord]:
    changed = [r for r in records
               if (scope is None or r.scope == scope)
               and (r.status == ProjectMemoryStatus.SUPERSEDED or r.progress_state == ProjectMemoryProgressState.REOPENED)]
    return sorted(changed, key=lambda r: r.occurred_at_utc, reverse=True)[:_RECENT_CHANGES_LIMIT]


def _known_scopes(records: list[ProjectMemoryRecord]) -> list[str]:
    seen: list[str] = []
    for r in sorted(records, key=lambda r: r.occurred_at_utc):
        if r.scope not in seen:
            seen.append(r.scope)
    return seen


def _scope_status(records: list[ProjectMemoryRecord], scope: str) -> str:
    if _open_blockers(records, scope):
        return "blocked"
    if _active_progress(records, scope) or _pending_decisions(records, scope):
        return "active"
    progress = _progress_projection(records, scope)
    if not progress:
        return "active"
    all_terminal = all(r.progress_state in _TERMINAL_PROGRESS_STATES for r in progress)
    # A scope whose only progress event happens to be terminal must still stay visible if it
    # carries standing current facts/constraints/preferences/decisions (e.g. "overall" holding a
    # budget and style preference alongside one completed delivery) - "resolved" means a
    # workstream finished, not merely "nothing currently in flight."
    has_standing_content = bool(_current_facts_constraints(records, scope)) or bool(_current_decisions(records, scope))
    if all_terminal and not has_standing_content:
        return "resolved"
    return "active"


def _summary(r: ProjectMemoryRecord) -> str:
    state = f" ({r.progress_state.value})" if r.progress_state else ""
    return f"[{r.scope}] {r.subject}/{r.slot}{state}: {r.value}"


def build_scope_state(records: list[ProjectMemoryRecord], scope: str) -> ProjectScopeState:
    active = _active_progress(records, scope)
    pending = _pending_decisions(records, scope)
    blockers = _open_blockers(records, scope)
    return ProjectScopeState(
        scope=scope,
        status=_scope_status(records, scope),
        facts=[_summary(r) for r in _current_facts_constraints(records, scope)],
        decisions=[_summary(r) for r in _current_decisions(records, scope)],
        blockers=[_summary(r) for r in blockers],
        active_progress=[_summary(r) for r in active],
        pending_decisions=[_summary(r) for r in pending],
        recently_completed=[_summary(r) for r in _recently_completed(records, scope)],
        recent_changes=[_summary(r) for r in _recent_changes(records, scope)],
    )


class ProjectCurrentStateService:
    """Derives Current Project State on demand. `extraction_client` is an
    object exposing `.chat.completions.create` (the same real OpenAI client
    used elsewhere) - only invoked for a global view with enough non-blocked
    active scopes to genuinely need selection; a scoped request never calls
    it. Recomputed fresh every call, per Stage 1's derived-not-persisted
    recommendation - no caching/incremental maintenance in this shadow slice."""

    def __init__(self, *, salience_client=None, salience_model: str = "gpt-4.1-mini"):
        self._client = salience_client
        self._model = salience_model

    def get_current_state(self, project_id: str, records: list[ProjectMemoryRecord],
                           scope: str | None = None) -> ProjectCurrentState:
        if scope is not None:
            return self._scoped_state(project_id, records, scope)
        return self._global_state(project_id, records)

    def _scoped_state(self, project_id: str, records: list[ProjectMemoryRecord], scope: str) -> ProjectCurrentState:
        state = build_scope_state(records, scope)
        return ProjectCurrentState(
            schema_version=PROJECT_CURRENT_STATE_SCHEMA_VERSION,
            project_id=project_id,
            requested_scope=scope,
            global_blockers=state.blockers,
            scope_summaries=[],
            resolved_scope_count=0,
            recent_changes=state.recent_changes,
            scope_detail={scope: state},
            salience_call_used=False,
        )

    def _global_state(self, project_id: str, records: list[ProjectMemoryRecord]) -> ProjectCurrentState:
        scopes = _known_scopes(records)
        blocked_scopes = [s for s in scopes if _scope_status(records, s) == "blocked"]
        active_scopes = [s for s in scopes if _scope_status(records, s) == "active"]
        resolved_count = len(scopes) - len(blocked_scopes) - len(active_scopes)

        shown_scopes = list(blocked_scopes)
        salience_used = False
        if len(active_scopes) <= _SALIENCE_CALL_THRESHOLD:
            shown_scopes += active_scopes
        else:
            selected = self._salience_select(active_scopes, records)
            salience_used = True
            shown_scopes += selected if selected is not None else active_scopes[:_SALIENCE_CALL_THRESHOLD]

        detail = {s: build_scope_state(records, s) for s in shown_scopes}
        global_blockers = [b for s in blocked_scopes for b in detail[s].blockers]
        scope_summaries = []
        for s in shown_scopes:
            d = detail[s]
            next_hint = (d.active_progress[-1] if d.active_progress else
                         (d.pending_decisions[-1] if d.pending_decisions else "no open items"))
            scope_summaries.append(f"- {s}: {d.status} - next: {next_hint}")

        return ProjectCurrentState(
            schema_version=PROJECT_CURRENT_STATE_SCHEMA_VERSION,
            project_id=project_id,
            requested_scope=None,
            global_blockers=global_blockers,
            scope_summaries=scope_summaries,
            resolved_scope_count=resolved_count,
            recent_changes=[_summary(r) for r in _recent_changes(records, None)],
            scope_detail=detail,
            salience_call_used=salience_used,
        )

    def _salience_select(self, active_scopes: list[str], records: list[ProjectMemoryRecord]) -> list[str] | None:
        if self._client is None:
            return None
        lines = []
        for s in active_scopes:
            active = _active_progress(records, s)
            pending = _pending_decisions(records, s)
            hint = active[-1] if active else (pending[-1] if pending else None)
            lines.append(f"{s}: {_summary(hint) if hint else 'no open items'}")
        numbered = "\n".join(f"{i}: {l}" for i, l in enumerate(lines))
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": (
                        f"Given a Project continuation question context and every active-but-not-"
                        f"blocked Project scope, select up to {_SALIENCE_CALL_THRESHOLD} that are "
                        "genuinely important to surface right now - not just the most recently "
                        "touched. Include anything whose description signals urgency/priority even "
                        "if it looks old or minor otherwise. Return JSON: "
                        '{"selected_indices": [..]}.'
                    )},
                    {"role": "user", "content": f"Scopes:\n{numbered}"},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            idx = json.loads(resp.choices[0].message.content).get("selected_indices", [])
            return [active_scopes[i] for i in idx if isinstance(i, int) and 0 <= i < len(active_scopes)]
        except Exception:  # noqa: BLE001 - shadow read path must degrade, never raise
            logger.warning("Current Project State salience selection failed; falling back to a bounded slice.")
            return None
