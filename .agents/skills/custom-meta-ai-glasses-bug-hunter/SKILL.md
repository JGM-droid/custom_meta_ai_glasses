---
name: custom-meta-ai-glasses-bug-hunter
description: "Quickly explore reachable Custom Meta AI Glasses MVP surfaces for small reproducible UX and integration defects. Use for broad lightweight bug discovery; remain read-only and route repairs through triage and development."
---

# Custom Meta AI Glasses Bug Hunter

Find small, reproducible defects a normal user would otherwise discover manually. This is faster and more defect-oriented than the full user journey audit.

## Boundaries

- Read both repositories' `AGENTS.md`, current status, and the smallest relevant authority documents before testing.
- Treat production source, live Project data, configuration, and external services as read-only. Do not edit, stage, commit, push, restart, deploy, or fix.
- Use existing tests, mocks, safe UI/browser checks, logs, and read-only API calls. Create data only in isolated test stores.
- Inspect every reachable backend/desktop/Android MVP surface; do not stop at the first defect.
- Preserve the MVP freeze. Mark unverified device behavior `PHYSICAL VALIDATION REQUIRED`.

## Exploration targets

Look for inert or wrongly wired buttons, misleading labels, stale placeholders, dead ends, broken Back/return routes, lost Project identity, stale screens, missing refresh, incorrect enablement/loading/retry states, duplicate workflows, exposed prototype UI, persisted capabilities missing from UI, inconsistent terminology, hidden pending actions, disappearing drafts, missing resume paths, result dead ends, repeated warnings, deterministic client defects, and obvious UI/API mismatch.

Classify each finding:

- `AUTO-FIX CANDIDATE`: deterministic, obvious intent, low architecture risk, and narrowly limited to existing UI/navigation/refresh/integration behavior.
- `NEEDS TRIAGE`: multiple plausible solutions, backend semantics, or a broader journey.
- `PHYSICAL VALIDATION REQUIRED`: code/tests/logs cannot establish glasses or phone behavior.
- `ARCHITECTURE DECISION REQUIRED`: Project Memory, trust/provenance, isolation, API/storage, canonical state, or provider behavior is implicated.
- `POST-MVP`: enhancement outside the frozen MVP.

## Report

Return:

### BUG HUNTER REPORT

For every finding: title, severity (`BLOCKER/HIGH/MEDIUM/LOW`), classification, screen/flow, reproduction, expected and actual behavior, likely components/files, and physical-validation status.

### RECOMMENDED LOW-RISK REPAIR BATCH

Group related `AUTO-FIX CANDIDATE` findings into exactly one coherent batch for `$custom-meta-ai-glasses-triage`.

### ESCALATE / DEFER

List everything that must not be automatically repaired.

Route work as: Bug Hunter → `$custom-meta-ai-glasses-triage` → `$custom-meta-ai-glasses-development` → `$custom-meta-ai-glasses-architecture-guardian` → regression validation.
