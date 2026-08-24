---
name: custom-meta-ai-glasses-explore-architect
description: "Translate ADR-057 into an implementation-ready, provider-neutral EXPLORE contract for Custom Meta AI Glasses. Strictly read-only; use before authorizing the first generalized Project Interaction milestone."
---

# Custom Meta AI Glasses Explore Architect

Define the smallest backend-first Room Redesign `EXPLORE` contract without implementing it.

## Authority and boundaries

- Read `AGENTS.md`, `docs/PROJECT_INTERACTION_FOUNDATION.md`, `docs/PROJECT_MEMORY_ARCHITECTURE.md`, `docs/ROADMAP.md`, and `docs/project_constitution.md`, then inspect relevant current models, stores, retrieval, Ideas, Proposals, and tests.
- Remain strictly read-only. Do not edit, stage, commit, push, mutate Project data, or invoke Development.
- Require explicit `project_id`; interaction execution must not change Active Project.
- Reuse Activity/Idea/Proposal/Checkpoint persistence. Do not create an Interaction store, Ideas store, workflow engine, or Investigation wrapper.
- Exclude Research, Compare, Guide, Plan, media, clients, and glasses implementation.

## Contract design

Specify:

- endpoint and application-service boundary;
- strict request schema and Project-owned input references;
- server-generated `interaction_id` and client idempotency identity;
- one deterministic, interpretable Context Pack contract;
- one provider-neutral execution call;
- strict `OPTION_SET | INFORMATION_REQUEST` result boundary;
- deterministic ordered AI/inferred Idea projections;
- linked source/provenance metadata within existing bounds;
- retry and concurrent same-key convergence;
- failure before provider completion, before first projection, and during multi-Idea projection;
- reconstruction after ambiguous response/restart;
- cross-Project ownership rejection and unchanged Active Project.

Do not solve concurrency or mid-write failure by casually adding a store. State the smallest serialization/convergence mechanism that existing project-scoped persistence can support, and surface any unresolved atomicity decision for human/Architecture Guardian review.

## Report

Return:

# EXPLORE CONTRACT
# REQUEST / ENDPOINT
# CONTEXT RETRIEVAL
# PROVIDER BOUNDARY
# RESULT / IDEA PROJECTION
# IDEMPOTENCY / CONCURRENCY
# FAILURE / RECOVERY
# PROJECT ISOLATION
# ACCEPTANCE-TEST MATRIX
# RISKS / OPEN DECISIONS
# IMPLEMENTATION-READY BATCH INPUT
