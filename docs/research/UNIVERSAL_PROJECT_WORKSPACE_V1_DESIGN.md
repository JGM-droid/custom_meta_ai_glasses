# Universal Project Workspace v1 — Design, Architecture Audit, MVP Plan

**RESEARCH / RECOMMENDATIONS — HUMAN REVIEW REQUIRED, EXCEPT WHERE MARKED APPROVED**

Status: The Universal Project Workspace *concept* (layout, Roadmap-as-structured-state, Ideas-vs-Roadmap, Continue/Disagree/More Evidence terminology, Evidence relationships, Recent Important Changes, Universal Kernel direction) is APPROVED ARCHITECTURE — see ADR-046 through ADR-051 in `docs/PROJECT_MEMORY_ARCHITECTURE.md`. The gap-analysis matrix, the sample Workspace Home, and the layout/semantics detail in Parts 1–14 below are audit findings that inform architecture but are not themselves architecture authority. **The MVP milestone sequencing (Parts 15–18) has been human-reviewed and is APPROVED** as of the 2026-08-23 revision below — see "Sequencing Revision" immediately before Part 15 for what changed and why. This document does not override `docs/PROJECT_MEMORY_ARCHITECTURE.md`.

Date: 2026-08-23 (original audit). Sequencing revised and approved: 2026-08-23.

## How this audit was performed

Direct inspection of the primary repository's authoritative architecture documents (`docs/PROJECT_MEMORY_ARCHITECTURE.md`, `AGENTS.md`, `docs/project_constitution.md`, `docs/runtime_governance.md`, `docs/research/MULTI_AGENT_PRODUCT_REVIEW.md`) and real implementation code (`code/prototype_v1/projects/models.py`, `project_store.py`, `activity_store.py`, `checkpoint_proposal_store.py`, `project_context_retriever.py`, and `code/prototype_v1/dashboard.html`'s Project Workspace rendering), plus read-only inspection of the Android repository's `ProjectDetailScreen.kt`, `ProjectWorkspaceScreen.kt`, and `BackendInvestigationPanel.kt`. No new code was written or run; conclusions are grounded in what the code and docs actually contain today, verified by direct reads/greps, not assumption.

---

## 1. Existing architecture structures that already support Universal Project Workspace v1

This is the single most important finding of this audit: **the backend schema already anticipates most of the Universal Project Workspace concept**, more than a first read of the product prompt would suggest.

- `ProjectCheckpoint` (`models.py:62`) already carries `current_objective`, `completed_summary`, `discoveries_summary`, `current_work`, `stopped_at`, `blockers`, `next_action` — directly maps to Workspace Home's Where We Are / Now / Next / Blockers.
- `ProjectActivityType` (`models.py:33`) already enumerates `NOTE`, `OBSERVATION`, `ACTION`, `RESULT`, `DECISION`, `BLOCKER`, `MILESTONE`. `DECISION` and `MILESTONE` in particular mean the "Decisions" drill-down and roadmap-item tagging do not require new activity types to exist at all — they already do.
- `ProjectActivityConfirmationStatus` (`models.py:49`) already enumerates `REPORTED`, `OBSERVED`, `INFERRED`, `CONFIRMED` — this closely tracks the requested trust progression (`INFERRED` ≈ AI Hypothesis, `CONFIRMED` ≈ Confirmed Finding) without needing a new enum for those two states.
- `ProjectActivity.metadata` (`models.py:196`) is an already-implemented flexible `dict[str, str|int|float|bool|None]` (up to 16 entries, 2048 chars total) — a ready-made place to attach roadmap-status, idea/promoted-from references, or evidence-relationship pointers without a schema change.
- `CheckpointProposal` (`models.py:388`, `checkpoint_proposal_store.py`) already implements exactly the "AI/human proposes a Checkpoint change, human validates before it becomes canonical" loop the Roadmap needs, including `source_activity_ids` provenance and a project-revision-bound apply/reject lifecycle.
- `ProjectContextRetriever`'s `_CONTRACTS` dict (`project_context_retriever.py:128`) already implements the MUST/MAY/MUST-NOT retrieval semantics (`required_categories`/`optional_categories`/`excluded_categories`) per question class, with interpretability metadata (`category_inclusion_reasons`, `fallback_used`/`fallback_reason`) already returned to the caller.
- `dashboard.html`'s Project Workspace already renders Now (objective + blockers combined), Next, History, Investigations/Evidence, and Suggested Next Steps (the Checkpoint Proposal UI, already using "Suggested"/"Confirm & Add"/"Dismiss" plain-language framing per the existing Presentation Addendum 2).
- Android's `ProjectDetailScreen.kt`/`ProjectWorkspaceScreen.kt` already render Where We Left Off, Next Action, Recent Activity, Continue Project, and Work-on-this-Project/Active toggling, plus project-scoped Capture (physically validated per Slice 3/4).

## 2. Existing structures that can be extended rather than replaced

- **Roadmap**: extend `ProjectActivityType` usage (already has `MILESTONE`) plus `ProjectActivity.metadata` for a roadmap-status tag (`upcoming`/`current`/`completed`/`deferred`/`idea`), rather than a new Roadmap store. Checkpoint's `current_objective`/`current_work`/`next_action` remain the single source for "Where We Are"/"Now"/"Next."
- **Ideas**: extend `ProjectActivityType` with one new value (`IDEA`) rather than a new store. Promotion (Idea → Roadmap) is a new Activity referencing the original via `metadata` (Activities are append-only/immutable — confirmed: `activity_store.py` exposes only `create_activity`/`list_activities`, no update — so "promotion" must be a new record, not an in-place mutation, which is actually consistent with the existing event-log design).
- **Open Questions**: extend `ProjectActivityType` with one new value (`OPEN_QUESTION`), or represent via `NOTE` + a `metadata` tag if a smaller footprint is preferred for MVP.
- **Findings**: `RESULT` and `DECISION` activity types plus `ProjectActivityConfirmationStatus` already carry most of what "Finding" needs (tentative vs. strongly supported = `INFERRED` vs. `CONFIRMED`). A dedicated `FINDING` activity type is optional, not required, for MVP.
- **Continue/Disagree/More Evidence**: extend the *existing* Investigation reassessment loop and Checkpoint Proposal creation (already used for "Propose as Next Action" from a History Activity per the C2 Addendum) rather than building a new state machine. "Continue" = create/apply a Proposal sourced from the AI activity without changing its `confirmation_status`. "Disagree" = create a new Activity capturing the user's correction, referencing the original AI activity in `metadata`, and re-invoke the existing Investigation reassessment path with that correction appended to context — no new backend concept needed beyond an Activity + a slightly richer Investigation reassessment call. "More Evidence" = the Investigation session simply stays `collecting`/unresolved (existing lifecycle state), with additional evidence appended before another `analyze` call — already fully supported by the existing Investigation session lifecycle.
- **Recent Important Changes**: a read-side filter over existing `list_activities` (by `activity_type` in `{MILESTONE, DECISION, BLOCKER}` or checkpoint-affecting Proposal-apply events) plus Checkpoint field diffs between the last two known revisions. No new store.
- **Evidence relationships**: Investigation evidence is already scoped to a session (`investigations/evidence_store.py`) and referenced by the resulting Activity (D2 projection already links `investigation_session_id`/`investigation_result_id` in Activity `metadata`). Extending "which Finding/Decision does this Evidence support" is largely a metadata-linking exercise, not a new relationship schema, for MVP.

## 3. Genuine missing capabilities

Being honest about what is NOT just "already there in disguise":

- **No structured Roadmap concept exists today.** Checkpoint has single current/next strings, not an ordered list of roadmap items with status. Even with the metadata-tagging approach above, *someone* has to write the small amount of new code that reads Activities filtered by roadmap-status and assembles them into a Completed/Current/Upcoming/Deferred view. This is real, if small, work.
- **No `IDEA` or `OPEN_QUESTION` activity type exists.** Two enum values, each requiring the small ripple of updating any code that pattern-matches on `ProjectActivityType` exhaustively (e.g. Activity rendering in `dashboard.html`, any future Android rendering).
- **No "Recent Important Changes" endpoint/view exists.** Only raw `list_activities` (full History) exists today.
- **No Continue/Disagree/More Evidence UI exists anywhere** (backend or either client). The backend primitives it would be built from (Activities, Proposals, Investigation reassessment) exist, but the actual reassessment flow — re-invoking analysis with the original evidence plus a user correction appended — has never been built or tested.
- **Blockers are not rendered on Android at all** (confirmed via grep — zero matches for "Blockers" in the Android UI source), even though the backend field and the dashboard.html rendering both already exist. Android-only gap; out of scope to fix under this task's read-only constraint, but material to the gap matrix below.
- **No Evidence drill-down screen exists on either client** — Investigations/Evidence exists on the dashboard as a list, but nothing lets a user browse Evidence independently of an Investigation session, or see "what Finding does this support."
- **No Decisions, Findings, History, Ideas, or Open Questions drill-down screens exist on either client**, even though the backend `DECISION` activity type already exists to power a Decisions view today with zero backend changes.

## 4. Proposed Universal Project Workspace v1 layout

(This restates ADR-046's approved layout; see that ADR for the authoritative wording.)

```
PROJECT IDENTITY        name, one-sentence objective, honest progress/health only if computable
WHERE WE ARE             current state / current milestone
NOW                       current work
NEXT                      immediate next action
BLOCKERS                  unresolved blockers (if any)
ROADMAP                   completed | current | upcoming | deferred
RECENT IMPORTANT CHANGES  meaningful state changes only (not raw History)
─────────────────────────────────────────────────────────────
Drill-downs: Evidence · Decisions · Findings · History · Ideas · Open Questions
```

Home summarizes; drill-downs detail. No section is populated with fabricated content — an honestly-empty section (matching the existing "No current work recorded." pattern already used by both clients) is correct behavior, not a bug, when a Project genuinely has nothing there yet.

## 5. Proposed Project state transitions

**Idea flow**: `IDEA` → user explicitly promotes → `ROADMAP (upcoming)` → becomes priority → `ROADMAP (current)` / `NOW` → completed → `OUTCOME` / `HISTORY`. Every arrow is a distinct, explicit user action (or an applied Proposal) — nothing here is implicit.

**Project Decision flow**: `PROPOSAL` (AI- or user-sourced, referencing source Activities) → human validation (apply/reject, i.e. Confirm & Add / Dismiss in existing UI language) → `DECISION` (recorded, becomes part of Recent Important Changes) → optionally changes Roadmap/current state.

**Investigation/AI flow**: `EVIDENCE` → `AI HYPOTHESIS` (Activity, `confirmation_status = inferred`) → user choice: **CONTINUE** (Now/Next may update; hypothesis stays `inferred`, never silently becomes `confirmed`) | **DISAGREE** (correction captured as a new Activity referencing the original; original never promoted; AI reassesses with correction + original evidence) | **MORE EVIDENCE** (Investigation session stays unresolved; gather more; reassess).

No giant state machine is proposed. Three flows, each with 3–5 states, all built from primitives (`Activity`, `Proposal`, `Investigation session status`) that already exist.

## 6. Exact semantics of Continue / Disagree / More Evidence

See ADR-049 for the authoritative wording. Summary for implementation planning:

| Action | User burden | System effect | What must NOT happen |
|---|---|---|---|
| CONTINUE | None beyond "seems reasonable" | Now/Next may update to reflect the working direction | The claim must not become a Confirmed Finding or silently overwrite Checkpoint without going through the existing Proposal apply step |
| DISAGREE | Explain what seems wrong (free-form; may itself be uncertain) | Correction preserved as provenance (new Activity, referencing the original); AI reassesses using original evidence + correction; new proposal presented | The original AI conclusion must never become canonical; the user is never required to already know the right answer |
| MORE EVIDENCE | Provide another photo/measurement/explanation/test | Investigation session remains unresolved (existing `collecting`-equivalent state); reassess after new evidence is attached | Must not be collapsed into a binary accept/reject — it is a genuine third outcome |

## 7. Recommended Roadmap representation

Smallest-correct-change recommendation: do NOT add a new `RoadmapItem` model/store for MVP. Instead:
1. Represent an item's roadmap position using existing `ProjectActivity.metadata` (e.g. `{"roadmap_status": "upcoming"}`), read by a new small server-side aggregation function/endpoint (e.g. `GET /projects/{project_id}/roadmap`) that groups Activities by that metadata key plus falls back to Checkpoint's `current_objective`/`next_action` for the Current/Now items. **This alone is sufficient for Milestone 1 (Part 17) and requires no new enum value.**
2. Add `IDEA` to `ProjectActivityType` (one enum value) — see Part 3 and Part 8. **Per the approved sequencing (see "Sequencing Revision" before Part 15), this is deferred to Milestone 4, not part of Milestone 1.**
3. Promotion (Idea → Roadmap) creates a new Activity (not a mutation), referencing the original Idea Activity's id in its own `metadata`, consistent with the append-only Activity design already in place. **Also Milestone 4.**

This keeps Roadmap fully within existing storage/isolation/provenance guarantees (project-scoped, atomic, zero new schema, zero new store).

## 8. Recommended Ideas behavior

An Idea is simply an Activity with `activity_type = IDEA` (once added) and no roadmap-status metadata (or `roadmap_status: "idea"` explicitly). It is visible only in the Ideas drill-down, never in Roadmap/Now/Next, until a user explicitly promotes it. No automatic drift-detection is required for this MVP behavior to work — the guardrail is achieved simply by *never automatically writing to Roadmap-affecting fields from conversation*, which is already the existing rule for Checkpoint (ADR-017/021).

## 9. Recommended Evidence relationship model

For MVP: reuse existing Investigation evidence + Activity `metadata` linking (already how D2 projection ties an Activity back to its `investigation_session_id`/`investigation_result_id`). A Finding (a `RESULT`/`DECISION` Activity, or eventually a `FINDING` Activity if added) can reference its supporting evidence via the same `metadata` mechanism, pointing at Investigation evidence ids already owned by that session. This is not the full relational graph implied by the product prompt's `FINDING → EVIDENCE[] → INVESTIGATION → OUTCOME` conceptual model, but it is sufficient to prove the concept end-to-end without a new schema; a richer explicit relationship table is reasonable POST-MVP if the metadata-linking approach proves too limited in practice.

## 10. Recommended Recent Important Changes behavior

A read-side filter, not a new store: query `list_activities(project_id)`, filter to `activity_type in {MILESTONE, DECISION, BLOCKER}` plus any Activity that was the `source_activity_id` of an *applied* Checkpoint Proposal (a Roadmap/Checkpoint-affecting event), sort by `occurred_at_utc` descending, bound to a small limit (e.g. last 5–10), matching the existing bounded-context convention (ADR-030) already used for Context Packs. This can ship as a small addition to the existing Context Retriever module or as a thin new read-only endpoint; either is a small, additive change with no new persistence.

## 11. Universal Kernel assessment

The universal kernel (Objective, Current State, Roadmap, Next Action, History, Evidence, Decisions, Findings, Open Questions, Blockers, Outcomes, Ideas) is **sufficient for MVP** and is, per the findings in Part 1–3 above, already 60–70% represented by existing schema fields and enum values. Domain-specific specialization (HVAC asset/complaint/measurement, construction punch lists, IT incident symptom/root-cause fields) would each require their own field sets and is correctly deferred post-MVP — nothing about the current architecture blocks adding domain templates later as an *additive* layer over the same kernel Activities/Checkpoint, since `ProjectActivity.metadata` already provides an escape hatch for domain-specific key/value pairs without a schema change.

## 12. Context Engine / retrieval implications

No new retrieval architecture is needed — only new categories in the existing `_CONTRACTS` mechanism (`project_context_retriever.py`). For a "what should I do next" question, the existing `next_action` contract (`QUESTION_CLASS_NEXT_ACTION`, `required_categories=("project_identity","current_objective","blockers","next_action")`) would extend naturally to also require `roadmap_current` and optionally include `roadmap_upcoming`/`recent_important_changes`, while continuing to exclude `deep_historical_evidence`, deferred Ideas, and superseded recommendations — exactly the MUST/MAY/MUST-NOT shape the product prompt describes, because that shape is already how `_CONTRACTS` works today. This task does not implement any retrieval change; it confirms the existing mechanism is the correct extension point.

## 13. Sample Custom Meta AI Glasses Workspace Home

**SAMPLE — assembled by this audit from real repository state as of 2026-08-23. Not generated by a Workspace engine (none exists yet). Everything below is either directly sourced from `docs/PROJECT_MEMORY_ARCHITECTURE.md`'s own Phase Roadmap/ADR log, or explicitly marked [inferred].**

```
═══════════════════════════════════════════════════════════════
  PROJECT: Custom Meta AI Glasses / Persistent AI Project Assistant
═══════════════════════════════════════════════════════════════

OBJECTIVE
  Build a project-aware persistent AI assistant where the
  application - not the LLM - owns Project Memory, with glasses
  as an important but non-central interface. [from Product Vision]

WHERE WE ARE
  Core Project Memory, deterministic/question-aware retrieval,
  grounded Q&A, project-scoped Investigation capture, and the
  Investigation analysis path are all implemented and physically
  validated on real Android hardware with a real OpenAI call.
  Architecture for the next major surface (Universal Project
  Workspace v1) has just been designed and captured (this task).

NOW
  Deciding and sequencing the MVP implementation plan for
  Universal Project Workspace v1 (this audit's output, Part 15/16
  below) - not yet started as code.

NEXT
  [inferred - pending human decision] Implement the single next
  milestone identified in Part 18 of this audit's final report.

BLOCKERS
  None currently recorded in Project Memory. [Note: this Project
  itself does not yet use its own Checkpoint `blockers` field in
  the repository - illustrating the exact "can I trust an honestly
  empty section" case this Workspace design must handle correctly.]

ROADMAP
  Completed:
    - Phases A-G1 (Project schema, Activities, Checkpoint Proposals,
      Investigation-Project ownership, Context Retriever/Context
      Pack, question-aware retrieval, retrieval contracts +
      interpretability, grounded Q&A)
    - Slice 1/2 (Project-first navigation shell, Active Capture
      Project + ADR-037 precedence)
    - Slice 3 (Android project-scoped capture, physically validated)
    - Slice 4 (Investigation analysis orchestration restored, real
      end-to-end OpenAI call proven)
    - Multi-Agent Product Review (7 independent reviewer passes +
      synthesis)
  Current:
    - Universal Project Workspace v1 design/audit (this document)
  Upcoming:
    - [inferred] MVP implementation per Part 16 below, pending
      human approval of sequencing
  Deferred:
    - Glasses Project Navigator (ADR-045) - needs Meta SDK
      capability spike first
    - Project Memory Index (ADR-041)
    - Action Artifacts / cross-agent continuity (ADR-044)
    - Domain-specific Workspace templates
    - Automatic Project Drift detection

RECENT IMPORTANT CHANGES
  - ADR-038/039 captured: Android capture attribution physically
    proven; Investigation orchestration restored
  - ADR-040 through ADR-045 captured: ICM-informed context
    engineering, trust-progression model, cross-agent continuity,
    Glasses Navigator - all approved roadmap, none implemented
  - Multi-Agent Product Review completed and saved (research,
    human review required)
  - ADR-046 through ADR-051 captured (this task): Universal
    Project Workspace v1 concept approved

IDEAS (deferred, not on Roadmap)
  - "Who has the ball" responsibility tracking (research/roadmap
    only per this audit)
  - Multi-agent orchestration as a product feature (explicitly
    NOT approved - research possibility only, per
    MULTI_AGENT_PRODUCT_REVIEW.md)

OPEN QUESTIONS
  - [inferred] Exact MVP milestone sequencing (this audit proposes
    an answer in Part 16; requires human approval)
  - Whether external user validation should precede further
    roadmap investment (flagged by the Multi-Agent Product Review,
    unresolved)
```

**Test**: could a user open this tomorrow and understand where the Project stands without asking an AI "where were we"? For everything sourced directly from the repository's own Phase Roadmap/ADR log: yes. For the `[inferred]` items: no — those are exactly the gaps a real MVP must fill with actually-recorded Project state rather than an auditor's guess, which is itself evidence for why structured Roadmap/Blockers/Open-Questions state (not just an ADR log meant for architecture, not day-to-day orientation) is worth building.

## 14. Gap-analysis matrix

| Workspace Capability | Existing Support | Status | Gap | MVP Change Needed? |
|---|---|---|---|---|
| Project identity | `Project.name`, `.goal` | IMPLEMENTED | None | No |
| Objective | `Checkpoint.current_objective` | IMPLEMENTED | None | No |
| Current state / "Where We Are" | `Checkpoint.current_work`/`completed_summary` (backend); "Where We Left Off" (Android), "Now" (dashboard) | IMPLEMENTED | Naming inconsistency across clients (cosmetic) | No (MVP) |
| Current milestone | `ProjectActivityType.MILESTONE` exists; no aggregation view | ARCHITECTURE ONLY | No milestone-specific query/view | Yes - small |
| Now / current work | `Checkpoint.current_work` | IMPLEMENTED | None | No |
| Next action | `Checkpoint.next_action` | IMPLEMENTED | None | No |
| Blockers | `Checkpoint.blockers`; rendered on dashboard, NOT on Android | PARTIAL | Android rendering gap (Android is read-only for this task) | No backend change; Android gap noted only |
| Roadmap (completed/current/upcoming/deferred) | Enum values + metadata field exist; no aggregation | ARCHITECTURE ONLY | No roadmap-status convention or query endpoint | Yes - small |
| Completed roadmap items | Derivable from Activities | ARCHITECTURE ONLY | Same as above | Yes - small |
| Upcoming roadmap items | Not derivable from History alone (future-oriented, not an occurred event) | MISSING | Needs the roadmap-status metadata convention | Yes - small |
| Deferred roadmap items | Same as Upcoming | MISSING | Same | Yes - small |
| Recent Important Changes | Derivable by filtering `list_activities` | ARCHITECTURE ONLY | No filtered view/endpoint exists | Yes - small |
| Evidence | Investigation evidence store (photos/audio) | IMPLEMENTED (for Investigation evidence) | No cross-Investigation Evidence drill-down UI | Yes - small (UI + thin query) |
| Evidence relationships (Evidence → Finding) | Activity `metadata` linking pattern already used by D2 | PARTIAL | Not yet applied generically beyond D2's own use | Yes - small |
| Decisions | `ProjectActivityType.DECISION` | IMPLEMENTED (schema) | No Decisions drill-down UI on either client | Yes - small (UI + thin query) |
| Findings | `RESULT`/`DECISION` + confirmation_status | PARTIAL | No dedicated `FINDING` type or drill-down UI | Optional for MVP |
| History | `list_activities` | IMPLEMENTED | None | No |
| Ideas | No `IDEA` activity type | MISSING | One enum value + drill-down UI | Yes - small |
| Open Questions | No representation | MISSING | One enum value (or NOTE+metadata) + drill-down UI | Yes - small |
| Outcomes | `RESULT` activity type | IMPLEMENTED (schema) | No explicit Outcome-of-a-Finding linkage | Optional for MVP |
| Proposal / human validation | Checkpoint Proposal (Phase C2), pending/applied/rejected | IMPLEMENTED | None (already extends to Roadmap use per ADR-047) | No |
| Continue | No dedicated flow; closest analog is Proposal apply | MISSING (as a named flow) | New thin flow: apply Proposal without confirming underlying Activity | Yes - small |
| Disagree | No dedicated flow | MISSING | New: capture correction Activity + re-invoke Investigation reassessment | Yes - moderate |
| More Evidence | Investigation session lifecycle already supports staying unresolved | ARCHITECTURE ONLY | No explicit "More Evidence" UI affordance; underlying mechanism exists | Yes - small (UI mostly) |
| Project-scoped capture | Slice 3, physically validated | IMPLEMENTED | None | No |
| Project switching | Active Capture Project / Viewed Project distinction (Slice 1/2) | IMPLEMENTED | None | No |
| Context retrieval | E1/E2/E3 deterministic + question-aware + interpretable | IMPLEMENTED | New categories needed for Roadmap/Ideas/Recent-Changes once those exist | Yes - small, once new data exists |
| Provider independence | `ProjectReasoningProvider` Protocol; one concrete OpenAI implementation | PARTIAL | Never proven with a second provider | No (MVP) |
| Phone workspace | Android `ProjectDetailScreen`/`ProjectWorkspaceScreen` | IMPLEMENTED (subset) | Missing Roadmap/Ideas/Decisions/Findings/Open-Questions/Recent-Changes UI | Yes - moderate (Android, out of scope to implement under this task) |
| Future glasses workspace | ADR-045, gated on SDK spike | ROADMAP | Entire surface unbuilt | No (post-MVP by design) |

## Sequencing Revision (approved 2026-08-23, supersedes the original Part 17/18 below)

The original version of this document (Part 17) proposed a 5-milestone sequence organized around isolated backend concepts: (1) Roadmap as structured state *including adding the `IDEA` activity type*, (2) Recent Important Changes, (3) Continue/Disagree/More Evidence, (4) Evidence/Decisions/Findings drill-downs, (5) Ideas/Open-Questions drill-downs + promotion. That sequence was reviewed by the user and **NOT approved as written**. It has been superseded, for one stated reason: it organized work around backend concepts rather than around the user experience and MVP demo story.

**What changed, specifically:**

- The original Milestone 1 bundled adding the `IDEA` enum value into the first Roadmap milestone. The approved sequence explicitly moves all Idea/`IDEA` work out of Milestone 1 and into the new Milestone 4 ("Ideas / Plan Control"). **Milestone 1 in the approved sequence does not require or implement `IDEA`.**
- The original 5 milestones each targeted one backend concept (Roadmap, Recent Changes, Trust Loop, Evidence/Decisions/Findings, Ideas) largely independently. The approved sequence instead groups work around 5 *product-facing* milestones that together tell the MVP demo story end to end: Project Orientation/Roadmap → Trusted AI Loop → Project Knowledge → Ideas/Plan Control → MVP Demo Hardening. Recent Important Changes, previously its own milestone, is now folded into Milestone 3 ("Project Knowledge") alongside Evidence/Decisions/Findings/History, since all five are the same kind of user-facing "inspect what the Project knows" surface.
- A fifth milestone requirement - an explicit "stop adding concepts and harden the demo" phase - did not exist as a distinct, required milestone in the original sequence. It is now **Milestone 5, and is required**, ending with an explicit feature freeze.
- The underlying technical content of Parts 1–14 above (existing-architecture findings, gap matrix, semantics, sample Workspace Home) is unaffected by this revision and remains valid grounding for the approved sequence below.

## 15. Strict MVP boundary

The MVP must prove, using the smallest correct extension of what already exists:

1. **Application-owned Project state** — already proven; no new work required to keep proving it.
2. **Clear Workspace orientation** — Identity/Where We Are/Now/Next/Blockers already renderable from existing Checkpoint; the new piece needed is a structured Roadmap view (Milestone 1).
3. **Roadmap/current/next continuity** — a roadmap-status metadata convention + one small aggregation query, WITHOUT `IDEA` (Milestone 1; see Sequencing Revision above).
4. **Project-scoped evidence capture** — already proven (Slice 3/4); no new work.
5. **AI Investigation reasoning** — already proven (Slice 4); no new work.
6. **Continue / Disagree / More Evidence** — the one genuinely new *flow*, built on existing Activity/Proposal/Investigation-session primitives (Milestone 2).
7. **Human-validated Project state evolution** — already proven via Checkpoint Proposal apply/reject; extending this to Roadmap items via the same mechanism (ADR-047) is additive, not new.
8. **Project switching without losing state** — already proven (Slice 1/2).
9. **Selective/bounded AI context** — already proven (E1–E3); extending contracts with new categories once Roadmap/Knowledge data exists is small (Part 12; hardened in Milestone 5).
10. **A reproducible end-to-end demo** — the explicit deliverable of Milestone 5, not an incidental side effect of the other four.

Net: of the 10 MVP-proof requirements, 6 are already proven and require zero new work; the remaining 4 (Roadmap structure, Continue/Disagree/More Evidence, Project Knowledge inspectability, and a hardened reproducible demo) map directly onto Milestones 1, 2, 3, and 5 respectively. Milestone 4 (Ideas/Plan Control) is the one MVP milestone whose primary purpose is a guardrail (protecting Roadmap continuity) rather than a proof-of-capability in this list - it is still required because ADR-048 (Ideas separate from Roadmap until promoted) is part of the approved architecture and the demo story explicitly includes it (see product guardrail below).

## 16. Explicit post-MVP list (audited against current architecture) + MVP planning guardrail

**Guardrail, to be applied to every proposed feature during implementation**: for every proposed feature, ask **"does this block the MVP demo?"** If yes, it belongs in the current milestone. If no, it goes on the post-MVP list below unless it is nearly free AND clearly reduces implementation risk. An interesting idea surfaced mid-milestone must not interrupt the current milestone - it is exactly the kind of thing Milestone 4's Ideas mechanism exists to hold.

Auditing the post-MVP list against actual architecture blockers:

| Item | Genuinely blocks MVP? | Reasoning |
|---|---|---|
| Project Memory Index optimization | No | ADR-041; only needed once Activity volume makes the existing full-scan retrieval slow (per the Multi-Agent Review's Architecture finding) - not yet the case for a demo-sized Project |
| Advanced Interpretable Context Packs | No | E3 already provides baseline interpretability; deepening it is independent of the Workspace MVP |
| Full Action Artifact abstraction | No | Unrelated to Workspace; cross-agent continuity is its own future milestone |
| Full cross-agent execution orchestration | No | Same as above; not part of this product surface at all |
| MCP | No | Not currently needed by anything in this design; no MCP-shaped gap was found in this audit |
| Multiple production AI providers | No | One working OpenAI adapter is sufficient to prove Continue/Disagree/More Evidence end to end |
| Automatic Project Drift detection | No | The MVP-relevant protection (Ideas separate from Roadmap until promoted, Milestone 4) does not require automatic detection - it requires only that nothing writes to Roadmap-affecting fields without an explicit action, which is already the rule |
| Full Neural Band Project Navigator | No | Gated on an unstarted SDK spike (ADR-045); entirely independent of Workspace v1, which is phone/desktop-first |
| Advanced haptics | No | Same as above |
| Domain-specific templates | No | Universal Kernel is sufficient per Part 11 |
| Complex workflow customization | No | Explicitly out of scope per ADR-046 (not a Jira/Procore/ServiceTitan) |
| Sophisticated "who has the ball" | No | Research/roadmap idea only; no MVP dependency found |
| Full multi-user collaboration | No | Single-user prototype scope is unchanged by this design |

No item in this list was found to actually block the MVP. **After Milestone 5 (MVP Demo Hardening) completes, MVP feature development is explicitly frozen** - none of the items above, nor any other new product concept, should begin until that freeze is deliberately lifted by a future, separate decision.

## 17. Approved MVP implementation sequence (supersedes the original Part 17)

Five milestones, organized around the user-facing MVP demo story rather than isolated backend concepts. Each still answers "does this block the MVP demo?" before inclusion; each still prefers extending `Project`/`ProjectCheckpoint`/`ProjectActivity`/`ProjectActivityType`/`ProjectActivity.metadata`/`CheckpointProposal` over new stores or abstractions.

### Milestone 1 — Project Orientation / Roadmap

- **Purpose**: A user opens a Project and immediately understands where it stands - completed, where we are, now, next, deferred/later, and what's blocking it. Intentionally narrow.
- **Existing components reused**: `Project`, `ProjectCheckpoint`, `ProjectActivity`, `ProjectActivityType` (`MILESTONE`/`ACTION`/`BLOCKER` already exist), `ProjectActivity.metadata`, `CheckpointProposal`.
- **Smallest required changes**: adopt a roadmap-status metadata convention (e.g. `{"roadmap_status": "upcoming|current|completed|deferred"}` on existing Activities) and one small read-only aggregation endpoint (e.g. `GET /projects/{project_id}/roadmap`) that groups Activities by that key and merges in Checkpoint's current-state fields (objective/current_work/next_action/blockers).
- **Backend changes**: one small new function/module + one new FastAPI route. **No new enum value.**
- **Android changes**: none required for this milestone (backend/API only).
- **Tests/acceptance**: a Project with Activities tagged `upcoming`/`completed`/`deferred` returns a correctly-grouped Roadmap view; Blockers/Now/Next render correctly from Checkpoint; zero OpenAI calls; existing Activity/Checkpoint tests remain green.
- **What NOT to build here**: **no `IDEA` activity type, no Idea capture or promotion (that is Milestone 4)**; no new store; no roadmap reordering/drag-and-drop; no domain-specific roadmap fields.

### Milestone 2 — Trusted AI Loop

- **Purpose**: Complete the human validation loop around AI Investigation results: AI result → human judgment → validated working Project-state change → Workspace reflects the change.
- **Existing components reused**: Investigation session lifecycle (already supports staying unresolved), `ProjectActivity` (for capturing a Disagree correction), `CheckpointProposal` (for a Continue-driven Now/Next update).
- **Smallest required changes**: after an Investigation analysis completes, present the existing D2-projected Activity with three actions instead of none. **CONTINUE**: create/apply a Proposal sourced from the AI Activity to update Now/Next through the existing validated mechanism, without changing the AI Activity's `confirmation_status` to `confirmed`. **DISAGREE**: ask what the user thinks the AI got wrong (free-form, no correct answer required); create a new Activity capturing the correction, referencing the original AI Activity; never promote the original conclusion to canonical truth; reassess using the original evidence + original AI result + the user's feedback; present an updated proposal. **MORE EVIDENCE**: keep the Investigation session unresolved (existing lifecycle state) while more evidence (photo/measurement/observation/spoken context/test) is attached, then reassess.
- **Backend changes**: likely one new small endpoint or a parameter addition to the existing analyze/reassess path to accept a prior AI result + user correction as additional context; no new orchestrator; no new AI-call pattern beyond the existing "one call per analysis/reassessment."
- **Android changes**: UI for the three actions and the Disagree free-form correction input (out of scope to implement under this task's read-only Android constraint; scoped here for planning only).
- **Tests/acceptance**: Continue never flips `confirmation_status` to `confirmed`; Disagree preserves the original Activity unchanged and creates a new correction Activity, and the original AI conclusion never becomes canonical; More Evidence keeps the session unresolved; each action makes at most one OpenAI call.
- **What NOT to build here**: no automatic drift detection; no multi-round Disagree negotiation UI beyond one reassessment cycle; no formal "rejected" status exposed to the user (ADR-049).

### Milestone 3 — Project Knowledge

- **Purpose**: Make important Project knowledge inspectable and connected to the Project: Evidence, Decisions, Findings, History, and Recent Important Changes, as clickable/drill-down Workspace areas.
- **Existing components reused**: `ProjectActivityType.DECISION` (already exists), Investigation evidence store, existing Activity `metadata` linking pattern already used by the D2 projection, `list_activities`.
- **Smallest required changes**: three-to-four small read-only filtered views. Decisions = Activities where `activity_type=DECISION`. Evidence = existing Investigation evidence, presented per-Project and linked toward the Finding/Investigation/Decision it supports via existing `metadata` references, not a new relationship schema. Findings = `RESULT`/`DECISION` Activities with `confirmation_status` shown (tentative vs. strongly supported). History = existing `list_activities`, unchanged. Recent Important Changes = a filter over `list_activities` selecting `activity_type in {MILESTONE, DECISION, BLOCKER}` plus Proposal-apply-sourced Activities, bounded to a small limit - preferably derived here rather than becoming a new canonical store.
- **Backend changes**: minor filtering additions reusing existing store methods; no schema change; one or two new thin read-only endpoints.
- **Android changes**: new list/detail screens for these drill-downs (out of scope to implement here; scoped for planning).
- **Tests/acceptance**: each drill-down returns only Activities/evidence correctly scoped to the Project; Recent Important Changes returns only the meaningful subset, correctly bounded and ordered, and is visibly distinct from raw History; zero OpenAI calls; cross-Project isolation holds.
- **What NOT to build here**: no general graph database or new evidence-relationship architecture; no rich evidence-graph visualization; no Findings confidence scoring beyond existing `confirmation_status`.

### Milestone 4 — Ideas / Plan Control

- **Purpose**: Allow useful ideas to be captured without disrupting current work - the concrete implementation of ADR-048 (Ideas separate from Roadmap until promoted).
- **Existing components reused**: `ProjectActivity`, `ProjectActivity.metadata`, the append-only Activity design (confirmed: `activity_store.py` exposes only `create_activity`/`list_activities`, no update).
- **Smallest required changes**: add `IDEA` to `ProjectActivityType` (the one new enum value deliberately deferred out of Milestone 1); add `OPEN_QUESTION` (or represent via `NOTE` + a metadata tag if a smaller footprint is preferred); a simple "Promote to Roadmap" action that creates a **new**, separate roadmap-tagged Activity referencing the original Idea's id in `metadata` - it must never mutate the original Idea Activity into a different historical event, consistent with the existing append-only design.
- **Backend changes**: one or two enum values, one small promotion action/endpoint.
- **Android changes**: Ideas/Open Questions list screens + a Promote action (out of scope to implement here; scoped for planning).
- **Tests/acceptance**: capturing an Idea never appears in Roadmap/Now/Next until explicitly promoted; promoting an Idea creates a new, correctly-linked Roadmap Activity without altering the original; the original Idea Activity remains unchanged and independently retrievable after promotion.
- **What NOT to build here**: no automatic Project Drift detection; no AI-suggested promotions (post-MVP research idea only).

### Milestone 5 — MVP Demo Hardening (REQUIRED)

- **Purpose**: Stop adding product concepts. Make the existing MVP reliable, understandable, and demo-ready. This milestone is explicitly required, not optional or implicit.
- **Existing components reused**: everything built in Milestones 1–4, plus already-proven Slice 1–4 capabilities (Project switching/persistence, Android capture, Investigation analysis, bounded context retrieval).
- **Smallest required changes**: no new product surface. Validate end to end: Project switching, Project persistence, Roadmap persistence, the Investigation workflow, Continue/Disagree/More Evidence, validated Project-state changes, Evidence relationships, Workspace orientation, History, bounded/selective Context retrieval, and Android-backend integration, assembled into one realistic demo scenario. Add or finish the smallest appropriate regression harness covering that complete MVP story (extending existing deterministic zero-OpenAI test patterns where possible). Perform UX cleanup only where necessary for the demo to be understandable - not a general polish pass. Use realistic demo evidence (real-looking photos/measurements) rather than meaningless placeholder images where practical.
- **Backend changes**: none expected beyond bug fixes surfaced by end-to-end testing; no new endpoints, no new schema.
- **Android changes**: none expected beyond bug fixes surfaced by end-to-end testing (still read-only for the purposes of this documentation task).
- **Tests/acceptance**: the full 15-step MVP story (open a Project → orientation → capture evidence → AI analysis → Continue/Disagree/More Evidence → validated state change → Workspace reflects it → Evidence/Decisions/Findings/History inspectable → Ideas captured without hijacking Roadmap → switch Projects → independent state confirmed → return → exact prior state → Context Engine sends only relevant context → full workflow regression-tested) passes reproducibly.
- **What NOT to build here**: MCP, multi-agent orchestration, Project Memory Index, advanced Interpretable Context Packs, full Action Artifact framework, additional production AI providers, automatic Project Drift detection, full Glasses Project Navigator, advanced Neural Band/haptic behavior, domain-specific templates, complex workflow customization, multi-user collaboration - **all explicitly post-MVP, and MVP feature development is frozen once this milestone completes.**

Design-risk note: Milestone 2's Disagree reassessment path remains the single highest-design-risk piece of work in this plan (genuinely new behavior, not just a new view over existing data) and should be built and tested most carefully, ideally after Milestone 1 exists so it has real Roadmap context to update into.

## 18. The single next implementation milestone after this audit

**Milestone 1 — Project Orientation / Roadmap**, explicitly **without** `IDEA`/Ideas work (deferred to Milestone 4). It is the smallest, lowest-risk milestone, requires zero Android changes, reuses existing storage/isolation/provenance guarantees entirely, and its acceptance criteria are fully testable with existing deterministic (zero-OpenAI) test patterns already used throughout the codebase. It is also a prerequisite for Milestone 2's Continue action to have something concrete to update ("Now/Next may update" needs a Now/Next that's more than a single string once Roadmap exists).
