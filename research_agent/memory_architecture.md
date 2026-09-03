# Memory Architecture Research for Multimodal AI Assistants

## Scope

This document focuses on practical memory design for multimodal assistants, with emphasis on:

- Long-term memory
- Session memory
- Task continuity
- Agent memory
- Visual memory
- Open-source implementations

## System Survey

### 1) Mem0

**What it is:** A memory layer focused on extracting, storing, and retrieving useful user/context facts over time.  
**Strengths:**
- Strong long-term memory abstraction for assistants
- Structured memory extraction patterns
- Useful retrieval APIs for personalization and continuity
**Tradeoffs:**
- Requires careful memory quality control (what gets stored vs ignored)
- Needs explicit privacy/retention policies

### 2) LangGraph Memory

**What it is:** Graph-based agent orchestration with checkpointing and state persistence.  
**Strengths:**
- Strong session/task continuity through graph state
- Checkpoint-based recovery and resumability
- Clear fit for multi-step agent workflows
**Tradeoffs:**
- Architecture complexity increases with larger graphs
- Needs deliberate schema design for long-lived state

### 3) OpenAI Memory Patterns (implementation patterns)

**Typical patterns:**
- Short-term context window + retrieval from external store
- Structured tool-based memory writes (facts, preferences, plans)
- Separate working memory (ephemeral) and persistent memory (durable)
**Strengths:**
- Flexible and model-agnostic architecture
- Easy to add ranking/scoring for retrieved memories
**Tradeoffs:**
- Requires strict guardrails to avoid over-personalization or stale facts

### 4) Claude Memory Approaches (implementation patterns)

**Typical patterns:**
- Session-aware context layering
- Durable memory tool integration for user/repository facts
- Retrieval-first approach with selective context injection
**Strengths:**
- Good separation of conversation context vs durable memory
- Strong for incremental task continuity
**Tradeoffs:**
- Requires memory curation and deduplication workflows

### 5) Open Interpreter Memory

**What it is:** Local-first agent framework where memory is often file/system-backed and task-oriented.  
**Strengths:**
- Transparent local memory artifacts
- Good fit for persistent task execution and iterative coding workflows
**Tradeoffs:**
- Memory may become fragmented without schema/versioning discipline
- Requires robust cleanup and indexing strategy

### 6) Agent Architecture Patterns (cross-system)

Common memory layers across successful systems:
- **Working memory:** current turn/tool outputs (short-lived)
- **Session memory:** current objective, progress, recent decisions
- **Long-term semantic memory:** user/project facts and preferences
- **Episodic memory:** prior tasks, outcomes, mistakes, fixes
- **Multimodal memory:** image/audio embeddings + linked metadata

## Recommended Architecture

### Layered Hybrid Memory

1. **L0: Prompt/Working Memory (ephemeral)**
   - Current tool outputs, latest observations, immediate reasoning context
   - TTL: current turn / short window

2. **L1: Session State Store (durable per active session)**
   - Current task, last completed step, next step, blockers
   - Checkpoints for resume/recovery

3. **L2: Long-Term Fact Store (durable cross-session)**
   - User preferences, project facts, stable environment constraints
   - Confidence score + source citation + last-verified timestamp

4. **L3: Episodic Task Log (durable event stream)**
   - Task timelines, actions taken, outcomes, failures, lessons
   - Enables post-task learning and continuity handoff

5. **L4: Visual Memory Index (multimodal)**
   - Image/video embeddings + OCR + scene tags + linked task context
   - Cross-reference visual observations with session/task IDs

## Storage Options

Use a polyglot approach rather than one database for all memory types:

- **Relational DB (Postgres/SQLite):**
  - Session state, task progress, durable facts, audit trails
  - Strong consistency and straightforward querying

- **Vector DB (pgvector, Weaviate, Qdrant, Milvus):**
  - Semantic retrieval for text and visual embeddings
  - Similarity search across prior conversations and image observations

- **Object Store (S3/local blob):**
  - Raw media artifacts (images, audio, snapshots)
  - Linked by IDs from relational tables

- **Cache layer (Redis):**
  - Fast short-term session retrieval and lock/coordination support

## Session Persistence

Recommended persistence model:

- Assign every interaction to a `session_id`, `agent_id`, and `task_id`
- Persist checkpoints at meaningful boundaries:
  - after tool execution
  - after step completion
  - before context truncation
- Store resumable state:
  - goal
  - completed actions
  - pending actions
  - important intermediate artifacts
- Include schema version in every checkpoint for migration safety

## Task Tracking

Track tasks as state machines:

- **States:** planned → in_progress → blocked → completed/abandoned
- **Per-step metadata:** owner agent, inputs, outputs, verification status
- **Continuity artifacts:** “last completed step”, “next recommended step”, “known blockers”
- **Handoff packet:** minimal summary for another agent/session to continue without rework

Suggested minimum task record fields:

- `task_id`
- `objective`
- `status`
- `last_completed_step`
- `next_recommended_step`
- `blockers`
- `updated_at`
- `evidence_links` (logs, files, visual references)

## Visual Memory Design

For multimodal assistants, visual memory should store both semantic and operational context:

- Media reference (URI/hash)
- Timestamp, location/context metadata (if available)
- OCR transcript and extracted entities
- Embedding vectors for retrieval
- Linked task/session IDs
- Confidence and provenance metadata

Retrieval strategy:

1. Filter by task/session recency and relevance
2. Run semantic similarity on embeddings
3. Re-rank by confidence, freshness, and source quality
4. Inject only top-k compact visual memories into prompt context

## Open-Source Implementation Notes

- **Mem0:** strong option for user/project long-term memory abstraction
- **LangGraph memory/checkpointing:** strong option for workflow/session continuity
- **Open Interpreter-style local files:** useful for transparent, local-first episodic memory
- **Vector + SQL hybrid:** common architecture in production-grade agent systems

## Lessons Learned

1. **Single-store memory is rarely enough** for multimodal assistants.
2. **Explicit memory curation is mandatory** (dedupe, freshness, confidence scoring).
3. **Task continuity works best with structured state**, not free-form chat logs.
4. **Visual memory needs metadata + embeddings together** to stay actionable.
5. **Memory safety/governance must be built-in early**:
   - retention policies
   - deletion controls
   - sensitive data filtering
   - source attribution and traceability

## Practical Starter Blueprint

For a first production-capable version:

- SQL store for session/task/fact records
- pgvector (or dedicated vector DB) for semantic retrieval
- Object store for raw visual artifacts
- Checkpointing at each task step
- Memory write policy:
  - write only high-signal facts
  - attach source + confidence
  - periodic re-validation of long-term memory

This architecture balances reliability, continuity, and multimodal retrieval quality while remaining implementation-friendly for open-source agent stacks.
