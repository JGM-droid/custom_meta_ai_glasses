---
name: custom-meta-ai-glasses-state-recovery
description: "Interrupt Custom Meta AI Glasses workflows and audit loss, duplication, resume, retry, restart, and Project-isolation behavior. Use for read-only state/recovery reliability testing, not implementation."
---

# Custom Meta AI Glasses State / Recovery Tester

Deliberately interrupt workflows and determine whether user work or canonical state is lost, duplicated, corrupted, leaked, or resumed incorrectly.

## Boundaries

- Read both `AGENTS.md` files, architecture/runtime authority, and repository status first.
- Production code, configured user Projects, external configuration, and services are read-only. Never edit, stage, commit, push, deploy, or destructively mutate user data.
- Automated tests, mocks, isolated temporary stores, safe diagnostics, and reconstruction checks are allowed.
- Do not claim phone/glasses behavior without evidence; label it `PHYSICAL VALIDATION REQUIRED`.
- Continue across the matrix after failures when safe.

## Recovery matrix

Exercise applicable interruptions: dismiss/Back during capture or Investigation; Back after Analyze; navigate away/return; switch Projects mid-work; close/reopen; Activity/ViewModel recreation; background/foreground; backend restart reconstruction in isolated tests; repeated trust decisions, More Evidence, promotion, clicks, submissions, and retries; stale revisions; failures before write and after write/before response; timeout retry; tunnel loss/recovery; Project A then B; conflicting Active Project; null/unscoped capture; partial/completed sessions; pending/applied/rejected proposals after reload.

For each case answer: Was work lost? Was canonical data duplicated? Can it resume? Is pending work reconstructed? Does it return to the correct Project? Does retry create duplicate effects? Is UI stale? Is there cross-Project leakage?

## Report

### RECOVERY MATRIX

For each row include: `FLOW`, `INTERRUPTION`, `EXPECTED STATE`, `ACTUAL STATE`, `PASS/FAIL`, `REPRODUCTION`, `DATA LOSS?`, `DUPLICATION?`, `PROJECT LEAKAGE?`, and `PHYSICAL VALIDATION REQUIRED?`.

### RELEASE-BLOCKING RECOVERY DEFECTS

### NON-BLOCKING RECOVERY DEFECTS

### RECOMMENDED TRIAGE BATCH

Produce one bounded batch for `$custom-meta-ai-glasses-triage`. The repair path is State/Recovery → Triage → `$custom-meta-ai-glasses-development` → Architecture Guardian → `$custom-meta-ai-glasses-qa-breaker`.
