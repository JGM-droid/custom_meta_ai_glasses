# Investigation Session API V1

Phase 1B performs one combined multimodal analysis for Investigation Sessions.

## Endpoint

- `POST /investigations/analyze`

## Multipart Fields

- `schema_version`: string
- `session_id`: string
- `idempotency_key`: string
- `user_explanation`: string
- `images`: repeated uploaded files in client order

## Validation Rules

- Supported `schema_version`: `1.0`
- `session_id` must be present and non-empty after trimming
- `idempotency_key` must be present and non-empty after trimming
- `user_explanation` may be empty and is normalized by collapsing internal whitespace
- `images` must contain exactly 2 or 3 files
- upload order is preserved exactly as received
- only `image/jpeg` and `image/png` are accepted
- empty uploaded files are rejected

Phase 1B uses one combined model request with all uploaded images (2 or 3) in capture order and the normalized spoken explanation.
Optional Context Engine enrichment may be included when available.

## Response Model

- `schema_version`
- `investigation_id`
- `session_id`
- `status`
- `diagnosis`
- `required_next_action`
- `image_count`
- `image_order`
- `used_user_explanation`

`image_order` contains one entry per uploaded image using this format:

- `<1-based position>:<original filename>`

Examples:

- `1:first.png`
- `2:second.png`
- `1:capture.png`
- `2:capture.png`

Phase 1A baseline placeholder values were:

- `status`: `validated`
- `diagnosis`: `Investigation session received and validated.`
- `required_next_action`: `Proceed to combined multimodal analysis integration.`

These values are deterministic placeholder outputs and are not an AI diagnosis.

## Phase 1B Success Behavior

- `status` is `analyzed`
- `diagnosis` is produced by one combined multimodal model result
- `required_next_action` is produced by the same model result
- the model analyzes all images together as one investigation sequence
- image upload order is used as capture sequence context
- no per-image model calls are made

The successful response model remains unchanged:

- `schema_version`
- `investigation_id`
- `session_id`
- `status`
- `diagnosis`
- `required_next_action`
- `image_count`
- `image_order`
- `used_user_explanation`

Future delivery work:

- concise glasses output publishing
- detailed desktop web result presentation

## Phase 1C: Retention And Delivery

Phase 1C adds retained latest-result delivery without changing the `POST /investigations/analyze` response schema.

### Retention Behavior

- On successful `POST /investigations/analyze`, the backend writes one retained result file:
  - `code/prototype_v1/results/investigation_latest.json`
- Writes are atomic and replace the previous retained result only after a successful analysis.
- On analysis failure, the previous retained result remains unchanged.
- Retained data excludes raw image bytes.

### New Retrieval Endpoints

- `GET /investigations/latest`
  - Returns desktop projection with:
    - diagnosis
    - required_next_action
    - copilot_prompt
    - freshness metadata
  - `404` when no retained result exists
  - `500` when retained result is unreadable or schema-invalid

- `GET /investigations/latest/glasses`
  - Returns compact glasses projection with:
    - diagnosis_short
    - required_next_action_short
    - uncertainty_flag
    - freshness metadata
  - Follows the same `GLASSES_API_TOKEN` auth convention as other glasses endpoints
  - `404` when no retained result exists

- `GET /investigations`
  - Optional desktop alias route to the existing mock display page.

### Freshness

- Projection freshness is derived from retained `completed_at_utc`.
- `INVESTIGATION_RESULT_STALE_SECONDS` controls stale threshold.
  - default: `900` seconds
- `freshness_state` values:
  - `fresh`
  - `stale`
  - `unknown`

### Copilot Prompt Generation

- One deterministic prompt is generated from retained fields.
- Prompt includes diagnosis, required next action, context usage/freshness summary, and guarded implementation instructions.
- No additional OpenAI calls are used for retrieval projections or prompt generation.

## Versioning Rule

The backend rejects unsupported schema versions. Phase 1A supports only `1.0`.

Phase 1B combined multimodal analysis is implemented under the same endpoint contract.

## Example PowerShell Request

```powershell
curl.exe -X POST "http://127.0.0.1:8001/investigations/analyze" ^
  -F "schema_version=1.0" ^
  -F "session_id=session-123" ^
  -F "idempotency_key=idem-123" ^
  -F "user_explanation=The display is blank after reboot." ^
  -F "images=@C:\path\to\capture1.png;type=image/png" ^
  -F "images=@C:\path\to\capture2.jpg;type=image/jpeg"
```