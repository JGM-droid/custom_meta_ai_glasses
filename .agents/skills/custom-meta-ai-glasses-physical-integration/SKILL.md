---
name: custom-meta-ai-glasses-physical-integration
description: "Diagnose the Meta glasses to Android to Cloudflare to FastAPI to Investigation and Project-attribution chain. Use for physical capture, connectivity, stale-build, backend URL, tunnel, request-routing, or attribution failures; diagnose before proposing changes."
---

# Custom Meta AI Glasses Physical Integration Investigator

Diagnose first. Do not redesign architecture or edit production code. A fix may be implemented only through a separately authorized `$custom-meta-ai-glasses-development` task.

## Boundaries

- Read both repositories' `AGENTS.md`, backend `docs/runtime_governance.md`, Android `docs/backend_integration.md`, and current status.
- Inspect source, local properties without exposing secrets, generated BuildConfig, APK/install state, connected-device state, processes, logs, DNS, tunnel status, public endpoints, and local FastAPI health as needed.
- Do not print credentials, tokens, certificates, API keys, or secret values.
- Do not edit files, stage, commit, push, start/stop/restart services or tunnels, reinstall apps, change DNS/configuration, or run mutating backend requests unless explicitly authorized.
- Distinguish proven facts from hypotheses and mark steps requiring the owner to handle hardware as physical retests.

## Diagnostic chain

Trace evidence in order:

`Meta glasses -> Android capture/speech -> generated backend URL -> phone network -> Cloudflare DNS/tunnel -> local FastAPI -> Investigation lifecycle -> explicit/fallback Project attribution`

Check glasses/DAT active state, capture intermittency, stream availability, Android URL and BuildConfig mismatch, installed-build freshness, DNS/tunnel routing, public and local endpoints, whether a phone request reaches FastAPI, speech capture versus submission, and `project_id` ownership.

## Output

### PHYSICAL CHAIN STATUS

```text
GLASSES: PASS/FAIL/UNKNOWN
ANDROID: PASS/FAIL/UNKNOWN
PUBLIC BACKEND: PASS/FAIL
FASTAPI: PASS/FAIL
PROJECT ATTRIBUTION: PASS/FAIL/UNKNOWN

ROOT CAUSE:
<evidence-backed cause or NOT YET ISOLATED>

SMALLEST FIX:
<one bounded next action; route code changes through the development skill>

PHYSICAL RETEST REQUIRED:
YES/NO
```
