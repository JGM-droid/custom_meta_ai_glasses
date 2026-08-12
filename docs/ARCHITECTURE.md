# Architecture

## Authority and Scope

This document summarizes architecture in three categories:

- legacy/historical architecture,
- currently implemented architecture,
- approved future architecture.

Forward product architecture authority is:

- docs/PROJECT_MEMORY_ARCHITECTURE.md

Runtime/startup ownership authority remains:

- docs/runtime_governance.md

Investigation API contract authority remains:

- docs/investigation_session_api_v1.md

## Legacy Architecture (Historical)

Early prototype flow emphasized screenshot-to-guidance with global session memory:

```text
Screenshot Input
    |
    v
Image Analysis
    |
    v
Task Continuity
    |
    v
Global Session Memory (legacy)
    |
    v
Dashboard / Glasses Guidance
```

Legacy components preserved for compatibility/reference:

- code/prototype_v1/memory_manager.py
- code/prototype_v1/results/session_memory.json

Important status:

- This legacy global-memory pattern is not the approved foundation for Project Memory.

## Currently Implemented Architecture (Investigation Subsystem)

### Phase 1C retained-result architecture

```text
POST /investigations/analyze
  |
  v
Context + one OpenAI multimodal request
  |
  v
Canonical Retained Investigation
  |
  +--> Desktop projection endpoint
  +--> Glasses projection endpoint
```

### Phase 2A/2B/2C session-centric architecture

```text
POST /investigation-sessions
POST /investigation-sessions/{session_id}/evidence/image
POST /investigation-sessions/{session_id}/evidence/audio
POST /investigation-sessions/{session_id}/analyze
GET  /investigation-sessions/{session_id}/poll
        |
        v
Investigation session lifecycle + evidence store + orchestrator
        |
        v
Filesystem persistence under results/investigation_sessions/
```

Implemented invariants preserved:

- explicit UUID identities,
- server-owned evidence identities and sequencing,
- atomic persistence,
- optimistic revision protection,
- frozen evidence manifests,
- attempt ownership,
- canonical retained results,
- provider abstraction,
- compatible existing Investigation endpoints and projections.

## Approved Future Architecture (Product Pivot)

The approved product direction is a project-aware persistent AI assistant where Investigation remains a subsystem.

Conceptual direction:

```text
Interfaces (glasses, desktop, phone, voice)
    |
    v
Project Manager
    |
    v
Project-scoped memory + checkpoint + activities + evidence
    |
    v
Selective Context Retriever
    |
    v
AI reasoning / Investigation orchestration
```

Key principle:

- Application-owned state is authoritative.
- LLM reasoning is applied to selected state.
- LLM conversation is not canonical project memory.

## Project vs Investigation

- Project: long-lived container for continuity and isolation.
- Investigation Session: bounded activity that may occur inside a project.

Project is not equal to Investigation Session.

## Contradiction Guardrails

When planning architecture or memory changes:

1. Read docs/PROJECT_MEMORY_ARCHITECTURE.md first.
2. Preserve working Investigation behavior unless architecture decisions are intentionally changed.
3. Do not expand legacy global session memory as new project memory.

## Historical Notes Kept Intentionally

Historical sections and repository artifacts describing glasses-first exploration are retained for research lineage and release history. They do not override the approved forward architecture.
