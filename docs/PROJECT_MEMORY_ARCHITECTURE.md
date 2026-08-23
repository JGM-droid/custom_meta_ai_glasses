# Project Memory Architecture

Status: Authoritative for approved forward product architecture.

Last Updated: 2026-08-23

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
Approved future milestone: a Glasses Project Navigator / Hands-Free Project Controller on the Meta Ray-Ban Display, using Neural Band navigation/select to browse and open Projects and drive a capture -> speak context -> analyze -> finding/next-action -> Continue/Correct/More-Evidence loop, so glasses interaction feels like a hands-free Project controller rather than passive AI-answer display. A Project selected/opened through glasses supplies explicit Project context/`project_id` to capture and Investigation, following the same ADR-037/ADR-038 explicit-Project -> Active-Project-fallback -> unscoped precedence; opening/selecting a Project on glasses remains distinct from changing the global Active Project unless explicitly requested. No separate glasses memory is permitted - all clients (glasses, phone, desktop/web) operate over the same application-owned Project Memory, with responsibilities split as: glasses+Neural Band for the immediate hands-free action loop, phone for richer field workspace/control, desktop/web for deep Project workspace (timeline, history, evidence, files, detailed AI results, Project management, coding/action prompts). A dedicated Meta SDK capability spike (Ray-Ban Display UI/text capabilities, available controls/buttons, Neural Band navigation/select behavior, gesture callbacks, Project navigation feasibility, capture integration, and whether programmable haptic output is actually exposed) is required before implementation begins; do not architect around arbitrary programmable Neural Band haptic patterns until SDK support is proven. Builds on existing capability research in `research/display_capabilities.md`, `research/meta_glasses_capabilities.md`, and `research_agent/display_sdk_integration_findings.md`.

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

## Approved Roadmap - Research-Informed Extensions

Status: APPROVED ROADMAP. None of the items in this section are implemented. They extend existing architecture and must not be read as competing/replacement definitions of it. Each item is backed by an ADR above (ADR-040 through ADR-051); this section is a readable index, not additional authority beyond those ADRs.

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

- Approved future milestone, not yet implemented: use the Meta Ray-Ban Display + Neural Band as a hands-free Project controller (select Project -> Project-scoped capture -> speak context -> analyze -> concise finding/next action -> Continue/Correct/More Evidence/Help/Done -> continue working), not passive AI-answer display.
- Project selection on glasses follows the same ADR-037/ADR-038 precedence and must not silently change the global Active Project.
- No separate glasses memory: glasses, phone, and desktop/web all operate over the same application-owned Project Memory. Approximate responsibilities: glasses+Neural Band = immediate hands-free action loop; phone = richer field workspace/control/review/capture; desktop/web = deep Project workspace (timeline, history, evidence, files, detailed AI results, Project management, coding/action prompts).
- Hard prerequisite: a dedicated Meta SDK capability spike (Display UI/text capabilities, available controls, Neural Band navigation/select behavior, gesture callbacks, Project navigation feasibility, capture integration, and whether programmable haptic output is actually exposed) must be performed with the then-current SDK before implementation begins. Do not architect around arbitrary programmable Neural Band haptic patterns until SDK support is proven. See `research/display_capabilities.md`, `research/meta_glasses_capabilities.md`, and `research_agent/display_sdk_integration_findings.md` for existing capability research this spike should build on.

### Multi-agent methodology - development/review practice, not product architecture

Multi-agent/multi-perspective review (distinct mandates, deliberate disagreement, independent-then-synthesized conclusions) is approved as a development and architecture-review practice for high-value decisions - see `docs/research/MULTI_AGENT_PRODUCT_REVIEW.md` for the first application of this practice. It is explicitly NOT an approved product feature: a multi-agent swarm (Project Memory -> specialized Context Packs -> multiple agents/providers -> synthesis -> proposed Project update) remains a research/product possibility only, not implementation work, and would require its own future architecture decision before any implementation. Reviewer/agent conclusions are proposals/research input, never automatically architecture.

## Relationship to Other Documents

- docs/PROJECT_MEMORY_ARCHITECTURE.md is authoritative for approved forward product architecture.
- docs/runtime_governance.md remains authoritative for runtime execution/startup ownership.
- docs/investigation_session_api_v1.md remains authoritative for current Investigation Session API contract.
- architecture/Phase2_System_Design.md remains valuable as Investigation subsystem design history and implementation reference.
- docs/research/PERSISTENT_PROJECT_MEMORY_REFERENCES.md is supporting external research evidence and does not override architecture authority.
- docs/research/MULTI_AGENT_PRODUCT_REVIEW.md is a structured product/architecture review (RESEARCH / RECOMMENDATIONS - HUMAN REVIEW REQUIRED); it does not override architecture authority, and its recommendations are not automatically approved architecture or roadmap.
- docs/research/UNIVERSAL_PROJECT_WORKSPACE_V1_DESIGN.md is the Universal Project Workspace v1 design/gap-analysis/MVP plan (RESEARCH / RECOMMENDATIONS - HUMAN REVIEW REQUIRED for its MVP scoping and implementation sequencing); the underlying Workspace concept itself is approved architecture (ADR-046 through ADR-051 above), but the specific MVP boundary, milestone sequencing, and implementation choices in that document are audit output, not automatically approved roadmap.
