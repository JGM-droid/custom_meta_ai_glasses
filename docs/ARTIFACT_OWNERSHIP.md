# JSON Artifact Ownership

This registry defines the single canonical writer for every JSON file produced or maintained by the repository. Readers may consume an artifact, but new write paths must be added here and must not compete with the canonical writer.

At startup, `start_assistant.py` calls `artifact_ownership.warn_if_multiple_writers()`. The validation uses the matching registry in `code/prototype_v1/artifact_ownership.py` and warns when more than one retained writer exists for an artifact. A warning does not stop startup.

## Runtime artifacts

All paths below are relative to `code/prototype_v1` unless otherwise noted.

| Artifact | Canonical writer | Primary purpose / consumers |
| --- | --- | --- |
| `results/active_editor_state.json` | `vscode_extension/active-file-signal/extension.js` | Raw VS Code active-editor signal; read by `active_editor_context.py`, `context_fusion.py`, and launch validation. |
| `results/active_editor_state.tmp.json` | `vscode_extension/active-file-signal/extension.js` | Transient atomic-write staging file; renamed to `active_editor_state.json`. |
| `results/active_editor_context.json` | `active_editor_context.py` | Normalized editor context; read by `context_fusion.py`. |
| `results/terminal_error_context.json` | `terminal_error_context.py` | Terminal-error signal; read by `context_fusion.py` and `glasses_demo.py`. |
| `results/coding_context_pack.json` | `coding_context_pack.py` | Repository, session, Git, and editor context; read by recovery, prompt preview, and guidance generation. |
| `results/milestone_history.json` | `coding_context_pack.py` | Persisted milestone transitions used while building the context pack. |
| `results/coding_session_snapshot.json` | `coding_session_snapshot.py` | Current coding-session snapshot; read by `context_fusion.py`. |
| `results/context_fusion.json` | `context_fusion.py` | Fused workflow signals; read by `glasses_demo.py` and `api.py`. |
| `results/latest_response.json` | `fix_writer.py` | Latest image-analysis and continuity payload; read by API, recovery, tests, voice, and context builders. |
| `results/session_memory.json` | `memory_manager.py` | Active task and recent observations; read by context and recovery modules. `watch_latest_image.py` writes only through `memory_manager.py`. |
| `results/session_recovery.json` | `session_recovery.py` | Restart/resume summary assembled from context and memory. |
| `results/resume_now.json` | `glasses_demo.py` | Canonical HUD guidance payload; read by `api.py`, `refresh_guidance.py`, and the display fallback. |
| `results/glasses_demo.json` | `glasses_demo.py` | Demo execution summary. |
| `results/project_progress.json` | `glasses_demo.py` | Current project milestone and progress state. |
| `results/task_state.json` | `glasses_demo.py` | Current task-tracking decision. |
| `results/task_completion.json` | `glasses_demo.py` | Most recent task-completion assessment. |
| `results/chatgpt_context_payload.json` | `glasses_demo.py` | Debug snapshot of the model context payload. |
| `results/guidance_response.json` | `glasses_demo.py` | Normalized guidance-engine response. |
| `results/chatgpt_request.json` | `glasses_demo.py` | Debug snapshot of the outbound model request. |
| `results/chatgpt_response_raw.json` | `glasses_demo.py` | Debug snapshot of the raw model response. |
| `results/developer_validation_log.json` | `glasses_demo.py` | Rolling developer-validation observations. |
| `results/usability_report.json` | `glasses_demo.py` | Derived usability report. |
| `results/last_known_hud_payload.json` | `api.py` | Last complete HUD response used for graceful fallback. |
| `results/vision_context.json` | `api.py` | Latest vision-analysis result served by vision endpoints. |

## Diagnostic and scenario artifacts

These are not part of the canonical assistant startup chain.

| Artifact | Canonical writer | Scope |
| --- | --- | --- |
| `results/https_tunnel_readiness.json` | `https_tunnel_readiness.py` | HTTPS tunnel diagnostic result. |
| `results/https_tunnel_test_runner.json` | `https_tunnel_test_runner.py` | HTTPS test-run summary. |
| `results/network_display_test.json` | `network_display_test.py` | Display reachability diagnostic. |
| `results/demo_server_status.json` | `demo_server_manager.py` | Legacy-only server diagnostic; launcher is blocked unless explicitly overridden. |
| `results/demo_context/<scenario>/coding_context_pack.json` | `dev_demo_scenarios.py` | Isolated scenario fixture, not the live context pack. |
| `results/demo_context/<scenario>/session_recovery.json` | `dev_demo_scenarios.py` | Isolated scenario fixture, not the live recovery artifact. |

## Repository metadata

| Artifact | Canonical writer | Scope |
| --- | --- | --- |
| `vscode_extension/active-file-signal/package.json` | Maintainers / package tooling | VS Code extension manifest; it is source metadata, not a runtime result. |

JSON returned by HTTP APIs, such as the ngrok tunnel API or FastAPI responses, is transport data and is not a repository artifact because it is not persisted by this project.

## Known retained conflict

`resume_now.py` can still write `results/resume_now.json`, but it is a quarantined legacy entry point. Its runtime guard blocks execution unless `--allow-legacy-run` is supplied. The canonical writer remains `glasses_demo.py`; startup validation warns while both writer implementations remain in the repository.

## Ownership rule

When adding or changing an artifact:

1. Assign one canonical writer module.
2. Route all writes through that module's public function or entry point.
3. Keep other modules read-only for that artifact.
4. Update this document and `artifact_ownership.py` in the same change.
5. If a legacy writer must remain, quarantine it and keep the startup warning until it is removed.
