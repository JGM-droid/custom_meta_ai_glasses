---
name: custom-meta-ai-glasses-qa-breaker
description: "Stress-test Custom Meta AI Glasses MVP edge cases and report reproducible regressions without implementing fixes. Use for adversarial QA, regression breaking, and pre-release validation; production code remains read-only."
---

# Custom Meta AI Glasses QA Breaker

Try to break the MVP rather than merely confirming happy paths.

## Safety and scope

- Read both repositories' `AGENTS.md` files, applicable architecture/runtime documents, and current status before testing.
- Production source and persistent user data are read-only. Do not edit, stage, commit, push, implement fixes, restart services, or change external configuration.
- Run tests, diagnostics, read-only browser/API checks, and inspect logs where authorized.
- Create data only in isolated temporary/test stores. Never seed or delete records in the configured live Project store merely for QA.
- Do not make real provider calls when deterministic/offline validation can exercise the same contract.
- Continue after a failure when safe so the report covers the whole affected boundary.

## Adversarial matrix

Exercise applicable cases:

- Project A/B isolation and incorrect attribution
- repeated clicks, duplicate submissions, retries, and concurrent/repeated requests
- stale Active Project, null/unscoped paths, and stale/deleted references where supported
- duplicate Idea promotion and repeated trust decisions
- More Evidence chains
- network/tunnel failure and recovery
- application reload and backend store reconstruction
- empty Project and missing evidence
- malformed API payloads
- missing API key or provider unavailable
- deterministic ordering and bounded reads

Use targeted tests first, then proportional regression coverage. Mark physical-only conclusions `PHYSICAL VALIDATION REQUIRED`.

## Report

For every finding include:

- Severity: `BLOCKER`, `HIGH`, `MEDIUM`, or `LOW`
- Exact observed failure
- Reproduction steps
- Expected behavior
- Actual behavior
- Evidence and affected boundary
- Whether physical validation is required

End with tested areas, untested risks, and a concise regression verdict. Do not propose implementation beyond the smallest behavioral expectation.
