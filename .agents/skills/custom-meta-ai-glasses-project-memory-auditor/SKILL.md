---
name: custom-meta-ai-glasses-project-memory-auditor
description: "Audit whether Custom Meta AI Glasses remembers and reconstructs the correct Project state, knowledge, provenance, ideas, and deterministic retrieval. Use for read-only Project Memory correctness and human-continuity assessment."
---

# Custom Meta AI Glasses Project Memory Auditor

Test the core thesis: application-owned state must let a user reopen the right Project tomorrow and understand continuity without relying on an AI conversation.

## Boundaries

- Read `AGENTS.md`, `docs/PROJECT_MEMORY_ARCHITECTURE.md`, runtime governance, and both repository statuses.
- Production code and live user Projects are read-only. Use isolated deterministic stores/Projects and zero-AI paths where possible.
- Do not edit, stage, commit, push, change architecture, or repair findings.
- Distinguish structured-store correctness from human-visible continuity. Do not infer correctness from UI text alone.

## Audit domains

- **Identity/isolation:** correct `project_id`; nothing from another Project.
- **Orientation/roadmap:** objective, where-we-left-off, Now, Next, blockers, completed/current/upcoming/deferred work.
- **Knowledge/history:** evidence, decisions, confirmed findings, chronology, important changes, rejected/superseded state.
- **Trust/provenance:** inference remains distinct; Continue is working direction, Disagree is retained, More Evidence remains unresolved, proposal statuses remain distinct.
- **Ideas/control:** unpromoted ideas stay outside Roadmap; promotions remain traceable; deferred work does not become current automatically.
- **Retrieval:** deterministic, bounded, relevant, properly excluding unrelated/superseded records, and zero provider calls where promised.
- **Persistence:** reconstruct after store/application restart without ChatGPT/Claude history.

Evaluate questions equivalent to: What is this Project? Where did we leave off? What is Now/Next/blocked/completed? What decisions and evidence exist, why, what did AI suggest, did the user agree, what remains unresolved, which ideas were promoted, what changed, and what must not appear from another Project?

## Report

### PROJECT MEMORY SCORECARD

Give `PASS/FAIL` for: `PROJECT IDENTITY`, `ORIENTATION`, `ROADMAP`, `EVIDENCE`, `DECISIONS`, `FINDINGS`, `HISTORY`, `TRUST/PROVENANCE`, `IDEAS`, `RETRIEVAL`, `RECONSTRUCTION`, `CROSS-PROJECT ISOLATION`.

### MEMORY DEFECTS

For each: severity, exact missing/incorrect knowledge, source records, expected and actual reconstruction, and affected read/retrieval path.

### USER CONTINUITY VERDICT

Return `READY` or `NOT READY` and explicitly answer whether a user can reopen tomorrow and know where they left off without asking AI.

Route defects: Auditor → Triage → `$custom-meta-ai-glasses-development` if needed → Architecture Guardian → rerun this Auditor.
