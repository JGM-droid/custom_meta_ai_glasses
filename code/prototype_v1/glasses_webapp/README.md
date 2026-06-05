# Glasses Web App MVP

This folder contains a dedicated compact HUD client for Meta Ray-Ban Display style rendering.

## Purpose

Render only compact guidance fields from `/glasses/latest`:

- headline
- next action
- blocked/not blocked
- confidence
- short reason
- active context
- stale/error state

## Local usage

1. Start backend:

   - `python code/prototype_v1/start_assistant.py`

2. Open:

   - `http://127.0.0.1:8001/glasses`

3. Optional API override:

   - `http://127.0.0.1:8001/glasses?api=http://127.0.0.1:8001/glasses/latest`

4. Optional token query:

   - `http://127.0.0.1:8001/glasses?token=YOUR_TOKEN`

## Security

- If `GLASSES_API_TOKEN` is set on the backend, `/glasses/latest` requires a token.
- The client supports token usage by:
  - query parameter `?token=...` and/or
  - Authorization header `Bearer <token>` when token query is present.
- No OpenAI key is exposed through this client.

## Notes

- UI is 600x600-first with high contrast and no debug/prompt panels.
- This client is separate from `glasses_display_mock.html`.
