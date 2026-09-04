"""ADR-060 Response Planner: real-model routing evaluation (hardening pass).

Not a pytest test - this makes real OpenAI calls and is meant to be run
manually/occasionally to assess routing accuracy and clarification quality,
per the ADR-060 requirement that passing unit tests alone does not prove AI
quality. Uses the SAME OpenAIProjectResponseRoutingProvider the application
uses; scenarios are hand-built bounded context payloads (no Project/session
infrastructure needed) so this evaluates routing judgment in isolation from
downstream family execution.

Scores four dimensions separately:
  A. family-selection accuracy (scenarios where a family should be chosen)
  B. clarification precision/recall (scenarios where clarification is expected)
  C. unnecessary-clarification rate (false positives on grounded scenarios)
  D. stability on repeated ambiguous cases (does the model guess differently
     across identical repeated calls?)

Run: python eval_response_planner_routing.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from dataclasses import dataclass, field

import api
from projects.project_ai_result import (
    OpenAIProjectResponseRoutingProvider,
    ProjectAIResultRoutingUnavailable,
    load_project_response_router_model_name,
    load_project_response_router_timeout_seconds,
)


@dataclass
class Scenario:
    name: str
    project_name: str
    project_goal: str
    current_objective: str | None
    next_action: str | None
    user_request: str
    # expect_clarification is the primary label. expected_family is only
    # meaningful when expect_clarification is False.
    expect_clarification: bool
    expected_family: str | None = None
    recent_activities: list[dict] = field(default_factory=list)
    recent_investigations: list[dict] = field(default_factory=list)
    session_snapshot: dict | None = None
    notes: str = ""
    repeat: int = 1  # >1 marks a scenario for repeated-call stability testing


SCENARIOS: list[Scenario] = [
    # --- Room Redesign: planning / troubleshooting / follow-up on the SAME Project ---
    Scenario("room_redesign_planning_1", "Redo My Room", "Modern, comfortable room under $1,000",
        "Decide on a design direction", "Review design options",
        "What would you change about this room? Give me some ideas.",
        expect_clarification=False, expected_family="EXPLORE_PLAN"),
    Scenario("room_redesign_planning_2", "Redo My Room", "Modern, comfortable room under $1,000",
        "Decide on a design direction", "Review design options",
        "I want a warmer, more modern feel in here - what are some directions I could take?",
        expect_clarification=False, expected_family="EXPLORE_PLAN"),
    Scenario("room_redesign_troubleshoot_1", "Redo My Room", "Modern, comfortable room under $1,000",
        "Decide on a design direction", "Review design options",
        "This drawer won't close properly. What's wrong with it?",
        expect_clarification=False, expected_family="TROUBLESHOOT",
        notes="Same Project as the planning scenarios - proves family is not permanently locked."),
    Scenario("room_redesign_troubleshoot_2", "Redo My Room", "Modern, comfortable room under $1,000",
        "Decide on a design direction", "Review design options",
        "The lamp I just installed keeps flickering. Why would that happen?",
        expect_clarification=False, expected_family="TROUBLESHOOT"),
    Scenario("room_redesign_followup_why", "Redo My Room", "Modern, comfortable room under $1,000",
        "Warm Modern direction selected", "Choose seating and finalize furniture placement",
        "Why did you recommend that over the other two options?",
        expect_clarification=False, expected_family="GENERAL_GUIDANCE",
        recent_investigations=[{"status": "explore_plan", "diagnosis": "Recommended Warm Modern over Dark Contemporary and Minimal Natural.",
                                 "required_next_action": "Choose seating and finalize furniture placement."}]),
    Scenario("room_redesign_short_why", "Redo My Room", "Modern, comfortable room under $1,000",
        "Warm Modern direction selected", "Choose seating and finalize furniture placement",
        "Why?",
        expect_clarification=False, expected_family="GENERAL_GUIDANCE",
        recent_investigations=[{"status": "explore_plan", "diagnosis": "Recommended Warm Modern over Dark Contemporary and Minimal Natural.",
                                 "required_next_action": "Choose seating and finalize furniture placement."}],
        notes="Contextual short follow-up - a bare 'Why?' right after a recorded recommendation should resolve, not need clarification."),

    # --- AC Repair: diagnostic / follow-up / groundable-ambiguous on the SAME Project ---
    Scenario("ac_repair_diagnostic_1", "Fix Upstairs AC", "Get the AC working again before summer",
        "Diagnose why the AC is not cooling", "Check the condenser",
        "The condenser won't start. What should I check?",
        expect_clarification=False, expected_family="TROUBLESHOOT"),
    Scenario("ac_repair_diagnostic_2", "Fix Upstairs AC", "Get the AC working again before summer",
        "Diagnose why the AC is not cooling", "Check the condenser",
        "Airflow from the vents is really weak. What could cause that?",
        expect_clarification=False, expected_family="TROUBLESHOOT"),
    Scenario("ac_repair_followup_why", "Fix Upstairs AC", "Get the AC working again before summer",
        "Diagnose why the AC is not cooling", "Replace the capacitor",
        "Why did you think it was the capacitor and not the compressor?",
        expect_clarification=False, expected_family="GENERAL_GUIDANCE",
        recent_investigations=[{"status": "troubleshoot", "diagnosis": "The run capacitor has failed.",
                                 "required_next_action": "Replace the capacitor."}]),
    Scenario("ac_repair_repair_or_replace", "Fix Upstairs AC", "Get the AC working again before summer",
        "Diagnose why the AC is not cooling", "Decide on repair vs. replacement",
        "Should I repair the compressor or just replace the whole unit?",
        expect_clarification=False, expected_family="EXPLORE_PLAN",
        notes="Ambiguous-but-groundable: explicitly weighs two options."),
    Scenario("ac_repair_whats_next", "Fix Upstairs AC", "Get the AC working again before summer",
        "Diagnose why the AC is not cooling", "Replace the capacitor",
        "What's next?",
        expect_clarification=False, expected_family="GENERAL_GUIDANCE",
        recent_investigations=[{"status": "troubleshoot", "diagnosis": "The run capacitor has failed.",
                                 "required_next_action": "Replace the capacitor."}],
        notes="Ambiguous phrasing but the checkpoint already establishes a specific next action - resolvable without asking."),

    # --- Other domains: planning / troubleshooting pairs ---
    Scenario("deck_build_planning", "New Backyard Deck", "A 12x14 deck for outdoor dining",
        "Choose a layout", "Finalize the layout",
        "What layout options would work best for a 12x14 deck?",
        expect_clarification=False, expected_family="EXPLORE_PLAN"),
    Scenario("deck_build_troubleshoot", "New Backyard Deck", "A 12x14 deck for outdoor dining",
        "Finish framing", "Install decking boards",
        "One of the support posts feels wobbly. What's going on?",
        expect_clarification=False, expected_family="TROUBLESHOOT"),
    Scenario("garden_planning", "Backyard Garden Redesign", "A productive, low-maintenance vegetable garden",
        "Plan the layout", "Choose plant placement",
        "Give me a few planting layout ideas for a full-sun bed.",
        expect_clarification=False, expected_family="EXPLORE_PLAN"),
    Scenario("garden_troubleshoot", "Backyard Garden Redesign", "A productive, low-maintenance vegetable garden",
        "Keep the tomatoes healthy", "Diagnose the wilting",
        "My tomato plants are wilting even though I water them daily. Why?",
        expect_clarification=False, expected_family="TROUBLESHOOT"),
    Scenario("software_status_question", "Inventory Sync Service", "Reliable nightly inventory sync between two systems",
        "Stabilize the nightly sync job", "Add retry logic",
        "What's the current status of this project?",
        expect_clarification=False, expected_family="GENERAL_GUIDANCE"),
    Scenario("software_diagnostic", "Inventory Sync Service", "Reliable nightly inventory sync between two systems",
        "Stabilize the nightly sync job", "Add retry logic",
        "The build is failing with a null pointer exception. What's wrong?",
        expect_clarification=False, expected_family="TROUBLESHOOT"),
    Scenario("software_planning", "Inventory Sync Service", "Reliable nightly inventory sync between two systems",
        "Improve read performance", "Evaluate caching approaches",
        "What are some architecture options for adding caching here?",
        expect_clarification=False, expected_family="EXPLORE_PLAN"),
    Scenario("bathroom_planning", "Small Bathroom Remodel", "A refreshed, more spacious-feeling small bathroom",
        "Decide on a design direction", "Review design options",
        "I'm thinking of redoing this bathroom - what direction should I go for a small space?",
        expect_clarification=False, expected_family="EXPLORE_PLAN"),
    Scenario("bathroom_troubleshoot", "Small Bathroom Remodel", "A refreshed, more spacious-feeling small bathroom",
        "Decide on a design direction", "Review design options",
        "There's a leak under the sink. What should I look at?",
        expect_clarification=False, expected_family="TROUBLESHOOT",
        session_snapshot={"status": "collecting", "evidence_count": 1}),

    # --- Adversarial vague phrases x differing grounding levels ---
    Scenario("help_me_rich_context", "Redo My Room", "Modern, comfortable room under $1,000",
        "Warm Modern direction selected", "Choose seating and finalize furniture placement",
        "Help me",
        expect_clarification=True,
        recent_investigations=[{"status": "explore_plan", "diagnosis": "Recommended Warm Modern over Dark Contemporary and Minimal Natural.",
                                 "required_next_action": "Choose seating and finalize furniture placement."}],
        notes="Rich Project context must NOT be used to justify guessing on a content-free request."),
    Scenario("help_me_no_context", "New Project", "Not yet defined",
        None, None, "Help me",
        expect_clarification=True,
        notes="No context at all - the clearest possible case for clarification.", repeat=5),
    Scenario("what_should_i_do_resolvable", "Fix Upstairs AC", "Get the AC working again before summer",
        "Diagnose why the AC is not cooling", "Replace the capacitor",
        "What should I do?",
        expect_clarification=False, expected_family="GENERAL_GUIDANCE",
        recent_investigations=[{"status": "troubleshoot", "diagnosis": "The run capacitor has failed.",
                                 "required_next_action": "Replace the capacitor."}],
        notes="Vague phrasing but next_action is already specific and known - answerable without asking."),
    Scenario("what_should_i_do_no_context", "New Project", "Not yet defined",
        None, None, "What should I do?",
        expect_clarification=True,
        notes="Same vague phrase as above, but nothing in context establishes an answer."),
    Scenario("what_about_this_dangling_referent", "Fix Upstairs AC", "Get the AC working again before summer",
        "Diagnose why the AC is not cooling", "Replace the capacitor",
        "What about this?",
        expect_clarification=True,
        recent_investigations=[{"status": "troubleshoot", "diagnosis": "The run capacitor has failed.",
                                 "required_next_action": "Replace the capacitor."}],
        notes="Genuinely ambiguous even WITH context - 'this' has no clear antecedent action."),
    Scenario("what_about_this_no_context", "New Project", "Not yet defined",
        None, None, "What about this?",
        expect_clarification=True, repeat=5),
    Scenario("can_you_help_me_with_this_rich_context", "Redo My Room", "Modern, comfortable room under $1,000",
        "Decide on a design direction", "Review design options",
        "Can you help me with this?",
        expect_clarification=True,
        session_snapshot={"status": "collecting", "evidence_count": 2},
        notes="The original observed failure case - evidence present, but the request itself is still content-free.", repeat=5),
    Scenario("can_you_help_me_with_this_no_context", "New Project", "Not yet defined",
        None, None, "Can you help me with this?",
        expect_clarification=True, repeat=5),

    # --- Genuinely ambiguous, non-adversarial-phrase, insufficient grounding ---
    Scenario("other_option_no_prior_context", "Redo My Room", "Modern, comfortable room under $1,000",
        "Decide on a design direction", "Review design options",
        "Can we look at the other option?",
        expect_clarification=True,
        notes="'the other option' has no antecedent - recent_investigations is empty."),
    Scenario("is_that_a_good_idea_no_context", "New Project", "Not yet defined",
        None, None, "Is that a good idea?",
        expect_clarification=True,
        notes="'that' has no antecedent at all."),

    # --- A couple more grounded/ordinary cases to round out the set ---
    Scenario("garden_followup_why", "Backyard Garden Redesign", "A productive, low-maintenance vegetable garden",
        "Keep the tomatoes healthy", "Adjust watering schedule",
        "Why did you think it was overwatering and not a pest?",
        expect_clarification=False, expected_family="GENERAL_GUIDANCE",
        recent_investigations=[{"status": "troubleshoot", "diagnosis": "Overwatering is the likely cause of the wilting.",
                                 "required_next_action": "Adjust watering schedule."}]),
    Scenario("software_followup_why", "Inventory Sync Service", "Reliable nightly inventory sync between two systems",
        "Stabilize the nightly sync job", "Add a null check before the sync call",
        "Why do you think it's a null pointer and not a timeout?",
        expect_clarification=False, expected_family="GENERAL_GUIDANCE",
        recent_investigations=[{"status": "troubleshoot", "diagnosis": "A null reference during the nightly sync call.",
                                 "required_next_action": "Add a null check before the sync call."}]),
]


def _build_context_payload(scenario: Scenario) -> dict[str, object]:
    return {
        "project": {
            "project_id": "00000000-0000-0000-0000-000000000000",
            "project_name": scenario.project_name,
            "project_goal": scenario.project_goal,
        },
        "checkpoint": {
            "current_objective": scenario.current_objective,
            "blockers": None,
            "next_action": scenario.next_action,
        },
        "recent_activities": scenario.recent_activities,
        "recent_investigations": scenario.recent_investigations,
        "current_investigation_session": scenario.session_snapshot,
        "current_request": scenario.user_request,
    }


def _classify_once(provider, payload):
    started = time.monotonic()
    try:
        decision = provider.classify(payload)
        elapsed = time.monotonic() - started
        usage = dict(provider.last_usage) if provider.last_usage else None
        return decision, elapsed, usage, None
    except ProjectAIResultRoutingUnavailable as exc:
        elapsed = time.monotonic() - started
        return None, elapsed, None, str(exc)


def main() -> int:
    api_key = api._load_openai_api_key()
    if not api_key:
        print("BLOCKED: OPENAI_API_KEY is not configured (checked env and .env files).")
        return 1

    model = load_project_response_router_model_name()
    provider = OpenAIProjectResponseRoutingProvider(
        api_key=api_key, model=model, timeout_seconds=load_project_response_router_timeout_seconds(),
    )

    rows: list[dict[str, object]] = []
    stability_rows: list[dict[str, object]] = []
    latencies: list[float] = []
    prompt_tokens: list[int] = []
    completion_tokens: list[int] = []

    for scenario in SCENARIOS:
        payload = _build_context_payload(scenario)
        decision, elapsed, usage, error = _classify_once(provider, payload)
        latencies.append(elapsed)
        if usage:
            prompt_tokens.append(usage.get("prompt_tokens", 0))
            completion_tokens.append(usage.get("completion_tokens", 0))

        if error is not None:
            rows.append({
                "name": scenario.name, "expect_clarification": scenario.expect_clarification,
                "expected_family": scenario.expected_family, "predicted_clarification": None,
                "predicted_family": "TECHNICAL_FAILURE", "confidence": None, "correct": False,
                "latency_s": round(elapsed, 2), "error": error, "notes": scenario.notes,
            })
            continue

        predicted_clarification = decision.needs_clarification
        predicted_family = decision.response_family.value if decision.response_family else None
        if scenario.expect_clarification:
            correct = predicted_clarification is True
        else:
            correct = (not predicted_clarification) and predicted_family == scenario.expected_family

        rows.append({
            "name": scenario.name,
            "expect_clarification": scenario.expect_clarification,
            "expected_family": scenario.expected_family,
            "predicted_clarification": predicted_clarification,
            "predicted_family": predicted_family,
            "clarifying_question": decision.clarifying_question,
            "confidence": round(decision.confidence, 2),
            "brief_reason": decision.brief_reason,
            "correct": correct,
            "latency_s": round(elapsed, 2),
            "notes": scenario.notes,
        })

        if scenario.repeat > 1:
            repeat_results = [{
                "clarification": predicted_clarification,
                "family": predicted_family,
            }]
            for _ in range(scenario.repeat - 1):
                repeat_decision, repeat_elapsed, repeat_usage, repeat_error = _classify_once(provider, payload)
                latencies.append(repeat_elapsed)
                if repeat_usage:
                    prompt_tokens.append(repeat_usage.get("prompt_tokens", 0))
                    completion_tokens.append(repeat_usage.get("completion_tokens", 0))
                if repeat_error is not None:
                    repeat_results.append({"clarification": None, "family": "TECHNICAL_FAILURE", "error": repeat_error})
                else:
                    repeat_results.append({
                        "clarification": repeat_decision.needs_clarification,
                        "family": repeat_decision.response_family.value if repeat_decision.response_family else None,
                    })
            distinct_answers = {json.dumps(r, sort_keys=True) for r in repeat_results}
            stability_rows.append({
                "name": scenario.name, "runs": scenario.repeat,
                "distinct_answers": len(distinct_answers), "stable": len(distinct_answers) == 1,
                "results": repeat_results,
            })

    # --- Scoring ---
    grounded = [r for r in rows if not r["expect_clarification"]]
    ambiguous = [r for r in rows if r["expect_clarification"]]

    family_accuracy = sum(1 for r in grounded if r["correct"]) / len(grounded) if grounded else float("nan")
    clarification_recall = sum(1 for r in ambiguous if r["predicted_clarification"] is True) / len(ambiguous) if ambiguous else float("nan")
    predicted_clarifications = [r for r in rows if r["predicted_clarification"] is True]
    clarification_precision = (
        sum(1 for r in predicted_clarifications if r["expect_clarification"]) / len(predicted_clarifications)
        if predicted_clarifications else float("nan")
    )
    unnecessary_clarification_rate = sum(1 for r in grounded if r["predicted_clarification"] is True) / len(grounded) if grounded else float("nan")

    print(f"\n=== ADR-060 Response Planner routing evaluation - hardening pass ({model}) ===\n")
    header = f"{'scenario':<40}{'expect_clar':<12}{'exp_family':<14}{'pred_clar':<10}{'pred_family':<14}{'conf':<6}{'ok':<4}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['name']:<40}{str(r['expect_clarification']):<12}{str(r['expected_family']):<14}"
            f"{str(r['predicted_clarification']):<10}{str(r['predicted_family']):<14}"
            f"{('' if r['confidence'] is None else r['confidence']):<6}{('YES' if r['correct'] else 'NO'):<4}"
        )
    print("-" * len(header))

    print(f"\nA. Family-selection accuracy (grounded scenarios, n={len(grounded)}): {sum(1 for r in grounded if r['correct'])}/{len(grounded)} ({100*family_accuracy:.0f}%)")
    print(f"B. Clarification recall (ambiguous scenarios, n={len(ambiguous)}): {sum(1 for r in ambiguous if r['predicted_clarification'] is True)}/{len(ambiguous)} ({100*clarification_recall:.0f}%)")
    print(f"   Clarification precision (of {len(predicted_clarifications)} predicted clarifications): {100*clarification_precision:.0f}%" if predicted_clarifications else "   Clarification precision: n/a (no clarifications predicted)")
    print(f"C. Unnecessary-clarification rate (false positives on grounded scenarios): {sum(1 for r in grounded if r['predicted_clarification'] is True)}/{len(grounded)} ({100*unnecessary_clarification_rate:.0f}%)")

    incorrect = [r for r in rows if not r["correct"]]
    if incorrect:
        print("\n--- Incorrect / notable cases ---")
        for r in incorrect:
            print(f"- {r['name']}: expect_clarification={r['expect_clarification']} expected_family={r['expected_family']} "
                  f"predicted_clarification={r['predicted_clarification']} predicted_family={r['predicted_family']} "
                  f"confidence={r.get('confidence')} reason={r.get('brief_reason')} notes={r.get('notes')}")

    print("\nD. Stability on repeated ambiguous cases:")
    for s in stability_rows:
        print(f"- {s['name']}: {s['runs']} runs, {s['distinct_answers']} distinct answer(s), stable={s['stable']}")
        if not s["stable"]:
            print(f"    {s['results']}")

    if latencies:
        print(f"\nLatency: mean={statistics.mean(latencies):.2f}s p50={statistics.median(latencies):.2f}s max={max(latencies):.2f}s min={min(latencies):.2f}s (n={len(latencies)})")
    if prompt_tokens:
        print(f"Prompt tokens: mean={statistics.mean(prompt_tokens):.0f} max={max(prompt_tokens)} min={min(prompt_tokens)}")
    if completion_tokens:
        print(f"Completion tokens: mean={statistics.mean(completion_tokens):.0f} max={max(completion_tokens)} min={min(completion_tokens)}")

    confidences = [r["confidence"] for r in rows if r["confidence"] is not None]
    if confidences:
        print(f"\nConfidence distribution: mean={statistics.mean(confidences):.2f} min={min(confidences):.2f} max={max(confidences):.2f} stdev={statistics.pstdev(confidences):.3f}")

    print(f"\nTotal scenarios: {len(SCENARIOS)}  Total classifier calls: {len(latencies)}")
    print("\n(Full row + stability data as JSON below for downstream analysis.)")
    print(json.dumps({"rows": rows, "stability": stability_rows}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
