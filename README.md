# Context-Aware AI Assistant for Workflow Continuity

This project is a local-first AI prototype that explores workflow-aware assistance for complex technical tasks.

Most AI assistants are effectively stateless and optimized for single interactions. They respond to the current prompt or screenshot, but they typically do not retain workflow context over time.

This prototype focuses on continuity across observations: it analyzes screenshots, maintains session state, tracks progress, detects stalled steps, and generates concise next-step guidance so users can continue technical workflows with less friction.
## Canonical Runtime (V16+)

> **One startup path. One writer per artifact. Venv only.**

## Execution Contract (Authoritative)

This section is the single authoritative execution contract for this repository.
If another document conflicts with this section, this section wins.

### Canonical Repository

- Active canonical repository path: `C:\Users\jesse\OneDrive\Documents\custom_meta_ai_glasses`
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

---


## Why I Built This

After spending more than a decade working with enterprise technology customers and technical teams, I repeatedly saw how easily context is lost during complex implementation and troubleshooting workflows.

As part of my transition into AI and software engineering, I built this project to explore whether a workflow-aware assistant could preserve task continuity, detect stalled progress, and provide real-time guidance designed for wearable interfaces.

## The Problem

Modern knowledge work often involves long, multi-step tasks across changing screens and tools.

- People lose context while working, especially when interrupted or switching windows.
- Most AI assistants respond to a single prompt or screenshot, but do not track workflow continuity over time.
- Without continuity, users get generic advice rather than actionable next steps based on where they are in the task.

## The Solution

This prototype provides a context-aware assistance loop built for continuity.

- Screenshot analysis: interprets what is happening in the current screen.
- Task continuity: classifies whether the current view is continuation, task switch, or new task.
- Progress tracking: captures completed steps and next step recommendations.
- Stuck detection: detects repeated next-step patterns that indicate lack of progress.
- Smart intervention: recommends interventions when stuck signals are present.
- Glasses-friendly guidance: generates concise guidance designed for lightweight display surfaces.

## Recruiter Highlights

- Python application development for end-to-end AI workflow prototypes.
- OpenAI API integration for multimodal screenshot analysis.
- Session memory architecture for continuity across sequential runs.
- Workflow state management for continuity, progress, and interventions.
- Structured JSON pipeline design for reproducible downstream consumption.
- Dashboard development for live state visibility and recruiter demos.
- Automated testing and smoke-test style scenario validation.
- AI-assisted product design with incremental milestone delivery.
- Wearable AI interaction concepts via glasses-friendly output constraints.

## Engineering Focus

This project is primarily an engineering effort in workflow orchestration and stateful AI application design, not model training.

Core focus areas include workflow state management, task continuity classification, progress tracking, interruption recovery, and user guidance generation from structured state.

The central challenge is maintaining context across sequential observations and converting that context into practical, actionable next-step recommendations. This is intentionally built as a workflow assistant rather than a traditional chatbot.

## Skills Demonstrated

- Python: orchestration scripts, parsing logic, and state-processing utilities.
- API Integration: practical local service integration for dashboard consumption.
- OpenAI API: multimodal screenshot analysis integration in the prototype pipeline.
- AI Application Development: end-to-end workflow-aware assistant implementation.
- State Management: continuity, progress, and intervention state derived per run.
- Workflow Automation: repeatable analysis flows and sequence-based demo execution.
- Structured JSON Pipelines: consistent output contracts for downstream rendering.
- Session Memory Architecture: persisted observation history and active-task state.
- Prompt Engineering: structured prompting for continuity-aware guidance output.
- Dashboard Development: recruiter-friendly UI for live state visualization.
- Testing and Validation: smoke tests, syntax checks, and scenario verification.
- Product Prototyping: iterative milestone delivery with measurable feature increments.
- Human-AI Interaction Design: concise, context-aware guidance for wearable surfaces.

## Current Features

- Structured JSON output in [code/prototype_v1/results/latest_response.json](code/prototype_v1/results/latest_response.json)
- Session memory in [code/prototype_v1/results/session_memory.json](code/prototype_v1/results/session_memory.json)
- Continuity and guidance logic in [code/prototype_v1/fix_writer.py](code/prototype_v1/fix_writer.py)
- Image analysis entrypoint in [code/prototype_v1/watch_latest_image.py](code/prototype_v1/watch_latest_image.py)
- Live dashboard in [code/prototype_v1/dashboard.html](code/prototype_v1/dashboard.html)
- Demo scenario runner in [code/prototype_v1/demo_scenario.py](code/prototype_v1/demo_scenario.py)
- Metrics snapshot and intervention visualization in the dashboard

## Current Status

### Implemented

- ✅ Task Continuity
- ✅ Progress Tracking
- ✅ Stuck Detection
- ✅ Resume Previous Task
- ✅ Smart Intervention
- ✅ Metrics Snapshot
- ✅ Demo Mode
- ✅ Demo Scenario Runner

## Architecture and Data Flow

Core flow:

1. A screenshot is provided to [code/prototype_v1/watch_latest_image.py](code/prototype_v1/watch_latest_image.py).
2. The assistant analyzes the image and generates structured task guidance.
3. [code/prototype_v1/fix_writer.py](code/prototype_v1/fix_writer.py) parses and writes structured output to [code/prototype_v1/results/latest_response.json](code/prototype_v1/results/latest_response.json).
4. Session context is persisted in [code/prototype_v1/results/session_memory.json](code/prototype_v1/results/session_memory.json).
5. The dashboard and demo scripts read the latest JSON to present state, intervention, and metrics.

Key prototype components:

- Prompt and guidance assembly: [code/prototype_v1/context_aware_prompt.py](code/prototype_v1/context_aware_prompt.py)
- Memory management: [code/prototype_v1/memory_manager.py](code/prototype_v1/memory_manager.py)
- API bridge for dashboard polling: [code/prototype_v1/api.py](code/prototype_v1/api.py)
- Optional auto-processing watcher: [code/prototype_v1/folder_watcher.py](code/prototype_v1/folder_watcher.py)

## Architecture Diagram

```text
Screenshot Input
   |
   v
Image Analysis
   |
   v
Task Continuity
   |
   v
Session Memory
   |
   v
Progress Tracking
   |
   v
Stuck Detection
   |
   v
Resume Previous Task
   |
   v
Smart Intervention
   |
   v
Metrics Snapshot
   |
   v
Dashboard / Glasses Guidance
```

Stage summary:

- Screenshot Input: a new image is provided to the local pipeline.
- Image Analysis: model inference produces structured workflow observations.
- Task Continuity: classifies whether the flow is continuation, switch, or new task.
- Session Memory: observations and active task context are persisted for later runs.
- Progress Tracking: completed steps and next step are extracted into structured state.
- Stuck Detection: repeated next-step patterns are evaluated for stalled progress.
- Resume Previous Task: prior task context is surfaced when relevant.
- Smart Intervention: concise intervention guidance is generated when stuck signals are present.
- Metrics Snapshot: lightweight behavioral counters summarize recent pipeline behavior.
- Dashboard / Glasses Guidance: structured output is rendered for recruiter view and concise wearable guidance.

## Run Locally

Prerequisites:

- Python 3.11+ (3.12 recommended)
- An OpenAI API key in the root .env file as OPENAI_API_KEY

Setup:

1. Use the canonical project environment at `.\venv`.
2. Install dependencies from [code/prototype_v1/requirements.txt](code/prototype_v1/requirements.txt).
3. Run one analysis directly:
   .\venv\Scripts\python.exe code\prototype_v1\watch_latest_image.py code\prototype_v1\test_images\test_image.png

Canonical backend startup:

1. Start the backend:
   .\venv\Scripts\python.exe code\prototype_v1\start_assistant.py
2. Open [code/prototype_v1/dashboard.html](code/prototype_v1/dashboard.html).

### Legacy / Diagnostic Commands

These commands are retained only for diagnostics, historical reference, or compatibility verification. They are not the canonical production path and must not be used for new Investigation Session development.

1. Direct manual Uvicorn startup:
   `python -m uvicorn api:app --host 127.0.0.1 --port 8001 --app-dir code/prototype_v1`
2. Legacy launchers under `code/prototype_v1/`:
   `local_demo_launcher.py`, `ngrok_demo_launcher.py`, `demo_server_manager.py`, and `resume_now.py`

## Demo Workflow (Recruiter-Friendly)

Run the repeatable demo scenario script:

.\venv\Scripts\python.exe code\prototype_v1\demo_scenario.py

What it does:

1. Runs a Razer task image.
2. Runs the same Razer image again to demonstrate stuck detection and intervention behavior.
3. Runs a scenic image to demonstrate new-task behavior.
4. Prints a clean summary after each run:
   - image filename
   - task continuity
   - task progress
   - stuck status
   - intervention message
   - glasses guidance

## Evaluation Snapshot

Current validation coverage is based on repository test scripts and scenario runners. The project intentionally uses practical smoke-validation for behavior checks rather than benchmark metrics.

- Continuity testing: [code/prototype_v1/test_continuity_flow.py](code/prototype_v1/test_continuity_flow.py) validates continuation and new-task classification on known images, with an optional task-switch case.
- Progress tracking validation: [code/prototype_v1/test_completed_steps.py](code/prototype_v1/test_completed_steps.py) validates completed steps extraction and non-empty step count.
- Stuck detection positive tests: [code/prototype_v1/demo_scenario.py](code/prototype_v1/demo_scenario.py) includes a repeated-task run designed to surface stuck and intervention behavior in output.
- Stuck detection negative tests: [code/prototype_v1/demo_scenario.py](code/prototype_v1/demo_scenario.py) includes a scenic new-task run used to observe non-stuck behavior in practice.
- Resume previous task validation: [code/prototype_v1/dashboard.html](code/prototype_v1/dashboard.html) and [code/prototype_v1/demo_scenario.py](code/prototype_v1/demo_scenario.py) expose resume fields from [code/prototype_v1/results/latest_response.json](code/prototype_v1/results/latest_response.json) for scenario verification.
- Demo scenario validation: [code/prototype_v1/demo_scenario.py](code/prototype_v1/demo_scenario.py) executes a repeatable three-step recruiter flow and verifies latest response readability after each stage.

## Privacy and Local-First Considerations

- Runtime state is stored locally in JSON files under [code/prototype_v1/results](code/prototype_v1/results).
- No local database or external analytics service is required for the prototype.
- The pipeline can be run directly from local scripts without dashboard or API interaction.
- Screenshots may contain sensitive information, so teams should use controlled test data and environment-level secret management.

## Future Research Direction

- Voice-first workflow guidance for hands-free step navigation.
- Context-aware wearable computing for low-friction task support.
- Smart glasses interfaces for concise, glanceable assistance.
- Workflow interruption recovery strategies under realistic context switching.
- Real-time developer assistance for technical troubleshooting sequences.
- Human-AI collaboration systems focused on continuity and execution support.

## Roadmap

- Voice readout for hands-free guidance consumption.
- Hosted glasses web app for lightweight device delivery.
- Meta Ray-Ban Display integration for real-world wearable workflows.
- Expanded metrics and evaluation harness for quality tracking across scenarios.

## Why This Matters

This project demonstrates a practical path beyond one-shot AI interactions toward workflow-aware assistance that retains context, tracks progress, and supports interruption recovery. The long-term value is reliable task continuity and actionable guidance delivered in formats that can extend to wearable AI experiences.
