# Runtime Governance

## Canonical Runtime (V16+)

> **One startup path. One writer per artifact. Venv only.**

## Execution Contract (Authoritative)

This section is the single authoritative execution contract for this repository.
If another document conflicts with this section, this section wins.

### Canonical Repository

- Active canonical repository path: repository root
- Legacy local repository is preserved for historical verification only and is not an active development target.

### Official Runtime Entry Points

- Official startup command:

```
.\venv\Scripts\python.exe code\prototype_v1\start_assistant.py
```

- Official launcher command (demo/operator workflow):

```
.\venv\Scripts\python.exe code\prototype_v1\launch_demo.py
```

- Official backend service:
   - FastAPI app in `code/prototype_v1/api.py`
   - Started and supervised by `code/prototype_v1/start_assistant.py`

### Official Tunnel Workflow

- Preferred operational command:

```
.\venv\Scripts\python.exe code\prototype_v1\launch_demo.py --prefer-cloudflare
```

- `launch_demo.py` is the official operator launcher for tunnel-aware demo startup and endpoint validation.
- Diagnostic scripts such as `https_tunnel_readiness.py` and `https_tunnel_test_runner.py` are support tools and do not replace canonical startup ownership.

### Official Testing Workflow

- Run tests from repository root using the canonical environment:

```
.\venv\Scripts\python.exe -m pytest code\prototype_v1 --basetemp code\prototype_v1\results\.pytest_tmp
```

- Focused contract suites for Investigation Sessions and API compatibility:

```
.\venv\Scripts\python.exe -m pytest code\prototype_v1\test_investigation_sessions_phase2a.py --basetemp code\prototype_v1\results\.pytest_tmp
.\venv\Scripts\python.exe -m pytest code\prototype_v1\test_investigation_sessions_phase2b.py --basetemp code\prototype_v1\results\.pytest_tmp
.\venv\Scripts\python.exe -m pytest code\prototype_v1\test_investigations_api.py --basetemp code\prototype_v1\results\.pytest_tmp
```

### Official Debugging Workflow

1. Start canonical runtime using `start_assistant.py`.
2. Validate API availability on `http://127.0.0.1:8001/latest` and session routes via OpenAPI.
3. Use diagnostic scripts only for targeted troubleshooting.
4. Do not switch startup ownership to legacy launchers during debugging.

### Official Runtime Ownership

- Runtime supervisor: `code/prototype_v1/start_assistant.py`
- Refresh loop owner: `code/prototype_v1/refresh_guidance.py --watch` (spawned by startup supervisor)
- API owner: `code/prototype_v1/api.py`
- Context fusion owner: `code/prototype_v1/context_fusion.py`
- Guidance/HUD payload owner: `code/prototype_v1/glasses_demo.py`

### Official Artifact Ownership

| Artifact | Canonical writer | Primary reader | Lifecycle |
|---|---|---|---|
| `results/active_editor_state.json` | VS Code extension only | `active_editor_context.py`, `context_fusion.py` | Continuously updated signal |
| `results/context_fusion.json` | `context_fusion.py` only | `glasses_demo.py`, `api.py` | Regenerated per refresh cycle |
| `results/resume_now.json` | `glasses_demo.py --auto` only | `api.py`, display clients | Regenerated per refresh cycle |
| `results/investigation_latest.json` | Investigation result persistence path in `api.py` / `investigations/result_store.py` | `api.py` projection routes | Updated on successful retained-result persistence |
| `results/investigation_sessions/` | Investigation Session stores in `investigations/` | Session/evidence/analyze routes | Session lifecycle managed, append/update over time |

### Compatibility-Only Scripts

These remain for backward compatibility and historical verification. They are not official startup paths for new Investigation Session development.

- `code/prototype_v1/local_demo_launcher.py`
- `code/prototype_v1/ngrok_demo_launcher.py`
- `code/prototype_v1/demo_server_manager.py`
- `code/prototype_v1/resume_now.py`
- `code/prototype_v1/folder_watcher.py`
- `code/prototype_v1/watch_latest_image.py`

### Deprecated Scripts (Governance)

- Governance status for this phase: no script is physically removed.
- Deprecated behavior means the script is retained only for compatibility verification and is blocked/warned by default where implemented.
- Current deprecated operational paths are the same files listed in Compatibility-Only Scripts.

### Script Governance Tiers (Phase 2)

Each executable script in `code/prototype_v1` is assigned exactly one support tier.

| Script | Support tier | Responsibility | Classification reason |
|---|---|---|---|
| `code/prototype_v1/api.py` | CANONICAL | FastAPI application surface and canonical backend route contract. | Official backend service owned by canonical runtime contract. |
| `code/prototype_v1/start_assistant.py` | CANONICAL | Canonical backend/runtime supervisor and process guard. | Official startup entry point. |
| `code/prototype_v1/launch_demo.py` | CANONICAL | Canonical demo launcher and tunnel-aware operator workflow. | Official launcher entry point. |
| `code/prototype_v1/refresh_guidance.py` | CANONICAL | Canonical refresh/watch coordination. | Owned by canonical runtime supervision flow. |
| `code/prototype_v1/context_fusion.py` | CANONICAL | Canonical context-fusion writer. | Official writer for `results/context_fusion.json`. |
| `code/prototype_v1/glasses_demo.py` | CANONICAL | Canonical guidance/HUD payload generation. | Official writer for `results/resume_now.json`. |
| `code/prototype_v1/active_editor_context.py` | SUPPORTED DIAGNOSTIC | Active editor context normalization utility. | Safe helper utility, not runtime owner. |
| `code/prototype_v1/coding_context_pack.py` | SUPPORTED DIAGNOSTIC | Aggregates coding context signals for guidance. | Support utility for diagnostics and pipeline context. |
| `code/prototype_v1/coding_session_snapshot.py` | SUPPORTED DIAGNOSTIC | Produces coding session snapshot artifact. | Support utility, non-canonical launcher. |
| `code/prototype_v1/context_pack_prompt_preview.py` | SUPPORTED DIAGNOSTIC | Prompt preview helper from context artifacts. | Inspection utility; does not own runtime. |
| `code/prototype_v1/demo_live_investigation.py` | SUPPORTED DIAGNOSTIC | Manual investigation live/dry-run smoke runner. | Safe manual validation utility. |
| `code/prototype_v1/demo_scenario.py` | SUPPORTED DIAGNOSTIC | Repeatable recruiter/demo scenario runner. | Demonstration and validation script. |
| `code/prototype_v1/dev_demo_scenarios.py` | SUPPORTED DIAGNOSTIC | Development scenario fixture writer. | Developer support utility. |
| `code/prototype_v1/glasses_test_checklist.py` | SUPPORTED DIAGNOSTIC | Checklist generation for validation flows. | Documentation/validation helper. |
| `code/prototype_v1/https_tunnel_readiness.py` | SUPPORTED DIAGNOSTIC | HTTPS tunnel readiness guidance payload. | Diagnostic/readiness utility only. |
| `code/prototype_v1/https_tunnel_test_runner.py` | SUPPORTED DIAGNOSTIC | HTTPS tunnel test workflow helper. | Diagnostic/test utility only. |
| `code/prototype_v1/network_display_test.py` | SUPPORTED DIAGNOSTIC | LAN display/test payload utility. | Troubleshooting utility; non-canonical runtime owner. |
| `code/prototype_v1/repo_context.py` | SUPPORTED DIAGNOSTIC | Repository context extraction helper. | Safe support utility. |
| `code/prototype_v1/screenshot_watcher.py` | SUPPORTED DIAGNOSTIC | Optional screenshot-to-vision endpoint watcher. | Optional workflow utility; not canonical startup owner. |
| `code/prototype_v1/session_recovery.py` | SUPPORTED DIAGNOSTIC | Session recovery context utility. | Support utility for developer guidance context. |
| `code/prototype_v1/terminal_error_context.py` | SUPPORTED DIAGNOSTIC | Terminal error context extraction utility. | Support utility; no runtime ownership. |
| `code/prototype_v1/voice_readout.py` | SUPPORTED DIAGNOSTIC | Local TTS readout utility for latest guidance payload. | Optional local UX diagnostic utility. |
| `code/prototype_v1/test_api.py` | SUPPORTED DIAGNOSTIC | Manual API smoke invocation script. | Diagnostic helper, not production runtime owner. |
| `code/prototype_v1/test_completed_steps.py` | SUPPORTED DIAGNOSTIC | Scripted completed-step extraction validation. | Manual validation script. |
| `code/prototype_v1/test_continuity_flow.py` | SUPPORTED DIAGNOSTIC | Scripted continuity behavior validation. | Manual validation script. |
| `code/prototype_v1/test_glasses_guidance.py` | SUPPORTED DIAGNOSTIC | Scripted glasses guidance payload validation. | Manual validation script. |
| `code/prototype_v1/image_test.py` | SUPPORTED DIAGNOSTIC | Simple single-image OpenAI diagnostic script. | Developer diagnostic; not canonical workflow owner. |
| `code/prototype_v1/task_guidance_test.py` | SUPPORTED DIAGNOSTIC | Prompted task-guidance OpenAI diagnostic script. | Developer diagnostic; not canonical workflow owner. |
| `code/prototype_v1/vision_test.py` | SUPPORTED DIAGNOSTIC | Basic OpenAI vision connectivity diagnostic script. | Developer diagnostic; not canonical workflow owner. |
| `code/prototype_v1/folder_watcher.py` | COMPATIBILITY | Legacy/prototype folder watcher calling `watch_latest_image.py`. | Retained older workflow; not approved normal path. |
| `code/prototype_v1/watch_latest_image.py` | COMPATIBILITY | Legacy direct single-image analysis script. | Retained for historical verification and compatibility flows. |
| `code/prototype_v1/local_demo_launcher.py` | DEPRECATED | Legacy pre-V16 local launcher. | Blocked-by-default legacy path; duplicate runtime risk. |
| `code/prototype_v1/ngrok_demo_launcher.py` | DEPRECATED | Legacy pre-V16 ngrok launcher. | Blocked-by-default legacy path; tunnel/runtime conflict risk. |
| `code/prototype_v1/demo_server_manager.py` | DEPRECATED | Legacy V5.2 server manager with optional process spawning. | Blocked-by-default legacy path; non-canonical process ownership. |
| `code/prototype_v1/resume_now.py` | DEPRECATED | Legacy standalone resume payload writer. | Blocked-by-default legacy path; canonical artifact writer conflict. |

Canonical backend interpreter:

```
.\venv\Scripts\python.exe
```

Do not use `.venv` as the active backend runtime for this repository.

### Start the assistant

```
.\venv\Scripts\python.exe code\prototype_v1\start_assistant.py
```

This is the **only valid backend startup command**. `code\prototype_v1\start_assistant.py` owns canonical backend startup. It starts the API server and the 5-second refresh process as guarded subprocesses, pinned to the project `venv`, with single-instance lockfiles.

### Canonical runtime files

| Role | File |
|---|---|
| Startup entry point | `code/prototype_v1/start_assistant.py` |
| Pipeline watcher (spawned by start_assistant) | `code/prototype_v1/refresh_guidance.py` |
| Signal fusion | `code/prototype_v1/context_fusion.py` |
| HUD payload generator | `code/prototype_v1/glasses_demo.py` |
| API server | `code/prototype_v1/api.py` |
| Active-file signal | `vscode_extension/active-file-signal/extension.js` |

### One writer per artifact

| Artifact | Canonical writer |
|---|---|
| `results/active_editor_state.json` | VS Code extension only |
| `results/context_fusion.json` | `context_fusion.py` only |
| `results/resume_now.json` | `glasses_demo.py --auto` only |

### Legacy files — do not run

These files are quarantined. Running them will create duplicate runtime chains and bypass V16 single-instance guards. They will refuse to run by default and print an error.

| File | Risk |
|---|---|
| `code/prototype_v1/local_demo_launcher.py` | Starts duplicate uvicorn on :8001, writes resume_now.json |
| `code/prototype_v1/ngrok_demo_launcher.py` | Starts duplicate uvicorn on :8001, conflicts with Cloudflare tunnel |
| `code/prototype_v1/demo_server_manager.py` | `--start` flag spawns unvenv-pinned uvicorn |
| `code/prototype_v1/resume_now.py` | Overwrites resume_now.json with wrong schema |
