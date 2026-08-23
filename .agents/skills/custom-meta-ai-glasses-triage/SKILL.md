---
name: custom-meta-ai-glasses-triage
description: "Convert a Custom Meta AI Glasses User Tester report into one deduplicated, architecture-aware MVP repair batch. Use for read-only planning after a usability audit; never edit files or implement fixes."
---

# Custom Meta AI Glasses Triage

Accept a complete User Tester report as input and produce one coherent repair batch for `$custom-meta-ai-glasses-development`.

## Context and boundaries

1. Read the backend `AGENTS.md`, `docs/PROJECT_MEMORY_ARCHITECTURE.md`, and the existing development skill at `.agents/skills/custom-meta-ai-glasses-development/SKILL.md`. Read Android guidance only when findings involve Android.
2. Inspect both repositories' status and preserve the recorded pre-existing changes.
3. This role is strictly read-only and planning-only: do not edit, stage, commit, push, implement fixes, change configuration, or promote a recommendation into architecture or roadmap truth.
4. Enforce the frozen MVP boundary. Reject proposed Project Memory Index, MCP, product multi-agent features, Action Artifact framework, extra AI providers, Project Drift detection, Glasses Project Navigator, Neural Band/haptics, domain templates, and multi-user collaboration unless a separately authorized post-MVP task exists.

## Triage method

- Deduplicate findings by root user journey and observable failure.
- Separate defects from preferences and polish.
- Classify every item as `BLOCKER`, `DEMO UX`, `POLISH`, `POST-MVP`, or `NOT A BUG`.
- Rank by demo-blocking severity, user confusion, implementation risk, and architecture impact.
- Group related issues into journey-level batches. Prefer a coherent path such as `Project -> Start Working -> Capture -> Analyze` over isolated button edits when the same flow owns several defects.
- Avoid one-bug-at-a-time planning unless batching would increase safety, ambiguity, or regression risk.
- Treat `PHYSICAL VALIDATION REQUIRED` findings as unconfirmed unless other evidence proves them.

## Required output

### TRIAGE SUMMARY

Show deduplicated findings with classification, severity rationale, evidence status, dependencies, and architecture risk.

### REPAIR BATCH NOW

Produce exactly one bounded batch containing related `BLOCKER` items and the highest-value `DEMO UX` items that can safely be repaired together. Include:

- User journey boundary
- Included findings and why they belong together
- Explicit acceptance criteria stated as observable behavior
- Likely repository ownership: backend, Android, or both
- Required validation, including any physical validation
- Explicit exclusions

Make this section directly consumable as the bounded task for `$custom-meta-ai-glasses-development`.

### DEFER

List lower-value, risky, uncertain, or polish work with reasons.

### DO NOT BUILD

List post-MVP, scope-creeping, or unnecessary proposals and the rule that excludes each.
