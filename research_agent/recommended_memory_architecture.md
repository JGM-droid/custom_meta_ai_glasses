# Recommended Long-Term Memory Architecture for a Multimodal Wearable AI Assistant

## Scope
This research compares real projects and platforms for long-term memory in multimodal assistants, with emphasis on wearable workflows:
- OpenAI memory systems
- LangGraph memory
- Mem0
- Zep
- Graphiti
- Personal knowledge graph patterns
- Wearable AI assistants

---

## What real projects are doing

## 1) OpenAI memory systems
- OpenAI model calls are fundamentally stateless unless you pass prior context each request (OpenAI cookbook docs explicitly note models have no memory of past requests unless conversation history is supplied).
- Newer OpenAI agent/workspace patterns add persistent memory constructs (e.g., persistent folder/session memory in workspace agent examples), which is useful for cross-session continuity.

**Takeaway:** Good foundation APIs and memory controls, but you still need to design your own production memory architecture for a custom wearable assistant.

## 2) LangGraph memory
- LangGraph positions memory as both:
  - **short-term working memory** for current reasoning
  - **long-term persistent memory** across sessions
- LangGraph config surfaces clearly separate:
  - **checkpointer** (state checkpointing)
  - **store** (long-term memory store with optional semantic indexing)

**Takeaway:** Excellent orchestration skeleton for durable, stateful multimodal agents.

## 3) Mem0
- Mem0 is purpose-built as a memory layer for assistants/agents with user/session/agent memory levels.
- Current project direction emphasizes efficient single-pass memory extraction and hybrid retrieval.

**Takeaway:** Strong practical choice if you want plug-in personalization quickly with less infra burden.

## 4) Zep
- Zep frames memory as **context engineering** with relationship-aware retrieval and temporal understanding.
- Designed as managed platform with low-latency context assembly and enterprise posture.

**Takeaway:** Great for teams wanting managed infra and strong retrieval quality; more platform dependence than DIY OSS stacks.

## 5) Graphiti
- Graphiti is an OSS temporal knowledge graph engine (entities, edges/facts, temporal validity windows, provenance episodes).
- Built for evolving facts and historical truth queries ("what is true now" vs "what was true then").

**Takeaway:** Best architectural fit for relationship-rich, evolving user memory (especially useful in wearable context streams).

## 6) Personal knowledge graph patterns
Across systems, high-performing long-term memory tends to converge on:
1. **event ingestion** from multimodal streams
2. **fact extraction** + entity resolution
3. **temporal/versioned facts** (avoid destructive overwrite)
4. **hybrid retrieval** (semantic + keyword + graph traversal)
5. **profile + episodic memory separation**

## 7) Wearable AI assistants
- Open-source wearable projects like **Omi** show real-world architecture pressure: continuous capture, transcription, backend memory endpoints, and cross-device sync.
- Wearables generate noisy, high-volume temporal data; memory systems must prioritize compression, salience scoring, and recency/importance balancing.

---

## Direct answers

### 1. Which memory architecture should this project use?
**Recommendation: Hybrid layered architecture**
- **Orchestration:** LangGraph
- **Fast personalization layer:** Mem0-style user/session memory API
- **Deep long-term memory:** Temporal knowledge graph (Graphiti-style model)
- **Optional managed upgrade path:** Zep Cloud later if ops burden grows

Why this blend:
- LangGraph gives durable agent flow control.
- Mem0-like memory gives quick wins for personalization and retrieval.
- Temporal graph layer captures evolving user facts and relationships better than vector-only memory.

### 2. What scales best?
**Best long-term scaling:** Temporal graph + hybrid retrieval + tiered storage
- Hot path: recent episodic summaries in vector/index store
- Warm path: profile/preferences/facts in structured memory
- Cold path: raw multimodal events in object store
- Graph layer maintains evolving truth + provenance

Among evaluated options:
- **Zep (managed)** likely easiest at production scale fastest.
- **Graphiti + custom infra** scales architecturally very well but requires higher ops maturity.

### 3. What is easiest for a solo developer?
**Easiest path:** LangGraph + Mem0 first, defer graph complexity
- Step 1: Implement short-term session memory + profile memory
- Step 2: Add episodic summarization and memory decay policies
- Step 3: Add temporal graph only for high-value entities (people/projects/tasks)

This yields strong functionality quickly without overbuilding infra too early.

### 4. What would impress recruiters most?
**Most impressive portfolio architecture:**
1. Multimodal wearable ingestion pipeline
2. Dual memory system (profile memory + episodic memory)
3. Temporal personal knowledge graph with provenance
4. Retrieval evaluation dashboard (latency, recall@k, hallucination rate, stale-memory rate)
5. Safety/privacy controls (PII tagging, user-delete semantics, retention windows)

Recruiters tend to value systems thinking + production constraints more than model novelty.

### 5. Architecture diagrams

## A) Recommended phased architecture (now)
```text
[Wearable + Mobile + Desktop Inputs]
            |
            v
   [Multimodal Event Bus]
            |
   +--------+---------+
   |                  |
   v                  v
[Session State]   [Memory Extractor]
(LangGraph        (fact + preference +
 checkpointer)     episodic summary)
   |                  |
   |             +----+----------------------+
   |             |                           |
   v             v                           v
[Agent Runtime] [Profile/Episodic Store] [Vector Index]
 (LangGraph)      (Mem0-style API)       (semantic recall)
      \              |                        /
       \             |                       /
        +------------+----------+-----------+
                               |
                               v
                    [Context Assembler + Ranker]
                               |
                               v
                      [LLM Response + Actions]
```

## B) Recruiter-impressive target architecture
```text
                   [Wearable Streams]
                 (audio, image, events)
                           |
                           v
                 [Ingestion + Normalization]
                           |
        +------------------+-------------------+
        |                                      |
        v                                      v
 [Episodic Store + Summaries]          [Temporal Knowledge Graph]
 (time-sliced interactions)            (entities, relations,
                                        valid_at/invalid_at,
                                        provenance episodes)
        |                                      |
        +------------------+-------------------+
                           |
                           v
            [Hybrid Retrieval: semantic + keyword + graph]
                           |
                           v
             [Policy Layer: privacy, consent, deletion]
                           |
                           v
                [Agent Orchestrator (LangGraph)]
                           |
                           v
                 [Personalized Multimodal Assistant]
```

## C) Scale-oriented deployment topology
```text
Edge Devices -> API Gateway -> Async Queue/Kafka -> Memory Workers
                                     |                    |
                                     v                    v
                              Object Storage        Vector DB / Graph DB
                              (raw events)          (retrieval + relations)
                                     \                    /
                                      \                  /
                                       v                v
                                  Context Service + Ranker
                                              |
                                              v
                                       Agent Runtime/LLM
```

---

## Final recommendation for this project
If building in phases for speed + credibility:
1. **Start now:** LangGraph + Mem0-style memory layer.
2. **Next:** Add temporal personal knowledge graph for key entities and long-horizon reasoning.
3. **Scale:** Move to managed context platform (e.g., Zep) only when operational load justifies it.

This gives the best balance of:
- practical implementation speed,
- scalable architecture,
- and recruiter-visible technical depth.

---

## Sources (real projects/documentation)
- OpenAI Cookbook (stateless model context + workspace agent memory example):
  - https://github.com/openai/openai-cookbook
  - https://github.com/openai/openai-cookbook/blob/main/examples/data/oai_docs/text-generation.txt
  - https://github.com/openai/openai-cookbook/blob/main/articles/chatgpt-agents-sales-meeting-prep.md
- LangGraph:
  - https://github.com/langchain-ai/langgraph
  - https://github.com/langchain-ai/langgraph/blob/main/libs/cli/langgraph_cli/schemas.py
- Mem0:
  - https://github.com/mem0ai/mem0
- Zep:
  - https://github.com/getzep/zep
- Graphiti:
  - https://github.com/getzep/graphiti
  - https://arxiv.org/abs/2501.13956
- Wearable assistant reference:
  - https://github.com/BasedHardware/omi
