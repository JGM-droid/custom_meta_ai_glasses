# Project Interaction Foundation

Status: Authoritative design for the approved Project Interaction foundation. No production implementation is authorized by this document.

Last updated: 2026-09-03

Authority: This document refines ADR-052, ADR-054, and ADR-057 in `PROJECT_MEMORY_ARCHITECTURE.md`. If it conflicts with that document, `PROJECT_MEMORY_ARCHITECTURE.md` wins.

## Purpose

A Project is a persistent objective. An Investigation is one bounded way of working toward that objective, not the universal container for every AI task.

The shared application flow is:

```text
explicit Project
-> Project Interaction
-> deterministic Context Pack
-> AI / tools / media capabilities
-> validated structured result
-> durable projection where warranted
-> explicit user decision
-> existing Project Memory mechanisms
```

Candidate future interaction families include `INVESTIGATE`, `EXPLORE`, `RESEARCH`, `COMPARE`, `GUIDE`, `PLAN`, `EXPLAIN`, and `ANALYZE_EVIDENCE`. This foundation does not implement or authorize all of them.

## Core Decision

Project Interaction is a lightweight application-level orchestration and correlation boundary. It is not initially:

- a new persisted aggregate or store;
- a universal session or workflow state machine;
- a conversation log;
- an Activity replacement;
- an Investigation replacement;
- a device-owned state model.

The first implementation reuses the existing Project Store, Activity Store, Idea service, Checkpoint Proposals, Context Pack retrieval, Knowledge/Orientation projections, and Investigation subsystem.

## Minimum Interaction Contract

The generic request boundary contains only properties that apply across interaction families:

```text
ProjectInteractionRequest
    project_id          explicit ownership boundary
    interaction_type
    user_intent
    input_refs          bounded references owned by the same Project
    idempotency_key     when retry convergence is required
```

The application supplies:

```text
interaction_id         server-generated correlation identity
context contract/retrieval identity
timestamps
provider/tool provenance
```

The common contract does not contain universal evidence readiness, current step, trust state, proposal state, result storage, or Investigation attempt fields. Those are transient or interaction-family-specific.

All durable operations require explicit `project_id`. Active Project is a client convenience and must not replace explicit identity. Starting or viewing an interaction must not change the Active Project.

## Lifecycle and Persistence

The generic lifecycle is conceptual service behavior:

```text
RECEIVED
-> CONTEXT_ASSEMBLED
-> EXECUTING
-> RESULT_VALIDATED
-> DURABLE_PROJECTIONS_RECORDED
-> COMPLETED
```

A controlled failure may occur before completion. This lifecycle is not initially a persisted enum.

Project Interaction itself is not persisted as a first-class object. A stable `interaction_id` is carried by the durable records produced by an interaction. Retry convergence uses explicit Project identity, an idempotency key, the interaction identity, project-scoped lookup, and deterministic projection order. A retry must reconstruct or return the same durable projections instead of duplicating them.

Result retention is family-specific:

- `INVESTIGATE`: the existing Investigation Session and retained result remain authoritative.
- Initial `EXPLORE`: validated options are projected idempotently as ordered AI/inferred `IDEA` Activities sharing one `interaction_id`.
- Future `RESEARCH`: unsaved references may remain transient; explicitly saved references become bounded Activities.
- Future `GUIDE`: instructions may remain transient; meaningful completed actions, blockers, decisions, and proposed next actions use existing Project Memory records.
- Read-only `EXPLAIN`: no write occurs unless the user explicitly records a correction, observation, decision, or action.

Activity metadata may contain bounded scalar correlation fields such as `interaction_id`, `interaction_type`, `result_item_id`, `option_ordinal`, `source_activity_id`, disposition, and idempotency key. It must not become storage for nested structured results, provider payloads, instructions, or arbitrary JSON.

A dedicated Interaction or result store may be reconsidered only after a measured resumability, concurrency, recovery, or query requirement cannot be met by these existing owners.

## Relationship to Existing Project Memory

### Project and Checkpoint

The Project is the ownership boundary. The Checkpoint remains canonical current state. AI execution and result projection never mutate it directly.

### Activity

Activity remains the append-only Project history and principal durable projection for non-Investigation interactions. Activities may represent AI Ideas, user Decisions, completed Actions, Blockers, saved References, promoted Roadmap work, and source/result correlation.

Activity records what durably happened; it does not orchestrate provider work. Later dispositions are new linked Activities, never in-place rewrites.

### Investigation

Investigation keeps its specialized lifecycle and stores. Ordered evidence, validation/readiness, frozen manifests, analysis attempts, retained diagnostic results, retry behavior, trust decisions, follow-up sessions, and More Evidence continuity remain Investigation-specific.

`ANALYZE_EVIDENCE` uses Investigation when it creates a diagnostic inference requiring evidence retention, trust assessment, or follow-up evidence. A generic interaction label must not bypass those guarantees.

### Evidence

Evidence remains with its existing authoritative owner. Investigation evidence stays in the Investigation Evidence Store; observation Activities remain Project evidence. Other interactions reference Project-owned evidence rather than copying media into another store.

### Context Pack

Every AI-backed interaction uses the existing deterministic, bounded Project Context Retriever. Each interaction type declares required, optional, and excluded categories. Providers do not independently receive unrestricted Project history.

Durable decisions needed for continuity may need explicit contract inclusion even when older than the current recency window. This extends the existing interpretable retrieval contracts; it does not authorize vector search, graph storage, or a second retrieval system.

### Ideas, Decisions, Roadmap, and Proposals

AI-generated Explore options are AI-sourced, `inferred` Idea Activities. They are proposals under consideration, not Findings, Decisions, Roadmap items, or Project truth.

User dispositions are append-only user Decision Activities linked to an Idea:

- keep for consideration;
- dismiss;
- select direction.

A read projection derives current disposition without mutating the original Idea. Dismissed Ideas remain in audit history but are excluded from active/default context.

These states remain distinct:

- `promoted`: existing Idea promotion created upcoming Roadmap work;
- `selected`: the user recorded a Decision;
- `canonical direction`: an applicable Checkpoint Proposal was explicitly applied.

Consequential checkpoint changes continue through revision-bound Checkpoint Proposal Apply/Reject. AI output never silently mutates canonical Project state.

### Knowledge and Orientation

Knowledge and Orientation remain deterministic read models. They may project interaction output only according to existing source and confirmation semantics. An inferred Idea is never a confirmed Finding merely because it was generated, retained, selected, or promoted.

## Initial Structured Result Model

The first discriminated result union contains exactly two semantic types.

### `OPTION_SET`

An option set offers possible directions. It is intentionally not called `DECISION`, because the AI has not made the user's decision.

```text
OPTION_SET
    result_id
    title
    summary
    source_refs
    options[1..N]

Option
    option_id
    ordinal
    title
    summary
    rationale?          bounded
    tradeoffs?          bounded
    source_refs
```

The application, not the provider, derives allowed actions such as keep, dismiss, select, or promote. Successful initial Explore projection already retains the options as inferred Ideas; the UI must not misleadingly present them as approved or canonical.

### `INFORMATION_REQUEST`

This allows a provider to report insufficient context rather than invent an answer.

```text
INFORMATION_REQUEST
    result_id
    title
    prompt
    requested_inputs
    continuation_key
    source_refs
```

Requested inputs describe semantic needs such as evidence, measurement, preference, constraint, or confirmation. They do not contain Android routes, camera intents, HUD callbacks, or device-specific controls.

Deferred result families are `INSTRUCTION`, `REFERENCE`, `ANNOTATED_EVIDENCE`, generic `DECISION`, and `PROJECT_UPDATE`. `PROJECT_UPDATE` must not duplicate Activities or Checkpoint Proposals. The wider candidate families in ADR-054 remain roadmap direction, not first-milestone scope.

## Provider, Provenance, and Validation Boundary

Provider output is never accepted as arbitrary canonical text. Before projection, the application must enforce:

- a recognized discriminator and schema version;
- unknown-field rejection;
- bounded counts and text lengths;
- application-generated or normalized IDs;
- same-Project resolution for every source reference;
- provider-neutral schemas;
- application-authorized actions only;
- controlled failure for invalid output;
- no silent fallback from arbitrary prose to structured Project state.

Provenance records the interaction, Context Pack contract/retrieval identity, relevant source references, provider/tool identity, timestamps, and projected Activity IDs. Raw prompts, secrets, conversation history, and provider-native response structures are not canonical Project Memory.

AI projections remain `source_type=ai` and `confirmation_status=inferred`. A later user Decision does not rewrite their origin or retroactively confirm them.

## Cross-Device Rendering

The canonical result is semantic and device-independent.

- Desktop may show the complete option set, rationale, tradeoffs, sources, provenance, and all authorized actions.
- Android may show concise expandable option cards and richer decision controls, followed by canonical reload after ambiguous mutations.
- Glasses may show Project identity, result title, one concise option at a time, and a very small supported action set.

Layout, colors, icons, route names, carousel position, truncation, local media paths, and SDK callbacks are renderer state, not canonical result fields. Glasses remain a lossy projection/controller over the same backend state and never own memory.

The original DAT 0.8 Display/Band capture *spike* (pre-Project-aware, abandoned on
`feature/glasses-display-capture`) is not part of this foundation. As of 2026-09-02, HUD/Band
photo capture is an explicit approved MVP requirement implemented fresh inside this foundation's
Project-aware architecture (see docs/ROADMAP.md's "Status Update - 2026-09-02" under the DAT 0.8
Capture Capability Gate) - the underlying `Stream.capturePhoto()` reliability risk that gate
documented remains `NOT PRODUCT-READY` as a *guarantee*, and is surfaced honestly rather than
hidden.

## Room Redesign Architecture Test

1. Open `Room Redesign` with explicit `project_id`.
2. Submit `EXPLORE`: "Give me ideas for making this room warmer and more modern."
3. Retrieve bounded room evidence, constraints, prior Decisions, and current Project state through one deterministic Context Pack contract.
4. Perform one provider-neutral call and validate one `OPTION_SET`.
5. Idempotently project Warm Modern, Dark Contemporary, and Minimal Natural as ordered AI/inferred Idea Activities sharing one `interaction_id`.
6. Do not mutate Checkpoint, revision, Active Project, Roadmap, Findings, or Decisions.
7. Record user-linked Decisions: select Warm Modern, dismiss Dark Contemporary, keep Minimal Natural for consideration.
8. Use existing Idea promotion only if the user explicitly wants upcoming Roadmap work.
9. Use a Checkpoint Proposal plus explicit Apply only if Warm Modern should change canonical direction or next action.
10. Reopen and derive:
    - selected direction from user Decision and applied checkpoint state;
    - considering options from Ideas and dispositions;
    - dismissed options in history but not default active context;
    - next action from the canonical Checkpoint;
    - provenance from interaction, Ideas, sources, and Decisions.

Another Project must be unable to retrieve or act on any option, Activity, or source reference from this interaction.

## AC Repair Architecture Test

- `INVESTIGATE` — "Why isn't this blower working?" uses the existing Investigation evidence/result/trust/Proposal lifecycle.
- `GUIDE` — "Show me how to remove this blower motor" will consume bounded accepted context and return a future Instruction. Only meaningful completed Actions, Blockers, or proposed next-action changes become durable.
- `RESEARCH` — "Find me a diagram or useful video" will return provider-neutral References. Unsaved candidates remain transient; saved references become bounded Activities without duplicating media.
- `ANALYZE_EVIDENCE` — "Mine doesn't look like the reference" uses an existing or follow-up Investigation when diagnostic evidence/trust semantics apply.
- `EXPLAIN` — "Why do you think this part is bad?" may remain grounded read-only reasoning unless the user records a durable correction, Decision, Observation, or Action.

All remain within the same Project continuity without sharing an artificial universal lifecycle.

## Project Guidance Engine Boundary

A future Project Guidance Engine selects an interaction type, retrieval contract, provider/tool capability, structured result family, authorized actions, and device projection.

It does not own Project Memory, a universal workflow state machine, Investigation evidence/trust, provider-specific core schemas, device UI state, or automatic Project mutation. Initial routing should be explicit service dispatch, not autonomous intent classification. **Amended by ADR-060** (`PROJECT_MEMORY_ARCHITECTURE.md`): physical Room Redesign acceptance testing showed explicit dispatch pushed response-family choice onto the user and prevented the natural workflow from ever reaching `EXPLORE_PLAN`. Routing is now application-owned bounded intent inference (a Response Planner reading a narrow deterministic Context Pack, never full Project history or a chat transcript) - the Engine's other boundaries in this paragraph (no Project Memory ownership, no workflow state machine, no automatic Project mutation) are unchanged.

ADR-059 in `PROJECT_MEMORY_ARCHITECTURE.md` names and scopes the first approved realization of this engine as the Response Planner, selecting exactly one of three V1 response families (`TROUBLESHOOT`, `EXPLORE_PLAN`, `GENERAL_GUIDANCE`) - `TROUBLESHOOT` maps to the existing `INVESTIGATE` interaction/Investigation lifecycle above unchanged, and `EXPLORE_PLAN` evolves this document's `OPTION_SET` result (below) with a richer payload. ADR-060 amends only how the family is selected (inferred by the Planner from Project context and the current request, not chosen by the user or the client) - it does not change these three families, `ProjectAIResult`, or the trust boundary. Exact schemas remain a future design milestone; see ADR-059, ADR-060, and `docs/ROADMAP.md`'s "Rich Project Intelligence V1" entry for current status and non-goals.

## Media and External Tool Boundary

Web research, documentation, products, diagrams, images, and videos remain provider/source neutral. Core interaction schemas request capabilities rather than naming YouTube, shopping, or another vendor.

Unsaved candidates remain transient. Saved references use existing bounded Activity/provenance mechanisms. Rich media remains at its authoritative source; Project Memory stores references, not a second research/media database.

## First Implementation Milestone

The single smallest proof is a backend-first Room Redesign `EXPLORE` interaction:

1. One explicit Project-scoped Explore endpoint/service.
2. One server-generated `interaction_id` and idempotency contract.
3. One interaction-specific deterministic Context Pack contract.
4. One provider-neutral call.
5. Strict `OPTION_SET | INFORMATION_REQUEST` validation.
6. Idempotent projection of three ordered AI/inferred Ideas into the existing Activity store.
7. Linked user Keep/Dismiss/Select Decision Activities.
8. Existing Idea promotion and Checkpoint Proposal/Apply boundaries where explicitly requested.
9. Store reconstruction proving selected, considering, dismissed, promoted, and canonical next-action state.
10. Tests for retries, deterministic order, provenance, Project A/B isolation, explicit Project precedence, zero Active Project mutation, one provider call, and no Investigation creation.

This milestone is approved as the next proposed proof, not implemented or authorized by this documentation task. It should remain backend-first; client and glasses work require separately bounded follow-up scope.

## Rejected and Deferred

Rejected for the foundation:

- universal Interaction persistence or retained-result store;
- making every interaction an Investigation;
- Activity as the orchestration engine;
- rich structured JSON in Activity metadata;
- client-owned canonical state;
- direct AI mutation;
- mutable Ideas or another Ideas/Research/Reference store;
- universal trust or workflow engines;
- device-specific canonical schemas;
- vector/graph retrieval;
- the abandoned pre-Project-aware DAT 0.8 Display/Band capture *spike* (`feature/glasses-display-capture`) specifically - not HUD/Band capture as a capability, which is approved MVP scope as of 2026-09-02 (see Cross-Device Rendering above and docs/ROADMAP.md).

Deferred:

- Guide step recovery and generalized automatic routing;
- media/provider implementations;
- comparison persistence;
- additional structured-result families;
- glasses implementation and DAT 0.9 evaluation;
- full Action Artifact machinery.
