# Ideas to Implement in This Project

## 1) Task continuity MVP (high impact)
- Persist:
  - `current_task`
  - `last_completed_step`
  - `next_recommended_step`
  - `confidence`
- Inject this state into every context-aware prompt.
- Add “resume task” behavior after interruptions.

## 2) Confidence-aware response mode
- If confidence high: provide direct next step.
- If confidence medium: provide next step + one verification question.
- If confidence low: request retake/zoom/clarification before acting.

## 3) Voice-first concise output policy
- Enforce max spoken length (for example 1-2 short sentences).
- Provide optional “show more” text for phone/display logs.
- Prioritize actionability over explanation.

## 4) Vision + OCR fusion
- Run scene understanding and OCR in parallel.
- Merge into a structured context object:
  - `scene_summary`
  - `detected_objects`
  - `detected_text`
  - `risk_flags`

## 5) User memory profile
- Track stable preferences:
  - preferred response verbosity,
  - recurring tasks,
  - safety sensitivity settings.
- Keep these separate from per-task state.

## 6) Lightweight observability
- Add structured logs for:
  - latency by stage,
  - memory reads/writes,
  - tool failures,
  - fallback usage.
- This is essential for wearable UX tuning.

## 7) Failure-recovery workflow
- On network or model failure:
  - return a short offline-safe response,
  - preserve queued task state,
  - auto-retry when connectivity returns.
