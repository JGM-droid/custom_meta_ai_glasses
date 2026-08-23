---
name: custom-meta-ai-glasses-mvp-usability-sweep
description: "Orchestrate the complete Custom Meta AI Glasses MVP usability sweep: full-journey user testing, architecture-aware triage, one bounded repair batch, implementation, independent review, and approval-ready handoff. Use when the user wants consolidated usability repair rather than one defect at a time."
---

# Custom Meta AI Glasses MVP Usability Sweep

Run one sequential, consolidated workflow using these repository-scoped skills:

1. `$custom-meta-ai-glasses-user-tester`
2. `$custom-meta-ai-glasses-triage`
3. `$custom-meta-ai-glasses-development`

The primary agent owns orchestration and implementation. Tester, triage, and final architecture review are read-only subagent roles. Do not write tester or triage reports into the repository unless the user explicitly asks for report artifacts.

## Preconditions

- Read the backend `AGENTS.md` and inspect status in both repositories.
- Preserve all pre-existing unrelated changes.
- Confirm the user's prompt authorizes product repair. If it requests audit or setup only, stop after the corresponding read-only stage.
- The workflow does not authorize commits, pushes, PRs, merges, deployments, external configuration changes, or post-MVP work unless explicitly requested.

## Orchestration

1. Launch one read-only subagent and instruct it to use `$custom-meta-ai-glasses-user-tester` at `.agents/skills/custom-meta-ai-glasses-user-tester/SKILL.md`. Require the complete journey report even if an early step fails. Wait for its final report.
2. Launch a separate read-only subagent and instruct it to use `$custom-meta-ai-glasses-triage` at `.agents/skills/custom-meta-ai-glasses-triage/SKILL.md`, supplying the tester report unchanged. Require exactly one `REPAIR BATCH NOW`. Wait for its final report.
3. Review the triage batch for authorization and MVP scope. If it requires post-MVP work, external changes, or an unresolved product choice, stop and ask the user. Otherwise treat `REPAIR BATCH NOW` as the bounded task.
4. In the primary agent, load and follow `$custom-meta-ai-glasses-development` at `.agents/skills/custom-meta-ai-glasses-development/SKILL.md`. Implement only the accepted batch and run its required tests and checks.
5. Let the development skill launch its independent read-only reviewer/architecture guardian. Fix blocking findings only and rerun affected validation.
6. Return one consolidated report. Do not continue into deferred findings or another repair batch.

If subagents are unavailable, perform the tester and triage as distinct sequential read-only passes before loading the development skill. Do not collapse the mindsets or start implementation before the triage batch is complete.

## Consolidated report

Include:

- Journey coverage and evidence limitations
- Deduplicated issue inventory by triage classification
- The one repair batch selected and explicit exclusions
- Exact files changed
- Tests/builds and results
- Reviewer `PASS` or resolved `BLOCKING FINDINGS`
- Remaining `DEFER` and `DO NOT BUILD` items
- Physical validation still required
- Final status of both repositories
- Whether the change set is ready for human approval

Stop after the consolidated report. Human approval remains the commit, PR, deployment, and merge gate.
