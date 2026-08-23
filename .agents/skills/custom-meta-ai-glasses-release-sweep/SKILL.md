---
name: custom-meta-ai-glasses-release-sweep
description: "Orchestrate one bounded Custom Meta AI Glasses pre-release audit across bug, recovery, memory, contract, QA, physical, and demo readiness roles. Use before a major physical demo; allow at most one human-authorized repair batch."
---

# Custom Meta AI Glasses Release Sweep

Run a controlled, finite pre-release workflow. This skill coordinates specialists; it is not an autonomous repair loop.

## Authority and limits

- Read both repository instructions/statuses and preserve unrelated work.
- Run auditors sequentially and read-only. Do not allow concurrent mutation or specialist edits.
- Only `$custom-meta-ai-glasses-development` may edit production code, and only when the user's invocation authorizes repair.
- `$custom-meta-ai-glasses-triage`, Architecture Guardian, QA Breaker, Demo Manager, and all four specialists remain production-code read-only.
- Permit at most **one** coherent bounded repair batch per invocation. If another repair is needed, stop for human approval.
- Never commit, push, deploy, change configuration, mutate live user Projects, or perform physical-device actions without explicit human authority.
- Preserve the frozen MVP and stop on architecture decisions or post-MVP scope.

## Sequential flow

1. `$custom-meta-ai-glasses-bug-hunter`
2. `$custom-meta-ai-glasses-state-recovery`
3. `$custom-meta-ai-glasses-project-memory-auditor`
4. `$custom-meta-ai-glasses-api-contract-watchdog`
5. Combine and deduplicate findings without weakening evidence labels.
6. `$custom-meta-ai-glasses-triage` selects exactly one bounded batch.
7. If repair is authorized, `$custom-meta-ai-glasses-development` implements that batch; otherwise stop with the audit.
8. `$custom-meta-ai-glasses-architecture-guardian` performs independent read-only review.
9. Fix blocking guardian findings within the same batch only, then rerun affected specialist checks once.
10. Run `$custom-meta-ai-glasses-qa-breaker` read-only regression coverage.
11. Run `$custom-meta-ai-glasses-physical-integration` for verified physical-chain status without unapproved mutation.
12. Run `$custom-meta-ai-glasses-demo-manager` for the final readiness verdict.

If any step requires user interaction, architecture authority, deployment, configuration, or a second repair batch, report the gate and stop.

## Report

Return specialist findings, triage batch/exclusions, changes if authorized, validation, guardian verdict, rerun outcomes, physical unknowns, demo readiness, both repository statuses, and the human-controlled next action.

Recommended focused flows remain:

- Small bug: Bug Hunter → Triage → Development → Guardian → regression.
- State reliability: State/Recovery → Triage → Development → Guardian → QA Breaker.
- Project Memory: Memory Auditor → Triage → Development if needed → Guardian → rerun Auditor.
- API contract: Watchdog → Triage → Development if needed → Guardian → rerun Watchdog.
