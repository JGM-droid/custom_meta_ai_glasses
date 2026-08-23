---
name: custom-meta-ai-glasses-api-contract-watchdog
description: "Compare Custom Meta AI Glasses FastAPI/OpenAPI contracts with Android callers and models to detect runtime drift before physical testing. Use for read-only cross-repository API compatibility audits."
---

# Custom Meta AI Glasses API Contract Watchdog

Detect backend/Android contract drift before it reaches a phone or glasses test.

## Boundaries

- Read both `AGENTS.md` files, architecture/runtime authority, statuses, FastAPI route/model definitions, generated OpenAPI where safely available, and Android client/model code.
- Do not edit, stage, commit, push, restart services, change configuration, or repair mismatches.
- Prefer static and deterministic contract inspection; use safe GET/OpenAPI checks only when already-running services are available.
- Do not treat a backend capability absent from Android as drift unless the MVP journey requires that connection.

## Compare

For each critical feature compare route, verb, body, response, required/optional/null fields, enum values, status/error payloads, IDs, timestamps, bounds/pagination, content type, and Project scoping.

Cover Projects/list/read/Active/checkpoint/orientation/activities; Investigation create/evidence/analyze/result/attribution; trust Continue/Disagree/More Evidence/read; proposals pending/apply/reject/revision; Project Knowledge; Ideas create/list/promote; and retained-evidence media review.

Look for missing/renamed routes or fields, incomplete enums, nullability mismatch, wrong URLs, stale models/status codes, ignored newly required fields, duplicate hardcoded paths, omitted `project_id`, and incorrect Active fallback.

## Report

### CONTRACT MATRIX

Columns: `FEATURE`, `BACKEND ROUTE`, `ANDROID CALLER`, `REQUEST MATCH`, `RESPONSE MATCH`, `ENUM MATCH`, `ERROR MATCH`, `PROJECT SCOPING`, `STATUS`.

### CONTRACT DRIFT FINDINGS

For each include severity (`BLOCKER/HIGH/MEDIUM/LOW`), exact mismatch, backend and Android locations, expected behavior, and likely runtime symptom.

### SAFE CONTRACTS

List critical contracts verified aligned.

Route mismatches: Watchdog → Triage → `$custom-meta-ai-glasses-development` if needed → Architecture Guardian → rerun this Watchdog.
