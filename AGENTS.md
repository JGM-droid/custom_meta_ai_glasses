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
- docs/research/MULTI_AGENT_PRODUCT_REVIEW.md (structured product/architecture review; RESEARCH / RECOMMENDATIONS - HUMAN REVIEW REQUIRED, not architecture authority)

## Documentation Governance

Conversation memory (this chat, a Claude/Codex/Copilot session, etc.) is useful for continuity but is NOT this project's architectural source of truth. Once a meaningful product/architecture decision has been researched, reviewed, and approved, it must eventually be represented in repository documentation and Git history - a future agent should be able to reconstruct the important product direction from the repository alone, without access to the conversation that produced it.

When writing or reading architecture documentation, keep these four categories distinct and never blur them:

- LOCKED ARCHITECTURE: rules implementations must obey (see the Architecture Decision Log in docs/PROJECT_MEMORY_ARCHITECTURE.md).
- CURRENT IMPLEMENTATION: what actually exists and has been validated (see "Implemented" Phase/Slice entries).
- APPROVED ROADMAP: agreed future direction that is NOT yet implemented (see "Approved Roadmap" sections and ADRs marked "Research-Informed Roadmap").
- RESEARCH / PROPOSALS: ideas/recommendations that have NOT yet been approved (e.g. docs/research/*.md). These must never silently become LOCKED ARCHITECTURE or APPROVED ROADMAP just by being written down - a human approval step is required first.

Multi-agent/multi-perspective review (deliberately different mandates, not the same question asked six times) is an approved development/review practice for high-value decisions, not a product feature. Reviewer/agent conclusions are proposals/research input; they are never automatically architecture.

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
