# Large File Decomposition Plan

This is a planning document only. The current cleanup does not move runtime logic or change public behavior.

## Constraints

- Preserve CLI arguments, exit codes, endpoint paths, payload schemas, artifact paths, and writer ownership.
- Preserve guidance-priority ordering and graceful fallbacks.
- Keep `glasses_demo.py`, `api.py`, and `refresh_guidance.py` as compatibility entry points during extraction.
- Move code in small, independently testable changes; do not combine extraction with policy changes.

## `glasses_demo.py`

Current responsibilities include project-memory loading, prompt-mode selection, architecture and Git reasoning, guidance policy, OpenAI request handling, completion detection, validation reporting, task tracking, scenario construction, artifact persistence, and CLI orchestration.

Proposed boundaries:

| Module | Responsibility |
| --- | --- |
| `guidance/project_memory.py` | Load and normalize `AGENTS.md` project memory and progress state. |
| `guidance/context_reasoning.py` | Active-file, architecture, deployment, UI, Git-risk, and terminal-error reasoning. |
| `guidance/decision_policy.py` | Next-step selection, confidence, prompt mode, guidance priority, and advisory policy. |
| `guidance/prompts.py` | Prompt library, actionable prompt, ChatGPT template, and context payload construction. |
| `guidance/openai_client.py` | Request payload construction, API invocation, response extraction, normalization, and mock fallback. |
| `guidance/completion.py` | Completion evidence, reason codes, milestone advancement, and completion record construction. |
| `guidance/validation.py` | Developer validation log and usability report calculations. |
| `guidance/artifacts.py` | Typed loading and atomic persistence for artifacts owned by `glasses_demo.py`. |
| `guidance/scenarios.py` | Demo scenario payloads and scenario-specific defaults. |
| `guidance/runner.py` | Compose context, decisions, model guidance, completion, and output payloads. |

Keep `glasses_demo.py` as the argument parser and thin call into `guidance.runner`. First extraction should be pure prompt/normalization helpers, followed by artifact persistence, then decision policy. CLI orchestration should move last.

## `api.py`

Current responsibilities include FastAPI setup, process locking, static files, dotenv/API-key loading, image preparation, mock and OpenAI vision analysis, evidence gating, workflow-context fusion, HUD shaping and caching, authentication, and endpoint handlers.

Proposed boundaries:

| Module | Responsibility |
| --- | --- |
| `api_app/config.py` | Paths, environment loading, model selection, limits, and token configuration. |
| `api_app/lifecycle.py` | Single-instance lock and application startup/shutdown hooks. |
| `api_app/json_store.py` | Tolerant JSON reads and atomic cache writes. |
| `api_app/vision/images.py` | Image validation, resizing, MIME handling, and data encoding. |
| `api_app/vision/client.py` | OpenAI vision request and deterministic fallback behavior. |
| `api_app/vision/policy.py` | Payload normalization, development relevance, and evidence gating. |
| `api_app/hud.py` | Resume loading, freshness calculation, HUD merge/cache logic, and glasses payload shaping. |
| `api_app/auth.py` | Bearer/query token extraction and validation. |
| `api_app/routes/display.py` | Display and glasses static-file routes. |
| `api_app/routes/guidance.py` | `/latest` and `/glasses/latest`. |
| `api_app/routes/vision.py` | `/analyze`, `/vision/latest`, and `/vision/analyze`. |

Keep `api.py` exporting `app` so the existing `uvicorn api:app` command remains valid. Extract pure HUD and vision-policy functions first, then route modules, and migrate startup locking to FastAPI lifespan only after focused lifecycle tests exist.

## `refresh_guidance.py`

Current responsibilities include interpreter and lock validation, file signatures, JSON loading, import/subprocess execution, pipeline sequencing, summaries, watch-state change detection, CLI parsing, and watch lifecycle.

Proposed boundaries:

| Module | Responsibility |
| --- | --- |
| `refresh/runtime.py` | Interpreter validation and single-instance lock helpers. |
| `refresh/pipeline.py` | Step definitions, import-preferred execution, subprocess fallback, and refresh result. |
| `refresh/status.py` | File signatures, payload status fields, summaries, and change detection. |
| `refresh/watcher.py` | Interval loop and shutdown behavior. |
| `refresh/cli.py` | Argument parsing and command dispatch. |

Keep `refresh_guidance.py` as a compatibility wrapper. Extract `StepResult` and pipeline execution together so callers retain one result contract.

## Recommended sequence

1. Add characterization tests for CLI parsing, artifact paths, key payload builders, and API route responses.
2. Introduce package directories with no behavior changes and move pure functions first.
3. Centralize JSON persistence according to `ARTIFACT_OWNERSHIP.md`, preserving exact formatting and fallback semantics.
4. Extract external I/O boundaries: OpenAI calls, subprocess execution, filesystem reads, and clocks.
5. Move orchestration after lower-level modules have coverage.
6. Retain compatibility imports and entry points for one release cycle before considering removals.

## Validation gates

Each extraction PR should run syntax checks and existing smoke tests, compare representative JSON payloads before and after, verify `uvicorn api:app` import compatibility, and exercise `glasses_demo.py --help` plus `refresh_guidance.py --help`. No extraction should change the canonical writer table without a separate ownership decision.

## Legacy launcher audit

The four audited files remain in place because moving them would break historical paths. Each already carries a top-level deprecation notice and a runtime guard requiring `--allow-legacy-run`:

- `local_demo_launcher.py`: can start duplicate API/display/demo chains.
- `ngrok_demo_launcher.py`: can start a duplicate API and obsolete ngrok tunnel chain.
- `demo_server_manager.py`: uses Windows-specific diagnostics and can launch unguarded servers.
- `resume_now.py`: writes the canonical HUD artifact with an incompatible legacy schema.

They are excluded from normal startup. Future removal should occur only after references and historical workflows have been checked.
