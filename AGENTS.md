# Custom Meta AI Glasses - Agent Guidance

## Instruction Hierarchy

1. Repository safety and runtime governance constraints.
2. Product architecture authority: docs/PROJECT_MEMORY_ARCHITECTURE.md.
3. Current phase implementation contract and tests.
4. Historical reference documents.

Before making architecture changes, memory changes, Investigation changes, project-state changes, or context-retrieval changes, read docs/PROJECT_MEMORY_ARCHITECTURE.md.

If an implementation task conflicts with docs/PROJECT_MEMORY_ARCHITECTURE.md:

1. Stop.
2. Describe the conflict and why a change may be required.
3. Update architecture decisions intentionally before implementation drift.

Recommended supporting architecture research reading:
- docs/research/PERSISTENT_PROJECT_MEMORY_REFERENCES.md (supporting evidence only; not architecture authority)
- docs/research/MULTI_AGENT_PRODUCT_REVIEW.md (structured product/architecture review; RESEARCH / RECOMMENDATIONS - HUMAN REVIEW REQUIRED, not architecture authority)

## Documentation Governance

Conversation memory (this chat, a Claude/Codex/Copilot session, etc.) is useful for continuity but is NOT this project's architectural source of truth. Once a meaningful product/architecture decision has been researched, reviewed, and approved, it must eventually be represented in repository documentation and Git history - a future agent should be able to reconstruct the important product direction from the repository alone, without access to the conversation that produced it.

When writing or reading architecture documentation, keep these four categories distinct and never blur them:

- LOCKED ARCHITECTURE: rules implementations must obey (see the Architecture Decision Log in docs/PROJECT_MEMORY_ARCHITECTURE.md).
- CURRENT IMPLEMENTATION: what actually exists and has been validated (see "Implemented" Phase/Slice entries).
- APPROVED ROADMAP: agreed future direction that is NOT yet implemented (see "Approved Roadmap" sections and ADRs marked "Research-Informed Roadmap").
- RESEARCH / PROPOSALS: ideas/recommendations that have NOT yet been approved (e.g. docs/research/*.md). These must never silently become LOCKED ARCHITECTURE or APPROVED ROADMAP just by being written down - a human approval step is required first.

Multi-agent/multi-perspective review (deliberately different mandates, not the same question asked six times) is an approved development/review practice for high-value decisions, not a product feature. Reviewer/agent conclusions are proposals/research input; they are never automatically architecture.

## Agent Team Routing and Operating Policy

`AGENTS.md` defines routing, authority, and permission boundaries. Detailed procedures live in `.agents/skills/<skill-name>/SKILL.md`. When a listed skill matches the task, read and follow that skill rather than approximating its behavior from this summary.

### Available team

Product and experience:

- `$custom-meta-ai-glasses-product-designer`
- `$custom-meta-ai-glasses-information-architect`
- `$custom-meta-ai-glasses-trust-ux-reviewer`
- `$custom-meta-ai-glasses-cross-device-designer`
- `$custom-meta-ai-glasses-scope-guardian`
- `$custom-meta-ai-glasses-ux-critic`
- `$custom-meta-ai-glasses-user-tester`
- `$custom-meta-ai-glasses-demo-scenario-designer`
- `$custom-meta-ai-glasses-explore-ux-tester`

Architecture, memory, and contracts:

- `$custom-meta-ai-glasses-architecture-guardian`
- `$custom-meta-ai-glasses-project-memory-auditor`
- `$custom-meta-ai-glasses-api-contract-watchdog`
- `$custom-meta-ai-glasses-explore-architect`
- `$custom-meta-ai-glasses-structured-output-validator`
- `$custom-meta-ai-glasses-interaction-persistence-auditor`

Quality and reliability:

- `$custom-meta-ai-glasses-bug-hunter`
- `$custom-meta-ai-glasses-state-recovery`
- `$custom-meta-ai-glasses-qa-breaker`
- `$custom-meta-ai-glasses-physical-integration`
- `$custom-meta-ai-glasses-demo-manager`

Orchestration and implementation:

- `$custom-meta-ai-glasses-mvp-completion`
- `$custom-meta-ai-glasses-triage`
- `$custom-meta-ai-glasses-development`
- `$custom-meta-ai-glasses-mvp-usability-sweep`
- `$custom-meta-ai-glasses-release-sweep`
- `$custom-meta-ai-glasses-explore-milestone`

Do not reference or simulate a specialist that does not exist under `.agents/skills/`.

### Authority and permissions

Only `$custom-meta-ai-glasses-development` may edit production code, and only within a user-authorized bounded batch. Triage plans but does not implement. Architecture Guardian, Product Designer, Scope Guardian, product/UX specialists, auditors, contract reviewers, and QA discovery roles are read-only unless their own skill explicitly permits isolated test artifacts.

Human approval is required for:

- architecture changes;
- post-MVP scope or Product Idea promotion;
- destructive Project-data operations;
- commits or pushes unless explicitly requested;
- deployment, runtime, DNS, tunnel, or configuration changes;
- SDK upgrades or unsupported Meta integration;
- a new persistence system;
- provider or core architecture changes.

### Default routing rule

Do not jump directly from a material feature request to Development. First determine which product, trust, architecture, memory, contract, recovery, and cross-device specialists apply. Role skipping is allowed only for a clearly trivial bounded change with no meaningful product, architecture, trust, persistence, contract, recovery, or cross-device decision.

Do not collapse specialist responsibilities into Development merely for speed. Discovery and review roles produce evidence or a bounded contract; Triage selects one coherent batch; a human authorizes material implementation; Development implements; independent reviewers validate.

### Token-Efficient Agent Routing

- Use the minimum number of agents necessary for the task; do not automatically run the full agent team.
- Small/local bug: `Development + QA` is the default route; add the relevant specialist only when a product, architecture, trust, contract, or persistence decision is material.
- UX issue: `Product Designer + Development + QA` is the default route; add `Trust UX Reviewer` when AI/approval semantics or user trust are affected.
- Architecture/Project Memory/persistence issue: one relevant specialist + `Development + QA` is the default route.
- API/contract issue: the relevant contract specialist + `Development + QA` is the default route.
- Full multi-agent sweeps are reserved for major milestones and release gates, not routine work.
- Avoid multiple agents with substantially overlapping responsibilities.
- Reuse prior validated findings instead of rerunning the same reviews.
- Read only the files/docs necessary for the current task; avoid broad repo rereads by default.
- Prefer targeted tests during development; keep full regression for meaningful integration/release gates.
- Agent reports should be concise and decision-oriented.
- Prompts should not repeat architecture, constraints, or procedures already defined in `AGENTS.md`, `.agents/skills/<skill>/SKILL.md`, or authoritative repo docs.
- Orchestrators must follow these efficiency rules too.
- Token efficiency must never bypass architecture, safety, Project isolation, trust, destructive-action, or human-approval gates.
- If one agent can safely do the work, use one agent.

### Default workflows

Small bug:

```text
Bug Hunter -> Triage -> Development -> Architecture Guardian -> relevant regression validation
```

UX or product flow:

```text
Product Designer -> UX Critic and/or User Tester -> Scope Guardian -> Triage
-> Development -> Trust UX Reviewer when relevant -> Architecture Guardian -> QA
```

Cross-device feature:

```text
Product Designer -> Cross-Device Designer -> Trust UX Reviewer when AI/approval is involved
-> relevant architecture/contract specialist -> Scope Guardian -> Triage -> Development
-> Architecture Guardian -> device-specific validation
```

Project Memory or persistence change:

```text
Project Memory Auditor -> Architecture Guardian -> Triage -> Development
-> State/Recovery -> QA Breaker
```

API or client contract change:

```text
API Contract Watchdog -> Triage -> Development -> Architecture Guardian
-> contract rerun -> QA Breaker
```

Major product milestone:

```text
Product Designer
-> Information Architect when Workspace organization changes
-> Cross-Device Designer when multiple surfaces participate
-> Trust UX Reviewer
-> Scope Guardian
-> applicable technical specialists
-> Triage
-> HUMAN APPROVAL
-> Development
-> Architecture Guardian
-> affected specialist reruns
-> QA Breaker
-> Physical Integration when applicable
-> Demo Manager
```

For a release sweep, use `$custom-meta-ai-glasses-release-sweep`. For the complete current MVP usability workflow, use `$custom-meta-ai-glasses-mvp-usability-sweep`.

For the remaining approved MVP critical path, use `$custom-meta-ai-glasses-mvp-completion`. It coordinates completed-milestone closure, real acceptance Projects, retry-safe Record Project Progress, realistic acceptance, one bounded hardening batch, and release-candidate validation. It is not a production editor; it routes all production changes through Development and stops only at its explicit human gates.

For the first generalized Project Interaction milestone, use `$custom-meta-ai-glasses-explore-milestone`.

### Mandatory product-role triggers

Product Designer is required when creating a workflow, changing primary actions, introducing a Project Interaction, adding a significant user capability, or changing approval/resume behavior.

Information Architect is required when changing Project Detail/Workspace hierarchy, adding durable information categories, reorganizing History/Evidence/Ideas/Roadmap/References, or materially increasing information density.

Trust UX Reviewer is required when AI suggestions can influence Project state, approval/rejection semantics or provenance change, or labels such as Save, Select, Apply, or Confirm could mislead users.

Cross-Device Designer is required when glasses and phone, phone and desktop, or all three surfaces participate in one workflow.

Scope Guardian is required when a bounded milestone is gaining features, Product Ideas appear during implementation, hypothetical infrastructure is proposed, or scope-creep risk is meaningful.

### Current architecture routing

Read these authorities rather than duplicating them here:

1. `docs/PROJECT_MEMORY_ARCHITECTURE.md` - approved forward architecture.
2. `docs/PROJECT_INTERACTION_FOUNDATION.md` - Project Interaction foundation under ADR-057.
3. `docs/ROADMAP.md` - approved direction versus future work.
4. `docs/project_constitution.md` - implementation and subsystem guardrails.
5. `docs/runtime_governance.md` - runtime/startup authority when applicable.

Core rules:

- The application owns Project Memory; provider conversation does not.
- AI output is not automatically canonical.
- Project identity and namespace isolation remain explicit.
- Investigation remains specialized.
- Project Interaction is a lightweight orchestration boundary, not a universal store.
- User-controlled Idea promotion and Proposal/Apply remain authoritative.
- Device UIs are projections/controllers over canonical Project state.
- Preserve provider-neutral application boundaries where practical.

### Anti-drift rules

- Do not invent persistence when existing Project Memory primitives suffice.
- Do not turn every interaction into Investigation.
- Do not put Product Ideas into implementation without explicit approval.
- Do not hard-code device rendering into canonical schemas.
- Do not silently change the Active Project.
- Do not bypass Proposal/Apply for canonical Project changes.
- Do not reintroduce the rejected DAT 0.8 Display/Band capture spike.
- Do not use unsupported Meta internal APIs or interception workarounds.
- Do not rewrite historical architecture decisions as though they never existed.

## Product Direction (Approved)

The product direction is now a project-aware persistent AI assistant.

- Glasses remain an important interface and evidence source.
- Glasses are not the sole architectural center.
- Persistent project continuity and project isolation are first-class requirements.

## Investigation Subsystem Status

The Investigation subsystem remains active and must be preserved:

- FastAPI backend and existing investigation APIs.
- Session lifecycle, evidence storage, orchestration, and retained results.
- Desktop and glasses projections.
- Backward compatibility guarantees already in place.

Investigation architecture is an important pattern source for upcoming Project Memory design, but Project Memory should reuse principles before reusing implementation classes.

## Legacy Memory Warning

code/prototype_v1/memory_manager.py and results/session_memory.json are legacy prototype memory and not the foundation of the approved Project Memory architecture.

- Keep for compatibility until migration is intentionally planned.
- Do not expand legacy global-memory patterns for new project-memory features.

## Existing Runtime/Signal Context

Signals currently available:

- Active file
- Language
- Dirty state
- Git state
- Terminal errors
- Coding session snapshot

Current architecture relationships in the implemented guidance pipeline:

- active_editor_context.py -> context_fusion.py
- context_fusion.py -> glasses_demo.py
- glasses_demo.py -> resume_now.json
- resume_now.json -> FastAPI
- FastAPI -> glasses_display_mock.html

These relationships are still valid for current runtime behavior, while forward product architecture is governed by docs/PROJECT_MEMORY_ARCHITECTURE.md.
