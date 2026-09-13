# Project Memory Architecture

Status: Authoritative for approved forward product architecture.

Last Updated: 2026-09-12

Product name (canonical, use this internally, not "ChatGPT with memory" or "AI chatbot for Meta glasses"): **Persistent AI Project Workspace**. See "Canonical Architecture Re-Baseline (2026-09-12)" near the end of this document for the current authoritative reference architecture, proven-vs-unproven findings, the one remaining architecture gate, product positioning, and the usability acceptance specification. That section supersedes any prior informal framing in this document where the two conflict; it does not delete or invalidate the ADR history below.

## Product Vision

The product has evolved from a primarily glasses-centered assistant into a project-aware persistent AI assistant.

Core user outcome:

- The user can switch between multiple independent projects.
- The system restores each project's correct state without cross-project contamination.
- Backend restarts do not erase project continuity.

Examples of projects:

- Upstairs AC Repair
- Custom Meta AI Glasses
- Lanyard Construction Website
- Capstone Project

Meta Ray-Ban Display glasses remain an important interface and evidence source, but they are not the sole architectural center.

## Why the Architecture Changed

The repository now has a strong Investigation subsystem with durable identity, lifecycle, evidence, orchestration, and retained-result patterns.

However, product continuity needs now exceed a single investigation flow:

- Users need long-lived project containers.
- Multiple projects must remain isolated.
- State must survive application restarts.
- LLM conversation cannot be the authoritative memory.

The approved pivot is additive:

- Keep the working Investigation architecture.
- Add project-scoped persistent memory as the top-level platform concern.

## Core Architectural Principle

The application owns state.

The AI reasons over selected state.

The LLM conversation is not authoritative project memory.

```text
Interfaces
    |
    v
Project Manager
    |
    +-------------------+
    |                   |
    v                   v
Project A            Project B
    |                   |
Checkpoint           Checkpoint
Activities           Activities
Evidence             Evidence
Memory               Memory
    |
    v
Context Retriever
    |
    | selected relevant context only
    v
AI / Investigation / Reasoning
    |
    v
OpenAI
    |
    v
Answer + proposed structured updates
    |
    v
Validation
    |
    v
Application-owned Project Memory
```

## System Architecture

### Legacy Architecture (historical)

- Early prototype global session memory and active-task flow.
- Glasses-first framing for product narrative.

### Currently Implemented Architecture

- FastAPI backend with Investigation Session lifecycle.
- Session/evidence persistent stores under filesystem JSON.
- Deterministic orchestration, frozen manifests, attempt ownership, retained results.
- Desktop and glasses projections backed by canonical retained results.

### Approved Future Architecture

- Project Manager + Project Memory become top-level continuity layer.
- Investigation Sessions become bounded activities within projects.
- Context retrieval becomes explicit, deterministic, and selective per project/task.
- A Project Context Retriever sits between persistent Project Memory and model calls.
- The retriever produces a compact Context Pack instead of sending full project history by default.

## Project vs Investigation

This distinction is mandatory:

- Project: long-lived container for continuity.
- Investigation Session: bounded activity that can occur within a project.

Future conceptual relationship:

```text
Project
    |
    +-- Investigation Session
    +-- Investigation Session
    +-- manual activity
    +-- checkpoint
    +-- evidence
    +-- future activity types
```

Project is not equal to Investigation Session.

## Project Memory Model

Initial approved conceptual model (not implemented in this document):

```text
Project:
    project_id
    schema_version
    name
    goal
    status

    checkpoint:
        current_objective
        completed_summary
        discoveries_summary
        current_work
        stopped_at
        blockers
        next_action

    revision
    created_at_utc
    updated_at_utc
```

API direction (persistent operations should be explicit by project_id):

- get_project(project_id)
- get_checkpoint(project_id)
- list_project_activities(project_id)
- get_project_evidence(project_id)

An active_project_id may exist as a convenience, but must not replace explicit project identity in persistent APIs.

## Memory Layers

Approved long-term memory layering:

```text
RAW EVIDENCE / ACTIVITY
        |
        v
STRUCTURED OBSERVATIONS / EVENTS
        |
        v
PROJECT CHECKPOINT
        |
        v
PROJECT SUMMARY
```

Retrieval rule:

- Do not send full Project history to the LLM by default.
- Use checkpoint-level context for common continuity questions.
- Retrieve deeper evidence only when needed.

### Hot vs Historical Context

Hot context:

- canonical checkpoint
- current objective
- blockers
- next action
- recent/relevant activities
- relevant recent Investigation summaries

Historical memory:

- older activities
- older Investigations
- evidence
- historical checkpoint/proposal information

### Context Pack

Project Memory -> deterministic retrieval -> small Context Pack -> OpenAI.

The first implementation milestone for this layer is a deterministic Project Context Retriever / Context Pack.

## Context Retrieval

Memory write, memory retrieval, and AI reasoning are separate concerns.

Context Retriever responsibilities (future):

- Select only context needed for the current request.
- Enforce project namespace isolation.
- Avoid unrelated project leakage.

Example:

- Question: Where did we leave off on the AC?
- Typical context: project identity, checkpoint, blockers, next action.
- Exclude by default: unrelated project evidence, entire history, non-relevant transcripts.

## Storage Strategy

Approved near-term storage decision:

- Keep filesystem JSON for minimal Project foundation.
- Do not introduce PostgreSQL, Neo4j, Redis, vector DB, external memory service, or distributed storage yet.

Conceptual filesystem layout direction:

```text
results/
    projects/
        projects/
            <project_uuid>.json

        active_project.json

        corrupt/
        archive/
        temp/

    investigation_sessions/
        ...
```

SQLite may be considered later only if measured needs justify it.

## Provenance Strategy

Future project memory must distinguish:

1. User-provided facts
2. Directly observed evidence
3. AI inference
4. Confirmed conclusions
5. Hypotheses
6. Actions performed
7. Outcomes

AI inference must not silently become objective fact.

## Existing Components We Keep

Preserve and continue evolving:

- FastAPI backend
- Investigation Session lifecycle
- Session UUID identities
- Investigation evidence store and server-owned sequencing
- Atomic persistence and optimistic revision protection
- Frozen evidence manifests
- Analysis attempt ownership
- Canonical retained Investigation results
- OpenAI/provider abstraction
- Investigation orchestrator
- Glasses and desktop projections
- Existing Investigation APIs and compatibility guarantees

Pattern reuse guidance:

- Reuse design principles first.
- Do not tightly couple new Project Memory to Investigation implementation classes unless intentionally justified.

## Legacy Components to Deprecate

Legacy prototype memory system:

- code/prototype_v1/memory_manager.py
- code/prototype_v1/results/session_memory.json

Status:

- Legacy / to be deprecated.
- Keep temporarily for backwards compatibility.
- Do not expand as Project Memory foundation.

## Phase Roadmap

### Phase A - Complete

- Architecture/research review and pivot definition.

### Phase B - Implemented (Minimal Foundation)

Implemented scope:

- Project schema with explicit UUID identity.
- Project checkpoint schema (minimal fields only).
- Atomic filesystem ProjectStore.
- One-file-per-project durable persistence.
- Active project pointer persistence.
- Project API endpoints for create/list/get/checkpoint update/active selection/active retrieval.
- Optimistic revision conflict checks on checkpoint mutation.
- Isolation and restart-persistence tests.
- Investigation compatibility regression coverage.

Explicitly not implemented in Phase B:

- Investigation-to-Project ownership linking.
- Activity history and structured observations.
- Evidence provenance graphing.
- Context retrieval pipeline.
- AI-proposed memory updates.
- Semantic/vector/graph retrieval.
- Dashboard/UI workflow for project memory.

### Phase C

- Structured project activities and checkpoint evolution rules.

### Phase C1 - Implemented (Project Activity History Foundation)

Implemented scope:

- Structured project activity schema with explicit UUID identity.
- Project-scoped activity store with atomic one-file-per-activity persistence.
- Hard storage namespace boundary under `activities/<project_id>/`.
- Project activity API endpoints for append/list/get under project scope.
- Deterministic activity ordering by `occurred_at_utc`, then `created_at_utc`, then `activity_id`.
- Corruption quarantine handling for malformed activity records.
- Regression tests for project isolation, ownership denial, persistence, and zero-OpenAI behavior.

Explicitly not implemented in Phase C1:

- Automatic checkpoint mutation from activities.
- Automatic project revision or `updated_at_utc` mutation from activity append.
- Any AI-generated memory writing pipeline.

Phase C2 will define validated Activity -> Checkpoint update rules.

### Phase C2 - Implemented (Validated Checkpoint Update Pipeline)

Implemented scope:

- Explicit Checkpoint Proposal layer persisted separately from Project and Activity records.
- Project-scoped proposal storage under `checkpoint_proposals/<project_id>/`.
- Proposal fields include base project revision, source activity references, proposed checkpoint patch, and explicit status.
- Proposal lifecycle is intentionally minimal: `pending`, `applied`, `rejected`.
- Proposal creation validates source activity ownership and captures `base_project_revision`.
- Proposal retrieval remains project-scoped and deterministic.
- Proposal apply is explicit, validates pending state and base revision, applies only specified patch fields, and marks proposal applied.
- Proposal reject is explicit, terminal, and does not mutate canonical Project state.
- Proposal create/list/get/apply/reject operations perform zero OpenAI calls.

Semantics and constraints:

- Activity history does not directly mutate canonical Project checkpoint state.
- AI inference does not automatically become confirmed Project fact.
- Proposal creation does not mutate Project checkpoint, revision, or updated timestamp.
- Proposal rejection does not mutate Project checkpoint, revision, or updated timestamp.
- Proposal apply increments Project revision exactly once and updates Project `updated_at_utc`.
- Applied/rejected proposals are terminal and cannot transition between terminal states.

Atomicity note:

- Apply uses a project-scoped lock and deterministic write ordering (Project then Proposal) within one critical section.
- If filesystem failure occurs after Project write but before Proposal write, a subsequent apply request can reconcile by recognizing the already-applied patch at `base_revision + 1` and finalizing the Proposal state.
- This minimizes inconsistent windows without introducing a database or broad persistence redesign.

### Phase D

- Connect Investigation Sessions to Projects.

### Phase D1 - Implemented (Investigation -> Project Ownership)

Implemented scope:

- Investigation Session schema now supports an optional `project_id` ownership field.
- New project-scoped Investigation endpoints:
    - `POST /projects/{project_id}/investigation-sessions`
    - `GET /projects/{project_id}/investigation-sessions`
    - `GET /projects/{project_id}/investigation-sessions/{session_id}`
- Project-scoped create validates project existence before session creation.
- Project-scoped retrieval enforces ownership and returns not-found on cross-project access.
- Ownership operations perform zero OpenAI calls.

Compatibility decision:

- Legacy Investigation session records without `project_id` remain valid and loadable.
- Legacy sessions are intentionally excluded from project-scoped list/get endpoints.
- Existing global Investigation endpoints remain compatible for legacy and transitional clients.

### Phase D2 - Implemented (Investigation Result -> Project Activity)

Implemented scope:

- Successful project-owned Investigation completions create a durable Project Activity projection.
- Projection is idempotent and keyed by originating Investigation session/result identity.
- Projection uses conservative provenance:
    - source_type reflects AI/system origin
    - confirmation_status remains inferred
- Projection does not mutate Project checkpoint or revision.

Compatibility decision:

- Legacy/unowned Investigations do not receive Project Activities.
- Failed or cancelled Investigations do not create completed-result Activities.
- Projection failure is treated as deferred/non-canonical and does not overwrite the canonical Investigation result.

Next implementation milestone:

- Deterministic Project Context Retriever / Context Pack.
- First version must prove selective retrieval over existing checkpoint, Activity, and Investigation data.
- First version must not use embeddings, vector databases, graph databases, semantic RAG, new AI calls, dashboard changes, or glasses/Android changes.

### Phase E1 - Implemented (Deterministic Project Context Retriever / Context Pack)

Implemented scope:

- Read-only deterministic Project Context Retriever using existing Project, Activity, and Investigation stores.
- Explicit project-scoped Context Pack endpoint: `GET /projects/{project_id}/context`.
- Context Pack includes:
    - project identity/name/goal/status
    - canonical checkpoint
    - current objective
    - blockers
    - next action
    - recent project activities
    - recent completed project-owned Investigation summaries
- Deterministic hot-context limits:
    - recent activities: last 5
    - recent completed project-owned Investigations: last 3
- Context retrieval performs zero OpenAI/model calls.
- Context retrieval does not mutate Project state, revision, timestamps, checkpoints, or proposals.

Known limitations:

- First version is bounded but not question-aware.
- Historical memory, evidence expansion, and proposal history are intentionally excluded by default.
- Retrieval is deterministic only; no semantic/vector/graph retrieval is used.

### Phase E2 - Implemented (Question-Aware Project Context Retrieval)

Implemented scope:

- Read-only question-aware project context retrieval path: `POST /projects/{project_id}/context/query`.
- Uses the E1 Context Pack boundary and deterministic filtering/ranking over existing checkpoint, recent activities, and recent project-owned Investigation summaries.
- Core checkpoint/current objective/blockers/next action remain available as stable hot context.

Deterministic ranking strategy:

- Lowercased token normalization.
- Simple keyword overlap scoring.
- Common stopwords excluded from matching.
- Deterministic tie-breaking by recency and stable IDs.
- Activity metadata may influence tie-breaking through activity type, source, and confirmation status.

Fallback behavior:

- If the question does not meaningfully match hot-context terms, retrieval falls back to checkpoint plus bounded recent context.
- No historical expansion or semantic retrieval is attempted.

Known limitations:

- Ranking is lexical and deterministic only; it is not semantic.
- The query path does not yet generate answers or call OpenAI.
- Historical evidence/proposal expansion remains intentionally excluded by default.

### Phase E3 - Implemented (Retrieval Contracts + Interpretable Context Packs)

Implemented scope:

- Adds a deterministic question-classification layer before E2 lexical ranking.
- Initial deterministic question classes:
    - `continuity`
    - `status`
    - `next_action`
    - `evidence_lookup`
- Each class applies an explicit retrieval contract with required, optional, and excluded-by-default categories.
- Query Context Packs now include interpretability metadata:
    - detected question class
    - retrieval contract identifier
    - required/optional/excluded categories
    - selected categories
    - per-category inclusion/exclusion reasons
    - limits applied
    - fallback usage and reason

Behavior constraints:

- Classification and retrieval remain deterministic and perform zero OpenAI/model calls.
- Retrieval remains project-scoped, bounded, and read-only.
- Deep historical evidence remains excluded by default.
- E1 and E2 API compatibility is preserved through additive query metadata.

### Phase F1 - Implemented (Lightweight Project Workspace / Project Inspector)

Implemented scope:

- Adds a lightweight desktop/web Project Workspace projection in `dashboard.html`.
- Reuses existing read-only project APIs to render:
    - My Projects list
    - Project Inspector sections: Now, Next, History, Investigations / Evidence
    - Ask This Project using `POST /projects/{project_id}/context/query`
- Ask This Project displays selected context and compact interpretability metadata; it does not generate AI answers.

Authoritative-memory boundary:

- The Project Workspace is a projection over authoritative Project Memory and retained Investigation records.
- It does not mutate Project, Activity, Checkpoint, or Proposal state.

Known limitations:

- F1 is read-only and demo-oriented.
- Ask This Project shows context-selection output only; no OpenAI answer generation is performed.
- Investigation evidence relationships remain limited to currently implemented bounded summaries.

### Phase G1 - Implemented (Grounded Project Q&A over E3 Context Pack)

Implemented scope:

- Adds project-scoped grounded Q&A endpoint: `POST /projects/{project_id}/ask`.
- Uses the E3 deterministic question-aware Context Pack as the only retrieval source for answer generation.
- Introduces a provider-neutral reasoning boundary for project Q&A with an OpenAI-backed adapter.
- Returns explicit grounding metadata and compact source references with each answer.
- Reports insufficient-context outcomes explicitly without mutating canonical memory.

Behavior constraints:

- One ask request performs exactly one provider model call.
- Project Q&A does not mutate Project, Activity, Checkpoint, Proposal, or Investigation canonical state.
- Project-scoped isolation is preserved through the existing deterministic retriever boundary.
- Existing `POST /projects/{project_id}/context/query` behavior remains deterministic and zero-AI.

UI projection scope:

- Project Workspace adds a separate Ask AI action while preserving the original Get Context behavior.
- Ask AI output is labeled as non-canonical AI reasoning over selected project context.

Later phases may include richer evidence, provenance, selective retrieval, possible semantic retrieval, dashboarding, voice/project switching, automatic project suggestions, guided walkthroughs, and potential storage upgrades if justified.

### Phase G1 Addendum - Implemented (Demo Investigation Path Ownership)

Implemented scope:

- The dashboard's existing live demo Investigation path (`POST /demo/investigations`) now accepts an optional `project_id` field.
- When supplied, `project_id` must reference an existing Project (404 otherwise); the created Investigation Session is owned by that Project using the existing D1 ownership mechanism (`SESSION_STORE.create_session(project_id=...)`).
- On successful demo completion, the existing D2 conservative-provenance projection (`_project_completed_investigation_activity`) is invoked for project-owned demo sessions, reusing the same store-level idempotency guarantee already relied on by the canonical `/investigation-sessions/{id}/analyze` path.
- Absent or blank `project_id` preserves the original ownerless demo behavior exactly.
- Fixed a pre-existing defect in the demo path's result persistence (`_DemoResultPersistence.persist_result`) where the returned `result_id` was an unrelated random value instead of the deterministic id the canonical result store actually saves under. This silently prevented any downstream canonical-result lookup (including D2 projection) for demo-created results and is now corrected to match the derivation already used by the canonical session-scoped path.
- Dashboard: the existing "Start Demo Investigation" panel gained an optional Project selector, populated from the existing `GET /projects`, so a live demo Investigation can be attributed to an already-open Project Workspace without any new backend phase.

Compatibility decision:

- No Project creation UI was added in this slice; Projects must already exist (created via the existing `POST /projects`). Superseded by the Phase F1 Addendum below, which adds exactly that UI.
- No automatic checkpoint proposal is created from a demo-projected Activity; checkpoint state remains untouched (ADR-017/018 apply unchanged to the demo path).

### Phase F1 Addendum - Implemented (Create Project from Workspace)

Implemented scope:

- The Project Workspace's My Projects pane gains an explicit "Create Project" action so a Project can be created entirely from `dashboard.html`, with no PowerShell/curl step required.
- Reuses the existing Phase B `POST /projects` endpoint exactly as-is; no backend, storage, or schema changes.
- Required fields: `name`, `goal`. Optional initial checkpoint fields: `current_objective`, `next_action`, passed through unchanged via the existing `ProjectCreateRequest.checkpoint` field. No other checkpoint fields, and no backend-only concepts (revision, checkpoint proposals, schema versions, Activity store internals), are exposed in the form.
- On success, the new Project is opened/selected in the Workspace immediately by reusing the existing project-changed detection added for Ask-view persistence (see the "Preserve project ask results during workspace refresh" change): selecting the new project id before the existing `loadWorkspaceProjects()` refresh runs is sufficient to both open it and correctly clear the previously selected Project's Ask AI answer, Selected Project Context, Why This Context, and debug pack.
- On a validation or server error, the concise error message from the existing `POST /projects` error contract is shown inline in the form; the form stays open and editable, and is never left in a stuck/disabled state.

Compatibility decision:

- This updates the Phase F1 "read-only projection" framing: Project *creation* is now an explicit, user-initiated Workspace action. All other Phase F1 invariants are unchanged - the Workspace still does not edit, delete, archive, or AI-generate state for any *existing* Project, Activity, Checkpoint, or Proposal.

### Phase C2 Addendum - Implemented (Checkpoint Proposal Review UI in Project Workspace)

Implemented scope:

- Exposes the existing Phase C2 Checkpoint Proposal mechanism (`POST/GET /projects/{id}/checkpoint-proposals`, `POST .../{proposal_id}/apply`, `POST .../{proposal_id}/reject`) through a new "Checkpoint Updates" block in the Project Inspector, reusing all four endpoints exactly as-is. No backend, store, or schema changes.
- Closes the previously dead-ended `Investigation -> Activity -> Context -> AI reasoning -> ???` loop: a History Activity now offers a "Propose as Next Action" action that pre-fills a proposed `next_action` from text the existing D2 Activity projection already wrote (parsed from the Activity's own `details`/`summary`; no new AI/model call), which the user can review and edit before creating the proposal via the existing create endpoint with `source_activity_ids` provenance preserved.
- "Checkpoint Updates" is rendered directly beside Now/Next and is explicitly labeled non-canonical; creating a proposal never mutates Now/Next. Only an explicit user click on Apply calls the existing apply endpoint and repaints Now/Next from the server's response - there is no optimistic client-side mutation.
- Reject calls the existing reject endpoint; the checkpoint is left unchanged, matching the existing backend contract.
- A stale-revision Apply attempt (backend `revision_conflict`, HTTP 409) is surfaced as a concise, human-readable message; canonical Project state and the proposal list are refreshed from the server, and the proposal is left exactly as pending as the backend leaves it - it is not automatically rebased, retried, or recreated.
- Project isolation, the existing `loadToken` staleness guard, and the existing project-changed detection (added for Ask-view persistence) are reused unchanged: proposals are fetched in the same guarded batch as Activities/Investigations, a real Project switch clears any in-progress proposal draft, and a same-project background poll tick never touches an open draft.

Compatibility decision:

- No new architectural decision was required for this slice; it exposes Phase C2 exactly as governed by ADR-021 through ADR-027, plus the Project Workspace boundary in ADR-033. The critical rule those ADRs already establish - AI/Activity-derived information may be *proposed* but must never *silently* become canonical Project Memory - is unchanged and is now visible end-to-end in the UI rather than only reachable via direct API calls.
- Context Retriever and `/ask` behavior are untouched by this slice.

### Presentation Addendum - Implemented (Dashboard Leads with Project Workspace)

A read-only product audit found that, despite the architecture correctly treating Project Memory as the persistent center (ADR-002, ADR-012) since the initial pivot, `dashboard.html` itself still opened with the page titled "AI Glasses Live Analysis Dashboard" and led with the Investigation/glasses demo sections, pushing Project Workspace to the sixth section on the page. This is a presentation-only correction, not a new architecture decision:

- Page `<title>` and a new lead section now read "Persistent AI Project Assistant" with the sentence "Keep durable project state, evidence, history, and next actions across work sessions."
- `projectWorkspaceSection` is now the first functional section in `<main>`, before Investigation Session and the other glasses/Investigation-demo sections.
- A one-sentence, jargon-free explanation ("A Project keeps the current state, next action, evidence, and history for one ongoing piece of work.") now sits next to My Projects.
- The Investigation/glasses cluster is unchanged internally and not removed; it is preceded by a short note framing it as evidence capture that can be linked to a Project, and is now positioned below Project Workspace.
- No API, store, schema, Activity projection, context retrieval, Ask AI, proposal, revision, polling, isolation, or provider behavior was touched. This is a DOM-order and copy change only.

### Presentation Addendum 2 - Implemented (Market-Facing Provenance/Trust Terminology)

The Checkpoint Proposal Review UI (see the Phase C2 Addendum above) and History Activity cards used raw backend words - `pending`/`applied`/`rejected`, `ai`/`user`/`system`, `inferred` - as the primary thing a user saw. This addendum translates that presentation into plain, non-technical language while leaving every backend concept it describes completely unchanged:

- History Activity cards now lead with "Captured" (never implying "confirmed"), followed by a human provenance line ("From Investigation · Aug 21" / "Reported by user · Aug 21" / "System note · Aug 21"). Raw `activity_type`/`source_type`/`confirmation_status` values, the full timestamp, and the Activity UUID remain available in a per-card "Details" disclosure.
- "Checkpoint Updates" is now titled "Suggested Next Steps"; a pending Checkpoint Proposal is presented as "Suggested Next Step" with the suggested text, a human "Based on: Investigation from Aug 21" source line (no raw UUID in the primary view), the current canonical `next_action` for comparison, and the note "Nothing changes until you confirm."
- The Apply action is labeled "Confirm & Add" in the UI; on success the card and status message read "Confirmed & Added. This is now part of your project." The Reject action is labeled "Dismiss"; on success it reads "Dismissed. This suggestion was not added to your project."
- A stale-revision Apply attempt (still the existing `revision_conflict`/HTTP 409 backend response) is shown as "This project changed after this suggestion was created. Nothing was overwritten. Review the latest project state before confirming."
- The backend Checkpoint Proposal API, its endpoints (`create`/`list`/`get`/`apply`/`reject`), status enum values (`pending`/`applied`/`rejected`), revision semantics, Activity schema, and D1/D2 projection are entirely unchanged - only `dashboard.html`'s presentation of them changed. Internal JS function/variable names (`applyCheckpointProposal`, `rejectCheckpointProposal`, `workspaceProposalsCache`, etc.) intentionally still say apply/reject/proposal, matching the backend concepts they call.

No new ADR: this does not introduce a new architectural decision - it is the UI expressing the provenance/authority rules already established by ADR-010, ADR-021, and ADR-029 in language a non-technical user can trust, not changing what is or isn't canonical.

### Slice 1 - Implemented (Product Shell: Project-First Navigation Shell)

Restructures `dashboard.html` around the approved product principle - select the Project, get oriented, do the work, the Project captures what happens - without changing any backend contract. Browser and phone are responsive presentations of the exact same Project Workspace, over the exact same DOM, JS state, and API calls already proven by the Phase B/C1/C2/D1/D2 stores and the F1/G1 Workspace slices:

- Desktop shows a persistent Projects sidebar (My Projects list + Create Project, reusing the existing list/create markup unchanged) beside a center workspace. At narrow widths the same sidebar becomes an off-canvas drawer behind a toggle; no separate mobile DOM, JS state, or endpoint exists - `workspaceProjectsCache`/`workspaceSelectedProjectId` and every fetch remain singular and shared.
- A Home state ("What are you working on?", reusing the existing Create Project flow) shows only when zero Projects exist yet; once at least one exists, the existing auto-select-first-project behavior is unchanged and the selected-Project workspace shows instead. This is a pure presentation toggle over `workspaceProjectsCache.length`, not a new persisted "view mode".
- The selected-Project workspace is reordered to a Project header (name + state) - Now - Next - Capture/Ask (the existing Investigation Session form, its result panels, and Ask This Project, grouped) - Suggested Next Steps - History (History and Investigations/Evidence, unchanged; the unified Activity/Investigation/Proposal timeline described in a prior audit remains explicitly deferred). The reorder is CSS `order` over the same DOM nodes, not a rewrite of any of those features.
- **Viewed Project vs. Active Capture Project**: this slice only implements the Viewed Project (whichever Project a given browser/phone UI currently has open - ephemeral, per-tab, never persisted). It intentionally does **not** wire up the existing `ActiveProjectPointer` backend mechanism (`PUT/GET /projects/active[/{id}]`) into this UI, and the project header is labeled "Viewing" - never "Active" - so the UI does not imply capture-ownership routing exists yet. A safe, explicit Active Capture Project (and the device-scoping the current single-global pointer will need before it is safe for browser+phone+glasses to coexist) is deferred to a future slice.
- No `api.py`, Project/Activity/Investigation/Proposal model, Context Retriever, or provider change was made or required.

No new ADR: Slice 1 implements the Project-first shell direction already approved (see the Product Direction section and the prior Presentation Addenda) without introducing a new architectural decision. The Viewed Project / Active Capture Project distinction is a UI/navigation clarification of existing scope, not a new canonical-state concept.

### Slice 2 - Implemented (Active Capture Project)

Wires up the Phase B `ActiveProjectPointer` mechanism (`PUT/GET /projects/active[/{id}]`, deliberately left unconnected by Slice 1) as a real, distinct product concept - the Active Capture Project - separate from the Viewed Project the browser UI already had:

- **Backend contract**: reuses the existing Phase B pointer exactly as implemented (single-pointer, restart-persistent, does not mutate Project records - see the Phase B Acceptance Contract below) with one small, symmetric addition: `DELETE /projects/active` (`ProjectStore.clear_active_project()`), which deletes the pointer file so the system returns to the same `ActiveProjectNotSet`/404 state it already reports when nothing has ever been set. Clearing is idempotent and never touches any Project record. No new model, no device/client scoping, no per-user architecture was introduced - this remains a single-global pointer, matching the current single-user prototype scope Slice 1 flagged as a prerequisite for future multi-device work, not something this slice attempts to solve.
- **Investigation attribution precedence (ADR-037)**: `POST /demo/investigations` and `POST /investigation-sessions` (the two entry points that already accepted an optional `project_id`) now resolve project ownership as explicit `project_id` > Active Capture Project > unscoped, via a shared helper (`_resolve_active_project_id_if_any`) that is deliberately fail-safe: an unset, corrupt, or stale (referencing a since-invalid Project) pointer falls back to the pre-existing unscoped behavior rather than raising, since this is documented as a convenience layer that "must not replace explicit project identity in persistent APIs." The project-scoped `POST /projects/{project_id}/investigation-sessions` endpoint is unchanged - its `project_id` is always explicit via the URL path, so there is never ambiguity for it to resolve.
- **Dashboard**: adds a restrained "Work on this Project" / "● Active Project" + "Stop Working on Project" control next to the Project header, and a subtle sidebar dot beside whichever single Project is Active - both driven by `activeProjectId`, refreshed read-only on the existing `loadWorkspaceProjects()` poll cycle (no new interval, no new client-side state system). Viewing/opening a Project never calls the set-active endpoint by itself; only the explicit control does. The existing "Viewing" badge is preserved for any non-Active Project. The demo Investigation project selector now defaults to the Active Capture Project (labeled "\<name\> — Active") when the user has not explicitly chosen a different value in the current form session, while still allowing explicit override to any other Project or "No project" for debug/demo control.
- Reuses existing Project ownership/isolation (D1) and Activity projection (D2) mechanisms unchanged for however a session ends up owned, whether by explicit `project_id`, Active Capture Project, or neither.

No redundant ADR for the pointer mechanism itself (Phase B already accepted it); ADR-037 below covers only the new attribution-precedence rule, which is a genuinely new behavior (previously, omitting `project_id` always meant unscoped).

### Slice 3 - Implemented (Android Project-Scoped Capture Attribution, Physically Validated)

Implemented scope:

- Android's top-level Capture navigation state now carries an explicit `sourceProjectId`, threaded from a Project's Workspace ("Continue Project" -> "Capture / Test Glasses") through the existing, unmodified Meta camera/capture flow (`CameraAccessScaffold`/`StreamScreen`/Mock Device Kit) into the Investigation submission request, reusing the existing `POST /investigation-sessions` contract's optional `project_id` field. No new backend endpoint was introduced.
- The existing global "Capture / Test Glasses" entry point from Projects Home is unchanged: it supplies no explicit `project_id`, preserving ADR-037's Active Capture Project fallback / unscoped behavior exactly as already implemented server-side.
- Opening/viewing a Project through its Workspace and starting Capture from there does not call the Active Capture Project set endpoint - explicit Project context and global Active Project state are kept deliberately separate on the client, matching the same viewing-vs-active distinction Slice 1/Slice 2 already established for the dashboard.
- A pre-existing, unrelated Compose layout crash in the Mock Device Kit debug screen (nested `Modifier.verticalScroll()` containers - see `MockDeviceKitScreen.kt`/`BackendInvestigationPanel.kt`) was fixed as a prerequisite for physical validation; the fix is layout-only and did not touch Investigation, Project, or attribution logic.

Physical-device/backend validation performed (real backend, real Android device, no mocks):

1. Project A marked Active; Capture started from Project B's Workspace -> the created Investigation session's `project_id` equals Project B, and Project A remained the Active Project throughout. Project B did not become Active merely because Capture was opened from it.
2. Global Capture with Project A Active and no explicit Project context -> the created Investigation session's `project_id` resolves to Project A purely through the existing backend Active Capture Project fallback (Android sent no explicit `project_id`).
3. Global Capture with no Active Project set -> the created Investigation session's `project_id` is `null` (unscoped), confirming existing unscoped behavior remains intact.

This is the first client-side, physically-validated proof of the ADR-037 precedence rule (explicit Project -> Active Capture Project fallback -> unscoped/null) rather than a backend-only/test-only guarantee.

Known limitations:

- Validated against the Mock Device Kit / phone-camera evidence path, not yet against real Meta Ray-Ban Display capture end-to-end.
- No return-navigation, UI-indicator, or Android-side architecture changes beyond attribution plumbing were made; see the Android repository's own commit history for full diff detail (out of scope for this backend-authoritative document).

### Slice 4 - Implemented (Investigation Analysis Orchestration Restored)

Context:

- The existing `POST /investigation-sessions/{session_id}/analyze` orchestration path (`_create_session_orchestrator` -> `OpenAIInvestigationAnalysisProvider` -> `InvestigationOrchestrator.run_confirmed_investigation`) began failing in local development with a generic `"Analysis orchestration is unavailable."` (HTTP 500, category `orchestration_unavailable`).

Root cause (diagnosed, not a new architectural gap):

- `InvestigationOpenAIProviderConfig.from_env()` (`investigations/openai_analysis_provider.py`) reads `OPENAI_API_KEY` only via `os.environ`, with no fallback to the repository's `.env` file - unlike `_load_openai_api_key()` in `api.py` (used by the working Project Q&A path), which already falls back to reading `.env` directly. `api.py`, the actual FastAPI entrypoint, never loaded `.env` into its own process environment, so any `os.environ`-only reader (including the Investigation provider config) would fail in a correctly-configured checkout unless the launching shell happened to export the key manually. A compounding local-environment issue (the server process having been started via a non-canonical, dependency-incomplete Python interpreter instead of the project's own `venv` - see `docs/runtime_governance.md`'s "Venv only" execution contract) was also present and was corrected by restarting through the canonical `venv` interpreter.

Fix:

- `api.py` now calls `load_dotenv(dotenv_path=REPO_ROOT / ".env", override=False)` once at module load, immediately after `REPO_ROOT` is defined and before any `os.environ`-based configuration is read. This reuses the same `python-dotenv` mechanism `demo_live_investigation.py` already established for local Investigation runs, applied once at the actual app entrypoint so every current and future `os.environ`-based reader benefits consistently, rather than adding a third, inconsistent `.env`-reading convention. `override=False` preserves existing precedence: a value already exported in the real shell environment always wins over `.env`.
- No change was made to `investigations/openai_analysis_provider.py` (the provider layer) or to any orchestration/error-handling logic.

Physical-device/backend validation performed (real backend, real Android device, one real OpenAI call):

- Project B Workspace -> Capture -> Mock Device Kit evidence -> spoken/typed explanation -> Analyze, via Android, completed successfully end to end.
- Exactly one Investigation analysis attempt was created and completed (`current_analysis_attempt_id == active_analysis_attempt_id == latest_analysis_attempt_id`, single value, `last_error: null`).
- The completed session's `project_id` remained Project B; the global Active Capture Project (Project A) was unchanged before and after.
- Project B's canonical `checkpoint`/`revision` were unchanged by the AI result - the result was recorded only as a Project Activity with `source_type: "ai"` and `confirmation_status: "inferred"` (existing Phase D2 projection, unchanged), never written into canonical checkpoint state. This directly confirms ADR-029 and ADR-021 continue to hold under a real (non-mocked) analysis result, not only under test fakes.

No new ADR was required for the orchestration behavior itself (nothing about the orchestrator, provider contract, or error taxonomy changed); ADR-039 below covers only the new environment-loading requirement this fix establishes.

## Phase B Acceptance Contract

Proof scenario:

Project A:

- Name: Upstairs AC Repair
- Last: capacitor appears swollen
- Next: identify capacitor rating

Project B:

- Name: Custom Meta AI Glasses
- Last: investigation workflow operational
- Next: implement Project Memory

Required behavior:

- Switch A -> shows AC checkpoint state.
- Switch B -> shows glasses checkpoint state.
- Switch A again -> same AC checkpoint state.
- Restart backend -> switch A -> same AC state persists.

Mandatory requirements:

- Project A mutation does not change Project B.
- Project B mutation does not change Project A.
- Invalid IDs do not leak other project data.
- Malformed records fail safely.
- Persistence is atomic.
- Revision conflicts are detected.
- Active project survives restart.
- Project retrieval makes zero OpenAI calls.
- Project switching makes zero OpenAI calls.
- Existing Investigation tests remain green.
- Existing Investigation API behavior remains compatible.
- Existing glasses/HUD result behavior remains compatible.

### Phase B Implementation Note (2026-08-12)

Implemented backend components:

- Project models under `code/prototype_v1/projects/models.py`.
- Atomic ProjectStore under `code/prototype_v1/projects/project_store.py`.
- Project API surface in `code/prototype_v1/api.py`:
    - `POST /projects`
    - `GET /projects`
    - `GET /projects/{project_id}`
    - `PATCH /projects/{project_id}/checkpoint`
    - `PUT /projects/active/{project_id}`
    - `GET /projects/active`

Implemented storage layout:

```text
code/prototype_v1/results/projects/
        projects/
                <project_uuid>.json
        active_project.json
        corrupt/
        archive/
        temp/
```

Implemented semantics:

- Project identity is explicit and UUID-validated.
- Checkpoint patch updates only provided fields.
- Unspecified checkpoint fields are preserved.
- Successful checkpoint mutation increments project revision exactly once.
- Active project selection is a durable convenience pointer and does not mutate project records.
- Project operations are deterministic and perform zero OpenAI calls.

Known limitations after Phase B:

- No project activity timeline/history yet.
- Global Investigation session endpoints remain available for compatibility and may create sessions without project ownership during transition.
- No structured memory layering beyond checkpoint.
- No advanced retrieval or summarization pipeline.

## Architectural Risks

1. Cross-project contamination
- Highest-risk failure mode.
- Project identity must be a hard namespace boundary.

2. AI state corruption
- LLM output must not directly overwrite canonical Project state.
- AI updates should be structured, validated proposals.

3. Memory/context bloat
- Do not send full history by default.
- Selective retrieval is mandatory.

4. Evidence vs inference confusion
- Provenance and epistemic status must be explicit.

5. Premature infrastructure
- Avoid vector/graph/distributed infrastructure before measured need.

6. Breaking Investigation
- Investigation subsystem is working and must be preserved.

7. Duplicate sources of truth
- Avoid competing canonical state between legacy memory, Project Memory, Investigation results, and UI state.

## Non-Goals

Not part of this architecture alignment phase:

- Implementing ProjectStore or Project APIs
- Changing Investigation behavior/contracts
- Changing OpenAI provider behavior
- Introducing embeddings, RAG, vector DB, graph storage, or SQLite
- Migrating legacy session memory now
- Android changes
- Glasses UI redesign

## Open Questions

- Exact Project API surface for first implementation slice.
- Project activity/event schema granularity for Phase C.
- Active-project selection behavior across multiple client interfaces.
- Explicit archive/retention policy for project activities and evidence.
- Criteria for when simple retrieval becomes insufficient and measured upgrade is justified.

## Architecture Decision Log

ADR-001 - ACCEPTED
Application-owned state; LLM is not canonical memory.

ADR-002 - ACCEPTED
Projects are long-lived containers; Investigations are bounded activities.

ADR-003 - ACCEPTED
Project identity is an explicit isolation boundary.

ADR-004 - ACCEPTED
Legacy global session_memory is not the Project Memory foundation.

ADR-005 - ACCEPTED
Filesystem JSON remains the initial Project persistence mechanism.

ADR-006 - ACCEPTED
Project Memory starts with checkpoints before advanced retrieval.

ADR-007 - ACCEPTED
Memory writing, retrieval, and AI reasoning are separate concerns.

ADR-008 - ACCEPTED
Investigation subsystem remains intact during initial Project Memory implementation.

ADR-009 - ACCEPTED
AI-generated Project updates must eventually be structured and validated before persistence.

ADR-010 - ACCEPTED
Provenance/evidence status must eventually distinguish observations, user facts, inference, hypotheses, actions, and outcomes.

ADR-011 - ACCEPTED
Do not introduce embeddings/vector/graph infrastructure until simple retrieval is proven insufficient.

ADR-012 - ACCEPTED
Glasses are an interface to the platform, not the sole architectural center of the product.

ADR-013 - ACCEPTED
Backward compatibility with the existing Investigation workflow is required during the pivot.

ADR-014 - ACCEPTED
Project retrieval and switching should not require an LLM call.

ADR-015 - ACCEPTED
Phase B proves deterministic persistence/isolation before AI-assisted memory generation.

ADR-016 - ACCEPTED
Project activity records are persisted per project namespace and never globally shared.

ADR-017 - ACCEPTED
Activity append operations are non-authoritative and do not automatically mutate Project checkpoint state.

ADR-018 - ACCEPTED
Activity append operations do not increment Project revision or mutate Project updated_at_utc during C1.

ADR-019 - ACCEPTED
Project activity retrieval remains deterministic through stable ordering keys.

ADR-020 - ACCEPTED
Project activity append/list/get operations must perform zero OpenAI calls.

ADR-021 - ACCEPTED
Activity history does not directly mutate canonical Project checkpoint state.

ADR-022 - ACCEPTED
Checkpoint changes may be represented as explicit persisted proposals.

ADR-023 - ACCEPTED
Checkpoint proposals bind to a base Project revision and do not auto-rebase.

ADR-024 - ACCEPTED
Proposal apply is the only Phase C2 proposal operation that increments Project revision.

ADR-025 - ACCEPTED
Source activity references in proposals must belong to the same Project.

ADR-026 - ACCEPTED
Applied and rejected proposals are terminal states.

ADR-027 - ACCEPTED
Checkpoint proposals are durable records scoped to project identity.

ADR-028 - ACCEPTED
Investigation session ownership is project-scoped, while legacy sessions missing `project_id` remain loadable and backward compatible.

ADR-029 - ACCEPTED
Project Activity projection from completed Investigations must be idempotent, conservative in provenance, and must not mutate Project checkpoint state.

ADR-030 - ACCEPTED
Project context for model-facing use must be assembled through a deterministic, bounded Context Pack rather than by sending full Project history by default.

ADR-031 - ACCEPTED
Question-aware Project context retrieval should begin with deterministic lexical ranking and bounded fallback before any semantic retrieval is introduced.

ADR-032 - ACCEPTED
Question-aware retrieval should apply deterministic question-class contracts with explicit interpretability metadata before lexical ranking results are selected.

ADR-033 - ACCEPTED
The initial Project Workspace is a read-only projection over authoritative Project Memory and deterministic context retrieval outputs, without AI answer generation.

ADR-034 - ACCEPTED
Grounded Project Q&A must reason only over the E3 deterministic Context Pack through a provider-neutral boundary, execute one model call per ask request, and never mutate authoritative project memory.

ADR-035 - ACCEPTED
The dashboard's live demo Investigation entry point is not exempt from Project ownership: it reuses the existing D1 ownership and D2 projection mechanisms exactly as the canonical session-scoped path does, rather than remaining a permanently separate, unowned legacy-only surface.

ADR-036 - ACCEPTED
The Project Workspace may perform explicit, user-initiated Project creation by reusing the existing Phase B `POST /projects` endpoint unchanged; this does not authorize editing, deleting, archiving, templating, or AI-generated mutation of existing Project state, and does not expose backend-only concepts (revision, checkpoint proposals, schema versions, Activity store internals) in the UI.

ADR-037 - ACCEPTED
When an Investigation-start request omits an explicit `project_id`, ownership resolution falls back to the single-global Active Capture Project (Phase B `ActiveProjectPointer`) if one is set, and to unscoped otherwise; an explicitly supplied `project_id` always takes precedence and is never overridden by the Active Capture Project. This resolution must be fail-safe - any pointer/store problem falls back to unscoped rather than blocking Investigation creation - consistent with the Active Capture Project's existing status as a convenience layer that must not replace explicit project identity in persistent APIs.

ADR-038 - ACCEPTED
The ADR-037 precedence rule (explicit Project -> Active Capture Project fallback -> unscoped/null) is a client-observable contract, not only a backend/test guarantee: any client entering Capture/Investigation-creation from a specific Project's Workspace must forward that Project's canonical `project_id` explicitly, and must never call the Active Capture Project set endpoint merely because a Project was opened or captured from. Viewing/using a Project remains conceptually distinct from that Project being globally Active unless the user explicitly requests the latter. This has been physically validated for the Android client (Slice 3) and applies to any future client (Ray-Ban Display, other Android surfaces, desktop) that originates Investigation creation.

ADR-039 - ACCEPTED
`api.py`, as the actual FastAPI runtime entrypoint, must load the repository's `.env` file into its own process environment once at startup (via `load_dotenv`, `override=False`) so that every current and future `os.environ`-based configuration reader - not only the readers that happen to implement their own `.env` fallback - can resolve local secrets/configuration consistently. This does not change what belongs in `.env` versus real environment variables, and does not weaken `docs/runtime_governance.md`'s "one startup path, venv only" execution contract; it removes a gap where a correctly-configured `.env` checkout could still fail a specific provider's configuration loader depending on incidental reader implementation differences.

ADR-040 - ACCEPTED (Research-Informed Roadmap)
Adopt Interpretable Context Methodology (ICM, Jake Van Clief) context-engineering principles - interpretable retrieval, explicit inclusion/exclusion semantics, and bounded/measurable context - as approved future direction for the existing Context Retriever/Context Pack subsystem. Do not adopt ICM's filesystem-centric memory storage architecture. Structured, application-owned Project Memory (ProjectStore, Activities, Checkpoints) remains the sole authoritative memory model; ICM is a source of retrieval/observability principles only, not a storage architecture replacement.

ADR-041 - ACCEPTED (Research-Informed Roadmap)
A future Project Memory Index is approved as a derived, rebuildable, non-canonical compact summary layer over Project Memory (current state, objective, open tasks, blockers, major decisions, key evidence, recent checkpoints, investigations, artifacts, historical topics). It must never become an alternate source of truth; Project Memory (ProjectStore/Activities/Checkpoints) remains authoritative and the Index must always be reconstructable from it. Long-term retrieval direction: Project -> Memory Index -> relevant Project Memory -> Context Pack -> AI, rather than Project -> entire history -> AI.

ADR-042 - ACCEPTED (Research-Informed Roadmap)
Approved future direction: AI-derived Project knowledge follows a graduated trust progression - Observation/Event -> AI Hypothesis -> Accepted Hypothesis -> Confirmed Finding -> Action Performed -> Outcome - extending the provenance categories already established in ADR-010 and the Provenance Strategy section into an explicit, ordered state progression. User agreement ("Continue") does not equal objective proof and must not be conflated with a Confirmed Finding. A rejected AI hypothesis ("Correct"/"That's wrong") must never become canonical truth, and the correction/reason must be preserved as provenance/context so future reasoning does not blindly repeat the same mistake. This extends, and does not replace, the existing Phase C2 Checkpoint Proposal `pending`/`applied`/`rejected` lifecycle (ADR-022 through ADR-027); exact schema changes remain unspecified pending implementation design.

ADR-043 - ACCEPTED (Research-Informed Roadmap)
Approved future direction: validation/confirmation requirements scale with risk, not uniformly. Low-risk observable events (photo captured, timestamp, Investigation created, user-entered measurement, Project selection, user statement) may generally be recorded automatically without confirmation prompts, to avoid confirmation fatigue. Higher-risk interpretations/state changes (AI diagnosis, changing Project next action, declaring a component defective, marking an issue resolved, consequential recommendations, promoting an inference to confirmed Project knowledge) require stronger validation/evidence before becoming canonical. The model must never be permitted to unilaterally decide that its own conclusion is canonical truth; the application controls that transition. This extends ADR-009/ADR-010/ADR-021.

ADR-044 - ACCEPTED (Research-Informed Roadmap)
Approved future direction: Project continuity belongs to the application, not to any individual AI provider or coding agent (OpenAI, Anthropic/Claude, Codex, GitHub Copilot, Gemini, or future providers/agents). A provider usage limit or session boundary must become a provider-availability problem, not a Project-continuity problem. The application should eventually be able to produce a bounded, provider-agnostic work/handoff Action Artifact (Project goal, current objective, constraints, architecture rules, completed work, current checkpoint, relevant files, current issue, relevant evidence, proven vs. unproven state, acceptance criteria, next required action) sufficient for a different agent/provider to continue without depending on the previous agent's conversation. Different Artifact kinds (e.g., a field Investigation artifact versus a coding/implementation work order) are not assumed to share identical lifecycle semantics merely because they may eventually share a common Artifact abstraction. This generalizes the provider-neutral reasoning boundary already established for Project Q&A by ADR-034 to the broader cross-agent/cross-provider continuity problem.

ADR-045 - ACCEPTED (Research-Informed Roadmap)
Approved future milestone: a Glasses Project Navigator / Hands-Free Project Controller on the Meta Ray-Ban Display, using supported high-level Display/Neural Band navigation and selection to browse/open Projects and drive a Project-scoped evidence -> analyze -> finding/next-action -> trust loop, so glasses interaction feels like a hands-free Project controller rather than passive AI-answer display. Open-ended context remains phone-assisted unless a supported glasses microphone/voice callback is verified. A Project selected/opened through glasses supplies explicit Project context/`project_id` to capture and Investigation, following the same ADR-037/ADR-038 explicit-Project -> Active-Project-fallback -> unscoped precedence; opening/selecting a Project on glasses remains distinct from changing the global Active Project unless explicitly requested. No separate glasses memory is permitted - all clients (glasses, phone, desktop/web) operate over the same application-owned Project Memory, with responsibilities split as: glasses+supported Display interaction = immediate action loop; phone = richer field workspace/control/review/context capture; desktop/web = deep Project workspace. The required Meta SDK capability spike has begun; its current bounded status and verified DAT 0.8 limits are recorded by ADR-055. Do not architect around raw Neural Band/EMG, arbitrary programmable haptics, physical camera-button events, or other APIs until public support is proven. Builds on existing capability research in `research/display_capabilities.md`, `research/meta_glasses_capabilities.md`, and `research_agent/display_sdk_integration_findings.md`.

ADR-046 - ACCEPTED
The Project Workspace is the human-facing interface over application-owned Project Memory - not a project-management tool. Its purpose is to let a human (and an AI) always know where a Project stands and what matters next, answering "where are we / what's done / what changed / what's next / what's blocking us" before the user has to ask an AI. Approved minimal universal layout: Project Identity (name, short objective, honestly-computed progress/health only where it can be computed, never fabricated), Where We Are (current state/milestone), Now (current work), Next (immediate next action), Blockers (unresolved), Roadmap (completed/current/upcoming/deferred), Recent Important Changes (meaningful state changes only, distinct from raw History), and drill-down areas for Evidence, Decisions, Findings, History, Ideas, and Open Questions. The Workspace Home summarizes these areas; it does not enumerate every record inline. Explicitly out of scope for this product: Gantt charts, resource management, invoicing, dispatch, CRM, inventory, story points, large workflow builders, and dozens of configurable statuses - the product's job is maintaining Project context and state, not running a business.

ADR-047 - ACCEPTED
The Roadmap is represented as structured Project state answerable deterministically (current milestone, current work, next action, completed items, upcoming items, deferred items) rather than as an AI-generated paragraph regenerated on demand. The existing Project/Checkpoint/Activity/Proposal structures are the correct foundation for this - `ProjectActivityType` already includes `MILESTONE`, `ACTION`, `DECISION`, and `BLOCKER`, and Checkpoint already carries `current_objective`/`current_work`/`next_action`/`blockers`. A new canonical Roadmap database/store is NOT approved by this ADR; the smallest correct representation is additive tagging on existing Activities (e.g. a roadmap-status distinction across completed/current/upcoming/deferred) plus the existing Checkpoint fields for current state, reusing the existing flexible `metadata` field on `ProjectActivity` before introducing new schema. AI may propose Roadmap changes (as it already may propose Checkpoint changes via the Phase C2 Proposal mechanism); AI must never silently rewrite the Roadmap - a Proposal requires explicit human validation before it affects canonical Roadmap/Checkpoint state, exactly as ADR-009/017/021/022 already require for Checkpoint changes generally.

ADR-048 - ACCEPTED
Ideas are captured and stored separately from the Roadmap until a user explicitly promotes an Idea onto the Roadmap. When work or conversation surfaces a genuinely new, unrelated possibility (e.g. discovering "multi-agent orchestration" while building "Project Update Proposal"), the correct default behavior is to record it as an Idea / Future Research item and leave the current task/Roadmap unchanged - never to automatically replace or reorder current work. Promotion (Idea -> Roadmap) is an explicit user action. This is a roadmap-continuity guardrail, not a scheduling feature: its purpose is preventing Project drift/rabbit-holing, not managing a backlog.

ADR-049 - ACCEPTED
The user-facing terminology for the AI-hypothesis human-review loop is CONTINUE / DISAGREE / MORE EVIDENCE. This refines ADR-042's provisional "Correct" wording to the approved user-facing term DISAGREE, chosen specifically because it does not require the user to already know the right answer. Exact semantics: CONTINUE means "this seems reasonable enough to work from" and explicitly does NOT mean "objectively proven" - the Project's Now/Next may update accordingly, but the underlying claim must not be promoted to a Confirmed Finding merely because the user continued. DISAGREE means "I don't think the AI got this right"; the system should ask the equivalent of "what do you think the AI got wrong," accept a free-form correction (which may itself be uncertain), preserve that challenge/correction as provenance without requiring the user to supply the correct answer, never promote the original AI conclusion to canonical truth, and allow the AI to reassess using the original evidence plus the user's feedback and present an updated proposal. MORE EVIDENCE means "we don't know enough yet" - the Investigation/finding remains explicitly unresolved while additional evidence (photo, measurement, spoken explanation, test, observation) is gathered, after which reassessment occurs; this is a genuine third state, not a deferred yes/no. Backend/internal provenance vocabulary (e.g. "rejected hypothesis," `confirmation_status`) remains available in an audit/provenance view but must not be the primary user-facing language, consistent with the existing Presentation Addendum 2 precedent (`pending`/`applied`/`rejected` -> "Suggested"/"Confirm & Add"/"Dismiss").

ADR-050 - ACCEPTED
Evidence must relate to the specific Finding, Activity, Decision, or Investigation it supports rather than existing as an undifferentiated per-Project gallery. A Finding should be traceable to the Evidence that supports it, the Investigation (if any) it came from, and its Outcome once known. This extends the provenance principle already established by ADR-010/ADR-029 (Investigation evidence is already scoped to a session and referenced by resulting Activities); it does not require a new evidence-relationship schema beyond what Investigation session/evidence ownership and Activity `metadata`/source references already provide, unless implementation proves otherwise.

ADR-051 - ACCEPTED
Recent Important Changes is a distinct, filtered view over Project state - meaningful changes only (Roadmap changed, current milestone/current-work changed, blocker added or resolved, a Decision approved, a Confirmed Finding added, a major Action completed, Project objective changed) - and is explicitly NOT the same as raw History, which may contain everything. Recent Important Changes must be derivable from existing Activities and Checkpoint transitions (e.g. by `activity_type`, checkpoint field diffs, and Proposal-apply events) rather than requiring a new canonical data store; this is a read-side filtering/presentation concern, consistent with ADR-030's bounded-context principle applied to the human-facing Workspace rather than only to AI-facing Context Packs.

ADR-052 - ACCEPTED (Research-Informed Roadmap)
A Project represents a persistent user objective, not only a troubleshooting or repair case. Repair, restoration, design, building, planning, research, comparison, software development, learning, and travel are all valid Project domains over the same universal kernel. Investigation remains one bounded Project Interaction type; it must not become the container for every kind of Project work. Approved conceptual flow: Project -> Project Interaction -> Context Retrieval -> AI plus tools/media retrieval -> Structured Result or Artifact -> User Decision -> Project Memory. Candidate interaction families include INVESTIGATE, EXPLORE, RESEARCH, COMPARE, GUIDE, PLAN, EXPLAIN, and LOOK/ANALYZE EVIDENCE. This decision approves the abstraction and direction, not implementation of every interaction family or a generalized workflow engine.

ADR-053 - ACCEPTED (Research-Informed Roadmap)
The Meta Ray-Ban Display is an approved first-class projection and controller for the same application-owned Project Workspace, not a separate memory owner and not "ChatGPT running on glasses." The application owns Project identity, state, checkpoints, history, evidence, decisions, current step, next actions, references, and approved memory updates. Glasses and phone render and act on that canonical state at different levels of detail. The first glasses-native closed loop is: Select Project -> Where We Left Off -> Capture Evidence -> Add Context -> Analyze -> AI suggestion plus Next Action -> user trust action -> proposed Project change -> validated Project Memory update -> refreshed HUD state. It must preserve explicit `project_id`, Active Project semantics, provenance, and the separation between inference, user assessment, Proposal, and canonical update.

ADR-054 - ACCEPTED (Research-Informed Roadmap)
Project guidance should use application-level structured, renderable result families rather than treating every model response as an arbitrary text blob. Approved candidate families are INSTRUCTION, REFERENCE, ANNOTATED EVIDENCE, DECISION, PROJECT UPDATE, and QUESTION/INFORMATION REQUEST. The same semantic result may be projected differently on glasses, phone, and desktop. Project-scoped instructional media retrieval is approved roadmap direction: written instructions, images, diagrams, annotated user images, source references, instructional video, and appropriate product/reference results should be retrieved using relevant bounded Project context through provider/source-neutral boundaries. No specific media provider, YouTube integration, provider abstraction, or playback implementation is approved by this decision.

ADR-055 - ACCEPTED (Research-Informed Roadmap)
Current Meta DAT 0.8 capability claims must remain evidence-bounded. Verified public Display primitives include text, high-level buttons/onClick, clickable rows, lists, scrolling content, dynamic screen replacement, images, video, and supported Android callbacks; these make Project selection, Now/Next views, and Display-triggered Android actions feasible subjects for incremental prototypes. The public API has not been found to expose physical camera-button events, raw Neural Band/EMG, raw touchpad events, custom Hey Meta callbacks, glasses microphone/audio streaming, or application-controlled Band/glasses haptics. Open-ended spoken context therefore remains phone-assisted until a supported API is verified. The initial 2026-08-23 DAT 0.8 Display capability-handoff run was `MORE EVIDENCE REQUIRED` because a three-slot Investigation cap prevented completion of the five-capture test. After ADR-056 raised the ceiling to five and corrected HUD success semantics, the bounded physical retest conclusively classified the current DAT 0.8 handoff path as `NOT PRODUCT-READY AS THE RELIABLE CAPTURE FOUNDATION`: seven accepted Display/Band callbacks produced seven capture requests, four successful `PhotoData` results/four accepted ordered evidence items, and three approximately ten-second `Stream.capturePhoto()` failures. Display restored after all seven attempts and explicit Project attribution remained stable, so the interaction path is proven while its current capture reliability is blocked in DAT 0.8. This blocks productizing Band-triggered glasses capture on DAT 0.8 only; it does not block generalized Project Interactions, phone/desktop guidance, Project-scoped retrieval/media work, read-only glasses Now/Next projections, or supported non-camera Display actions. Immediate local captured-photo HUD preview is also blocked because DAT 0.8's public Display image API requires a supported HTTPS media source. This conclusion does not authorize retries, internal APIs, reflection, gallery polling, accessibility/Bluetooth interception, or other unsupported workarounds. A controlled newer-DAT investigation is justified only as a separate approved experiment.

ADR-056 - ACCEPTED
Investigation image evidence has a dynamic capacity of at most five accepted images. Five is a ceiling, never a completion requirement: each Analyze path preserves its existing minimum (one image for session orchestration; two images for the direct retained Analyze contract), and both accept every count through five above that minimum. The sixth distinct image must be explicitly rejected without changing retained evidence, sequence order, or Project attribution. Accepted evidence remains session- and Project-scoped, is ordered deterministically, and is supplied to one Analyze request as one ordered evidence set. This contract replaces the former maximum-three backend constraint without changing canonical Project Memory ownership or Active Project semantics.

ADR-057 - ACCEPTED (Project Interaction Foundation)
Project Interaction is a lightweight application-level orchestration and correlation boundary, not a new universal persisted aggregate, session store, result store, or workflow engine. The initial foundation requires explicit `project_id`, a server-owned `interaction_id`, deterministic Context Pack retrieval, provider-neutral structured validation, and idempotent projection into existing family-appropriate owners. Investigation retains its specialized session/evidence/result/trust lifecycle. The first non-Investigation proof is a backend-first Room Redesign `EXPLORE` interaction using only `OPTION_SET` and `INFORMATION_REQUEST`: validated options project as ordered AI/inferred Idea Activities, user dispositions are linked append-only Decisions, and canonical direction changes only through existing Checkpoint Proposal Apply. This decision authorizes the documented foundation and proposed milestone sequencing, not implementation. `docs/PROJECT_INTERACTION_FOUNDATION.md` is the focused authoritative design.

ADR-058 - ACCEPTED (Retry-safe Record Project Progress)
User-authored Project progress is recorded as exactly one append-only `USER` / `REPORTED` Project Activity under explicit `project_id`. A progress note never directly changes the canonical checkpoint. The user may optionally suggest changes only to `current_work`, `blockers`, and `next_action`; effective changes create one separate pending Checkpoint Proposal linked to the Activity, and Apply/Reject remains explicit. Preview is read-only and performs zero provider calls. Save is Project-scoped and idempotent: deterministic Activity/Proposal identities allow equivalent retries, concurrent requests, response loss, and restart reconstruction to converge, while conflicting key reuse is rejected. This reuses Project, Activity, and Checkpoint Proposal stores; it does not create a Progress store, generic Interaction store, automatic Apply path, or AI progress scoring.

ADR-059 - ACCEPTED (Rich Project Intelligence V1 - Response Planner and typed task-aware results)
The existing evidence+context -> hypothesis -> recommended-next-action Investigation result contract is correct for diagnosis but produces low-value output for design/planning/creative Project tasks (e.g. Room Redesign producing generic "declutter surfaces" guidance instead of reasoned alternatives). This ADR approves, as architecture direction only, a Response Planner - the named realization of the future "Project Guidance Engine" boundary `docs/PROJECT_INTERACTION_FOUNDATION.md` already describes - that selects, from explicit user intent and Project context, exactly one of three V1 response families: `TROUBLESHOOT` (the existing Investigation/`INVESTIGATE` lifecycle, unchanged), `EXPLORE_PLAN` (evolves the existing `EXPLORE`/`OPTION_SET` foundation under ADR-057 with a richer typed payload - observations, multiple options each with rationale/tradeoffs/proposed changes, a recommended option and reason, next steps, and follow-up questions), and `GENERAL_GUIDANCE` (a new minimal safe-fallback family for Project questions that do not justify the other two). No larger taxonomy is approved yet. The Planner selects only from these application-approved contracts and must not itself execute mutations. Results share one conceptual envelope, `ProjectAIResult` (`result_id`, `project_id`, `result_type`, `summary`, `hud_projection`, `evidence_refs`, `suggested_project_updates`, typed payload), rather than one large mostly-nullable schema. Selecting a rich option must not silently become canonical truth: AI proposal -> user selection/trust -> the existing Idea/Decision/Checkpoint Proposal mechanism -> validated canonical state, exactly as ADR-057/`PROJECT_INTERACTION_FOUNDATION.md` already require; the LLM does not mutate canonical Project state under this ADR either. The required proof before generalizing is a Room Redesign `EXPLORE_PLAN` vertical slice using the existing Room Redesign Architecture Test already scoped in `PROJECT_INTERACTION_FOUNDATION.md`, cross-checked against AC Repair still receiving a `TROUBLESHOOT`-shaped response from the same Planner. Rich Project Intelligence additionally requires an evaluation set (roughly 20-40 representative scenarios spanning troubleshooting, design/planning, and general guidance) assessing response-family selection correctness, grounding, usefulness, hallucination, option differentiation, next-step quality, Project isolation, structured-output validation, and latency/token/cost; passing unit tests alone does not prove AI quality. Exact per-family payload schemas, the Planner's internal selection mechanism, and intent/router persistence are explicitly NOT locked by this ADR and require a focused design milestone; intent/router persistence is not required unless later evidence proves a need. This ADR does not authorize implementation, does not introduce a universal chat transcript as memory, does not add a vector/graph store without demonstrated need, does not expand the response family list beyond these three for V1, and does not make on-demand rich media/visualization ("Visualize this option") automatic - that remains a separately gated later slice.

NOTE (2026-09-04): this entry's dispatch mechanism - "from explicit user intent" meaning the client explicitly names which of the three families to call - is amended, not reversed in full, by ADR-060 immediately below. ADR-060 does not change the three approved response families, the `ProjectAIResult` envelope, the trust boundary, or any other clause of this ADR; it changes only how a family is selected. This note is additive; ADR-059's original text above is preserved unchanged.

ADR-060 - ACCEPTED (Bounded Response Planner Intent Inference - amends ADR-059's dispatch mechanism)
Physical Room Redesign acceptance testing (2026-09-03/04) demonstrated that ADR-059's explicit-dispatch rule was wrong in practice: requiring the user to pick among `TROUBLESHOOT`, `EXPLORE_PLAN`, and `GENERAL_GUIDANCE` themselves - implemented as a visible "Or explore design/planning ideas instead" alternative next to Investigation's Analyze action, plus a separate always-visible "DESIGN & PLANNING GUIDANCE" composer further down the screen - forced the user to understand internal response-family architecture, and the natural glasses Capture/Use -> Continue on phone -> type context -> Analyze workflow never reached Rich Project Intelligence; it only ever reached the diagnostic `TROUBLESHOOT` path. This ADR amends ADR-059's dispatch mechanism only. Response-family selection becomes application-owned bounded intelligent routing: from explicit `project_id`, a narrow deterministic Context Pack (Project identity/goal, current checkpoint, recent relevant Activities/Investigations/Explore interactions, current evidence presence, and the current user request text - never full Project history and never a chat-transcript store), a Response Planner infers exactly one of the same three ADR-059 families and returns typed routing metadata only (`response_family`, `confidence`, `brief_reason`, `needs_clarification`) - it never mutates or persists canonical Project state, and this routing decision is never itself a `ProjectAIResult` or Project Memory record. A Project is never permanently typed to one family: the same Project can receive different families for different requests over time, grounded by Project context but not locked by it. The user takes one natural action, labeled neutrally ("Get guidance", replacing "Analyze investigation" as the primary label everywhere this action appears) rather than choosing a family; the Planner's existence is invisible unless it needs one concise clarifying question. A technical planner failure (provider error, timeout, invalid structured output) is a retryable routing failure and must never be silently converted to `GENERAL_GUIDANCE`; `GENERAL_GUIDANCE` is selected only when the Planner positively determines it is the appropriate family, or the Planner asks one concise clarifying question first when genuinely uncertain. The exact confidence policy governing proceed / ask-one-clarifying-question / choose-`GENERAL_GUIDANCE` is deliberately not fixed by this ADR and must be established from the routing evaluation set (extending ADR-059's existing 20-40 scenario requirement to additionally score family-selection accuracy), not an arbitrary constant. `TROUBLESHOOT` selected without an existing Investigation session is backend planner/orchestration-owned session creation/reuse; Android must not invent this lifecycle. Glasses/HUD-initiated Analyze remains `TROUBLESHOOT`-only for V1 because no open-ended glasses intent composer exists yet; intelligent routing applies only to the phone's single unified guidance entry point. This ADR does not authorize implementation - it approves the corrected architecture direction and the following bounded sequencing: (1) this ADR and its documentation updates; (2) backend planner/router contract; (3) routing evaluation and confidence policy; (4) Android unified "Get guidance" flow; (5) automated and instrumented QA; (6) one realistic physical Room Redesign acceptance retest; (7) checkpoint only after that acceptance. It does not expand the response family list beyond the three ADR-059 already approved, does not add a universal chat-transcript store, does not let the Planner mutate Project state, and does not change any other ADR-059 clause (the three response families, `ProjectAIResult` envelope, and trust boundary remain exactly as ADR-059 defines them).

ADR-061 - ACCEPTED (Persistent Provider-Neutral Project Conversation - supersedes only conflicting conversation restrictions in ADR-057/ADR-059/ADR-060)
The product's primary interaction model is one persistent primary conversation per Project for V1. Core product statement: **“A persistent, provider-neutral AI workspace where the conversation follows the Project—including its photos, evidence, decisions, generated artifacts, and state—across phone, desktop, and glasses.”** Governing principle: **“The model provider provides intelligence. The application provides continuity.”** The application owns `ProjectConversation` and ordered `ConversationTurn` persistence under explicit `project_id`; OpenAI, Claude, Gemini, and future providers are replaceable adapters and their native message, thread, content-block, tool-call, or conversation formats must never become canonical persistence. This supersedes only ADR-057/`PROJECT_INTERACTION_FOUNDATION.md`'s rejection of a conversation log/persisted conversation aggregate and ADR-059/ADR-060's statements that no chat-transcript store is introduced. It does not make conversation authoritative Project Memory, does not authorize full-history replay, and does not reverse their Project isolation, bounded retrieval, provider neutrality, typed validation, or trust requirements.

The locked target boundary is `Project -> ProjectConversation -> ConversationTurn -> Assistant Orchestrator -> bounded application capabilities/tools -> Provider Adapter -> OpenAI / Claude / Gemini / future providers`. `Project` remains the ownership boundary and Project Memory remains canonical truth. A conversation records what the user and assistant communicated; it references, rather than duplicates, authoritative Evidence, Activities, Investigations/results, VisualArtifacts, Checkpoint Proposals, Decisions, and other Project resources. Each `ConversationTurn` uses a versioned provider-neutral semantic content-part union (initially text and typed Project-resource references; later bounded structured cards/actions) plus Project-scoped typed references carrying resource kind, resource ID, and relationship such as attached, consulted, produced, cited, proposed, selected, or visualized. Evidence bytes, provider-native payloads, arbitrary nested domain records, raw prompts, and unrestricted provider history are not turn content.

The Assistant Orchestrator is application-owned. It validates Project/conversation ownership and turn idempotency, assembles selective bounded context through the Project Context Retriever, resolves only authorized same-Project resource references, negotiates configured provider capabilities, validates provider-neutral responses and capability requests, invokes only registered bounded application capabilities, records provenance, and persists the assistant turn. Provider tool requests are requests to this orchestrator, never authority to mutate canonical Project state. Important/canonical Project changes still require the existing explicit Proposal -> Apply or applicable trust boundary. Expensive generation, including image visualization, requires an explicit user action and may not be autonomously invoked. The orchestration loop must use explicit round/call/tool limits and must not blindly replay the complete conversation or Project.

Existing response-family work remains valuable but changes architectural position: `EXPLORE_PLAN` becomes an internal Explore capability; evidence-backed `TROUBLESHOOT` uses Investigation as a specialized evidence/diagnostic capability while text-only troubleshooting becomes ordinary assistant reasoning; `GENERAL_GUIDANCE` becomes ordinary conversational answering; `ProjectAIResult` and the ADR-060 Response Planner remain compatibility components during strangler migration rather than the permanent primary conversation contract. Investigation retains its evidence ordering, validation, frozen manifests, analysis attempts, retained results, trust, and follow-up guarantees, but is no longer the dominant user workflow. VisualArtifact, Activities, Checkpoints, Evidence, Knowledge/Orientation, Context Retrieval, provenance, isolation, idempotency, and Proposal -> Apply remain authoritative reusable foundations. Phone, desktop, and glasses are projections/controllers over the same ProjectConversation; no device may create a separate canonical conversation.

Migration is locked as a strangler migration, not a rewrite: **Phase 0 — Architecture authority. Phase 1A — Text conversation spine:** ProjectConversation/ConversationTurn persistence; send/read/reload; bounded Project context; provider-neutral assistant request/response boundary; OpenAI as the first adapter; persistent follow-up continuity; Project isolation and idempotency; no Android production migration. **Phase 1B — Multimodal conversation:** Evidence attachment/reference, actual image delivery to the provider, grounded response, persistence and reconstruction. **Phase 2 — Android conversation-first UI. Phase 3 — existing Explore, Investigation, and Proposal capabilities become conversational capabilities/cards. Phase 4 — VisualArtifact conversational integration. Phase 5 — desktop and glasses shared conversation projection. Phase 6 — retire old primary workflow UX only after conversational parity is proven.** Existing endpoints and clients remain runnable until their replacement path passes its acceptance gate.

Phase 1A acceptance gate: one explicit Project creates or reconstructs exactly one primary conversation; an idempotent send persists one ordered user text turn and one ordered assistant text turn; a follow-up after process restart is answered using bounded relevant Project context and bounded relevant prior turns without provider-native history; read/reload reconstructs stable ordering and semantic content; same-key retry and concurrent equivalent requests converge without duplicate turns or duplicate provider calls, while conflicting key reuse is rejected; Project B cannot read, append to, reference, or receive context from Project A's conversation; opening/sending does not change Active Project; the canonical store contains no provider-native message/thread/tool format, raw prompt, secret, or unrestricted transcript replay package; provider failure leaves an honest recoverable turn state; the OpenAI adapter is replaceable behind the canonical request/response boundary; existing Project Memory, Investigation, Explore, Proposal, VisualArtifact, and current clients/regressions remain unchanged. Phase 1A does not include Android production migration, image input, autonomous capability execution, or retirement of existing guidance UX.

ADR-062 - ACCEPTED (Conversational Project Progression, Slice 1 - reuses and reframes ADR-042/ADR-043/ADR-049, does not replace them)
The originally-planned Phase 3 "Proposal becomes a conversational capability/card" milestone is superseded by a different interaction model: ProjectConversation must progress naturally from grounded user-reported outcomes without a repeated, visible Apply/Reject Proposal ritual on the common path. This does not introduce a competing canonical-mutation system - `CheckpointProposal` remains the sole, unchanged internal trusted mutation primitive (ADR-022 through ADR-027), and this is not a new `AssistantCapabilityIntent` (ADR-061's closed capability enum is unchanged). A conversational turn may report progress as an orthogonal signal alongside (or instead of) a primary capability, resolved by native tool-calling in the SAME single provider call already used for capability routing - never a second model/classification call. The orchestrator, never the model, deterministically resolves which specific outstanding claim a turn's report applies to from its own conversation-owned state; the model only classifies the current message as confirming or correcting that specific, already-resolved target, and cannot fire this signal at all when no eligible target exists. Slice 1 scopes the eligible-target resolution to Investigation-originated outstanding claims only - the most recently `INVESTIGATION_REFERENCE`-d session in the conversation whose trust state (ADR-042/ADR-049's CONTINUE/DISAGREE/MORE EVIDENCE loop) is not yet settled beyond a single prior CONTINUE. A confirmed outcome is submitted through the existing `ProjectInvestigationTrustService.decide()` exactly as the legacy CONTINUE/DISAGREE UI already calls it - no second Activity/Proposal-creation implementation - and, only when the resulting patch is low-consequence (ADR-043's risk-scaled validation, realized for this slice as a narrow, explicitly-documented field allowlist covering narrative/working-state Checkpoint fields only, not a permanent redefinition of "low risk"), the resulting `CheckpointProposal` is applied through the existing, unchanged apply mechanism within the same request. A significant-change patch (not producible by any Slice 1 target today) remains PENDING exactly as it does today. A corrected outcome never advances the rejected claim; any PENDING proposal tied to the prior decision is rejected through the existing reject mechanism, and an already-applied prior proposal has no revert - correction is forward-only, matching ADR-049's principle that a disagreement must never retroactively rewrite history. This ADR authorizes Slice 1 exactly as implemented (Investigation-originated targets only) and explicitly reserves, without authorizing, later extension to ordinary-conversation-originated claims, Explore/VisualArtifact-originated claims, and the ADR-044 Action Artifact/cross-agent handoff outcome-reporting case - none of those are implemented by this ADR. It does not authorize Workstreams/scopes, but target resolution is deliberately anchored to a specific prior Activity/reference rather than "the Project as a whole," so it does not need to be redesigned when Workstreams are later introduced.

## Approved Roadmap - Research-Informed Extensions

Status: APPROVED ROADMAP. These entries mix implemented foundations with explicitly future extensions; each subsection labels its current state. They extend existing architecture and must not be read as competing/replacement definitions of it. Each item is backed by an ADR above (ADR-040 through ADR-061); this section is a readable index, not additional authority beyond those ADRs.

### Interpretable, bounded context (ICM-informed) - ADR-040, ADR-041

- Interpretable Context Packs: Phase E3 already emits interpretability metadata (question class, retrieval contract, required/optional/excluded categories, per-category inclusion/exclusion reasons, limits, fallback reason) for the question-aware query path. Approved extension: deepen and generalize this observability - across more question classes and the non-query Context Pack path - so a poor AI answer can always be diagnosed as either (a) retrieval selected bad/incomplete context or (b) the model reasoned incorrectly from good context.
- Retrieval inclusion/exclusion contracts: Phase E3's `required`/`optional`/`excluded` categories are the existing implementation of what ICM frames as MUST / MAY / MUST-NOT retrieve. Approved extension: broaden this pattern's coverage (e.g. NEXT_ACTION-style contracts that positively include the latest checkpoint, unresolved tasks, blockers, and recent relevant evidence while excluding completed historical tasks, unrelated investigations, and superseded recommendations) to reduce context contamination and token usage. Prefer extending the existing contract mechanism over introducing new terminology.
- Project Memory Index: a new, not-yet-implemented derived/rebuildable/non-canonical compact index (current state, objective, open tasks, blockers, major decisions, key evidence, recent checkpoints, investigations, artifacts, historical topics) sitting between Project Memory and the Context Retriever as Projects grow. See ADR-041 for the non-canonical constraint.
- Bounded context / token efficiency: as Project history grows, AI context size should grow substantially more slowly than that history (extends ADR-030). Approved direction: make this measurable/observable, not just qualitatively true.

### Universal Project Workspace v1 - ADR-046 through ADR-051

- The Workspace is the human-facing interface over application-owned Project Memory - not a project-management tool, and explicitly not Jira/Procore/ServiceTitan (no Gantt charts, resource management, invoicing, dispatch, CRM, inventory, story points, workflow builders, or dozens of configurable statuses). See `docs/research/UNIVERSAL_PROJECT_WORKSPACE_V1_DESIGN.md` for the full gap analysis, sample Workspace Home, and MVP/post-MVP boundary this roadmap entry is based on.
- Approved minimal layout (ADR-046): Project Identity, Where We Are, Now, Next, Blockers, Roadmap (completed/current/upcoming/deferred), Recent Important Changes, and drill-downs for Evidence, Decisions, Findings, History, Ideas, and Open Questions. The Home summarizes; drill-downs detail.
- Roadmap is structured Project state, not AI prose (ADR-047): reuse the existing `ProjectActivityType` values (`MILESTONE`, `ACTION`, `DECISION`, `BLOCKER`) and Checkpoint fields before inventing a new Roadmap store; AI may propose Roadmap changes but must not silently rewrite it, exactly as the existing Checkpoint Proposal mechanism already requires for Checkpoint changes.
- Ideas are separate from the Roadmap until explicitly promoted (ADR-048) - the core anti-drift guardrail: a Project exploring an unrelated idea records it as an Idea, not a silent change to current work.
- CONTINUE / DISAGREE / MORE EVIDENCE is the approved user-facing terminology for the AI-hypothesis review loop (ADR-049), refining ADR-042's provisional "Correct" wording. DISAGREE never requires the user to know the right answer.
- Evidence relates to the Finding/Activity/Decision/Investigation it supports (ADR-050), not a flat per-Project gallery.

- Recent Important Changes is a filtered, meaningful-only view distinct from raw History (ADR-051), derived from existing Activities/Checkpoint transitions rather than a new store.
- Universal kernel, not domain templates: a single set of core concepts (Objective, Current State, Roadmap, Next Action, History, Evidence, Decisions, Findings, Open Questions, Blockers, Outcomes, Ideas) is the approved MVP scope across Project types (software, field repair, construction, IT incident, etc.). Domain-specific specialization (e.g. HVAC asset/complaint/measurement fields, construction punch lists) is explicitly deferred post-MVP and does not require a new ADR to remain deferred.
- "Who has the ball" (representing who/what owns the next action - user, a specific AI agent, an external party) remains a research/roadmap idea, not approved for MVP scope, unless a future slice's implementation shows it falls out nearly for free from existing structures.
- Automatic Project Drift detection (recognizing conversation has branched from the current objective/milestone/task and proactively offering to capture it as an Idea) remains a future idea, not MVP. The one MVP-relevant behavior this protects - Ideas being separate from the Roadmap until promoted (ADR-048) - is already in scope without needing automatic detection.

### Universal Project Workspace MVP Milestone 1 - Implemented (Project Orientation / Roadmap Backend Contract)

Implemented:

- Read-only, project-scoped `GET /projects/{project_id}/orientation` endpoint.
- Deterministic orientation assembled entirely from application-owned Project and Activity state; no OpenAI/model/provider call occurs.
- Project identity fields: `project_id`, `name`, `status`, and `objective` (`Project.goal`).
- Checkpoint precedence is explicit and non-merging: `current_objective` supplies `where_we_are`, `current_work` supplies `now`, `next_action` supplies `next`, and `blockers` supplies `blockers`. Roadmap Activities do not override or synthesize these fields.
- Roadmap convention: an existing `ProjectActivity` is included only when `metadata.roadmap_status` is exactly one of `completed`, `current`, `upcoming`, or `deferred`. Untagged Activities and unknown values are excluded.
- Each Roadmap group returns full existing Activity records in the Activity store's deterministic order: `occurred_at_utc`, then `created_at_utc`, then `activity_id`.
- Empty Roadmap state returns all four groups as empty lists; absent Checkpoint values return `null`.
- The read does not mutate Project revision/timestamps/checkpoint, Activities, proposals, or the Active Project pointer.

No new persistence abstraction or Roadmap write endpoint was added. Existing Activity append and Checkpoint Proposal validation remain the available write foundations; consequential state evolution must continue through the approved validation rules.

Not implemented by Milestone 1: Milestones 2-5 (Trusted AI Loop, Project Knowledge, Ideas / Plan Control, and MVP Demo Hardening), including `IDEA`, any Roadmap editing/reordering API, and all Android/UI work.

### Universal Project Workspace MVP Milestone 2 - Implemented (Trusted AI Loop Backend Contract)

Implemented:

- Project-scoped trust decision write: `POST /projects/{project_id}/investigation-sessions/{session_id}/trust-decision` with exactly `continue`, `disagree`, or `more_evidence` and optional `correction`.
- Deterministic zero-AI read: `GET /projects/{project_id}/investigation-sessions/{session_id}/trust`.
- Each decision is a new append-only user `ACTION` Activity with `reported` confirmation status. Metadata records `trust_decision`, `trust_session_id`, `trust_result_id`, and `source_activity_id`; the original AI `RESULT` Activity and canonical retained result remain unchanged and `inferred`.
- CONTINUE records a working hypothesis and creates a pending Checkpoint Proposal for the AI-recommended next action, sourced from both the AI result Activity and user decision Activity. It does not apply the Proposal, confirm the hypothesis, or complete Roadmap work.
- DISAGREE records the optional user correction in the decision Activity, reports `needs_reassessment`, preserves the original AI result, and performs no reassessment/model call.
- MORE EVIDENCE reports `unresolved` and creates a new project-owned follow-up Investigation session whose client metadata links to the original session/result. The original completed Investigation/result remains immutable while the follow-up can collect additional evidence.
- The trust read reports the immutable hypothesis/recommendation, latest user decision/correction, decision Activity/timestamp, current Proposal id/status where applicable, and follow-up Investigation id where applicable. Activity ordering determines the latest decision deterministically.
- Project ownership is enforced through the existing project-scoped Investigation loader. Reads do not mutate Project, checkpoint, Activities, proposals, Investigation state, or Active Project.

No TrustStore, confirmed-finding mutation, direct checkpoint mutation, Roadmap completion, AI reassessment, Android/UI work, or Orientation redesign was added. Applied Continue proposals naturally flow into Milestone 1 Orientation through the canonical checkpoint `next_action`.

### Conversational Project Progression - Slice 1 - Implemented (ADR-062)

Implemented, automated-test-validated (backend, 820/820 full suite green), not yet physically validated:

- `AssistantRequest`/`AssistantResponse` gain an orthogonal `investigation_progress_eligible`/`reported_progress` signal, independent of `AssistantCapabilityIntent` - not a fifth intent. The `report_investigation_progress` tool is offered in the SAME single provider call as the existing capability tools, only when `AssistantOrchestrator._find_eligible_investigation_target` has already deterministically found a real, unsettled, Investigation-originated outstanding claim in the current conversation; the model only classifies `confirmed`/`corrected`, never identifies which claim.
- A `confirmed` outcome calls the existing `ProjectInvestigationTrustService.decide()` with `CONTINUE`; a `corrected` outcome calls it with `DISAGREE` - the exact same Activity/provenance/idempotency behavior Milestone 2's legacy CONTINUE/DISAGREE endpoint already produces, reused verbatim, not reimplemented.
- Slice 1 implementation policy (not a permanent product definition - see ADR-062): a resulting `CheckpointProposal` auto-applies through the existing, unchanged `CheckpointProposalStore.apply_proposal` in the same request only when its patch touches exclusively `current_work`/`next_action`/`discoveries_summary`. Every real proposal this slice can produce is next_action-only and therefore always eligible; a hypothetical significant-change patch would stay `PENDING` exactly as today, unproven by any reachable Slice 1 scenario, and is instead covered by a focused unit test of the gate function itself.
- A `corrected` outcome never advances the checkpoint; a `PENDING` proposal tied to the prior decision is rejected through the existing `reject_proposal`; an already-applied prior proposal is left as durable history (forward correction only, no revert/undo system was added).
- Target resolution is retry-safe (reuses `decide()`'s own idempotency, plus the conversation's own top-level idempotent-turn reconstruction - no second Activity/Proposal is ever created by a same-key retry) and Project-scoped throughout (a cross-Project or otherwise unresolvable session reference is treated as "no eligible target," never a silent cross-Project effect).

Not implemented by Slice 1: ordinary-conversation-originated or Explore/VisualArtifact-originated progression targets, the ADR-044 Action Artifact/cross-agent outcome-reporting case, Workstreams/scopes, a natural-language confirming question for the (currently unreachable) significant-change path, any revert/unapply system, and any Android/UI change - the assistant's own conversational reply is the only user-visible surface, with no new Proposal-mode UI in `ProjectConversationScreen`.

Implemented MVP milestones: 1-2. Not implemented: Milestones 3-5 (Project Knowledge, Ideas / Plan Control, MVP Demo Hardening).

### Universal Project Workspace MVP Milestone 3 - Implemented (Project Knowledge Backend Contract)

Implemented:

- Single read-only, project-scoped, zero-AI endpoint: `GET /projects/{project_id}/knowledge`.
- Evidence is the union of project-owned Investigation evidence and `OBSERVATION` Activities. Investigation evidence retains its evidence/session identifiers, source, validation state, storage reference, timestamp, and related Activity ids where the existing session metadata establishes that relationship. Observation Activities retain Activity provenance. AI result Activities are not reclassified as evidence.
- Decisions are `DECISION` Activities whose source is not AI, or AI Decision Activities explicitly marked `confirmed`, plus applied Checkpoint Proposals. Pending/rejected Proposals and raw AI hypotheses are excluded.
- Findings are only `RESULT` or `OBSERVATION` Activities with `confirmation_status=confirmed`. AI `inferred` results are never Findings merely because a model produced them.
- History is the existing append-only Activity log, newest first; no duplicate event store is introduced.
- Recent Important Changes deterministically includes Activities of type `MILESTONE`, `DECISION`, `BLOCKER`, or `RESULT`; Activities carrying a recognized Roadmap status; Milestone 2 trust decisions; and applied Checkpoint Proposals. Ordinary Notes and unrelated Actions are excluded. Provenance/confirmation fields remain visible, so inclusion does not imply confirmation.
- All sections order newest first, using timestamp and stable record id as the deterministic tie-breaker.
- Explicit bounds: Evidence 50, Decisions 50, Findings 50, History 100, Recent Important Changes 10. Each bound is returned in the response.
- Reads do not mutate Project/checkpoint/revision, Activities, Proposals, Investigations/evidence, or Active Project.

No new knowledge persistence, Evidence media duplication, Decision/Finding CRUD, AI importance scoring, Project Memory Index, Orientation expansion, Android/UI work, or domain-specific schema was added.

Implemented MVP milestones: 1-3. Not implemented: Milestones 4-5 (Ideas / Plan Control and MVP Demo Hardening).

### Universal Project Workspace MVP Milestone 4 - Implemented (Ideas / Plan Control Backend Contract)

Implemented:

- `IDEA` and `OPEN_QUESTION` are explicit `ProjectActivityType` values. Both reuse project-scoped append-only Activity persistence and existing provenance/ordering guarantees; no Ideas store was added.
- Idea routes: `POST /projects/{project_id}/ideas`, bounded deterministic `GET /projects/{project_id}/ideas`, and explicit `POST /projects/{project_id}/ideas/{activity_id}/promote`.
- Idea creation produces a user/reported `IDEA` Activity with `metadata.idea_state=captured`. It does not mutate Project/checkpoint/revision, Roadmap, Findings, Decisions, blockers, current work, or next action.
- Idea listing returns newest first, bounded to 100 Activities, and reports the bound.
- Promotion validates project ownership and Idea type, preserves the original Idea unchanged, and creates a new user/reported `MILESTONE` Activity with `roadmap_status=upcoming` and `promoted_from_activity_id=<idea activity id>`. It does not apply a Checkpoint Proposal or change current/next work.
- Duplicate promotion is sequentially idempotent: if a Roadmap Activity already references the Idea via `promoted_from_activity_id`, the route returns the existing Activity with `created=false` rather than creating duplicate Roadmap work.
- The promoted Activity naturally appears in Milestone 1 Orientation through the existing Roadmap metadata convention. Unpromoted Ideas/Open Questions appear in Milestone 3 History only; promotion is visible in Recent Important Changes because the new record is a `MILESTONE`. Neither Ideas nor Open Questions are classified as Evidence, Decisions, or Findings.
- Open Questions use the existing generic Activity create/list APIs; no redundant Open Question CRUD surface was introduced.
- All Idea operations are deterministic, project-scoped, append-only, and zero-AI.

No AI-generated Ideas, automatic promotion/prioritization, Roadmap reorder, UI/Android/glasses work, drift detection, Project Memory Index, or generalized workflow engine was added.

Implemented MVP milestones: 1-4. Not implemented: Milestone 5 (MVP Demo Hardening).

### Universal Project Workspace MVP Milestone 5 - Implemented (MVP Demo Hardening / Feature Freeze)

Implemented:

- Standalone desktop demo at `GET /mvp-demo`. It intentionally leaves the existing dashboard and phone-navigation work untouched while exposing the locked MVP backend contracts in one usable surface.
- The deterministic AC Repair bootstrap creates Project identity, checkpoint orientation, and completed/current/upcoming/deferred Roadmap Activities using only existing Project APIs.
- The demo supports project-scoped evidence capture and the existing offline `dry_run` Investigation path, shows the retained inferred AI result, and exposes CONTINUE / DISAGREE / MORE EVIDENCE. CONTINUE still requires the user to apply its pending Checkpoint Proposal before the recommendation becomes canonical Project state.
- Project Knowledge renders Recent Important Changes, Evidence, Decisions, confirmed Findings, and History without reclassifying inferred AI output as confirmed knowledge.
- Ideas remain outside the Roadmap until the user explicitly promotes one; promotion creates linked upcoming Roadmap work through the Milestone 4 contract.
- `test_mvp_demo_hardening_milestone5.py` is the deterministic end-to-end acceptance harness. It covers the complete AC Repair loop, explicit trust/proposal semantics, knowledge projection, Idea promotion linkage, store reconstruction (process-restart equivalent), Project isolation, and an offline/no-provider guarantee.
- Reload behavior is application-owned: after a page reload, selecting the Project reconstructs the same orientation, Roadmap, knowledge, and ideas from persisted stores rather than conversation or browser state.

Known MVP limitations:

- The page is a focused demonstration surface, not a replacement or redesign of the existing dashboard.
- Offline demo analysis is deterministic fixture behavior for acceptance/demo use; it is not a new diagnosis model or generalized domain engine.
- Confirming a Finding still requires an explicit existing Activity write; a CONTINUE decision accepts a working hypothesis but never self-confirms model output.
- There is no Roadmap drag/reorder, automatic Idea promotion, drift detection, Project Memory Index, generalized workflow engine, domain-specific HVAC schema, cross-agent handoff system, or new Android/glasses workflow in this milestone.
- Android attribution and glasses behavior remain unchanged because neither was a blocker to the backend/desktop MVP demonstration.

MVP FEATURE DEVELOPMENT IS FROZEN. Milestones 1-5 form the locked Universal Project Workspace MVP boundary. Further feature work requires a separately approved post-MVP milestone; maintenance may fix regressions without expanding scope.

### Project Update Proposal / trust model evolution - ADR-042, ADR-043

- Extends the existing Phase C2 Checkpoint Proposal mechanism (`pending`/`applied`/`rejected`, ADR-022 through ADR-027) and the provenance categories already anticipated in ADR-010, into an explicit graduated progression: Observation/Event -> AI Hypothesis -> Accepted Hypothesis -> Confirmed Finding -> Action Performed -> Outcome.
- Human review loop (interaction concept, not yet implemented UI): CONTINUE (plausible enough to keep working from; not proof), CORRECT/"that's wrong" (capture the correction/reason as provenance; a rejected hypothesis must never become canonical), MORE EVIDENCE (gather another image/explanation/measurement/test before accepting or rejecting - never collapse this to a binary yes/no).
- Risk-tiered validation (ADR-043): low-risk observable facts (photo captured, timestamp, Investigation created, user-entered measurement, Project selection, user statement) may be recorded automatically; higher-risk interpretations (AI diagnosis, next-action changes, defect declarations, resolution claims, promoting inference to confirmed knowledge) require stronger validation. The model never self-certifies its own conclusion as canonical.
- Exact schema/state-machine changes are intentionally left unspecified pending implementation design; this section locks the semantics, not a database migration.

### Cross-agent/provider continuity and Action Artifacts - ADR-044

- Generalizes the provider-neutral reasoning boundary ADR-034 already established for Project Q&A: Project continuity belongs to the application, not to OpenAI, Claude, Codex, Copilot, Gemini, or any other provider/agent. A provider usage limit is an availability problem, not a continuity problem.
- Approved future direction: a bounded, provider-agnostic work/handoff Action Artifact (goal, current objective, constraints, architecture rules, completed work, current checkpoint, relevant files, current issue, relevant evidence, proven/unproven state, acceptance criteria, next required action) that lets a different agent/provider continue a Project without the previous agent's conversation history.
- Different Artifact kinds (e.g. a field Investigation artifact vs. a coding/implementation work order) are not assumed to share identical lifecycle semantics merely because they may eventually share a common Artifact abstraction.
- Not approved: implementing this capability now. Consider prioritizing a minimal cross-agent continuation/handoff capability earlier in future roadmap sequencing than a full Artifact system.

### Glasses Project Navigator / Hands-Free Project Controller - ADR-045

- Use the Meta Ray-Ban Display and supported high-level interaction as a Project controller (select Project -> Project-scoped evidence -> phone-assisted context where required -> analyze -> concise finding/next action -> trust/navigation -> continue working), not passive AI-answer display. Status (2026-09-03): the Investigation MVP cross-device loop (glasses Capture/Use -> deterministic Continue-on-phone -> existing phone Investigation panel -> Analyze -> canonical result -> reconnect -> concise HUD trust flow) is now physically proven end to end - see `docs/ROADMAP.md`'s "Physical Validation - 2026-09-03" entry. This validates the loop's interaction path only; it does not mark overall MVP/release complete, and DAT `capturePhoto()` reliability remains the separately tracked known hardening issue under the DAT 0.8 Capture Capability Gate.
- Project selection on glasses follows the same ADR-037/ADR-038 precedence and must not silently change the global Active Project.
- No separate glasses memory: glasses, phone, and desktop/web all operate over the same application-owned Project Memory. Approximate responsibilities: glasses+Neural Band = immediate hands-free action loop; phone = richer field workspace/control/review/capture; desktop/web = deep Project workspace (timeline, history, evidence, files, detailed AI results, Project management, coding/action prompts).
- Capability gate: ADR-055 records that the supported DAT 0.8 capability-handoff path is `NOT PRODUCT-READY AS THE RELIABLE CAPTURE FOUNDATION` after the bounded max-five retest. This gate applies only to productizing Band-triggered camera capture on DAT 0.8; supported Display projections/actions and non-capture product roadmap work remain independently sequenced. Do not architect around arbitrary programmable Neural Band haptics or any other unexposed input until SDK support is proven. See `research/display_capabilities.md`, `research/meta_glasses_capabilities.md`, and `research_agent/display_sdk_integration_findings.md` for historical capability research.

### Goal-oriented Project Interactions and glasses-native workspace - ADR-052 through ADR-055

- Projects are persistent objectives across repair, creative, research, planning, learning, and building domains. Investigation remains one interaction family rather than the product-wide abstraction.
- The glasses are a first-class projection/controller over the same canonical Project Workspace. The first major glasses-native milestone is the complete Project-scoped evidence -> analysis -> trust -> Proposal -> validated update -> refreshed HUD loop in ADR-053.
- Guidance results are structured at the application boundary so one semantic result can be rendered concisely on glasses and richly on phone/desktop. Instructional media retrieval remains provider/source agnostic.
- Glasses foundation sequence: (1) reliable supported Display interaction/capture mechanism, (2) Project identity plus Where We Left Off/Next, (3) glasses-side evidence action, (4) evidence count/status, (5) Analyze, (6) concise structured result, (7) Looks right/Add more info/Not quite, and (8) refreshed Project state. Item (7)'s user-facing wording refines ADR-049's provisional CONTINUE/DISAGREE/MORE EVIDENCE terminology (same underlying trust decisions/persistence, simplified copy - see `docs/ROADMAP.md`'s "Physical Validation - 2026-09-03" entry); item (5) Analyze now has phone as its primary trigger, with HUD-initiated Analyze retained as secondary, not required for the primary path. Only after that foundation: History, Roadmap navigation, References, diagrams/images, annotated evidence, Project-scoped media retrieval, instructional video, and richer navigation. Project-level Apply/Reject may remain on phone initially.
- Phone-assisted reality: until supported glasses microphone/voice-command APIs are verified, glasses handle Project navigation, Now/Next, evidence actions, Analyze, concise guidance, and supported trust/navigation actions; phone handles open-ended spoken context, detailed review, rich approvals, and complex media/search controls.
- Meta Display video support makes instructional-video playback a legitimate prototype target, but YouTube playback is `NOT YET VERIFIED`. Required research includes search/Data API access, playback/embed restrictions, authentication, advertising/policy obligations, playable URL/stream availability, legal/technical suitability for direct glasses playback, alternative sources, and a provider-neutral source boundary.
- Detailed examples and phased sequencing are recorded in `docs/ROADMAP.md`. None of this section unfreezes MVP feature development or authorizes implementation.

### Multi-agent methodology - development/review practice, not product architecture

Multi-agent/multi-perspective review (distinct mandates, deliberate disagreement, independent-then-synthesized conclusions) is approved as a development and architecture-review practice for high-value decisions - see `docs/research/MULTI_AGENT_PRODUCT_REVIEW.md` for the first application of this practice. It is explicitly NOT an approved product feature: a multi-agent swarm (Project Memory -> specialized Context Packs -> multiple agents/providers -> synthesis -> proposed Project update) remains a research/product possibility only, not implementation work, and would require its own future architecture decision before any implementation. Reviewer/agent conclusions are proposals/research input, never automatically architecture.

### Rich Project Intelligence V1 - Response Planner and typed task-aware results - ADR-059

Status: APPROVED ROADMAP, next after the current glasses Investigation + trust UX milestone. Not implemented or authorized by this documentation update. See `docs/ROADMAP.md`'s "Rich Project Intelligence V1" entry for the full sequencing, non-goals, and vertical-slice acceptance target.

**Historical sequencing note:** ADR-061 supersedes this section as the target primary interaction architecture and supersedes only its prohibition on persistent Project conversation. Its implemented result families remain reusable internal/compatibility capabilities; its trust, isolation, bounded-context, and explicit-generation constraints remain in force.

- Extends ADR-057/`docs/PROJECT_INTERACTION_FOUNDATION.md`'s `EXPLORE`/`OPTION_SET` foundation and names its future "Project Guidance Engine" boundary as the Response Planner. From explicit user intent and Project context it selects exactly one of three V1 response families - `TROUBLESHOOT` (existing Investigation, unchanged), `EXPLORE_PLAN` (richer options/rationale/tradeoffs/recommendation/next-steps/follow-up-questions payload), `GENERAL_GUIDANCE` (new minimal safe fallback). No larger taxonomy is approved yet. **The "from explicit user intent" dispatch mechanism this bullet describes is superseded by ADR-060 below - see that entry. The three response families themselves are unchanged.**
- `ProjectAIResult` is the shared envelope (`result_id`, `project_id`, `result_type`, `summary`, `hud_projection`, `evidence_refs`, `suggested_project_updates`, typed payload) - not one large mostly-nullable schema. Exact per-family payload schemas, the Planner's internal selection mechanism, and intent/router persistence are explicitly deferred to a focused design milestone.
- Trust boundary is unchanged: an AI proposal becomes canonical only through the existing Idea/Decision/Checkpoint Proposal Apply mechanism (ADR-021 through ADR-027, ADR-057); the LLM never mutates Project state directly, and selecting a rich option must not silently become confirmed truth.
- First vertical-slice proof required before generalizing: Room Redesign selecting `EXPLORE_PLAN` and producing approximately three meaningful options a user can select, reusing the existing Room Redesign Architecture Test in `docs/PROJECT_INTERACTION_FOUNDATION.md`, cross-checked against AC Repair still receiving a `TROUBLESHOOT`-shaped response from the same Planner.
- Requires an evaluation set (roughly 20-40 representative scenarios across troubleshooting, design/planning, and general guidance) - see ADR-059. Passing unit tests alone does not prove AI quality.
- Not approved by this entry: implementation; a universal chat-transcript memory; direct AI mutation of Project state; a vector/graph store without demonstrated need; more than these three response families; automatic image generation for every result (on-demand "Visualize this option" remains a separately gated later slice); or replacing deterministic Project orientation (Orientation, HUD Project Navigator) with AI-generated content. The HUD remains a bounded orientation/execution projection - see the "Glasses foundation" sequence above - never a renderer of the full rich phone/desktop response.
- Existing Investigation/Explore mechanisms are not deleted or replaced by this direction; `TROUBLESHOOT` and `EXPLORE_PLAN` reuse them.

### Bounded Response Planner Intent Inference - ADR-060 (amends ADR-059's dispatch mechanism)

Status: APPROVED ROADMAP direction only; not implemented or authorized by this documentation update. Physical Room Redesign acceptance testing showed that requiring the user to explicitly choose a response family - a visible "Or explore design/planning ideas instead" alternative to Analyze, plus a separate always-visible "DESIGN & PLANNING GUIDANCE" composer - prevented the natural workflow from ever reaching `EXPLORE_PLAN`. See ADR-060 above for the full decision.

**Historical sequencing note:** ADR-061 preserves the router as a compatibility component but supersedes it as the permanent primary model and supersedes this section's prohibition on persistent Project conversation.

- Response-family selection (`TROUBLESHOOT` | `EXPLORE_PLAN` | `GENERAL_GUIDANCE` only - no larger taxonomy) becomes application-owned bounded intelligent routing rather than explicit client/user dispatch. The user takes one natural action ("Get guidance"); which family answers it is an invisible implementation detail unless the Planner needs one clarifying question.
- The Planner's input is a narrow, deterministic Context Pack (Project identity/goal, checkpoint, recent relevant Activities/Investigations/Explore interactions, evidence presence, current request text) - never full Project history, never a chat-transcript store.
- The Planner's output is typed routing metadata only (`response_family`, `confidence`, `brief_reason`, `needs_clarification`) - it is never persisted as Project Memory and never mutates canonical Project state.
- A Project is not permanently typed to one family: the same Project can receive different families for different requests over time.
- A technical planner failure is a retryable routing failure, never silently treated as `GENERAL_GUIDANCE`. `GENERAL_GUIDANCE` is chosen only when the Planner positively determines it, or after one concise clarifying question when genuinely uncertain.
- The confidence policy for proceed / clarify / `GENERAL_GUIDANCE` is deliberately not fixed yet - it must come from the routing evaluation set (extends ADR-059's existing evaluation requirement), not an arbitrary constant.
- `TROUBLESHOOT` selected with no existing Investigation session is backend-owned session creation/reuse; Android must not invent this lifecycle. Glasses/HUD-initiated Analyze remains `TROUBLESHOOT`-only for V1 (no open-ended glasses intent composer exists yet) - intelligent routing applies to the phone's unified entry point only.
- Not approved by this entry: implementation; expanding the response family list; a universal chat-transcript memory; Planner mutation of Project state; or any change to ADR-059's three response families, `ProjectAIResult` envelope, or trust boundary.
- Bounded sequence: (1) this ADR/documentation; (2) backend planner/router contract; (3) routing evaluation + confidence policy; (4) Android unified "Get guidance" flow; (5) automated/instrumented QA; (6) one realistic physical Room Redesign acceptance retest; (7) checkpoint only after that acceptance.

### Persistent provider-neutral Project Conversation - ADR-061

Status: APPROVED TARGET ARCHITECTURE. Phase 0, Phase 1A, and Phase 1B Multimodal Conversation are accepted; Phase 2 Android conversation-first UI passed physical acceptance on real Meta glasses and a real Android phone (see `docs/ROADMAP.md`'s Phase 2 Physical Validation entry). The canonical target is `Project -> ProjectConversation -> ConversationTurn -> Assistant Orchestrator -> bounded application capabilities/tools -> Provider Adapter -> replaceable providers`. Conversation is application-owned continuity but not canonical Project truth. Turns contain provider-neutral semantic content parts and typed references to authoritative Project resources. See ADR-061 above and `docs/ROADMAP.md` for the locked migration sequence; Phase 3 (conversational Explore/Investigation/Proposal capabilities and cards) is next, gated on this Phase 2 acceptance - this validates the conversation-first vertical slice only, not production readiness, security, or cloud deployment.

## Relationship to Other Documents

- docs/PROJECT_MEMORY_ARCHITECTURE.md is authoritative for approved forward product architecture.
- docs/runtime_governance.md remains authoritative for runtime execution/startup ownership.
- docs/investigation_session_api_v1.md remains authoritative for current Investigation Session API contract.
- docs/PROJECT_INTERACTION_FOUNDATION.md remains authoritative for the reusable lightweight Project Interaction/capability abstraction and structured-result boundary under ADR-057, as explicitly superseded by ADR-061 for the primary conversation model and next implementation milestone.
- architecture/Phase2_System_Design.md remains valuable as Investigation subsystem design history and implementation reference.
- docs/research/PERSISTENT_PROJECT_MEMORY_REFERENCES.md is supporting external research evidence and does not override architecture authority.
- docs/research/MULTI_AGENT_PRODUCT_REVIEW.md is a structured product/architecture review (RESEARCH / RECOMMENDATIONS - HUMAN REVIEW REQUIRED); it does not override architecture authority, and its recommendations are not automatically approved architecture or roadmap.
- This document's own "Canonical Architecture Re-Baseline (2026-09-12)" section, below, is authoritative for current architecture status, proven/unproven findings, and product positioning going forward.

ADR-063 - ACCEPTED
Architecture Cleanup + Roadmap Re-Baseline (2026-09-12)

Context: An independent architecture review (2026-09-12, conversation-only at the time) concluded the core memory/context direction from the week's falsification experiments (durable facts, assertion modality, supersession, bounded topic-narrowed retrieval, two-tier visual Evidence) is sound and converges with established external agent-memory patterns (Letta/MemGPT tiered memory, Mem0's extraction/update pipeline, LangMem's semantic/episodic/procedural split, Anthropic's compaction/note-taking guidance) - see the research citations in the Re-Baseline section below. The review also found this convergence was not a coincidence: this repository's own prior research (`docs/research/PERSISTENT_PROJECT_MEMORY_REFERENCES.md`) and a prior structured product review (`docs/research/MULTI_AGENT_PRODUCT_REVIEW.md`, 2026-08-23) had already identified the same failure classes (fixed-window blindness, silent misclassification, checkpoint rot) the week's dogfooding rediscovered empirically, and had already set an explicit "Revisit Trigger" for exactly this situation.

Decision: Adopt the Canonical Architecture Re-Baseline below as the current authoritative reference architecture and roadmap status. Perform only confirmed-safe cleanup now (see "Confirmed Cleanup" below) - no new Persistent Memory implementation, no Current Project State/Salience experiment, no multi-user collaboration, no embeddings/vector infrastructure, no local LLM, in this pass.

Consequence: `docs/ROADMAP.md` is re-baselined with an explicit Stage 0-7 sequence, current/next milestone, and a roadmap-discipline rule (see `AGENTS.md`) so future dogfood findings are triaged into an existing milestone, an explicit roadmap amendment, or backlog - never a silent, undocumented pivot.

## Canonical Architecture Re-Baseline (2026-09-12)

This section is the load-bearing summary of the 2026-09-12 independent architecture review and cleanup pass. It intentionally does not reproduce the full experimental transcripts (durable-fact extraction falsification, Memory Reader prototype, Decision/Progress retrieval falsification) - those were conversation-scoped falsification experiments, not themselves architecture; only their conclusions are recorded here, per this document's own Documentation Governance rule in `AGENTS.md` (research/experiments are not authority until their conclusions are approved and written down - this section is that write-down).

### Product Positioning

Canonical product name: **Persistent AI Project Workspace**. Do not describe this internally as "ChatGPT with memory" or "an AI chatbot for Meta glasses" - both undersell the actual differentiator and invite the wrong comparison set.

Working product thesis: a Project Workspace that preserves the history, current state, Evidence, decisions, and progress of real work, and lets users interact with that Project naturally through desktop, phone, and hands-free wearable interfaces. Provider-independent AI reasons over application-owned Project continuity - the application owns state, history, decisions, progress, Evidence, provenance, and retrieval; the provider supplies intelligence only.

This is a **thesis**, not a validated product-market fit claim. A prior structured review (`docs/research/MULTI_AGENT_PRODUCT_REVIEW.md`, 2026-08-23) independently found, with cited sources, that the core "persistent per-project AI memory" value proposition is already shipped free by the same providers this product depends on for its own model calls (ChatGPT Projects/Memory). That finding has not been re-litigated or resolved by this week's architecture work and should not be treated as settled. Potential future differentiators (glasses-first hands-free field capture, multimodal Evidence tied to Project history, cross-device continuity, provider independence, eventually shared/multi-user Project workspaces) remain unvalidated claims, not proven differentiation, until real external users demonstrate retention.

A useful mental model for the intended product shape (illustrative only - not authorization to pivot into a construction-specific product): a construction team today coordinates a Project through a Dropbox folder of photos/notes/documents that people manually search to understand status. The target product experience is a **Project Workspace** where photos/voice/observations belong to the Project, decisions and progress persist, Project state stays current, and authorized users can later ask natural questions ("Where did we leave off on electrical?", "What happened in unit 412?", "What's blocking inspection?") and get a trustworthy answer instead of manually searching files. Multi-user/shared-Project collaboration is a plausible long-term direction implied by this model; it is explicitly **not authorized for implementation now** (see Stage 7 in `docs/ROADMAP.md`).

### Canonical Reference Architecture

Eight responsibilities, mapped onto existing or planned components - no new component is introduced merely to fill a slot:

1. **Project Workspace / Project identity** - existing `ProjectStore`/`Project` schema. Canonical data: `project_id`, name, goal, status. Owns namespace isolation. No change.
2. **ProjectConversation** - existing `conversation_store.py`/`ConversationTurn`. Canonical data: raw episodic turn log. Explicitly NOT canonical durable truth (unchanged principle, now with real-provider evidence behind it). No change.
3. **Memory Extraction** (not yet implemented for ordinary conversation) - a planned, stateless pass recognizing durable facts/constraints/decisions/progress/corrections from a turn. AI-assisted where semantics require it (this week's experiments: deterministic-first, model fallback for ambiguous cases). Owns no canonical state itself.
4. **Structured Project Memory** (not yet implemented) - durable facts, constraints/preferences, decisions, progress/events, with supersession, provenance (`source_type`), and assertion modality (new field, not yet added to the schema). The natural extension of the existing `ProjectActivity` store and its trust taxonomy, not a replacement for it.
5. **Evidence** - existing Investigation evidence store/upload path, extended (not yet implemented) with a durable derived text description per Evidence record and a real "re-inspect original bytes" capability, proven viable this week.
6. **Current Project State** (not yet implemented as a first-class concept) - a bounded projection derived from Structured Project Memory, explicitly not a competing database. `project_knowledge.py`'s existing read-only projection pattern is the closest existing analog and a reasonable foundation to evolve (see Confirmed Cleanup Decisions above). Checkpoint's externally-visible behavior is the eventual target for this projection to subsume - not done yet.
7. **Context Retriever / Context Pack** - existing `project_context_retriever.py`. Deterministic eligibility/truth filtering first, topic narrowing where possible, semantic AI selection only where deterministic narrowing cannot resolve a subject - the three-stage shape proven this week, not yet implemented in the production retriever (see Confirmed Cleanup Decisions above for its current, unfixed defects).
8. **Provider Adapter** - existing OpenAI adapter. Owns no Project continuity; provider-neutral by design; unchanged.

`CheckpointProposal` remains the trust/mutation gate for genuinely consequential Project changes requiring explicit confirmation - unchanged, and explicitly the correct precedent to extend (not replace) when Structured Project Memory needs a similar gate for higher-consequence writes.

### Product Requirement Amendment — Structured Continuity from Natural Conversation (2026-09-12b)

Recorded as a requirement to shape Stage 2 onward. This is not authorization to implement it, not a schema, and not multi-user collaboration.

**Core principle**: the user talks naturally; the Workspace becomes structured automatically. `ProjectConversation` (component 2 above) is necessary but not sufficient - important user interactions (a finished repair, a budget, a changed decision, a photo of completed work) must eventually become durable, structured, queryable Project information owned by the application, without the user filling out a form. This is the product-level reason Structured Project Memory (component 4) and Current Project State (component 6) exist at all - they are not abstract data-modeling exercises.

Useful future dimensions for that structured information - **a requirement, not an authorized schema**: Project, actor/contributor, time, Project scope/location/work area, activity/observation, progress/status, decision, Evidence, provenance. The exact production schema remains unauthorized; do not build one from this list directly.

**Project History vs. Current Project State - keep this distinction explicit, they must never compete:**
- **Project History / episodic record**: what happened, in order, including superseded information (e.g. "Sept 3: decision - keep couch; Sept 5: decision changed - replace TV stand; Sept 7: rug ordered; Sept 12: rug arrived"). Unbounded by nature - it only grows.
- **Current Project State**: where the Project stands now (e.g. "Budget: ~$1,500; TV stand: replace; Rug: delivered; Next action: choose TV stand"). A bounded projection derived from History, never a second independently-written store.

**Queryable Project requirement**: the application must be able to answer/retrieve across these dimensions - by actor ("what did Jesse do last"), by scope/location ("what happened in Unit 412"), by topic ("where are we on electrical"), by state ("what's blocking this Project"), by change ("what decisions have changed") - **before** anything is sent to the model. The intended flow:

```text
User question
    |
    v
Project Workspace identifies relevant scope
    |
    v
Application-owned Project Memory / History / State / Evidence retrieval
    |
    v
small, trustworthy, bounded context
    |
    v
LLM reasoning / synthesis
    |
    v
natural answer
```

Explicit separation: the **application** decides what Project information is relevant and authoritative; the **LLM** decides what that information means and how to explain/reason over it. This does not mean every query must be solved deterministically - semantic interpretation (classification, paraphrase resolution, synthesis) may use a model where this week's experiments showed deterministic rules cannot reliably do the job (see "Proven vs. Not Yet Proven" above). Canonical Project information itself remains application-owned regardless of which layer answers a given question.

**Future actor/contributor requirement (not multi-user collaboration)**: the architecture must not assume a Project will forever have exactly one human contributor, and must not make future attribution ("what did Jesse do last," "who reported this") impossible or require redefining what a Project event fundamentally is. `ProjectActivity`'s existing `source_type` field and per-record provenance are the reuse point for this - extend that model's attribution capability when the time comes rather than inventing a second one. Do **not** build accounts, roles, permissions, teams, invitations, multi-tenant authorization, or collaboration UI now - none of that is authorized by this entry.

**Architectural guardrail**: one canonical Project history/event substrate with different query dimensions over it - not separate "Activity History," "User History," "Actor History," or "Construction History" systems, and not a separate "glasses memory" or "construction memory." Everything in this amendment is a way of *querying* the same Structured Project Memory/History (components 4 and 6 above), never a reason to fork it.

**Construction / field-work example**: illustrative of the product thesis only (a Project Workspace where photos/voice/observations/decisions/progress belong to the Project instead of living in a manually-searched folder) - not a pivot into construction software, and not scheduled before Stage 7.

**Glasses differentiation**: unchanged center - the Project Workspace remains canonical; desktop, phone, and glasses are interfaces into it. Glasses are a potential differentiator specifically for hands-free capture, Evidence collection, observation, Investigation, Project queries, and progression while the user is physically performing work - recorded as product thesis, explicitly not market-validated (see "Product Positioning" above), and never a reason to make Meta-specific infrastructure canonical.

### External Research Consulted (2026-09-12)

Extends, and does not replace, `docs/research/PERSISTENT_PROJECT_MEMORY_REFERENCES.md` (which already covered Mem0, LangGraph checkpoints, Graphiti, MEMENTO, and wearable-specific references). New material consulted this pass:

- Anthropic, "Effective context engineering for AI agents" (anthropic.com/engineering) - compaction, structured note-taking outside the context window, and sub-agent summarization as the three patterns for long-running agent memory; Anthropic's file-based memory tool (Sonnet 4.5) and "Memory for Managed Agents" beta (2026-04-23) as concrete implementations of application-owned, file-based external memory.
- Letta (MemGPT) - tiered memory: core memory (small, always-in-context), recall memory (full searchable raw history), archival memory (processed/indexed long-term store). Cited for the general "small always-loaded tier vs. large on-demand tier" split; not adopted as an infrastructure dependency.
- Mem0 - explicit two-phase extraction/update pipeline where an LLM call decides ADD/UPDATE/DELETE/NOOP per candidate fact against existing memory. Independently convergent with this week's supersession-by-canonical-key design.
- LangMem/LangGraph - semantic (facts) vs. episodic (events/conversation) vs. procedural (skills/rules) memory typing, stored as namespaced documents, not necessarily vector-backed.
- OpenAI/ChatGPT - "saved memories" (explicit or auto-detected durable facts) vs. "chat history reference" (draws on past conversations without an explicit save step); exact conflict-resolution mechanism is not publicly documented and was not assumed.

Cross-cutting conclusion, consistent with the existing "Cross-Project Research Conclusions" list above: none of these systems reach for vector/embedding infrastructure as a first resort, and every one of them separates the "small, always-available current state" concern from the "large, on-demand history" concern - the same split this week's experiments independently arrived at for this repository's Decisions/Progress data.

### Proven vs. Not Yet Proven

This week's falsification experiments (durable-fact extraction, an isolated Memory Reader prototype, Decision/Progress retrieval) produced conversation-scoped, real-provider evidence. Their conclusions, and only their conclusions, are promoted to this document:

**Proven / strongly supported by real-provider experiments this pass:**
- Raw bounded conversation history alone is insufficient for long-running Project memory (independently consistent with this document's pre-existing "Do not send full Project history to the LLM by default" principle and with the 2026-08-23 product review's "fixed-window blindness" finding).
- Ordinary durable facts/constraints stated in plain conversation need a persistence path outside raw conversation turns; today none exists for ordinary conversation (only Explore/Investigate/Progression-triggered Activities are written).
- Current-vs-superseded filtering should be deterministic, applied before any AI selection step - AI-only filtering (no deterministic pre-filter) measurably, reproducibly resurrected superseded information in adversarial testing.
- Assertion modality (tentative / third-party / hypothetical / historical / committed) is a distinct concern from source/provenance (`source_type`) and is not currently represented by the existing `source_type`/`confirmation_status` taxonomy on `ProjectActivity` - that taxonomy needs a second, orthogonal field before a general fact-extraction pipeline can safely reuse it.
- Supersession must preserve full history (never delete/mutate in place) and must be modality-aware (a tentative/third-party/hypothetical statement must never be treated as "the thing being corrected").
- A structured subject+slot model (e.g. `tv_stand/disposition`, `tv_stand/style_choice`) correctly supports Decision supersession without false-collapsing genuinely distinct decisions about the same subject.
- Specific-topic Decision/Progress retrieval ("what did we decide about X") can remain bounded and cheap (near-constant Context Pack size measured from 20 to 2,000 synthetic records) once deterministic eligibility filtering and topic narrowing run before any AI selection step.
- AI semantic selection is genuinely useful, and outperforms deterministic keyword matching, for paraphrased/low-keyword questions and for questions with no single resolvable subject - but only once deterministic trust/eligibility filtering has already run first.
- A two-tier visual Evidence model (durable text description generated once, original image bytes re-fetched only when the description is judged insufficient for a specific question) works end-to-end against a real photo and a real vision call, without resending image bytes on every turn.
- Provider/model quality was not the primary cause of the Living Room dogfood memory failures - a real, controlled same-model comparison showed dramatically better answers once given correct structured context, with no model change.
- Simply enlarging the raw conversation window is not the correct primary fix - it delays when the underlying non-durability problem becomes visible without resolving it.
- Vector/embedding infrastructure is not currently justified by any evidence gathered this pass - a plain "compact summaries + a lightweight model selection call" approach correctly handled up to 2,000 synthetic candidates.

**Not yet proven - do not treat as architectural fact:**
- Long-horizon multi-user collaboration - not attempted, not modeled, not scheduled before Stage 7.
- Editable Project Workspace behavior (natural-language corrections becoming authoritative updates) - recorded as a requirement this pass (see "Editable Project Workspace Requirement" below), not implemented or tested.
- Large/mature-project onboarding (importing substantial pre-existing history into this architecture).
- That embeddings/vector-DB infrastructure will remain unnecessary indefinitely - only that it is not justified by evidence gathered so far, consistent with this document's existing "Storage Strategy" and "Architectural Risks" #5 (premature infrastructure).
- That a local/self-hosted model is needed for any part of this pipeline - nothing gathered this pass supports it; extraction/classification/selection tasks tested this pass all used the same general-purpose hosted provider already used elsewhere.

### Stage 1 Result: Current Project State / Salience Gate — PASSED (2026-09-12c)

The final planned architecture falsification experiment is complete. **Architecture exploration on the memory/context path is now closed** - it resumes only if Stage 2 implementation falsifies a foundational assumption below, not on discovery of an interesting optimization (see the Roadmap Discipline Rule in `AGENTS.md`).

**Core question tested**: given potentially thousands of facts, decisions, progress events, and Evidence records, how does the system produce a small, trustworthy, bounded representation of "where does this Project currently stand" for continuation-style questions, without either dumping the entire current-state set unbounded or under-selecting because almost every current item is nominally "relevant"?

**Additional findings promoted to Proven** (extending the list above):
- Recent-N history is insufficient for global Project continuation - it is both untrustworthy (carries no status filtering) and, at scale, incomplete (real content gets evicted by unrelated volume).
- A flat structured current-state projection (all workstreams/areas combined, no grouping) can be fully correct but becomes unbounded as the number of distinct active Project areas grows - it is not solved by supersession alone, only facts/single-slot decisions are bounded that way.
- Naive hierarchy (grouping by workstream/scope but expanding every group in full) is not an improvement over a flat projection for boundedness - it must be paired with resolved-area collapsing and a real selection mechanism to help at all.
- Deterministic recency-among-active-items is bounded but was measured to incorrectly evict an old, non-recently-touched item after its priority changed - recency is not a safe proxy for importance.
- Deterministic truth/eligibility filtering (current-vs-superseded, modality, abandoned-scope exclusion) must run before any AI selection step, not alongside or instead of it - confirmed again this pass.
- Active blockers must remain visible regardless of age - implemented as an unconditional, never-evicted category, not subject to recency or selection at all.
- Resolved (fully completed or abandoned) workstreams/areas can safely collapse to a count rather than being individually expanded.
- AI salience selection is justified - not merely convenient - for choosing which non-blocked active workstreams to surface for a broad continuation question; the deterministic recency alternative was directly measured to fail this specific job.
- Topic/scope-specific questions ("what did we decide about X," "where are we on electrical") remain a different, already-solved problem (targeted bounded retrieval, per the prior Decision & Progress gate) - global continuation and topic-specific retrieval are genuinely different mechanisms and should not be forced into one.
- Current Project State can be derived on demand from canonical History/Structured Project Memory rather than persisted as a second store - recomputing fresh on every request was fast and cheap enough at tested scale, with zero state-drift risk by construction.
- Workstreams/scopes do not currently justify a new canonical subsystem - grouping existing Project records by a scope field was sufficient for every case tested.
- Embeddings/vector infrastructure remains unjustified - plain-text candidate lists plus a single lightweight-model selection call worked correctly up to 2,000 records and 234 distinct workstreams.
- A local/internal LLM remains unjustified - every step used the same general-purpose hosted provider already used elsewhere.

**Winning flow, global continuation:**

```text
Canonical Project History / Structured Project Memory
    |
    v
deterministic current-truth eligibility filtering
    |
    v
deterministic blocker identification (age-independent, always shown)
    |
    v
resolved-area collapsing (fully completed/abandoned -> a count, not detail)
    |
    v
group remaining eligible state by workstream/scope
    |
    v
AI salience selection among non-blocked active workstreams
    |
    v
bounded Current Project State
    |
    v
Context Retriever / Context Pack
    |
    v
LLM synthesis
```

**Winning flow, topic/scope-specific questions** (unchanged from the prior gate, reconfirmed compatible):

```text
question
    |
    v
deterministic scope/topic resolution where possible
    |
    v
bounded relevant Project state/history
    |
    v
AI semantic fallback only where deterministic resolution fails
    |
    v
LLM synthesis
```

Preserve this distinction going forward: **Project History answers "what happened?"; Current Project State answers "what matters now?"** Current Project State is derived, never a second canonical truth store.

**Boundedness evidence** (~2,018 total records, real-provider measured, not simulated): flat projection grew to ~31,355 characters; naive full-expansion hierarchy grew to ~165,792 characters; the corrected bounded design (deterministic blockers + collapsed resolved areas + AI salience selection replacing recency) stayed at ~2,016 characters - flat across a 112x growth in total History.

**Remaining scaling caveat, not currently blocking**: the AI salience-ranking step's own candidate input (the list of currently non-resolved workstreams handed to the ranking call, not the final Current Project State output) grew with active-workstream count - about 21,000 characters at the 2,000-record/234-workstream test point. This is a real, different, gentler growth curve than growing with total History, and it did not cause a correctness or cost problem at tested scale. It is recorded as a **future escalation trigger**: if a real Project ever develops a very large number of simultaneously active workstreams and this candidate list becomes expensive or slow, evaluate additional deterministic narrowing or indexing at that time - not solved now, and not a reason to delay Stage 2.

### Editable Project Workspace Requirement (2026-09-12c)

Recorded as a requirement to shape Stage 2 onward, not authorization to implement this behavior now.

The Project Workspace must not be a read-only, AI-generated summary. Users must eventually be able to correct and progress Project state through the same natural conversation used for everything else - e.g. "those three things are already done," "we don't need to do that anymore," "actually John did that, not Jesse," "that issue came back," "we changed our mind, keep the existing fixture," "we're still waiting on inspection." These are eventually authoritative Project updates (completion, cancellation/no-longer-required, correction, attribution correction, reopening, decision supersession, blocker update, progress update) - not merely conversation.

**Architectural rule, non-negotiable**: users do not directly edit the derived Current Project State as if it were canonical truth. The flow is always:

```text
User natural-language correction/update
    |
    v
interpretation / validation
    |
    v
new authoritative Project event / memory update
    |
    v
canonical Project History is preserved (never overwritten)
    |
    v
Current Project State is re-derived
```

Consequently, editing current Project understanding must never erase historical truth. Example: "Replace Unit 412 panel" recorded, then later "we don't need to replace that panel anymore" - History preserves both the original decision and the cancellation as distinct events; Current Project State shows "panel replacement: no longer required"; a later historical question ("didn't we originally plan to replace the panel?") must still be answerable, correctly, as a superseded/cancelled decision - exactly the same supersession discipline already proven for ordinary decision changes, applied to user-initiated corrections as well as new information.

**Trust/confirmation boundary - reuses existing principles, no new trust system**: clear, low-consequence natural-language updates may eventually be interpreted as explicit user Project updates without a separate approval step, extending the precedent Conversational Project Progression Slice 1 (ADR-062) already established for low-consequence auto-apply. Ambiguous or consequential corrections require clarification or the existing `CheckpointProposal` confirmation mechanism, not a new one. Silence is never confirmation. The model never directly mutates canonical Project state; the application interprets/validates and owns persistence - unchanged from this document's Core Architectural Principle.

This requirement must remain compatible with, and must not fork into a separate system from, the previously recorded future dimensions (actor/contributor attribution, time, location/scope/workstream, Evidence, provenance, status/progress, decisions) and the existing architectural guardrail: one canonical Project history/event substrate with different projections and queries over it - not a separate Actor History, Construction History, Glasses History, or User History, and not a separate correction/edit subsystem either. Multi-user collaboration remains out of scope and deferred to Stage 7.

### Stage 2 Result: Integrated Persistent Memory Shadow Slice — IMPLEMENTED, SHADOW MODE (2026-09-12d)

The Stage 1-proven design is now real, production-integrated code, running in shadow alongside the existing Context Retriever/Checkpoint/Project Knowledge path - **not yet wired into normal conversation** (that is Stage 4). New modules: `projects/models.py` (`ProjectMemoryRecord`/`ProjectMemoryCandidate`/`ProjectScopeState`/`ProjectCurrentState` and the `ProjectMemoryCategory`/`ProjectMemoryModality`/`ProjectMemoryStatus`/`ProjectMemoryProgressState` enums), `projects/memory_store.py` (`ProjectMemoryStore` - atomic-write, per-project-locked, history-preserving supersession), `projects/memory_extraction.py` (`ProjectMemoryExtractionService` - one bounded JSON-mode model call per eligible turn), `projects/project_current_state.py` (`ProjectCurrentStateService` - pure, stateless derivation, ported verbatim from the Stage 1 winning flow). `AssistantOrchestrator.send()` fires shadow extraction after the real turn is durably saved and the conversation lock has been released (never while holding it - extraction is a real, potentially slow provider call), wrapped so a shadow failure is logged and never breaks the real conversation turn. Two minimal inspection endpoints exist for developer/test use only: `GET /projects/{id}/memory` (raw records) and `GET /projects/{id}/memory/state` (derived Current Project State, optional `?scope=`).

**Assertion modality**, a new axis orthogonal to `ProjectActivitySourceType`, closes the exact trust-taxonomy gap this document's "Proven" list already identified: `COMMITTED`/`TENTATIVE`/`HISTORICAL`/`HYPOTHETICAL`/`CONDITIONAL`/`THIRD_PARTY`. There is deliberately no `AMBIGUOUS` value - an extraction that cannot safely resolve a subject produces no candidate at all (abstains) rather than writing an ambiguous record. Only a `COMMITTED`, non-progress candidate may supersede a prior current `COMMITTED` record under the same `(scope, subject, slot)` - a later tentative/third-party/hypothetical statement never supersedes committed truth, and a later committed statement correctly skips past an intervening tentative aside to supersede the last real committed record. Progress is append-only and never superseded in storage; "current" progress is always the latest event per `(scope, subject, slot)`, derived at read time.

**Implementation-time correctness fix** (found via the realistic scenario below, not foundational): the ported Stage 1 `_scope_status` heuristic originally marked a scope "resolved" whenever all of its progress records were terminal, without checking whether the scope still carried standing current facts/constraints/preferences/decisions. In the real Living Room run, the `overall` scope held budget/style/durability facts alongside one incidental completed "rug arrived" progress event, and the original heuristic collapsed it out of the global summary - hiding still-true facts. Fixed in `project_current_state.py`'s `_scope_status`: a scope only collapses to "resolved" when its progress is all-terminal **and** it has no current facts/constraints/preferences/decisions left to show. All prior deterministic tests (including the ABC Apartments structural test) still pass unchanged after the fix.

**Real-provider findings** (Living Room 12-turn scenario, run through the actual `/projects/{id}/conversation/messages` endpoint and real `AssistantOrchestrator.send()`, real `ProjectMemoryExtractionService` calls, fake conversation-reply provider only): the extractor correctly split this scenario across two scopes on its own - Project-general standing facts (budget, style, dog/durability) under `overall`, and item-level decisions/progress (couch, TV stand, rug) under `living_room` - with both views correctly deriving from the same canonical record list (no separate per-scope store), confirming the architecture's core hierarchical-scope requirement under real model behavior, not just synthetic data. Final current truth matched expectations: budget ~$1,500 (not $1,750 tentative, not $3,000 third-party), couch kept, dog/durability constraint present, TV stand disposition superseded keep -> "no replacement needed" (history preserved), rug ordered -> arrived (both progress events preserved, append-only). One observed **known limitation**: a compound correction ("replace the TV stand with something warm wood") was split by the extractor into a separate `material` fact alongside the `disposition` slot, rather than folding the material choice into a single disposition update - both are independently reasonable, current, correctly-provenanced records, but a future compound-statement extraction refinement could represent this more cleanly. Not blocking; recorded for Stage 4 refinement, not a supersession or modality defect.

**Testing summary**: 19 deterministic unit tests (schema, modality-aware supersession, no false supersession across distinct slots, progress append-only/completion/reopening, decision cancellation via supersession, blocker retention, resolved-scope collapsing, scoped-view isolation, provenance, no-AI-call-below-threshold, and the ABC Apartments multi-scope structural test) + 4 fake-provider extraction unit tests + 6 fake-provider conversation-level integration tests (extraction orchestration, exactly-one-call-per-turn, shadow-failure isolation from the real turn, abstention, idempotent-replay non-double-extraction, multi-candidate persistence) + 6 minimal real-provider modality checks + 3 real-backend Living Room E2E tests, all passing, alongside the full pre-existing repository suite (859 tests total) with zero regressions. Provider cost discipline confirmed: exactly one extraction call per eligible turn, no agent loop, no embeddings/vector DB, no local model.

### Stage 3 Result: Visual Evidence Continuity — IMPLEMENTED, IN PRODUCTION (2026-09-12e)

The proven two-tier design (see this document's "Proven" list above, and the Stage 1 boundedness precedent it extends) is now real, production-integrated code. Unlike Stage 2, this is **not shadow-only**: a two-tier retrieval decision has to shape the current turn's own reply, so it runs on the real conversation critical path, inside the same project lock `AssistantProvider.respond()` itself already runs in - not a new pattern, the existing turn-generation call was already synchronous there. Only description GENERATION (a side-effect that does not gate this turn's reply) runs after the lock releases, exactly like Stage 2's shadow memory extraction, for the same reason (a real, potentially slow provider call must never hold the conversation lock).

**New module** `projects/visual_evidence.py`: `VisualEvidenceContinuityService` (one real-provider call for `describe()`, one for `select()` - both JSON-mode, temperature 0, never a multi-step agent loop), pure deterministic `select_candidates()` (scope-keyword narrowing + recency ordering + a small bound, no provider call), and a cheap deterministic keyword gate (`is_visual_continuity_candidate`) that avoids the selection call entirely for ordinary non-visual turns. **Schema**: `InvestigationEvidence` gained three new optional fields (`visual_description`, `visual_description_scope`, `visual_description_generated_at_utc`) - Evidence remains the sole canonical store; nothing here duplicates image bytes or creates a second Evidence store. `InvestigationEvidenceStore.set_visual_description()` mirrors `set_evidence_explanation()`'s exact atomic-write idiom, but deliberately does **not** reuse its COLLECTING-only mutation gate: visual continuity must cover Project history, including Evidence in a session that has moved on (analyzed/completed), so restricting description-writing to COLLECTING would make older Evidence permanently undescribable.

**Narrow integration seam** (the one place Stage 3 touched shared conversation machinery, exactly as authorized rather than a broader Context Retriever redesign): `AssistantRequest` gained one new optional field, `visual_context: str | None`, and `OpenAIAssistantProvider.respond()` includes it in the payload under `retrieved_visual_evidence_description` with an explicit instruction that this is a **stored TEXT description, not a live image** - the model must never claim to currently see/view it. Tier 2 needed no such seam: it simply populates the SAME `AssistantRequest.images` field an ordinary fresh attachment already uses, with the retrieved original Evidence bytes - reusing the exact existing vision-call machinery rather than a second "reinspection" path. `ConversationProviderProvenance` gained two optional inspectability fields, `visual_retrieval_tier`/`visual_evidence_id`, populated only when retrieval actually fired - free inspectability via the existing `GET /projects/{id}/conversation` endpoint and the existing `GET .../evidence` endpoint (which now also surfaces the new Evidence fields automatically), so no new inspection endpoint was needed.

**Failure behavior**: a description-generation failure preserves the original Evidence and is only logged, never breaking the real turn (verified by test). A Tier 2 selection whose original pixels turn out to be unavailable falls back to the stored description with an explicit "cannot be verified from the stored description" instruction, rather than silently answering as if Tier 1 were sufficient or fabricating the detail (verified by test). The AI selection call abstains (returns nothing) on any ambiguity or malformed output, rather than guessing a specific Evidence.

**Real-provider / real-backend findings** (Living Room scenario, a PIL-generated synthetic photo with a small printed tag detail deliberately excluded from the general-description prompt's own emphasis, run through the actual `/projects/{id}/conversation/messages` endpoint, real `AssistantOrchestrator.send()`, real `OpenAIAssistantProvider`, real `VisualEvidenceContinuityService` - only the recording wrapper around the real OpenAI client differs from production, and it forwards every call unchanged): a real vision call correctly produced a conservative description of the room's major elements while genuinely omitting the small tag; a later Tier 1 question ("Would blue work in this room?") was answered using only the stored description with the conversation call's outbound request carrying **zero image content** (directly inspected, not inferred); a later Tier 2 question about the tag correctly triggered original-pixel retrieval, the outbound request carried the actual image content, and the real vision-augmented reply correctly read the tag's two characters from the real pixels. One **reliability caveat**: the AI selection call is not perfectly deterministic even at temperature 0 - an early, more ambiguously-worded Tier 2 question occasionally produced a safe abstention (no hallucination, just a missed Tier 2 opportunity) rather than a firm original_required decision; rewording the question to explicitly reference "the photo I sent" (matching this document's own acceptance-scenario phrasing) resolved this across repeated runs. Recorded as a real-world reliability characteristic of relying on a live model for the tier decision, not a foundational defect - the failure mode observed was always safe (abstain), never a hallucinated visual claim.

**Testing summary**: 17 deterministic + fake-provider unit tests (description persistence/provenance/round-trip, description-writing allowed regardless of session state, Project isolation via session ownership, the visual-continuity keyword gate, scope-narrowing with no cross-contamination, recency ordering, bounded candidate lists, the ABC Apartments multi-scope structural test, and fake-provider describe/select behavior including abstention on malformed/out-of-range/not-applicable responses) + 7 conversation-level integration tests through the real endpoint (shadow description generation on fresh attachment, shadow-failure isolation, no retrieval for an ordinary non-visual question, Tier 1 sends zero pixels, Tier 2 sends the correct original pixels, Tier 2-with-unavailable-pixels falls back without hallucinating, a turn with its own fresh evidence_refs never treated as retrieval) + 4 real-provider checks (conservative non-inventing description generation, before-vs-current selection, abstention on an unrelated question) + 1 real-backend two-tier Living Room E2E test, all passing, alongside the full pre-existing repository suite (888 tests total) with zero regressions.

### Stage 4 Result: Real Conversation Integration — IMPLEMENTED, IN PRODUCTION (2026-09-12f)

Stages 2 and 3's substrates now actually shape normal ProjectConversation answers. **Nothing new was made canonical**: Structured Project Memory (Stage 2) remains the one substrate, Current Project State remains derived on demand, Evidence remains canonical for visual artifacts - Stage 4 added exactly one new retrieval seam, `projects/memory_retrieval.py`, that decides which already-canonical records are relevant to the current question and renders them as a small, clearly-labeled text block merged into the existing `bounded_project_context` payload dict. No `AssistantRequest`/provider schema change was required for this (unlike Stage 3's `visual_context`, which answers a different question - "is a live image present" - Stage 4's content is plain additional bounded text keyed as `structured_project_memory`).

**Question-aware retrieval, deterministic-first**: a cheap keyword gate first tries an unambiguous deterministic match - a known category word ("constraints"/"preferences"), an unambiguous subject-name match ("budget", "tv_stand"), or a continuation phrase ("where did we leave off", "what's next", "is anything blocking"). Continuation questions call the already-proven `ProjectCurrentStateService.get_current_state()` (Stage 1's global derivation, unchanged) and render its blockers/scope-summaries/recent-changes/detail into natural text. Subject questions render either the CURRENT+COMMITTED record(s) only, or - for a question recognized as historical ("originally", "why did", "what changed") - the full chain (current and superseded), each entry explicitly labeled CURRENT / ORIGINAL / superseded, plus the actual originating conversation-turn text when resolvable via the record's existing `source_turn_id` provenance (no new field, no new store). Only when deterministic matching is ambiguous or silent does one bounded AI selection call (`ProjectMemoryRetrievalService`, mirroring Stage 3's exact `select()` pattern) decide the subject/intent - given the current question, a little recent conversation (for anaphora - "why did **that** change" correctly resolves to the right subject using prior turns, verified with a real call), and a bounded list of known current subjects. It never decides canonical truth, only which already-canonical records are relevant.

**Trust boundary preserved**: only CURRENT+COMMITTED records ever appear under a "CURRENT (confirmed)" heading; tentative/third-party/hypothetical statements are excluded from `known_current_subjects()` entirely (verified by test) and one explicit instruction line was added to `OpenAIAssistantProvider`'s existing `instructions` payload telling the model text under a HISTORY heading is past record only, never confirmed present truth, and never to invent why something changed beyond what the history entries show.

**A real correctness bug was found and fixed during the long-horizon acceptance run, not a foundational failure**: the extraction system prompt's existing slot-splitting ambiguity (recorded as a Stage 2 "known limitation" - "replace X with Y" sometimes extracted as a standalone `material` fact that left the `disposition` slot stuck at its earlier value) surfaced as a genuinely wrong Stage 4 answer ("yes we're keeping the TV stand, it's made of warm wood") the first time a real long-horizon scenario exercised it end-to-end. Fixed by adding one concrete instruction to `memory_extraction.py`'s system prompt: a "replace/swap/change X for/to/with Y" statement about an item's fate must update that item's `disposition` slot with the whole outcome, never park it under an unrelated slot that leaves `disposition` stale. Re-verified against Stage 2's own real-backend Living Room E2E test (still passes) before re-running Stage 4's scenario. A second, smaller fix went into `render_subject_context`'s historical rendering: the CURRENT block was originally shown before HISTORY, which biased a real model toward answering "what did we originally decide" from the CURRENT (most prominent, "confirmed") block instead of the actual oldest history entry - fixed by reordering (HISTORY first, each entry explicitly labeled ORIGINAL/CURRENT/superseded) so "originally" and "current" questions are unambiguous regardless of read order.

**Editable Project Workspace groundwork**: one line was added to the extraction system prompt instructing it to abstain on a PLURAL or anaphoric correction referring to more than one prior item at once ("those are both already done") when the single message alone does not make the specific subjects unambiguous - extending the existing single-subject ambiguity-abstention rule rather than building a new correction subsystem, per Stage 4's explicit "implement only what coherent natural conversation integration requires" instruction.

**Long-horizon real-backend acceptance** (36-turn Living Room scenario - 23 setup turns with a fake conversation-reply provider but REAL Stage 2/3/4 calls throughout, since extraction/description/retrieval trigger on the user's own turn text regardless of what the assistant replies, followed by a genuine leave/return - a brand-new orchestrator with fresh store objects re-reading the same persisted files - then 13 graded questions through the REAL conversation provider): all 13 required questions answered correctly and grounded in real Project history, confirmed directly against persisted state, not just response text. Budget stayed exactly $1,500 despite a tentative $1,750 aside and a third-party $3,000 suggestion (neither ever reached CURRENT+COMMITTED status). The TV-stand answer correctly distinguished "originally kept, now being replaced with warm wood" from "currently being replaced" using the same underlying chain. A real blocker (a wiring issue) and real completed/open work were both surfaced correctly. Both visual tiers fired correctly on the same scenario used for the memory questions - Tier 1 (room appearance, blue suitability) sent zero image content (directly inspected in the outbound request); Tier 2 (a synthetic tag detail deliberately excluded from the general description) correctly re-fetched the original Evidence and the real vision-augmented reply read it correctly. Bounded context held even at this history length: the largest of the 13 graded requests' text payloads was 9,908 characters (the global continuation question, expected to be the largest) - two to three orders of magnitude below Stage 1's proven pathological range (31,355-165,792 characters) for naive/unbounded designs at comparable-or-smaller record counts.

**Provider-call discipline and one identified inefficiency**: across the full 36-turn scenario, extraction fired exactly once per turn (36 calls, as designed) and description generation fired exactly once (for the one fresh image attachment, also as designed). Deterministic matching successfully avoided the AI selection call for roughly 40% of turns in both Stage 3 (visual) and Stage 4 (memory) retrieval. The identified inefficiency: Stage 3's existing broad visual-continuity keyword gate and Stage 4's lack of an upfront "is this plausibly a retrieval question at all" gate let several ordinary SETUP statements (declarative, not questions - e.g. "I'm also thinking about repainting the hallway sometime") reach an AI selection call that then correctly abstained. This cost extra calls without ever producing an incorrect answer (abstention is always safe) - recorded as a tuning opportunity for a future pass (e.g. requiring question-like phrasing, not just keyword presence, before either selection call fires), not a Stage 4 blocker.

**Testing summary**: 21 deterministic unit tests (question-classification keyword gates, deterministic subject/category matching including ambiguity-triggered abstention, CURRENT-only rendering that excludes tentative/superseded, historical chain rendering with ORIGINAL/CURRENT labeling and original-turn-text grounding, continuation rendering from real `ProjectCurrentState`, and the full `retrieve_memory_context()` entry point's deterministic-short-circuit and AI-fallback-and-abstention paths) + 7 conversation-level integration tests through the real endpoint (no memory yet omits the key entirely, deterministic subject/continuation short-circuits with zero AI calls, tentative/third-party never contaminate CURRENT, AI fallback honors the selection service, abstention omits the key, and a simulated Structured Project Memory read failure never breaks the real turn) + 3 real-provider checks (anaphora resolution using prior conversation, continuation-intent recognition without deterministic phrasing, abstention on an unrelated question) + 1 real-backend 36-turn long-horizon E2E, all passing, alongside the full pre-existing repository suite (920 tests total) with zero regressions.

**Independent review addendum (2026-09-12g)**: a subsequent independent review of this implementation, before commit, found and fixed three real rendering-correctness bugs in `memory_retrieval.py`, none foundational, all now covered by dedicated regression tests:

1. **Modality leakage in historical rendering**: a tentative/hypothetical/third-party record independently sitting at `status=CURRENT` (Stage 2 never supersedes a non-committed record, so it can coexist indefinitely alongside the real committed current record) was labeled `"CURRENT / most recent"` in the historical chain view identically to the genuinely-current committed record - directly contradicting that view's own header claim that only one entry is still true. Fixed: the label now requires `modality == COMMITTED`; a non-committed current-status record gets its own distinct label (`"NOT SUPERSEDED, BUT NOT CONFIRMED"`).
2. **Truncation could mislabel a false "ORIGINAL"**: `render_subject_context`'s history window (`sorted(...)[-N:]`) truncated before computing which entry was oldest, so a subject with more than the window size of historical events (a plausible case for a frequently-revisited decision) would silently drop the true first record and mislabel a later surviving one "ORIGINAL" - a factually wrong answer to "what did we originally decide." Fixed: the true oldest record is identified from the full, untruncated chain and always shown, with a middle-omission marker when the chain exceeds the window.
3. **Unbounded category rendering**: `render_category_context` (the "what constraints should we keep in mind" path) had no cap, unlike every other rendering path here - capped to the 15 most recent, matching the bounded-by-design pattern used everywhere else.

A fourth issue was a labeling gap rather than a defect in the underlying data: Current Project State's `recent_changes` (used by the continuation view) surfaces a superseded record's bare value with no "no longer current" qualifier - this produced an observably confusing, backwards-sounding sentence in one real long-horizon run ("recently decided to keep" about a decision that had in fact just changed away from "keep"). Fixed by adding an explicit label at the Stage 4 rendering site (not by touching Stage 1/2's own `_summary`/`_recent_changes`, which remain unchanged and settled).

The review also ran adversarial extraction-prompt checks beyond the Living Room scenario (a server, a faucet, and three couch variants using hypothetical/third-party/conditional phrasing). The trust boundary held in every case - no non-committed statement ever reached current-truth status. The review did surface one **real, non-blocking, pre-existing Stage 2 limitation**, not introduced or worsened by Stage 4: `ProjectMemoryExtractionService.extract()` receives only the current message, with no visibility into already-known subject names, so the same real-world item referred to with different phrasing across turns ("the old server" vs. "the server") can be extracted under two different subject keys instead of one, leaving a stale record under the old key that never gets superseded. Stage 4's retrieval logic behaves correctly given whatever the store contains; this is an extraction-precision gap, not a retrieval or trust-boundary defect, and repairing it well requires passing bounded known-subject context into the extraction call - a scoped design change appropriately deferred to a dedicated follow-up rather than made during review. It did not affect the Living Room acceptance scenario, whose subject naming was consistent throughout.

All fixes were re-verified against the full regression suite (920 tests, zero failures) and a full re-run of the real-backend long-horizon E2E (still passes, with the Q1 "where did we leave off" answer now free of the backwards-sounding phrasing the labeling bug had caused).

### Confirmed Cleanup Decisions (2026-09-12)

- **Legacy memory manager** (`code/prototype_v1/memory_manager.py`, `results/session_memory.json`): confirmed still live via `watch_latest_image.py` (imports `save_observation`/`update_active_task`) and `context_aware_prompt.py` (imports `format_recent_memory`/`get_task_summary`), which are in turn invoked as a real subprocess from `api.py`'s legacy single-image `/analyze`-style endpoint (`WATCH_SCRIPT` at line ~2707). This is the original pre-Project glasses HUD guidance loop, not the ProjectConversation/Project Memory path - migrating it requires redesigning a still-functioning legacy feature's behavior, not a mechanical deletion. Per this document's own Legacy Components policy: **keep, do not expand, migrate only when that legacy endpoint is itself intentionally revisited.** Not removed in this pass.
- **`project_knowledge.py` (`ProjectKnowledgeReader`)**: inspected in full. It is a **read-only projection** over the same canonical stores everything else already uses (`ProjectActivityStore`, `CheckpointProposalStore`, Investigation session/evidence stores) - it owns no persistence and writes nothing. It already does real, correct provenance-respecting filtering (e.g. an AI-sourced Activity only counts as a "decision" if `confirmation_status == CONFIRMED`). It serves the Project Inspector/UI (Phase F1), a different consumer than the Context Retriever (which serves the model). Classification: **REUSE/EVOLVE** - not a competing knowledge system, and a reasonable existing foundation for part of the future Current Project State projection once Structured Project Memory exists. Not merged or deprecated now.
- **`Checkpoint`**: must not become a second, competing source of truth once Structured Project Memory (facts/decisions with supersession) is implemented. Recorded now, before implementation, per this document's own Architectural Risk #7 (duplicate sources of truth): `current_objective`/`next_action`/`blockers` are single-task-shaped fields and are the wrong shape for an accumulating set of independent Project constraints/decisions; the eventual direction is for Checkpoint's externally-visible behavior to become a **derived projection** over Structured Project Memory rather than a separately hand-maintained struct - not implemented in this pass, current Checkpoint behavior is preserved unchanged.
- **Context Retriever**: not redesigned in this pass. Confirmed, reproduced issues to carry into the correct future milestone (Stage 2/4 in `docs/ROADMAP.md`): the closed keyword-based question classifier has real, reproduced blind spots (a historical question with no keyword trigger word was misclassified in this week's experiments; the pre-existing product review independently found the same class of failure via a different example - "What did we discover about the capacitor?" scoring zero across all question classes); the `next_action`-classified-with-fallback rule returns zero supporting Activities by design, which is a defect, not a tuning gap; retrieval is bounded by a fixed recency window (last 5 Activities / 3 Investigations) reranked internally, not retrieval over full Project history.
- **Route file maintainability** (~3,600-line monolithic API route file, per the 2026-08-23 product review): recorded as debt, not addressed in this pass. Product usability work takes priority over this cosmetic/maintainability concern; scheduled loosely alongside Stage 4 (Real Conversation Integration) when the same file is next touched substantively, not as standalone cleanup work.

### Testing / Acceptance Philosophy

Five distinct tiers, not to be conflated with each other:

1. **Unit / deterministic tests** - prove implementation rules and invariants (e.g. supersession never mutates in place, eligibility filtering excludes non-committed modality). No provider calls.
2. **Fake-provider tests** - prove orchestration/routing logic in isolation from real model behavior.
3. **Real-provider tests** - prove actual model/tool-selection behavior (this week's experiments were entirely this tier: real `gpt-4.1-mini` calls, real extraction/classification/selection, no mocks).
4. **Realistic end-to-end** - proves product behavior across a real multi-turn scenario, not a single isolated call (see "Persistent Project Usability Acceptance" below).
5. **Physical phone/glasses** - proves device integration specifically; required only for interface-layer claims, never required to validate backend architecture changes.

"All automated tests passed" is never sufficient evidence that the user experience works - tier 4 (and, where the claim is interface-specific, tier 5) is required before any "usable" claim is made.

### Persistent Project Usability Acceptance ("Living Room Long-Horizon Acceptance")

The product must not be called usable merely because unit tests pass. This is the standing, reusable acceptance specification for that claim, superseding any single one-off dogfood run:

**Scenario**: a realistic Project (Living Room Redesign is the reference scenario, not the only permissible one) run across **20-30 natural turns spanning multiple sessions** (a genuine leave-and-return gap, not a single continuous conversation). The user, in natural, unscripted wording (never engineered around known routing/keyword rules):
- creates/selects the Project and attaches at least one real photograph;
- discusses goals naturally; states a budget; states an aesthetic preference; states a durability/pet constraint;
- makes at least one furniture/decision choice, then **changes that decision later** in the same or a later session;
- selects a specific option among several presented; reports completing real-world progress;
- asks natural follow-up questions;
- leaves the Project for a real gap, returns, and continues.

**At the end, the user must be able to naturally ask, and receive a trustworthy answer to, all of**: "Where did we leave off?"; "What was my budget?"; "What constraints did I give you?"; "What did we decide about [the changed item]?"; "Didn't we originally decide something different?"; "Why did we change it?"; "What have I already completed?"; "What should I do next?"; "What is still blocking me?"; "What did the room look like?"; a genuinely visual follow-up question about the room; and (implicitly, not necessarily asked in those words) correct use of original Evidence bytes if a question requires inspecting a visual detail the durable description doesn't cover.

**Success requires all of**: correct current facts; correct handling of the changed decision (new value wins, old value remains retrievable on request, never both presented as equally current); correct historical recall on request; no stale/tentative/third-party/hypothetical contamination of current-truth answers; a meaningful, non-empty current-Project-state answer; a genuinely useful (not generic) next action; real visual continuity; observably bounded context behavior (not a full-history dump); and no requirement that the user understand or work around internal memory mechanics to get a correct answer.

This specification does not itself constitute a passed acceptance run - it is the standing bar. It should be re-run as a tier-4 realistic E2E test at Stage 5 in `docs/ROADMAP.md`, and again after any material change to the memory/context path thereafter.
- docs/research/UNIVERSAL_PROJECT_WORKSPACE_V1_DESIGN.md is the Universal Project Workspace v1 design/gap-analysis/MVP plan (RESEARCH / RECOMMENDATIONS - HUMAN REVIEW REQUIRED for its MVP scoping and implementation sequencing); the underlying Workspace concept itself is approved architecture (ADR-046 through ADR-051 above), but the specific MVP boundary, milestone sequencing, and implementation choices in that document are audit output, not automatically approved roadmap.

### Stage 5 Dogfood Result: Realistic Usability Acceptance — USABLE WITH REQUIRED FIXES (2026-09-12/13)

A first genuine tier-4 run of the Persistent Project Usability Acceptance spec above, continuing a real pre-existing "Living Room Redesign Evaluation" Project whose early conversation predated Stage 2/3's existence - exactly the scenario this document's own Stage 4 review had already flagged as a latent risk ("no backfill for pre-existing Projects"). The dogfood run found this risk was worse than anticipated: it does not merely reduce capability, it produces **active fabrication and confident false denial**. Two BLOCKING findings, both reproduced with real persisted state, not just response text:

1. **Missing-memory fabrication**: asked "Didn't we originally say we were keeping the TV stand? Why did that change?" (a real decision reversal from the pre-Stage-2 era, so no structured memory record exists for it), `ProjectMemoryRetrievalService.select()` picked an unrelated known subject ("budget") as its best-effort answer instead of abstaining, and the assistant presented it as if it answered the question.
2. **Pre-Stage-3 Evidence false denial**: asked "What did the room look like in the photo I sent you originally?" (a real photo attached before Stage 3 existed, so it has no `visual_description`), the system concluded and stated "No photo was supplied originally" - inventing an absence rather than recognizing Evidence existed but its durable description did not.

The previously-documented subject-identity drift limitation (Stage 4 review, "the old server" vs "the server") also became user-visible in a related but distinct form: a natural progress correction ("I finished painting the wall" → "actually only halfway done") risked leaving two simultaneously-current, contradictory truths for the same real-world task rather than one coherent, superseded lineage.

Full dogfood findings, severity classification, and root-cause hypotheses were delivered as a standalone report (not persisted here); the three BLOCKING/HIGH items above were authorized for one bounded repair slice, documented next.

### Stage 5 Repair Slice: Missing-Memory Abstention, Historical Evidence Recognition, Subject-Identity Stabilization — IMPLEMENTED, NOT YET RE-DOGFOODED (2026-09-13)

Three targeted reliability fixes for the dogfood findings above, deliberately bounded: no Project-history backfill, no bulk Evidence description generation, no new canonical Subject entity/table, no scope taxonomy, no route refactors.

**Fix 1 - missing-memory abstention over fabrication**: `retrieve_memory_context()` now runs a deterministic, generic post-hoc **grounding check** (`_selection_is_grounded`) on every AI-selected subject before it is ever presented as evidence: the selection's subject keyword must actually appear in the current question text, or in something the user themselves said in the bounded recent conversation. An ungrounded selection (the exact "budget substituted for a TV stand question" failure) is discarded, and - for a question that reads as wanting Project history - replaced with an explicit, generic, reusable honesty notice (`NO_RELEVANT_MEMORY: ...this does NOT mean the Project definitely never contained this information...say you do not have enough durable Project history to verify this confidently, rather than guessing`) rather than silence, so the assistant is told to prefer honest uncertainty over invention. An ordinary question with no historical framing stays silent on abstention (no unnecessary notice noise).

The grounding check specifically excludes assistant-authored text from its "found in recent conversation" fallback, checking only the current question and the user's own recent turns. This was not incidental: an assistant recap/summary turn routinely lists several unrelated topics side by side ("...budget of $1,500... keeping the TV stand..."), and the first version of this check, which searched the full bounded recent-conversation text regardless of speaker, was proven - via live re-dogfooding of the exact same real Project - to let the identical "budget" misselection slip back through, grounded by nothing more than the assistant's own prior recap mentioning the word. Restricting the fallback to user-authored lines closed this, verified against the same live conversation afterward (selection now correctly discarded, `memory_retrieval_intent="not_found"`).

**Known residual limitation**: the grounding check governs the *structured-memory layer* only. When it correctly discards a selection and no other signal intervenes, the underlying conversational model still generates its own answer from the raw bounded conversation history it receives as normal chat context - and if that history already contains the model's own earlier wrong answer to the same question (as happened live, from repeated dogfood re-probing of the identical question), the model can reproduce that prior claim from simple self-consistency, independent of the memory layer entirely. This is a distinct failure surface from memory misattribution and was not in this slice's authorized scope (it would require changes to core reply-generation prompting, not the memory-retrieval seam); noted here for a future pass.

**Fix 2 - historical Evidence recognized, never denied**: `select_candidates()` in `visual_evidence.py` no longer excludes Evidence with no stored `visual_description` from the candidate pool - undescribed Evidence is now included (using a placeholder description string) and is never excluded by the existing scope-narrowing filter (which only applies to evidence that *has* a described scope). A deterministic override forces `tier="original_required"` whenever the selected candidate has no real description, regardless of what the selection model itself returned - defense-in-depth, not reliance on the model's own honesty. If nothing is confidently matched but Evidence genuinely exists, a new generic honesty notice (`_EVIDENCE_EXISTS_BUT_UNMATCHED_NOTICE`) tells the assistant Evidence exists but could not be confidently matched, and explicitly not to claim no photo was ever provided. Live re-verification against the real pre-Stage-3 photo in the dogfood Project: the assistant now correctly retrieves the original pixels and produces an accurate description of the actual room (previously: "No photo was supplied originally").

**Fix 3 - bounded known-subject hints for extraction (identity stabilization, not ontology design)**: `memory_retrieval.known_subject_hints()` returns a bounded (≤20), most-recent-first list of `(scope, subject, slot, current_value)` for existing CURRENT+COMMITTED records, passed into `ProjectMemoryExtractionService.extract()` and rendered into the extraction prompt as `scope/subject/slot: value` lines. The extraction system prompt was extended to reuse an existing subject's exact scope/subject/slot when a new statement is reasonably confidently about that SAME real-world item or task - explicitly not when it is merely the same general area or topic (a stated non-goal: forcing reuse would trade fabrication for a different kind of error, aggressive fuzzy merging). No new canonical entity system was introduced; this is a shortlist the model matches against, never a mandate.

The **slot** is included in the hint, not just scope/subject, and this was not incidental either: an earlier version of the hint carried only `(scope, subject, value)`, and a live re-dogfood run (a real "paint restocked, wall finished" progress update) showed the model correctly reusing the existing subject but inventing a *new* slot name for the update - leaving the item's original slot stuck at its stale value while the real update sat, unseen, under a slot nothing else reads. Concretely this manifested as a resolved `paint_purchase` blocker still showing in the global blockers list, and a wall-painting task showing "half done" and "finished" as simultaneously current. Including the slot in the hint and instructing the model to reuse it exactly fixed this in isolated verification and was then re-confirmed via a full end-to-end run of the required subject-drift acceptance script ("I finished painting the accent wall." → "Actually I only got halfway done..." → "The paint is back in stock and I finished the wall.") against a clean live Project: one consistent canonical subject throughout, correct final current state, full history preserved and inspectable.

**Known residual limitation**: subject-identity reuse is now reliable in testing; **slot** reuse compliance, while now explicitly instructed and verified as the common case, is a real-provider judgment call the model does not follow with absolute certainty on every call (observed once in ~10 real attempts during verification, always in the direction of a duplicate/stale-looking record under a second slot for the same subject - never data loss, never a fabricated claim). This is disclosed as a residual, inherent-to-LLM-judgment limitation, not a deterministic code defect, and not a violation of the fabrication/honesty safety bar this repair was scoped against (no information is destroyed or invented; the correct information exists, just organized under more than one slot until a future correction happens to land on the right one). A deterministic slot-consolidation safeguard was considered and deliberately not built in this slice, per the explicit "identity stabilization, not ontology design" scope boundary.

**A latent, unrelated schema gap was also found and fixed during real-provider regression testing**: `ProjectMemoryCandidate` (the pre-validation extraction output shape) had no rule preventing `progress_state` from being set together with a non-PROGRESS category, unlike `ProjectMemoryRecord`, which already enforces this. A real extraction call during Stage 4 long-horizon regression testing returned exactly this malformed shape (`category="fact"` with `progress_state="blocked"`), which was previously guaranteed to crash `ProjectMemoryStore.write_candidate` with an unhandled `ValidationError` rather than being safely discarded like any other malformed candidate. Fixed by adding the same shape validator `ProjectMemoryRecord` already had to `ProjectMemoryCandidate`, so a candidate like this is now caught and discarded at the existing "one malformed candidate must not drop the rest" boundary in `extract()`, exactly like a JSON-shape error already was.

**Testing**: 25 new deterministic/fake-provider tests across three new files (`test_stage5_repair_missing_memory.py`, `test_stage5_repair_visual_evidence.py`, `test_stage5_repair_subject_identity.py`), including 7 targeted real-provider calls proving cross-domain subject reuse (server, faucet) and that known-subject hints do not weaken tentative/third-party/ambiguous-reference abstention. Full repository regression suite (970 tests) passes; a small number of pre-existing real-provider E2E tests exhibit the same occasional pass-on-retry model-variance already documented in this file's Testing Philosophy section, unrelated to any of the three fixes. Live re-dogfooding against the same real pre-existing Living Room Project (not a synthetic replay) directly confirmed all three fixes against actual persisted state, not response text alone.

Per the repair's own explicit instruction, this fix is **not** a Stage 5 pass - it is ready for independent re-dogfooding against the standing Persistent Project Usability Acceptance bar above.

### Stage 5 Independent Re-Dogfood: three repairs held, one new HIGH finding (2026-09-13)

An independent acceptance pass (fresh clean Project, genuine leave/return via a real process restart, the old pre-Stage-3 Project reused only for the Evidence-compatibility check) confirmed all three repairs above hold under live, unscripted natural conversation: subject-identity lineage stayed coherent across a full done→half-done→blocked→resolved→finished progression (verified against persisted `/memory`), the missing-memory honesty behavior held for a genuinely undiscussed topic, and the pre-Stage-3 photo was correctly retrieved and described (including a specific follow-up detail question) with no false denial.

One new HIGH-severity, narrower issue was found: `Current Project State` correctly contained an active blocker, but the natural question "Is anything actually blocking me right now?" bypassed `is_continuation_question()` entirely, because that function matched a fixed list of literal phrase substrings and the inserted word "actually" broke the exact-match against `"is anything blocking"`. No current-state context was attached to that reply, and the model answered confidently and wrongly that nothing was blocking the user - directly contradicting the system's own correctly-derived state. This was the same general brittleness class as an earlier, already-patched gap ("what have I already completed?"), indicating the literal-substring approach does not generalize to natural rewording.

### Stage 5 Final Narrow Repair: token-sequence intent detection (2026-09-13)

`is_continuation_question()` and `is_historical_question()` no longer match literal phrase substrings. Both now tokenize the question and check for a small set of **order-preserving token-sequence patterns** (`_has_token_sequence`): each pattern is a short list of anchor words (2-4, occasionally an unambiguous single word like "blocking"/"originally"), and a pattern matches when its anchors appear anywhere in the question **in that relative order**, tolerating any amount of other text - including filler words like "actually"/"right now" - appearing before, between, or after them. Requiring order (not just co-occurrence) keeps this selective: a bare "what" or "did" is never sufficient alone, and none of it uses an AI call, embeddings, or a fuzzy-matching library - it is the same class of cheap deterministic gate this module already relies on everywhere else, just tolerant of natural insertion instead of requiring a contiguous literal phrase. Historical-intent detection was converted the same way, preserving it as a distinct intent from continuation (a historical question wants the past record and a change explanation; a continuation question wants current derived state) - not merged, and not made to over-fire on generic "what"/"did" questions.

Verified deterministically (`test_stage5_repair_intent_detection.py`, 22 tests: the required trigger list, the required non-trigger list, additional natural variants proving generalization rather than a second hand-tuned phrase list, and historical-intent coverage with the same filler-tolerance) and live: recreated the exact dogfood failure (a fresh Project with a real electrician/wiring blocker; "Is anything actually blocking me right now?" now correctly attaches Current Project State - `memory_retrieval_intent: "continuation"` - and the reply correctly names the real blocker) plus two additional natural phrasings not in the test list ("Am I stuck on anything at the moment?", "What's the current holdup with this project?"), which surfaced one more real synonym gap ("stuck"/"holdup") closed the same way. Full regression suite: 966 tests passing.

This closes the one HIGH finding from the independent re-dogfood. The three original repairs were not reopened or redesigned.

### Stage 5 Final Acceptance: PASS (2026-09-13)

A short, final product-acceptance pass - five targeted checks through the real application, no repairs performed during the pass - confirmed the repaired system is trustworthy in normal use:

1. **Blocker/continuation, fresh wording** ("Am I clear to keep moving forward, or is something in the way right now?") on a fresh Project with a genuine plumber-delay blocker: Current Project State was retrieved (`intent: "continuation"`) and the real blocker was correctly reported, consistent with `/memory/state`.
2. **Leave-off equivalent** ("Catch me up - what's the current status on all this?"): correct current progress and a useful next action, no stale work presented as current.
3. **Current-vs-historical decision** (a faucet keep→replace reversal): the current answer correctly said "replacing"; the historical answer correctly preserved the original "keep" decision and the real change reason ("it started leaking"), with no stale value presented as current.
4. **Missing-memory honesty** (a backsplash-tile question never discussed): no fabrication, no unrelated subject substituted, and the answer distinguished "not yet decided" from "definitely never happened."
5. **Visual Evidence** (a single natural question against the existing pre-Stage-3 photo Project): the original photo was correctly retrieved (`tier: "original_required"`) and accurately described.

All five passed. Stage 5 is marked **COMPLETE / PASSED** in `docs/ROADMAP.md`. Not yet committed as of this writing - see that document's git-boundary notes.
