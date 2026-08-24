---
name: custom-meta-ai-glasses-structured-output-validator
description: "Validate the strict provider-neutral OPTION_SET and INFORMATION_REQUEST boundary for Custom Meta AI Glasses. Strictly read-only; use during EXPLORE design, implementation review, and regression audits."
---

# Custom Meta AI Glasses Structured Output Validator

Audit whether provider output can safely cross the application-owned EXPLORE boundary.

## Authority and boundaries

- Read `AGENTS.md`, `docs/PROJECT_INTERACTION_FOUNDATION.md`, `docs/PROJECT_MEMORY_ARCHITECTURE.md`, `docs/ROADMAP.md`, and `docs/project_constitution.md`, then inspect the applicable schemas, provider adapter, and tests.
- Remain strictly read-only. Do not edit, stage, commit, push, mutate state, or invoke Development.
- Initial allowed semantic types are exactly `OPTION_SET` and `INFORMATION_REQUEST`.
- Neither result may mutate Project state. Application policy—not provider output—determines available actions.

## Validation matrix

Verify discriminated strict schemas, required fields, bounds, deterministic ordering, stable unique option IDs, provider neutrality, same-Project source references, and absence of device-specific canonical fields.

Adversarially test or inspect handling of malformed/partial JSON, arbitrary prose, unknown result types, duplicate IDs, empty or excessive option sets, missing fields, unexpected extra fields, mutation/action injection, provider-native objects, timeout, empty content, and invalid source references. Invalid output must produce a controlled contract failure with no partial canonical mutation or silent prose fallback.

## Report

Return:

# STRUCTURED OUTPUT VERDICT
# SCHEMA CONTRACT
# VALID CASES
# MALFORMED / ADVERSARIAL CASES
# PROVIDER NEUTRALITY
# ACTION-POLICY BOUNDARY
# MUTATION SAFETY
# TEST GAPS
# BLOCKERS
