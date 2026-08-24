---
name: custom-meta-ai-glasses-release-sweep
description: "Orchestrate one bounded Custom Meta AI Glasses pre-release audit across technical and conditionally relevant product-design roles. Use before a major product or physical demo; allow at most one human-authorized repair batch."
---

# Custom Meta AI Glasses Release Sweep

Run a controlled, finite pre-release workflow. This skill coordinates specialists; it is not an autonomous repair loop.

## Authority and limits

- Read both repository instructions/statuses and preserve unrelated work.
- Run auditors sequentially and read-only. Do not allow concurrent mutation or specialist edits.
- Only `$custom-meta-ai-glasses-development` may edit production code, and only when the user's invocation authorizes repair.
- `$custom-meta-ai-glasses-triage`, Architecture Guardian, QA Breaker, Demo Manager, and all discovery/product specialists remain production-code read-only.
- UX Critic suggestions are advisory. `PRODUCT IDEA` findings must remain outside Development, current work, and the Roadmap unless a human explicitly promotes them.
- Permit at most **one** coherent bounded repair batch per invocation. If another repair is needed, stop for human approval.
- Never commit, push, deploy, change configuration, mutate live user Projects, or perform physical-device actions without explicit human authority.
- Preserve the frozen MVP and stop on architecture decisions or post-MVP scope.

## Specialist selection

For a major product milestone, include Bug Hunter, UX Critic, Product Designer, Trust UX Reviewer, State/Recovery, Project Memory Auditor, API Contract Watchdog, Scope Guardian, QA Breaker, appropriate Physical Integration, and Demo Manager.

Run `$custom-meta-ai-glasses-cross-device-designer` only when behavior or state crosses device surfaces. Run `$custom-meta-ai-glasses-information-architect` only when Project Workspace organization or scaling changes. Use `$custom-meta-ai-glasses-demo-scenario-designer` when a milestone needs an end-to-end value proof; it does not replace Demo Manager readiness.

For a tiny isolated patch, select only specialists whose mandate can materially validate the change. Record why conditional specialists were included or skipped.

## Sequential flow

1. `$custom-meta-ai-glasses-bug-hunter`
2. `$custom-meta-ai-glasses-ux-critic`
3. For major product milestones, `$custom-meta-ai-glasses-product-designer` and `$custom-meta-ai-glasses-trust-ux-reviewer`.
4. Conditionally run Information Architect and Cross-Device Designer under the selection rules above.
5. `$custom-meta-ai-glasses-state-recovery`
6. `$custom-meta-ai-glasses-project-memory-auditor`
7. `$custom-meta-ai-glasses-api-contract-watchdog`
8. For major product milestones, `$custom-meta-ai-glasses-scope-guardian`.
9. Combine and deduplicate findings without weakening evidence, trust, UX, or scope classifications.
10. `$custom-meta-ai-glasses-triage` selects exactly one bounded batch. `PRODUCT IDEA` items from any specialist cannot enter Development, current work, or the Roadmap without explicit human promotion.
11. If repair is authorized, `$custom-meta-ai-glasses-development` implements that batch; otherwise stop with the audit.
12. `$custom-meta-ai-glasses-architecture-guardian` performs independent read-only review.
13. Fix blocking guardian findings within the same batch only, then rerun each affected specialist once.
14. Run `$custom-meta-ai-glasses-qa-breaker` read-only regression coverage.
15. Run `$custom-meta-ai-glasses-physical-integration` only when the affected workflow requires physical evidence and no unapproved mutation is needed.
16. Conditionally run `$custom-meta-ai-glasses-demo-scenario-designer` for the scenario proof.
17. Run `$custom-meta-ai-glasses-demo-manager` for the final readiness verdict.

If any step requires user interaction, architecture authority, deployment, configuration, or a second repair batch, report the gate and stop.

## Report

Return specialist findings, triage batch/exclusions, changes if authorized, validation, guardian verdict, rerun outcomes, physical unknowns, demo readiness, both repository statuses, and the human-controlled next action.

Recommended focused flows remain:

- Small bug: Bug Hunter → Triage → Development → Guardian → regression.
- State reliability: State/Recovery → Triage → Development → Guardian → QA Breaker.
- Project Memory: Memory Auditor → Triage → Development if needed → Guardian → rerun Auditor.
- API contract: Watchdog → Triage → Development if needed → Guardian → rerun Watchdog.
