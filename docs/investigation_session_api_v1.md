# Investigation Session API V1

Phase 1A adds a validation-only backend contract for Investigation Sessions.

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

Phase 1A performs validation and normalization only. It does not perform combined multimodal analysis yet.

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

Current Phase 1A placeholder values:

- `status`: `validated`
- `diagnosis`: `Investigation session received and validated.`
- `required_next_action`: `Proceed to combined multimodal analysis integration.`

These values are deterministic placeholder outputs and are not an AI diagnosis.

## Versioning Rule

The backend rejects unsupported schema versions. Phase 1A supports only `1.0`.

Combined multimodal analysis will be added in Phase 1B under the same endpoint contract unless a reviewed version increment becomes necessary.

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