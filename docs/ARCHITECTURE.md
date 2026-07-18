# Architecture

## System Overview

This repository implements a local-first, workflow-aware AI assistant prototype. The system processes screenshots, infers workflow state, and writes structured output that can be consumed by scripts and dashboard views.

The architecture emphasizes continuity across runs rather than isolated single-prompt responses.

## Architecture Diagram

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
Session Memory
    |
    v
Progress Tracking
    |
    v
Stuck Detection
    |
    v
Resume Previous Task
    |
    v
Smart Intervention
    |
    v
Metrics Snapshot
  |
  v
Dashboard / Glasses Guidance
```

## Phase 1C Completed Architecture

```text
Meta Ray-Ban Display Glasses
  |
  | Capture ordered investigation images
  v
POST /investigations/analyze
  |
  | Single OpenAI multimodal request
  v
Context Engine
  |
  v
Canonical Retained Investigation
  |
  |--------------|
  |              |
  v              v
Desktop Projection   Glasses Projection
  |              |
GET /investigations/latest
GET /investigations/latest/glasses
```

- Only one OpenAI request occurs during investigation analysis.
- The retained investigation is the canonical source of truth.
- Desktop and glasses responses are projections of the same retained result.
- Retrieval endpoints do not invoke OpenAI.
- Atomic persistence protects the retained investigation from partial writes.

## Phase 2A Implemented Architecture

```text
POST /investigation-sessions
GET /investigation-sessions/{session_id}
POST /investigation-sessions/{session_id}/pause
POST /investigation-sessions/{session_id}/resume
POST /investigation-sessions/{session_id}/cancel
        |
        v
InvestigationSession lifecycle state machine
  states: created, collecting, paused, cancelled
        |
        v
Filesystem session store
  code/prototype_v1/results/investigation_sessions/
  - sessions/
  - corrupt/
  - archive/
  - temp/
```

- Phase 2A session endpoints perform zero OpenAI calls.
- Phase 2A session endpoints perform zero Context Engine calls.
- Session persistence uses one JSON file per session with atomic replace semantics.
- Session mutation supports optional optimistic concurrency via expected_revision.
- Authentication reuses the existing optional GLASSES_API_TOKEN behavior.
- Phase 2B evidence storage is implemented as a separate per-session evidence workspace under code/prototype_v1/results/investigation_sessions/<session_id>/evidence/.
- Evidence uploads use server-managed sequence numbers, hard delete, quarantine for malformed records, and zero OpenAI / zero Context Engine execution.
- Session metadata ownership remains with the Phase 2A session store.

## Component Descriptions

- Pipeline entrypoint: [code/prototype_v1/watch_latest_image.py](code/prototype_v1/watch_latest_image.py)
  - Accepts an image path.
  - Builds prompt context.
  - Calls model inference.
  - Persists outputs.

- Prompt builder: [code/prototype_v1/context_aware_prompt.py](code/prototype_v1/context_aware_prompt.py)
  - Defines structured response expectations.
  - Encourages continuity-oriented guidance.

- Output and state logic: [code/prototype_v1/fix_writer.py](code/prototype_v1/fix_writer.py)
  - Parses structured sections from model text.
  - Builds task continuity, progress, stuck, resume, intervention, and metrics fields.
  - Writes [code/prototype_v1/results/latest_response.json](code/prototype_v1/results/latest_response.json).

- Session memory manager: [code/prototype_v1/memory_manager.py](code/prototype_v1/memory_manager.py)
  - Persists observations and active task state.
  - Maintains [code/prototype_v1/results/session_memory.json](code/prototype_v1/results/session_memory.json).

- API surface: [code/prototype_v1/api.py](code/prototype_v1/api.py)
  - Exposes analyze and latest-state endpoints for dashboard use.

- Dashboard: [code/prototype_v1/dashboard.html](code/prototype_v1/dashboard.html)
  - Renders structured fields, metrics snapshot, and demo-oriented summaries.

- Demo runner: [code/prototype_v1/demo_scenario.py](code/prototype_v1/demo_scenario.py)
  - Executes a repeatable recruiter scenario.
  - Prints stage-by-stage summaries from latest response output.

## Data Flow Walkthrough

1. A screenshot path is provided to [code/prototype_v1/watch_latest_image.py](code/prototype_v1/watch_latest_image.py).
2. The script invokes model analysis with structured workflow instructions.
3. Parsed fields are assembled and persisted by [code/prototype_v1/fix_writer.py](code/prototype_v1/fix_writer.py).
4. Observation history and active task data are updated in [code/prototype_v1/results/session_memory.json](code/prototype_v1/results/session_memory.json).
5. The latest structured payload is written to [code/prototype_v1/results/latest_response.json](code/prototype_v1/results/latest_response.json).
6. Dashboard and demo scripts consume the latest payload for presentation and validation.

## Session Memory Design

- Storage model: file-based JSON in [code/prototype_v1/results/session_memory.json](code/prototype_v1/results/session_memory.json).
- Main responsibilities:
  - Track observations over sequential runs.
  - Persist active task context.
- Design tradeoff:
  - Simple and transparent for prototyping.
  - Not optimized for multi-user or high-volume concurrent writes.

## Progress Tracking Design

- Output field: task_progress in [code/prototype_v1/results/latest_response.json](code/prototype_v1/results/latest_response.json).
- Contains:
  - completed_steps
  - next_step
  - step_count
- Source:
  - Structured extraction of response text sections and labeled fields.

## Stuck Detection Design

- Output field: stuck_status in [code/prototype_v1/results/latest_response.json](code/prototype_v1/results/latest_response.json).
- Heuristic:
  - Compares current task + next-step patterns against recent observations.
  - Flags repetition as a stalled-progress signal.
- Scope:
  - Lightweight heuristic for demo and prototyping.
  - Not a probabilistic classifier.

## Resume Previous Task Design

- Output field: resume_previous_task in [code/prototype_v1/results/latest_response.json](code/prototype_v1/results/latest_response.json).
- Behavior:
  - Uses active task and matching prior observations.
  - Surfaces available resume context, completed steps, and next step.

## Intervention Design

- Output field: intervention in [code/prototype_v1/results/latest_response.json](code/prototype_v1/results/latest_response.json).
- Behavior:
  - Generates concise intervention guidance when stuck signals are present.
  - Falls back to continue-current-step guidance when no intervention is recommended.

## Metrics Snapshot Design

- Output field: metrics_snapshot in [code/prototype_v1/results/latest_response.json](code/prototype_v1/results/latest_response.json).
- Current values summarize recent behavior:
  - recent_observation_count
  - stuck_count
  - intervention_count
  - latest_task_continuity
  - latest_step_count
- Purpose:
  - Lightweight visibility into recent assistant behavior for demos and iteration.

## Current Limitations

- File-based memory is single-node and prototype-oriented.
- Behavior quality depends on screenshot clarity and prompt/model responses.
- Stuck and continuity logic are heuristic and may need tuning for broader domains.
- Validation is mostly smoke-test style rather than benchmark-driven.

## Future Roadmap

- Voice readout for hands-free assistance.
- Hosted glasses web app delivery path.
- Meta Ray-Ban Display integration exploration.
- Expanded evaluation harness for scenario-level quality tracking.
