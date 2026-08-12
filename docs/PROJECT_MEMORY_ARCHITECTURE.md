# Project Memory Architecture

Status: Authoritative for approved forward product architecture.

Last Updated: 2026-08-12

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
- Context retrieval becomes explicit and selective per project/task.

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

- Do not send full history by default.
- Use checkpoint-level context for common continuity questions.
- Retrieve deeper evidence only when needed.

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

Later phases may include richer evidence, provenance, selective retrieval, possible semantic retrieval, dashboarding, voice/project switching, automatic project suggestions, guided walkthroughs, and potential storage upgrades if justified.

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
- No Investigation session ownership by project yet.
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

## Relationship to Other Documents

- docs/PROJECT_MEMORY_ARCHITECTURE.md is authoritative for approved forward product architecture.
- docs/runtime_governance.md remains authoritative for runtime execution/startup ownership.
- docs/investigation_session_api_v1.md remains authoritative for current Investigation Session API contract.
- architecture/Phase2_System_Design.md remains valuable as Investigation subsystem design history and implementation reference.
- docs/research/PERSISTENT_PROJECT_MEMORY_REFERENCES.md is supporting external research evidence and does not override architecture authority.
