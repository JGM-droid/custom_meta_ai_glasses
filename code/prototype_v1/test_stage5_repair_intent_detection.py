"""Stage 5 final narrow repair: continuation/state-question intent detection must tolerate normal
natural-language variation (inserted filler words, reordered helper verbs) instead of relying on an
ever-growing list of exact literal phrases.

Real dogfood regression this closes: Current Project State correctly contained an active blocker,
but "Is anything actually blocking me right now?" bypassed `is_continuation_question()` entirely
because the literal phrase "is anything blocking" no longer appeared as a contiguous substring once
the user naturally inserted "actually" - no current-state context was attached, and the assistant
gave a confidently wrong "nothing is blocking you" answer that contradicted the system's own
correctly-derived state. `is_continuation_question`/`is_historical_question` now match bounded,
order-preserving TOKEN SEQUENCES (see `_has_token_sequence`) rather than literal substrings, so
inserted filler words no longer break a match, while requiring the anchors in order keeps
false-positive risk low - a bare "what" or "did" is never enough on its own to trigger either
intent.
"""
from __future__ import annotations

import pytest

from projects.memory_retrieval import is_continuation_question, is_historical_question

# ---------------------------------------------------------------------------
# Continuation / current-state intent: must trigger despite natural phrasing variation
# ---------------------------------------------------------------------------

_CONTINUATION_TRIGGERS = [
    "Is anything blocking me?",
    "Is anything actually blocking me right now?",  # the exact real dogfood regression
    "Do I have any blockers?",
    "What's holding this up?",
    "What have I finished?",
    "What have I already completed?",
    "What still needs to be done?",
    "What should I focus on now?",
    "Where are we with this?",
    "Where did we leave off?",
]


@pytest.mark.parametrize("text", _CONTINUATION_TRIGGERS)
def test_continuation_question_triggers_on_natural_phrasing(text):
    assert is_continuation_question(text), f"expected continuation intent for: {text!r}"


_CONTINUATION_NON_TRIGGERS = [
    "What color should the wall be?",
    "Is blue too dark?",
    "What size rug should I buy?",
    "How much does this cost?",
    "Show me what the room looked like.",
]


@pytest.mark.parametrize("text", _CONTINUATION_NON_TRIGGERS)
def test_continuation_question_does_not_over_trigger(text):
    assert not is_continuation_question(text), f"did not expect continuation intent for: {text!r}"


def test_continuation_question_tolerates_additional_natural_variants_not_in_original_list():
    """Extra variants beyond the required minimum, proving this generalizes rather than being a
    second hand-tuned list of exact phrases in disguise."""
    assert is_continuation_question("Am I blocked on anything at the moment?")
    assert is_continuation_question("What do I still need to take care of?")
    assert is_continuation_question("So what's next for me here?")
    assert is_continuation_question("What have we already finished on this?")
    assert is_continuation_question("Am I stuck on anything at the moment?")
    assert is_continuation_question("What's the current holdup with this project?")


# ---------------------------------------------------------------------------
# Historical intent: preserved as its own distinct intent, same robustness technique
# ---------------------------------------------------------------------------

def test_historical_question_still_recognized_with_original_wording():
    assert is_historical_question("What did we originally decide about the TV stand?")
    assert is_historical_question("Why did that change?")


def test_historical_question_tolerates_inserted_filler_words():
    assert is_historical_question("What did we actually originally decide about the couch?")
    assert is_historical_question("Why did that really change again?")
    assert is_historical_question("What was the original plan for the TV stand?")


def test_historical_question_does_not_over_trigger_on_bare_what_or_did():
    assert not is_historical_question("Are we still keeping the TV stand?")
    assert not is_historical_question("What did you say the budget was?")
    assert not is_historical_question("What color should the wall be?")


# ---------------------------------------------------------------------------
# Continuation and historical intents remain distinct - neither swallows the other
# ---------------------------------------------------------------------------

def test_continuation_and_historical_are_mutually_exclusive_for_their_own_canonical_examples():
    assert is_continuation_question("Is anything blocking me?")
    assert not is_historical_question("Is anything blocking me?")

    assert is_historical_question("What did we originally decide?")
    assert not is_continuation_question("What did we originally decide?")
