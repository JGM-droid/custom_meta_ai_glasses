# Project Memory Architecture

Status: Authoritative for approved forward product architecture.

Last Updated: 2026-08-22

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

## Relationship to Other Documents

- docs/PROJECT_MEMORY_ARCHITECTURE.md is authoritative for approved forward product architecture.
- docs/runtime_governance.md remains authoritative for runtime execution/startup ownership.
- docs/investigation_session_api_v1.md remains authoritative for current Investigation Session API contract.
- architecture/Phase2_System_Design.md remains valuable as Investigation subsystem design history and implementation reference.
- docs/research/PERSISTENT_PROJECT_MEMORY_REFERENCES.md is supporting external research evidence and does not override architecture authority.
