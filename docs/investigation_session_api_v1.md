# Investigation Session API V1

This document is the Android-facing Investigation Session contract for the backend in this repository.

## Contract Scope

Current canonical mobile polling contract:

- GET /investigation-sessions/{session_id}/poll

Supporting session contract endpoints (same namespace):

- POST /investigation-sessions
- GET /investigation-sessions/{session_id}
- POST /investigation-sessions/{session_id}/pause
- POST /investigation-sessions/{session_id}/resume
- POST /investigation-sessions/{session_id}/cancel
- POST /investigation-sessions/{session_id}/evidence/image
- POST /investigation-sessions/{session_id}/evidence/audio
- GET /investigation-sessions/{session_id}/evidence
- DELETE /investigation-sessions/{session_id}/evidence/{evidence_id}
- POST /investigation-sessions/{session_id}/analyze

There is one canonical session-specific polling contract. Global latest endpoints are convenience read models and are not session polling contracts.

## Current Implementation

### Session Status Enum

Session status values are:

- created
- collecting
- paused
- finalizing
- analyzing
- failed
- completed
- cancelled

### Polling Endpoint

Method and path:

- GET /investigation-sessions/{session_id}/poll

Request requirements:

- session_id path parameter must be a valid UUID.
- Optional auth token follows existing glasses/session rule:
  - query token, or
  - Authorization: Bearer <token>
  - only enforced when GLASSES_API_TOKEN is configured.

Polling response model:

- session_id: string UUID
- investigation_id: string or null
- status: session status enum value
- created_at: UTC timestamp
- updated_at: UTC timestamp
- image_count: integer >= 0
- explanation_present: boolean
- retryable: boolean
- error: object or null
- compact_result: object or null
- result_available: boolean
- poll_after_ms: integer hint in milliseconds

Polling error object shape (when error is present):

- category: string
- message: string
- occurred_at_utc: UTC timestamp or null

Compact result shape (when present) is the compact glasses projection:

- schema_version
- projection_version
- investigation_id
- status
- diagnosis_short
- required_next_action_short
- uncertainty_flag
- freshness_state
- completed_at_utc
- age_seconds

Polling semantics:

- Read-only and idempotent.
- Repeated polling does not mutate session state.
- Polling does not invoke OpenAI.
- Polling does not invoke Context Engine loading.
- Polling does not create investigations, retained results, or evidence.

### Analyze Trigger Endpoint

Method and path:

- POST /investigation-sessions/{session_id}/analyze

Execution model:

- Current implementation is synchronous request/response orchestration.
- The route invokes the canonical InvestigationOrchestrator in-process.
- No background queue is used in this milestone.

Request requirements:

- session_id path parameter must be a valid UUID.
- Optional JSON body:
  - expected_revision: integer >= 0 (optional optimistic revision guard)
- Optional auth token follows existing glasses/session rule:
  - query token, or
  - Authorization: Bearer <token>
  - only enforced when GLASSES_API_TOKEN is configured.

Preconditions enforced before orchestration:

- Session must exist.
- Session must be collecting.
- Session must not be cancelled.
- Session must not already be finalizing or analyzing.
- Completed sessions are treated as idempotent success (no new provider call).
- Session must contain 1 to 3 accepted image evidence records.
- Image payload files must be present and readable.
- Explanation must be derivable from stored normalized_text evidence fields.

Stored evidence and explanation mapping:

- Image set comes from stored session evidence ordered by sequence_number (then evidence_id for stable ties).
- selected_capture_evidence_ids for orchestrator input follow that deterministic image order.
- normalized_explanation_text is sourced from stored normalized_text values across session evidence, including audio evidence transcripts when present.
- Android does not resend image bytes for this route.

Analyze trigger response model:

- session_id
- investigation_id (nullable)
- status
- accepted
- result_available
- compact_result (nullable)
- retryable
- error (nullable)
- poll_url

Lifecycle behavior:

- Successful path: collecting -> finalizing -> analyzing -> completed
- Failure path (caught orchestration failure after analysis start): finalizing/analyzing -> failed
- Polling remains read-only and does not mutate timestamps.

Duplicate and concurrency behavior:

- Completed session analyze calls are idempotent and do not invoke provider again.
- Calls while finalizing/analyzing return stable 409 conflict.
- Attempt ownership and session revision guards prevent duplicate simultaneous ownership under current local locking design.

### Polling Field Behavior

session_id vs investigation_id:

- session_id is always the stable session UUID.
- investigation_id is null until a canonical retained result linked to this session can be loaded.

compact_result behavior:

- null while no canonical retained result is linked/available.
- present only when session.completed_result_id resolves to a canonical retained result.

result_available behavior:

- true when compact_result is present.
- false when compact_result is null.

retryable behavior:

- false for completed or cancelled sessions.
- otherwise true when no last_error exists.
- when last_error exists, mirrors last_error.retryable.

poll_after_ms meaning:

- server hint for recommended next poll interval.
- current values:
  - 30000 when result_available is true
  - 1500 during finalizing or analyzing
  - 5000 otherwise

### Error Contract For Session Endpoints

Session endpoints return structured errors as:

- detail.category
- detail.message

Common status codes:

- 404: resource not found (for example session_not_found, evidence_not_found)
- 409: state/revision conflict (for example invalid_state_transition, revision_conflict)
- 422: validation/ID/upload issues (for example invalid_session_id, invalid_evidence_id, validation_error, invalid_upload)
- 500: storage/backend availability failures (for example session_storage_error, evidence_storage_error)

Analyze trigger status code expectations:

- 404: unknown session_id
- 409: invalid lifecycle transition, revision conflict, or analysis attempt conflict
- 422: invalid or incomplete evidence, missing explanation, invalid request fields
- 500: safe orchestration/storage failures

Additional evidence upload statuses:

- 413: upload_too_large
- 415: unsupported_media_type

400 status note:

- Session endpoints in this contract namespace do not currently use 400 for validation.
- Legacy investigation analyze routes outside this namespace may return 400 with route-specific validation messages.

## Compatibility Notes

Backward compatibility preserved:

- Existing legacy routes are unchanged.
- Existing demo routes are unchanged.
- Existing dashboard-related routes are unchanged.
- Global latest routes remain available and unchanged.
- Session polling was added additively via /investigation-sessions/{session_id}/poll.
- Session analysis trigger is additive at /investigation-sessions/{session_id}/analyze.

Timestamp naming note:

- Session lifecycle models use created_at_utc and updated_at_utc.
- Polling response intentionally exposes created_at and updated_at mapped from the same UTC session timestamps.

## Planned Future Work (Not Yet Implemented)

- Background queue/worker execution model for session analysis.
- Additional explicit server-driven polling/backoff policy controls beyond static hints.
- Expanded auth hardening policy for production deployment.
- Formal deprecation plan (if ever required) for non-session global latest convenience routes.

Cancellation limitation (current implementation):

- Mid-request cancellation during synchronous orchestrator execution is not currently supported.
- Cancellation is enforced before analysis begins, and terminal cancellation is reflected by polling.

Do not treat planned items as currently implemented behavior.