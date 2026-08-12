# Custom Meta AI Glasses - Agent Guidance

## Instruction Hierarchy

1. Repository safety and runtime governance constraints.
2. Product architecture authority: docs/PROJECT_MEMORY_ARCHITECTURE.md.
3. Current phase implementation contract and tests.
4. Historical reference documents.

Before making architecture changes, memory changes, Investigation changes, project-state changes, or context-retrieval changes, read docs/PROJECT_MEMORY_ARCHITECTURE.md.

If an implementation task conflicts with docs/PROJECT_MEMORY_ARCHITECTURE.md:

1. Stop.
2. Describe the conflict and why a change may be required.
3. Update architecture decisions intentionally before implementation drift.

Recommended supporting architecture research reading:
- docs/research/PERSISTENT_PROJECT_MEMORY_REFERENCES.md (supporting evidence only; not architecture authority)

## Product Direction (Approved)

The product direction is now a project-aware persistent AI assistant.

- Glasses remain an important interface and evidence source.
- Glasses are not the sole architectural center.
- Persistent project continuity and project isolation are first-class requirements.

## Investigation Subsystem Status

The Investigation subsystem remains active and must be preserved:

- FastAPI backend and existing investigation APIs.
- Session lifecycle, evidence storage, orchestration, and retained results.
- Desktop and glasses projections.
- Backward compatibility guarantees already in place.

Investigation architecture is an important pattern source for upcoming Project Memory design, but Project Memory should reuse principles before reusing implementation classes.

## Legacy Memory Warning

code/prototype_v1/memory_manager.py and results/session_memory.json are legacy prototype memory and not the foundation of the approved Project Memory architecture.

- Keep for compatibility until migration is intentionally planned.
- Do not expand legacy global-memory patterns for new project-memory features.

## Existing Runtime/Signal Context

Signals currently available:

- Active file
- Language
- Dirty state
- Git state
- Terminal errors
- Coding session snapshot

Current architecture relationships in the implemented guidance pipeline:

- active_editor_context.py -> context_fusion.py
- context_fusion.py -> glasses_demo.py
- glasses_demo.py -> resume_now.json
- resume_now.json -> FastAPI
- FastAPI -> glasses_display_mock.html

These relationships are still valid for current runtime behavior, while forward product architecture is governed by docs/PROJECT_MEMORY_ARCHITECTURE.md.
