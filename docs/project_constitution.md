# Custom Meta AI Glasses Project Constitution

Authoritative scope: This document defines architecture boundaries and guardrails for the backend repository at C:/Users/jesse/OneDrive/Documents/custom_meta_ai_glasses and its integration relationship with Android client work.

Evidence basis for this constitution:
- README.md
- AGENTS.md
- code/prototype_v1/api.py
- code/prototype_v1/investigations/
- code/prototype_v1/context_fusion.py
- code/prototype_v1/dashboard.html
- code/prototype_v1/glasses_display_mock.html
- code/prototype_v1/glasses_webapp/
- code/prototype_v1/start_assistant.py
- code/prototype_v1/refresh_guidance.py
- code/prototype_v1/test_investigations_api.py
- code/prototype_v1/test_investigation_sessions_phase2a.py
- code/prototype_v1/test_investigation_interaction_state_machine.py
- code/prototype_v1/test_investigation_orchestrator.py
- docs/ARCHITECTURE.md
- docs/investigation_session_api_v1.md
- docs/releases.md
- architecture/Phase2_System_Design.md

Implementation status legend used in this document:
- Implemented: Verified in current code and tests.
- Partially implemented: Present in code but not fully exposed as stable Android-facing contract.
- Planned: Documented intent with no complete implementation yet.
- Explicitly deferred: Intentionally out of current implementation scope.

## 1. Product Vision

Target product:
- Hands-free multimodal assistance for technical investigations.
- Meta Ray-Ban Display glasses as the wearable endpoint.
- Android as the capture and integration client.
- FastAPI backend as the orchestration and contract layer.
- OpenAI as the primary model and vision provider.
- Compact wearable guidance for glasses/Android.
- Full technical desktop output, including a Copilot-ready prompt.
- Recruiter-ready end-to-end demonstration of capture, analysis, and action guidance.

Current state relative to this vision:
- Implemented: FastAPI backend runtime, OpenAI-backed analysis paths, retained-result projections, desktop and glasses-facing outputs.
- Partially implemented: Investigation session lifecycle and orchestration are advanced in backend, but Android production contract is not fully finalized for mobile-first polling and submission.
- Planned: Full Android capture client integration through stable session contracts.
- Explicitly deferred: Production auth hardening, hosted production deployment, and advanced observability.

## 2. Primary User Workflow

Canonical Investigation Session workflow:
1. User starts an investigation.
2. User captures 1 to 3 ordered images.
3. User provides one spoken or typed explanation.
4. Android submits one combined session.
5. Backend validates and orchestrates analysis.
6. Context Engine produces one diagnosis and one required next action.
7. Android or glasses receive compact guidance.
8. Desktop dashboard receives the full technical response and Copilot prompt.

Workflow priority:
- Multi-capture investigation is the primary workflow.
- Single-photo analysis remains a secondary quick workflow.

Current implementation reality:
- Implemented: Multi-image combined analysis at POST /investigations/analyze with ordered evidence and one normalized explanation.
- Implemented: Session and evidence lifecycle APIs under /investigation-sessions/.
- Partially implemented: Backend interaction/orchestration internals currently support one selected capture minimum in some flows, while retained canonical investigation output enforces 2 to 3 images.
- Planned: Android-side session submission and mobile polling as primary client behavior.

## 3. Repository Ownership

This program is split across separate codebases.

### custom_meta_ai_glasses

Owns:
- FastAPI API
- Investigation Session contracts
- Validation
- Orchestration
- Context Engine integration
- OpenAI calls
- Persistence
- Retained results
- Desktop projections
- Compact glasses projections
- Backend tests

Primary paths in this repository:
- code/prototype_v1/api.py
- code/prototype_v1/investigations/
- code/prototype_v1/results/
- code/prototype_v1/dashboard.html
- code/prototype_v1/glasses_display_mock.html
- code/prototype_v1/glasses_webapp/

### meta-wearables-dat-android / custom Android client

Owns:
- Meta DAT SDK integration
- Wearable registration
- Camera streaming
- Image capture
- Local capture ordering before submission
- Explanation input
- Speech-to-text on the Android device
- API networking
- Upload and polling states
- Compact result rendering

Integration rule:
- Repositories communicate through HTTP APIs.
- Physical folder proximity does not define architectural integration.

## 4. Component Responsibility Boundaries

Locked boundaries:
- Android is a lightweight capture client.
- Android must not contain OpenAI keys.
- Android must not perform diagnosis or duplicate Context Engine logic.
- Backend is the sole owner of investigation orchestration.
- Context Engine remains canonical and must not be duplicated.
- Desktop dashboard owns full technical and copyable output.
- Glasses/Android own concise guidance and status output only.
- Retained results are server-owned.
- Global latest result convenience endpoints must not replace session-specific polling for production clients.

Current state:
- Implemented: Backend owns orchestration and retained results.
- Implemented: OpenAI access and keys are backend-side only.
- Implemented: Desktop and compact projections are separated at endpoint level.
- Implemented: Mixed legacy and investigation-era endpoints coexist; production mobile session polling contract is finalized under /investigation-sessions/{session_id}/poll.

## 5. Canonical Architecture

Canonical target architecture:

Meta Ray-Ban Display Glasses
        |
        v
Android CameraAccess Client
        |
        | HTTPS / Investigation API
        v
FastAPI Backend
        |
        v
Investigation Session Service
        |
        v
Canonical Context Engine
        |
        v
OpenAI
        |
        +--> Compact Android/Glasses Projection
        |
        +--> Full Desktop Dashboard Projection

Non-duplication rule:
- No second AI path.
- No second Context Engine.
- No Android-side orchestration engine.

Current code alignment:
- Implemented: Single backend AI call path per investigation request in service/orchestrator flows.
- Implemented: Shared retained result powering desktop and glasses projections.
- Partially implemented: Legacy /latest and /glasses/latest routes remain for HUD continuity and are not session-scoped investigation contracts.

## 6. Investigation Session Rules

Locked rules:
- 1 to 3 images per investigation session workflow.
- Capture order must be preserved.
- One explanation per submitted session.
- One stable session identifier.
- One stable investigation identifier once analysis begins.
- Idempotency where applicable.
- Structured validation errors.
- Pollable processing state.
- Compact result projection.
- Retained desktop result.
- Reset and retry behavior must be explicit.
- Failed uploads must not corrupt the last valid retained result.

Current implementation constraints versus target Android-facing contract:

Current backend constraints (implemented now):
- POST /investigations/analyze validates 2 to 3 images and requires schema_version 1.0.
- Session lifecycle and evidence APIs are live under /investigation-sessions/*.
- Evidence ordering is server-managed and persisted per session.
- Retained investigation result model requires image_count 2 to 3 for canonical retained projections.
- Atomic result write behavior is implemented so failed analysis does not overwrite previous retained result.

Target Android-facing contract (to finalize before full Android integration):
- Session-first submission and polling contract should be the canonical mobile path.
- Mobile workflow must enforce 1 to 3 capture UX while preserving backend validation invariants.
- Session-specific status/result polling should replace dependence on global latest convenience routes for production mobile clients.

## 7. API Contract Principles

Contract principles:
- Production Android code must not depend permanently on demo-only endpoints.
- Backend contracts must be finalized and tested before Android integration.
- Routes should be additive rather than breaking existing routes.
- Legacy routes remain unchanged unless a separate approved migration is performed.
- Android should use a session-specific status/result contract.
- Global latest routes are dashboard conveniences, not canonical mobile polling contracts.
- Field names, status values, MIME rules, size limits, and errors must be tested.

Current status:
- Implemented: Strong contract and validation tests for investigation analyze and session/evidence APIs.
- Implemented: Session-specific result polling contract is stable and tied to canonical session lifecycle and retained result linkage.

## 8. Model Provider and Secret Handling

Rules:
- OpenAI is the primary provider unless explicitly changed by user direction.
- OpenAI API keys remain server-side.
- Android must never contain provider secrets.
- Local development secrets belong in environment variables or ignored local configuration.
- Logs must not print secrets.
- Client-visible errors must not leak internal prompts or credentials.

Current status:
- Implemented: Backend loads OpenAI key from environment/.env paths server-side.
- Implemented: Optional token auth for glasses/session endpoints.
- Planned: Broader production-grade secret hygiene and centralized deployment policy.

## 9. Meta DAT Preservation Strategy

Strategy:
- Meta official repository is an upstream reference.
- Long-term custom product work should not remain as uncontrolled edits inside official sample code.
- A separate custom Android repository or controlled fork will be established before significant product implementation.
- Future Meta SDK changes should remain reviewable and mergeable.
- Vendor sample code should be changed minimally.
- DAT registration and camera-stream behavior should not be refactored merely to add backend networking.

Decision status:
- This repository currently contains backend code only.
- Final Android repository strategy is an architectural decision that must be completed before substantial Android implementation.

## 10. Development Guardrails

Guardrails:
- Inspect for duplicate files, processes, routes, stores, and data sources before adding components.
- Prefer minimal additive changes.
- Do not perform broad cleanup during focused feature slices.
- Do not mix unrelated refactors with feature work.
- Inspect installed library versions before adding dependencies or using fast-changing APIs.
- Use non-interactive Git commands.
- Never run destructive Git commands without explicit user approval.
- Preserve existing passing behavior.
- Add tests before or with contract changes.
- Keep implementation slices small enough for focused review.
- Document any intentional deviation from this constitution.

## 11. Testing and Acceptance Standards

Expected validation standards:
- Python compilation where relevant.
- Focused unit tests.
- Full backend pytest suite.
- Android unit tests for capture order and networking.
- UI tests for submission and status states.
- Physical-phone testing.
- Meta glasses end-to-end test.
- Desktop projection verification.
- Git diff review.
- Git status review.
- Confirmation that unrelated files were not changed.

Current state:
- Implemented: Broad backend contract/lifecycle/orchestration test coverage.
- Planned: Android unit/UI/physical tests and production-client contract validation.

## 12. Git Workflow

Preferred workflow:

git --no-pager status
git add .
git --no-pager status
git commit -m "<meaningful message>"
git push

Commit policy:
- Commits should represent coherent milestones.

## 13. Implementation Roadmap

### Completed or substantially implemented

- Backend FastAPI runtime.
- Context Engine and context fusion pipeline.
- Investigation Session foundation.
- Retained result persistence.
- Desktop dashboard output.
- Compact glasses projection output.
- CameraAccess/DAT discovery and architecture audit (documentation and analysis level).

### Next

- Project Constitution (draft complete; architect ratification pending).
- Slice 1A backend Android-facing contract preparation.
- Slice 1B Android networking foundation.
- Slice 1C ordered image-session state.
- Slice 1D explanation and submission UI.
- Slice 1E polling and compact result UI.
- Slice 1F physical Android phone test.
- Slice 1G Meta glasses end-to-end demo.

### Later

- Spoken explanation through Android speech-to-text.
- Guided walkthrough or short video context mode.
- Production authentication.
- Stable hosted backend or managed tunnel.
- Improved observability.
- Polished recruiter demo.

## 14. Locked Decisions

| Decision | Status | Rationale | Change authority |
|---|---|---|---|
| Meta Ray-Ban Display is the target wearable | Locked | Core product direction and recruiter demo goal | User/Lead Architect approval required |
| OpenAI is the primary model provider | Locked | Existing backend and tests are built around OpenAI contract behavior | User/Lead Architect approval required |
| Multi-capture session is the primary UX | Locked | Better investigation quality and sequence context than single-image quick checks | User/Lead Architect approval required |
| Backend owns orchestration | Locked | Prevents duplicate client-side logic and preserves deterministic lifecycle | User/Lead Architect approval required |
| Android remains lightweight | Locked | Keeps secrets and orchestration server-side; reduces drift and duplication | User/Lead Architect approval required |
| Desktop owns full output | Locked | Enables rich technical guidance and copyable Copilot prompts | User/Lead Architect approval required |
| Repositories remain separate | Locked | Supports clean ownership boundaries and controlled integration | User/Lead Architect approval required |
| No duplicate Context Engine | Locked | Maintains one source of truth for context-aware guidance | User/Lead Architect approval required |
| Backend contract is completed before Android networking | Locked | Prevents client churn and integration breakage | User/Lead Architect approval required |
| Meta official sample is not the long-term uncontrolled product repository | Locked | Preserves upstream mergeability and reduces vendor drift | User/Lead Architect approval required |

## 15. Decision-Change Procedure

Locked architecture decisions may change only when:
1. The reason is documented.
2. Affected components are identified.
3. Migration and rollback are defined.
4. Tests are updated.
5. The user approves the change.

## 16. Definition of Done for the First Wearable Demo

The first true demo is complete only when all are true:
- Glasses are connected through Meta DAT.
- User captures 1 to 3 images.
- Explanation is entered or spoken.
- Android submits the session.
- Backend analyzes it through the canonical Context Engine.
- Android shows compact guidance.
- Desktop dashboard shows the full Copilot-ready prompt.
- Failures are understandable and retryable.
- No provider secrets exist on Android.
- Tests pass.
- No duplicate architecture was introduced.

## 17. Current Reality, Conflicts, and Gaps

### 17.1 Implemented

- FastAPI runtime with canonical startup path in code/prototype_v1/start_assistant.py and code/prototype_v1/api.py.
- Investigation analyze route and retained projection routes:
  - POST /investigations/analyze
  - GET /investigations/latest
  - GET /investigations/latest/glasses
- Investigation session lifecycle/evidence routes in api.py under /investigation-sessions/*.
- Orchestrator pipeline with deterministic stage events in code/prototype_v1/investigations/investigation_orchestrator.py.
- Retained/canonical result persistence with atomic writes in code/prototype_v1/investigations/result_store.py.
- Dashboard and glasses UI layers:
  - code/prototype_v1/dashboard.html
  - code/prototype_v1/glasses_display_mock.html
  - code/prototype_v1/glasses_webapp/

### 17.2 Partially implemented

- Session-centric orchestration and production Android session polling/analyze contracts are implemented as the canonical mobile path in this backend.
- Some internal/session-interaction flows support one selected capture during orchestration, while retained canonical projection model enforces 2 to 3 image results.
- Legacy HUD endpoints (/latest, /glasses/latest) and investigation endpoints coexist; governance is needed so mobile clients rely on canonical session-scoped contracts.

### 17.3 Planned

- Finalized Android-facing session-specific status/result contract.
- Android networking integration and capture UX implementation.
- End-to-end physical Meta glasses demonstration through Android + backend flow.

### 17.4 Explicitly deferred

- Production-grade auth and hosted deployment.
- Expanded observability stack.
- Broad non-essential refactoring during slice delivery.

### 17.5 Documentation conflicts found (not modified in this task)

- Conflict A:
  - docs/investigation_session_api_v1.md currently defines analyze image count as exactly 2 or 3.
  - Target constitution workflow sets primary session UX to 1 to 3 captures.
  - Current code reality is mixed: retained canonical results enforce 2 to 3, while some session-interaction/orchestration pathways can operate from one selected capture.

- Conflict B:
  - architecture/Phase2_System_Design.md describes broader designed lifecycle states (ready, awaiting_more_evidence, archived and others) as full design.
  - Current externally exposed session lifecycle endpoints and existing test emphasis are still centered on the implemented subset and incremental expansion.

- Conflict C:
  - architecture/system_architecture.md and architecture/architecture_decisions.md emphasize older iPhone-centered flow narratives.
  - Current backend has concrete FastAPI investigation/session APIs that align more directly with Android client integration as the capture submitter.

### 17.6 Current-code versus target-architecture gaps documented

- Gap 1: Canonical mobile contract finalization
  - Needed: Session-specific status/result polling contract for Android production integration.
  - Current: Global latest convenience routes still coexist and can be misused by mobile clients.

- Gap 2: 1-to-3 capture policy harmonization
  - Needed: Unified rules across interaction state machine, orchestration persistence, retained result model, and public API docs.
  - Current: Mixed enforcement between one-capture capable internal flows and retained 2-to-3 canonical projection constraints.

- Gap 3: Android repository implementation readiness
  - Needed: Controlled Android repo/fork strategy ratified before substantial Android implementation.
  - Current: Backend is ready for contract hardening, but Android production integration is not yet complete.
