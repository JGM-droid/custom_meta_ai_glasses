# Persistent Project Memory References

Status: Supporting research evidence only.

Purpose:
- Preserve external architecture research that informed Project Memory decisions.
- Help future Copilot sessions/agents understand why specific architecture choices were made.
- Provide revisit points for later phases without changing current authority boundaries.

Non-authority note:
- This document does not define architecture authority.
- Canonical authority remains docs/PROJECT_MEMORY_ARCHITECTURE.md.

Authority hierarchy reminder:
- AGENTS.md
- docs/PROJECT_MEMORY_ARCHITECTURE.md
- current phase implementation contract
- research/historical references (including this file)

## LightMem-Ego

Project/repository name:
- LightMem-Ego

Official repository/project URL:
- https://github.com/Wang-ML-Lab/LightMem

Problem the system is solving:
- Efficiently ingesting and organizing large ego-centric multimodal streams into usable memory for reasoning.

Relevant architectural concepts:
- Separation of ingestion from memory processing.
- Layered memory organization (current/short-term/long-term).
- Refinement and consolidation stages before retrieval.
- Retrieval packaging that prepares evidence for downstream reasoning.

What we want to borrow:
- Clear separation of concerns between ingestion, memory construction, retrieval, and reasoning.
- Layered-memory model for future glasses/video ingestion.
- Consolidation patterns that prevent raw-stream overload.

What we explicitly do NOT want to copy yet:
- Heavy worker pipelines.
- GPU-dependent indexing infrastructure.
- Large-scale indexing/serving complexity for early phases.

How it relates to Custom Meta AI Glasses / Persistent AI Project Assistant:
- Strong conceptual reference for future wearable evidence ingestion and memory layering.
- Supports our decision to keep application-owned project memory separate from model reasoning calls.

Which future phase should reconsider the concept:
- Phase C and Phase D for memory-layer implementation and investigation-to-project evidence integration.

## EgoLife / EgoRAG

Project/repository name:
- EgoLife / EgoRAG research direction

Official repository/project URL:
- https://github.com/EgoLifeAI/EgoLife

Problem the system is solving:
- Long-horizon personal/ego-centric memory retrieval where recency, hierarchy, and temporal relevance matter.

Relevant architectural concepts:
- Hierarchical memory abstraction.
- Timestamp-aware retrieval.
- Retrieval focused on useful summaries over raw history dumps.

What we want to borrow:
- Hierarchical memory progression:
  - raw evidence/activity
  - structured observations/activity
  - checkpoint
  - project summary
- Checkpoint-first retrieval for common resume questions.

What we explicitly do NOT want to copy yet:
- Full retrieval stack reproduction.
- Complex ranking/orchestration components before baseline deterministic retrieval is proven insufficient.

How it relates to Custom Meta AI Glasses / Persistent AI Project Assistant:
- Directly informs project resume behavior and selective context construction.
- Reinforces that most "where did we leave off" requests should resolve from checkpoint data first.

Which future phase should reconsider the concept:
- Phase C for hierarchical activity/checkpoint structure and Phase E for more advanced retrieval expansion.

## Mem0

Project/repository name:
- Mem0

Official repository/project URL:
- https://github.com/mem0ai/mem0

Problem the system is solving:
- Agent memory management where memory writing and memory retrieval must be handled as distinct capabilities.

Relevant architectural concepts:
- Distinct write path and retrieval path.
- Selective retrieval instead of repeatedly providing full history.
- Multiple retrieval modes (semantic, keyword, entity, temporal).

What we want to borrow:
- Explicit design rule: memory WRITE and memory RETRIEVAL are different operations.
- Selective retrieval as the default strategy.
- Future optional retrieval modes if deterministic retrieval becomes insufficient.

What we explicitly do NOT want to copy yet:
- Immediate vector-retrieval adoption.
- Any advanced retrieval infrastructure introduced only because Mem0 supports it.

How it relates to Custom Meta AI Glasses / Persistent AI Project Assistant:
- Supports clean boundaries between project-state persistence and context retrieval logic.
- Aligns with checkpoint-first resume flow and minimal-context prompt assembly.

Which future phase should reconsider the concept:
- Phase E (or later) if deterministic retrieval metrics show insufficiency.

## Graphiti

Project/repository name:
- Graphiti

Official repository/project URL:
- https://github.com/getzep/graphiti

Problem the system is solving:
- Long-term memory with provenance and temporal relationships across entities, episodes, and derived facts.

Relevant architectural concepts:
- Temporal and provenance-aware memory representation.
- Distinction among entities, relationships/facts, episodes/source evidence, and derived conclusions.

What we want to borrow:
- Provenance discipline: evidence must remain distinguishable from inference.
- Explicit temporal/context lineage for future higher-trust memory.

What we explicitly do NOT want to copy yet:
- No Neo4j adoption now.
- No FalkorDB adoption now.
- No Kuzu or alternate graph database adoption now.
- No graph infrastructure introduction before proven need.

How it relates to Custom Meta AI Glasses / Persistent AI Project Assistant:
- Reinforces our requirement that AI inference must not silently become project fact.
- Useful for future provenance-rich project activities and investigation evidence traceability.

Which future phase should reconsider the concept:
- Phase E or later, after deterministic checkpoint/activity retrieval baselines are measured.

## LangGraph Persistence / Checkpoints

Project/repository name:
- LangGraph (checkpoint and persistence concepts)

Official repository/project URL:
- https://github.com/langchain-ai/langgraph

Problem the system is solving:
- Durable state/checkpoints for long-running agent workflows with explicit identity and resumability.

Relevant architectural concepts:
- Durable checkpoints tied to explicit identities.
- Resume semantics from durable state snapshots.

What we want to borrow:
- Checkpoint semantics as inspiration for project stop/resume continuity.
- Durable identity-first continuity model.

What we explicitly do NOT want to copy yet:
- Do not introduce LangGraph merely to implement Project Memory.
- Do not add framework-level dependency without a demonstrated gap in our simpler architecture.

How it relates to Custom Meta AI Glasses / Persistent AI Project Assistant:
- Our Project checkpoint serves a similar conceptual purpose and should remain application-owned.
- Validates resume-from-checkpoint UX without requiring orchestration-framework adoption.

Which future phase should reconsider the concept:
- Phase C when checkpoint mutation and resume semantics are expanded.

## VisionClaw

Project/repository name:
- VisionClaw

Official repository/project URL:
- https://github.com/VisionClaw/VisionClaw

Problem the system is solving:
- Wearable/egocentric vision pipelines that integrate multimodal perception with model-driven interpretation.

Relevant architectural concepts:
- Glasses/camera ingestion to multimodal model pipelines.
- Streaming or near-streaming perception patterns.

What we want to borrow:
- Practical perspective that glasses -> multimodal reasoning is becoming baseline infrastructure.
- Ingestion and perception patterns that can inform future evidence capture workflows.

What we explicitly do NOT want to copy yet:
- Do not center architecture only on camera-to-LLM throughput.
- Do not let wearable ingestion displace project continuity requirements.

How it relates to Custom Meta AI Glasses / Persistent AI Project Assistant:
- Confirms glasses remain important interface and evidence input.
- Reinforces that platform differentiator is persistent project continuity, not only perception throughput.

Which future phase should reconsider the concept:
- Phase D for deeper project + investigation + wearable ingestion integration.

## MEMENTO / Hierarchical-Memory Research

Project/repository name:
- MEMENTO and related hierarchical-memory research

Official repository/project URL:
- https://arxiv.org/abs/2402.09408

Problem the system is solving:
- Agent-memory overload where too much undifferentiated memory degrades reasoning quality.

Relevant architectural concepts:
- Hierarchical memory representations.
- Compression and summarization boundaries.
- Selective retrieval to reduce cognitive/context overload.

What we want to borrow:
- Strong warning that more stored memory does not imply more context should be sent to AI.
- Hierarchical/selective memory strategy to protect reasoning quality.

What we explicitly do NOT want to copy yet:
- No premature adoption of large, complex memory compression/retrieval pipelines before baseline measurement.

How it relates to Custom Meta AI Glasses / Persistent AI Project Assistant:
- Reinforces checkpoint-first resume and selective evidence expansion.
- Supports bounded context assembly as a quality and cost control.

Which future phase should reconsider the concept:
- Phase C and Phase E when hierarchical retrieval and summarization policies mature.

## Cross-Project Research Conclusions

1. Application-owned Project state remains authoritative.
2. Project identity is the primary namespace/isolation boundary.
3. Investigation Sessions become bounded activities/evidence sources inside Projects.
4. Memory construction, persistence, retrieval, and reasoning should remain separable concerns.
5. Hierarchical memory should eventually prevent raw-history overload.
6. Checkpoints are the first retrieval layer for project resumption.
7. Evidence provenance must prevent AI inference from silently becoming fact.
8. Advanced semantic/vector/graph retrieval should be introduced only when simple deterministic retrieval becomes insufficient.
9. Glasses ingestion and multimodal reasoning remain important, but Project continuity is the platform-level differentiator.
10. Cross-project contamination is a more serious architectural failure than imperfect semantic retrieval.

11. Durable structured knowledge plus a map/index plus selective retrieval is preferable to repeatedly sending the entire knowledge corpus to an AI.

Supporting inspiration note:

- Clief Notes is a useful pattern reference for the idea above, but it is inspiration only and not an implementation dependency.

## Revisit Triggers

Revisit these references when any of the following occur:
- Deterministic checkpoint/activity retrieval no longer answers resume questions with acceptable precision.
- Cross-project isolation remains correct, but retrieval relevance degrades under project growth.
- Evidence provenance disputes appear in review or incident analysis.
- Investigation-to-project linking requires richer temporal/entity reasoning.
- Measured product goals require memory retrieval sophistication beyond current deterministic methods.
