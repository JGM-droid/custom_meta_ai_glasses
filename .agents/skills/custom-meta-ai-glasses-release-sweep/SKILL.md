---
name: custom-meta-ai-glasses-release-sweep
description: "Orchestrate one bounded Custom Meta AI Glasses pre-release audit across bug, human-centered UX, recovery, memory, contract, QA, physical, and demo readiness roles. Use before a major physical demo; allow at most one human-authorized repair batch."
---

# Custom Meta AI Glasses Release Sweep

Run a controlled, finite pre-release workflow. This skill coordinates specialists; it is not an autonomous repair loop.

## Authority and limits

- Read both repository instructions/statuses and preserve unrelated work.
- Run auditors sequentially and read-only. Do not allow concurrent mutation or specialist edits.
- Only `$custom-meta-ai-glasses-development` may edit production code, and only when the user's invocation authorizes repair.
- `$custom-meta-ai-glasses-triage`, Architecture Guardian, QA Breaker, Demo Manager, and all five discovery specialists remain production-code read-only.
- UX Critic suggestions are advisory. `PRODUCT IDEA` findings must remain outside Development, current work, and the Roadmap unless a human explicitly promotes them.
- Permit at most **one** coherent bounded repair batch per invocation. If another repair is needed, stop for human approval.
- Never commit, push, deploy, change configuration, mutate live user Projects, or perform physical-device actions without explicit human authority.
- Preserve the frozen MVP and stop on architecture decisions or post-MVP scope.

## Sequential flow

1. `$custom-meta-ai-glasses-bug-hunter`
2. `$custom-meta-ai-glasses-ux-critic`
3. `$custom-meta-ai-glasses-state-recovery`
4. `$custom-meta-ai-glasses-project-memory-auditor`
5. `$custom-meta-ai-glasses-api-contract-watchdog`
6. Combine and deduplicate findings without weakening evidence or UX classification labels.
7. `$custom-meta-ai-glasses-triage` separately classifies UX findings as `FIX NOW`, `DEFER`, `PRODUCT IDEA`, or `DO NOT BUILD`, then selects exactly one bounded batch. UX `PRODUCT IDEA` items cannot enter that batch without explicit human promotion.
8. If repair is authorized, `$custom-meta-ai-glasses-development` implements that batch; otherwise stop with the audit.
9. `$custom-meta-ai-glasses-architecture-guardian` performs independent read-only review.
10. Fix blocking guardian findings within the same batch only, then rerun each affected discovery specialist once.
11. Run `$custom-meta-ai-glasses-qa-breaker` read-only regression coverage.
12. Run `$custom-meta-ai-glasses-physical-integration` for verified physical-chain status without unapproved mutation.
13. Run `$custom-meta-ai-glasses-demo-manager` for the final readiness verdict.

If any step requires user interaction, architecture authority, deployment, configuration, or a second repair batch, report the gate and stop.

## Report

Return specialist findings, triage batch/exclusions, changes if authorized, validation, guardian verdict, rerun outcomes, physical unknowns, demo readiness, both repository statuses, and the human-controlled next action.

Recommended focused flows remain:

- Small bug: Bug Hunter → Triage → Development → Guardian → regression.
- State reliability: State/Recovery → Triage → Development → Guardian → QA Breaker.
- Project Memory: Memory Auditor → Triage → Development if needed → Guardian → rerun Auditor.
- API contract: Watchdog → Triage → Development if needed → Guardian → rerun Watchdog.
