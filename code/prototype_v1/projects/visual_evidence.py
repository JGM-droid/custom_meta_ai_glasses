"""Visual Evidence Continuity (Stage 3).

Two-tier design (see docs/PROJECT_MEMORY_ARCHITECTURE.md's Stage 3 section, and the Stage 1/2
falsification finding it is built on): an Evidence image gets a durable TEXT description generated
once; a later visual question is answered from that description when it is sufficient (Tier 1 -
original pixels are never re-fetched); only when the description is judged insufficient for the
specific question asked are the original Evidence bytes re-fetched and sent to a vision-capable
provider (Tier 2). Evidence remains canonical in InvestigationEvidenceStore - nothing here
duplicates image bytes or creates a second Evidence store; this module only generates/selects text.

Deterministic-first: `select_candidates` is a pure function with no provider call - it narrows
across the whole Project's described Evidence to a small, bounded, scope-aware candidate list
before any AI involvement. `VisualEvidenceContinuityService` is the one place a real provider is
called, for exactly two purposes: (1) generate a description once per eligible Evidence, and (2)
decide, among the bounded candidates, whether a question is even about existing Evidence at all
and if so which Evidence and which tier - never which Evidence is canonically owned by the
Project, only which one a question is most plausibly about.
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime

from investigations import InvestigationEvidence

logger = logging.getLogger(__name__)

_DEFAULT_SCOPE = "overall"

# Bounded, deliberately small - matches the Stage 1/2 salience-candidate threshold convention. This
# is a candidate-list size cap, not a call-skipping threshold: unlike Stage 1/2's salience step, the
# tier decision here always needs a real semantic judgment (is the stored description sufficient
# for THIS question), so the AI call always fires once real candidates exist - only the input list
# size is bounded.
_MAX_CANDIDATES = 8

# Cheap, no-provider-call gate: only run candidate gathering/selection at all when the current
# text plausibly refers to something visual. This is intentionally a coarse recall-favoring filter,
# not a precision filter - the AI selection call still returns "not applicable" for anything that
# slips through but isn't genuinely about existing Evidence (see _SELECTION_SYSTEM_PROMPT). Its job
# is only to keep the common case (an ordinary non-visual question) from making any extra call.
_VISUAL_CONTINUITY_KEYWORDS = frozenset({
    "room", "picture", "pictures", "photo", "photos", "image", "images", "pic", "pics",
    "look", "looks", "looked", "looking", "see", "seen", "showed", "show", "shown",
    "color", "colour", "colors", "colours", "paint", "painted", "wall", "walls", "floor",
    "flooring", "furniture", "pillow", "pillows", "couch", "sofa", "pattern", "layout",
    "before", "after", "picture i sent", "photo i sent", "sent you",
})


def is_visual_continuity_candidate(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(keyword in lowered for keyword in _VISUAL_CONTINUITY_KEYWORDS)


@dataclass(frozen=True)
class VisualEvidenceDescriptionResult:
    description: str
    scope: str


@dataclass(frozen=True)
class VisualEvidenceCandidate:
    session_id: str
    evidence_id: str
    scope: str
    description: str
    occurred_at_utc: datetime


@dataclass(frozen=True)
class VisualEvidenceSelection:
    session_id: str
    evidence_id: str
    tier: str  # "description_sufficient" | "original_required"
    description: str


def select_candidates(
    all_evidence: list[InvestigationEvidence], *, question_text: str, limit: int = _MAX_CANDIDATES,
) -> list[VisualEvidenceCandidate]:
    """Deterministic-only, no provider call. Narrows to Evidence that already has a durable
    description, prefers Evidence whose stored scope is named in the question text (so "what does
    the kitchen look like" never has to consider Living Room candidates when a kitchen scope
    exists), falls back to the full described set otherwise, and bounds the result to `limit`,
    most-recent first."""
    described = [item for item in all_evidence if item.visual_description]
    described.sort(key=lambda item: item.created_at_utc, reverse=True)

    lowered = str(question_text or "").lower()
    known_scopes = {item.visual_description_scope for item in described if item.visual_description_scope}
    matched_scopes = {scope for scope in known_scopes if scope.replace("_", " ") in lowered or scope in lowered}
    pool = [item for item in described if item.visual_description_scope in matched_scopes] if matched_scopes else described

    bounded = pool[:limit]
    return [
        VisualEvidenceCandidate(
            session_id=item.session_id,
            evidence_id=item.evidence_id,
            scope=item.visual_description_scope or _DEFAULT_SCOPE,
            description=item.visual_description or "",
            occurred_at_utc=item.created_at_utc,
        )
        for item in bounded
    ]


_DESCRIPTION_SYSTEM_PROMPT = """You are a conservative visual-description component for a persistent \
Project assistant. Given one photograph, write a short, durable text description capturing only \
what is CLEARLY, VISIBLY present and materially useful for future Project reasoning (e.g. major \
furniture, fixtures, wall/floor treatment, layout, color/style impression, visible condition).

Do NOT invent or state:
- exact dimensions not visible or measurable from the image
- specific materials, brands, or models not reliably readable/identifiable
- hidden conditions (behind walls, inside objects, anything not visible)
- conclusions not directly supported by what is shown

Also provide a short lowercase scope identifier for the Project area/workstream this image most \
likely belongs to (e.g. "living_room", "kitchen", "unit_412") - use "overall" if it is not \
identifiable as a specific area.

Output ONLY a JSON object: {"description": "...", "scope": "..."}."""

_SELECTION_SYSTEM_PROMPT = """You are a conservative Evidence-selection component for a persistent \
Project assistant with visual memory. Given the user's current question and a bounded list of \
candidate prior Evidence photos (each with an index, scope, recency label, and stored text \
description), decide:

- applicable: true only if the question is plausibly asking about one of these specific prior \
photos/scenes. False for anything else (including a plain question unrelated to any stored \
Evidence, or an ordinary conversational message that merely contains a visual-sounding word).
- selected_index: the index of the single most relevant candidate, or null if not applicable or \
you cannot reasonably tell which one.
- tier: "description_sufficient" if the stored description text already contains enough \
information to answer the question reliably; "original_required" if answering requires a visual \
detail (e.g. an exact pattern, a small object, precise color, text/label) that the stored \
description does not cover and only the original photo could show.

Never guess a specific candidate when multiple are plausible and the question does not disambiguate \
- return applicable=false with selected_index=null instead. Output ONLY a JSON object: \
{"applicable": true/false, "selected_index": <int or null>, "tier": "description_sufficient" or \
"original_required" or null}."""


class VisualEvidenceContinuityError(RuntimeError):
    pass


class VisualEvidenceContinuityService:
    """One bounded real-provider call per purpose - a description call once per eligible Evidence,
    a selection call once per eligible text-only turn. Never a multi-step agent loop, matching the
    exact discipline already proven for Stage 2's ProjectMemoryExtractionService."""

    def __init__(self, *, api_key: str, model: str = "gpt-4.1-mini",
                 timeout_seconds: float = 20.0, client_factory=None):
        if not str(api_key or "").strip():
            raise VisualEvidenceContinuityError("OPENAI_API_KEY is required for visual evidence continuity.")
        if client_factory is None:
            try:
                from openai import OpenAI
            except Exception as exc:  # pragma: no cover
                raise VisualEvidenceContinuityError("OpenAI SDK is unavailable.") from exc
            client_factory = OpenAI
        self._client = client_factory(api_key=api_key.strip(), timeout=float(timeout_seconds))
        self._model = str(model or "gpt-4.1-mini").strip()

    def describe(self, *, image_bytes: bytes, media_type: str) -> VisualEvidenceDescriptionResult:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _DESCRIPTION_SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}},
                    ]},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            raw = response.choices[0].message.content
        except Exception as exc:  # noqa: BLE001 - shadow path must never raise into the real turn
            raise VisualEvidenceContinuityError(f"Visual description generation failed: {exc}") from exc

        try:
            parsed = json.loads(raw or "{}")
        except (TypeError, ValueError) as exc:
            raise VisualEvidenceContinuityError("Visual description generation returned invalid JSON.") from exc

        description = str(parsed.get("description") or "").strip() if isinstance(parsed, dict) else ""
        if not description:
            raise VisualEvidenceContinuityError("Visual description generation returned no description.")
        scope = str(parsed.get("scope") or "").strip().lower() if isinstance(parsed, dict) else ""
        return VisualEvidenceDescriptionResult(description=description, scope=scope or _DEFAULT_SCOPE)

    def select(
        self, *, question_text: str, candidates: list[VisualEvidenceCandidate],
    ) -> VisualEvidenceSelection | None:
        """Returns None (abstain) on any ambiguity or failure - the caller must proceed as an
        ordinary turn with no visual context injected, never guess."""
        if not candidates:
            return None
        sorted_candidates = sorted(candidates, key=lambda item: item.occurred_at_utc, reverse=True)
        lines = []
        for index, item in enumerate(sorted_candidates):
            recency = "most recent" if index == 0 else f"{index + 1} evidence items ago"
            lines.append(f"{index}: scope={item.scope}, recency={recency}, description={item.description!r}")
        numbered = "\n".join(lines)
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SELECTION_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Question: {question_text}\n\nCandidates:\n{numbered}"},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            parsed = json.loads(response.choices[0].message.content or "{}")
        except Exception:  # noqa: BLE001 - selection failure must degrade, never raise into the turn
            logger.warning("Visual evidence selection failed; proceeding without visual context.")
            return None

        if not isinstance(parsed, dict) or not parsed.get("applicable"):
            return None
        index = parsed.get("selected_index")
        tier = parsed.get("tier")
        if not isinstance(index, int) or not (0 <= index < len(sorted_candidates)):
            return None
        if tier not in ("description_sufficient", "original_required"):
            return None
        chosen = sorted_candidates[index]
        return VisualEvidenceSelection(
            session_id=chosen.session_id, evidence_id=chosen.evidence_id,
            tier=tier, description=chosen.description,
        )
