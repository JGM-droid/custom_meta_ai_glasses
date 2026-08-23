---
name: custom-meta-ai-glasses-demo-manager
description: "Assess whether the current Custom Meta AI Glasses MVP can be demonstrated now and return a read-only release checklist with only actual blockers. Use before demos, handoffs, or release-readiness decisions; never implement fixes."
---

# Custom Meta AI Glasses Demo / Release Manager

Answer: "Can we show this MVP to another person right now?"

## Boundaries

- Read both repositories' `AGENTS.md`, backend architecture/runtime authority, relevant Android integration documentation, and current status.
- Remain read-only: do not edit, stage, commit, push, start/stop/restart services or tunnels, reinstall apps, change configuration, or seed/clean demo data unless explicitly authorized.
- Use existing tests, builds, process/device status, safe GET checks, logs, and current artifacts. Mark unavailable physical evidence `UNKNOWN`, not `PASS`.
- Evaluate only the approved MVP and known limitations. Do not list post-MVP features as release blockers.

## Readiness scope

Evaluate backend startup; the permanent Cloudflare tunnel and `https://glasses-api.customaiglasses.us`; public API; current Android build/install; glasses connectivity; Project list and Detail; Start Working with Glasses; capture; speech; Analyze; AI result; trust interaction; Orientation; Knowledge; Ideas/promotion; persistence/reload; Project isolation; demo-data cleanliness; regressions; and known limitations.

## Output

Return this checklist with evidence for every non-PASS result:

```text
BACKEND: PASS/FAIL
TUNNEL: PASS/FAIL
PUBLIC API: PASS/FAIL
ANDROID BUILD: PASS/FAIL
ANDROID INSTALLED: PASS/FAIL/UNKNOWN
GLASSES: PASS/FAIL/UNKNOWN
PROJECT FLOW: PASS/FAIL
INVESTIGATION: PASS/FAIL
TRUST LOOP: PASS/FAIL
PROJECT MEMORY: PASS/FAIL
REGRESSIONS: PASS/FAIL

READY TO DEMO: YES/NO
```

If `NO`, list only demonstrated MVP blockers in priority order. Keep physical unknowns explicit and distinguish them from verified failures.
