---
name: custom-meta-ai-glasses-development
description: "Implement, validate, and independently review bounded Custom Meta AI Glasses backend or Android changes while preserving Project Memory architecture, repository isolation, unrelated work, and the frozen MVP boundary. Use for development, integration repair, regression fixes, and change-set review in this project; not for unrelated Meta SDK work."
---

# Custom Meta AI Glasses Development Workflow

Use this workflow from the primary repository:

- Backend and architecture: `C:\Dev\Projects\CustomMetaAIGlasses\custom_meta_ai_glasses`
- Android and Meta client: `C:\Users\jesse\StudioProjects\meta-wearables-dat-android`

The user's current task defines the allowed scope. This skill does not authorize commits, pushes, pull requests, deployments, external configuration changes, or post-MVP feature work unless the user explicitly requests them.

## Orient and bound the task

1. Read the applicable repository's `AGENTS.md` before any other project action.
2. Inspect `git status` in both repositories. Record pre-existing modifications and protect them throughout the task; never clean, revert, overwrite, stage, or otherwise absorb unrelated work.
3. Read authoritative documents instead of treating chat history as project truth:
   - For backend, architecture, Project Memory, Investigation, project state, retrieval, or cross-repository integration work, read `docs/PROJECT_MEMORY_ARCHITECTURE.md`.
   - For backend startup, process, artifact, tunnel, or execution behavior, also read `docs/runtime_governance.md`.
   - For Android work, read the Android `AGENTS.md` and the smallest relevant documentation such as `docs/backend_integration.md`.
4. State the task's acceptance criteria and allowed files. Resolve current behavior from repository state, tests, and configuration.
5. Keep repository responsibilities separate. Modify Android only when the task requires Android work, and backend only when it requires backend work.

## Architecture guardrails

Apply the authority documents' current rules. In particular:

- Application-owned Project Memory is canonical; provider conversation history is not.
- Preserve explicit `project_id` identity and the precedence `explicit Project context > Active Project fallback > unscoped/null`.
- Merely viewing or working in Project B must not silently change the global Active Project.
- AI output is non-canonical until it passes the existing explicit validation/proposal path.
- Preserve append-only Activity and provenance history.
- Reuse existing Project, Checkpoint, Activity, Proposal, Investigation, and retrieval architecture before proposing a new abstraction.
- Do not expose or hardcode secrets or credentials.
- Prefer deterministic/offline validation before real provider calls.

MVP feature development is frozen. Unless the user explicitly authorizes a post-MVP milestone, fix only integration, regression, or demo blockers. Do not introduce Project Memory Index, MCP, product multi-agent features, Action Artifact framework, extra AI providers, Project Drift detection, Glasses Project Navigator, Neural Band/haptic features, domain templates, or multi-user collaboration.

## Implement and validate

1. Make the smallest bounded change that satisfies the acceptance criteria.
2. Add or update focused regression coverage when behavior changes.
3. Run targeted deterministic tests first, then the relevant broader suite, build, or install check in proportion to risk. Follow the commands in the applicable `AGENTS.md` and runtime governance.
4. Run `git diff --check` and inspect the complete scoped diff.
5. Recheck both repositories' status and confirm unrelated changes are untouched.

## Independent architecture review

After implementation and initial validation, launch one read-only reviewer subagent when subagents are available. Give it the task acceptance criteria, applicable authority paths, pre-existing dirty-file list, and resulting diff. It must not edit files. Ask it to return either `PASS` or `BLOCKING FINDINGS` and inspect:

- Project isolation and `project_id` semantics
- canonical-state mutation and trust/provenance violations
- unintended provider calls
- scope creep or post-MVP expansion
- unrelated-file changes
- missing tests and regression risk
- backend/Android responsibility leakage

If subagents are unavailable, perform a distinct second pass with the same checklist after setting aside the implementation rationale and rereading the diff from the acceptance criteria outward.

Classify every observation as `blocking defect`, `demo/UX issue`, `optional improvement`, or `post-MVP work`. Fix blocking findings only, then rerun affected tests, `git diff --check`, and final status checks. Do not turn reviewer suggestions into architecture or roadmap decisions.

## Handoff

Leave the change set ready for human approval. Do not commit or push unless explicitly requested, do not merge directly to `master`/`main`, and do not create or merge a pull request without authorization.

Report:

- outcome and exact files changed
- tests/builds run and results
- reviewer result and any blocking fixes made
- remaining non-blocking or post-MVP observations
- `git diff --check`
- final status of both repositories, including preserved unrelated changes
- whether the change set is ready for commit/PR or needs human input

For future branch work, prefer: task -> feature branch or isolated worktree -> implementation -> tests -> independent review -> blocking fixes -> push branch -> pull request -> human merge.
