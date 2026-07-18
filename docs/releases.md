# Release Notes

## Phase 2B

- Added evidence collection endpoints for image and audio uploads, evidence listing, and hard delete.
- Added per-session evidence workspace storage under code/prototype_v1/results/investigation_sessions/<session_id>/evidence/ with atomic payload and metadata writes.
- Added server-managed sequence allocation persisted in a per-session evidence manifest so ordering survives restart and deletion does not renumber history.
- Added safe storage-ref validation, quarantine for malformed or unsafe evidence records, and controlled delete safety checks.
- Added bounded upload limits for image and audio evidence with controlled oversized-upload rejection.
- Added deterministic Phase 2B model/store/API tests covering ordering, rollback, dedupe, quarantine, auth, and zero OpenAI / zero Context Engine guarantees.
- Phase 2B remains storage-only and does not invoke OpenAI, Context Engine, transcription, embeddings, or streaming.

## Phase 2A

- Added InvestigationSession Phase 2A model with validated UUID identity, UTC timestamps, revision semantics, bounded metadata, and safe failure metadata.
- Added Phase 2A lifecycle transitions for created, collecting, paused, and cancelled states with deterministic idempotency behavior.
- Added dedicated session filesystem store under code/prototype_v1/results/investigation_sessions/ with atomic writes, malformed-file quarantine, and per-session write serialization.
- Added optional expected_revision conflict handling for session mutation endpoints.
- Added Phase 2A endpoints:
	- POST /investigation-sessions
	- GET /investigation-sessions/{session_id}
	- POST /investigation-sessions/{session_id}/pause
	- POST /investigation-sessions/{session_id}/resume
	- POST /investigation-sessions/{session_id}/cancel
- Added controlled session error categories for not found, invalid session ID, invalid transitions, revision conflicts, storage failures, validation failures, and unauthorized access.
- Added token enforcement on session endpoints using existing optional GLASSES_API_TOKEN behavior.
- Added deterministic Phase 2A model/store/lifecycle/API tests, including zero OpenAI and zero Context Engine invocation checks.
- Phase 2A still defers voice transcription and session analysis integration.

## Phase 1C

- Added investigation analysis endpoint workflow for ordered-image sessions.
- Added canonical retained investigation model as the single retained result source.
- Added desktop projection endpoint: GET /investigations/latest.
- Added glasses projection endpoint: GET /investigations/latest/glasses.
- Added deterministic Copilot prompt generation from retained investigation data.
- Added atomic persistence for retained investigation writes.
- Added unknown freshness handling in the desktop investigation panel.
- Added focused regression coverage for retention and atomic persistence behavior.
- Investigation suite status: 53 tests passing in code/prototype_v1/test_investigations_api.py.
