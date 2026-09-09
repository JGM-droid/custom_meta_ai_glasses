# Architecture Patterns for Wearable Multimodal Agents

## Pattern 1: Phone-centered multimodal pipeline (recommended default)

```text
Glasses Camera/Mic
  -> Phone Ingestion Service
  -> Multimodal Inference (Vision + ASR + LLM)
  -> Memory Manager (task + session + preferences)
  -> Response Composer
  -> Audio/Display Output
```

Why it works:
- aligns with current wearable hardware constraints,
- keeps glasses lightweight,
- centralizes auth/network/retries on phone.

## Pattern 2: Event-driven agent loop

```text
Event (new frame / wake-word / user command)
  -> Context Builder
  -> Planner Agent
  -> Tool Calls (OCR, object detect, calendar, notes)
  -> Verifier/Safety Layer
  -> Action + next-step memory update
```

Design pattern:
- use explicit event types and idempotent handlers,
- persist intermediate state so interruptions can resume.

## Pattern 3: Task continuity memory pattern

```text
Current Task Record:
- current_task
- last_completed_step
- next_recommended_step
- blockers
- confidence
- updated_at
```

Rules:
- update memory only on explicit evidence,
- keep short rolling history to avoid prompt bloat,
- separate factual memory from speculative inference.

## Pattern 4: Voice-first control pattern

```text
Wake Word -> ASR -> Intent Router -> Action
                 -> Clarify (if confidence low)
                 -> Confirm (if risky)
                 -> Execute + brief spoken summary
```

Design pattern:
- optimize for 1-2 sentence answers,
- prefer “next action” over long explanations,
- always include safe fallback path (“I’m not sure, should I zoom in / retake image?”).

## Pattern 5: Safety and privacy guardrail layer

```text
Sensor Input
  -> Privacy Filter (faces/screens/location-sensitive data)
  -> Policy Check (allowed tools/actions)
  -> Model Inference
  -> Output Redaction + confidence gating
```

Design pattern:
- deny by default for sensitive actions,
- log policy decisions for debugging and audits,
- degrade gracefully when confidence is low.
