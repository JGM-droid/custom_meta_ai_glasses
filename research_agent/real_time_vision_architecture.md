# Real-Time Vision Architecture for Wearable AI Assistants

## 1) Camera → AI → Response Pipelines

### A. Fastest cloud-assisted pipeline (MVP)

```text
Smart Glasses Camera
  ↓ (frame/sample every 500–1000 ms)
Phone Companion App (iOS/Android)
  ↓ (quality gate: blur, brightness, duplicate-frame hash)
Companion App Preprocessor (crop/resize/compress + prompt template)
  ↓
Vision LLM API (OpenAI Vision / Gemini Vision / Claude Vision)
  ↓
Response Orchestrator (intent router + safety + truncation)
  ↓
Output Channel (TTS + short HUD text + phone notification)
```

### B. Hybrid low-latency production pipeline

```text
Wearable Camera Stream
  ├─→ On-device quick detectors (scene change, text presence, code-screen detection)
  └─→ Event bus
         ↓
      Router
      ├─ OCR fast path (PaddleOCR/Tesseract/EasyOCR)
      ├─ Screen-understanding path (Vision LLM + UI grounding prompt)
      ├─ Coding-assistant path (Vision LLM + repo/tool context)
      └─ Memory path (vector retrieval + recent task state)
         ↓
      Response Composer
         ↓
      Multimodal Output (audio first, 1-line display summary, optional detailed phone view)
```

## 2) OCR Systems (What to use where)

- **Fast OCR (<300 ms on phone/edge for simple text):** PaddleOCR / EasyOCR
- **Higher-accuracy document OCR:** Cloud OCR or Vision LLM OCR fallback
- **Pipeline pattern:**
  1. detect text regions locally
  2. OCR locally first
  3. escalate hard regions to Vision LLM with focused crop prompts
- **Wearable-specific optimization:** keep small ROI crops instead of sending full frames.

## 3) Screen Understanding

For laptop/monitor/IDE capture through glasses:

- detect "screen frame" + perspective correction
- split into regions: code pane / terminal / error trace / browser tabs
- send structured prompt:
  - "Summarize current task"
  - "Extract error lines"
  - "Recommend next command"
- return **tiered response**:
  - Tier 1 (glasses): 1 sentence
  - Tier 2 (phone): full explanation + steps

## 4) Coding Assistant Workflows

### Workflow diagram

```text
Camera sees terminal error
  ↓
OCR extracts stack trace
  ↓
Repo Context Retriever (last files, active branch, recent commands)
  ↓
LLM Fix Planner (Claude/OpenAI/Gemini)
  ↓
Actionable response:
  - likely root cause
  - exact command(s)
  - minimal patch suggestion
  ↓
Optional: Open Interpreter / tool runner executes user-approved fix
```

### Best workflow choices

- **Explain mode:** no auto-exec; safest for demos
- **Assist mode:** generate exact shell/git commands
- **Execute mode (guarded):** only user-confirmed operations

## 5) Latency Optimization Strategy

### End-to-end target budgets

- **“Feels real-time” voice loop:** 1.0–2.5 s
- **Acceptable complex vision reasoning:** 2.5–6.0 s

### Stage-by-stage estimate (hybrid pipeline)

| Stage | Typical latency |
|---|---|
| Frame capture + transfer to phone | 80–180 ms |
| Preprocessing + quality checks | 40–120 ms |
| Local OCR/detectors (fast path) | 120–400 ms |
| Cloud vision inference (single image) | 900–2800 ms |
| Response synthesis + TTS kick-off | 120–350 ms |
| **Total (fast OCR-first path)** | **0.4–1.2 seconds** |
| **Total (cloud-vision path)** | **1.3–3.8 seconds** |

### Optimization checklist

- event-driven sampling (not full video upload)
- ROI cropping before API calls
- prompt compression + strict output schema
- deduplicate near-identical frames with perceptual hash
- parallelize OCR and intent classification
- cache recent memory retrieval and prompt context

## 6) Memory Integration Architecture

```text
Short-term memory (session ring buffer: last 20 events)
  +
Task memory (active goal, current step, blockers)
  +
Long-term memory (vector DB: past fixes, user preferences, frequent locations/screens)
  ↓
Context packer injects only top-K relevant memories into each request
```

Recommended memory policy:
- short-term: high recency weight
- long-term: semantic relevance + confidence score
- decay stale observations; keep explicit user-confirmed facts

## 7) Research Notes on Requested Systems

### Open Interpreter
- strong for tool execution and computer-control workflows
- useful as **post-vision action layer** (run commands after OCR/vision interpretation)
- not primarily a native high-frequency wearable camera runtime; best used with a custom capture/orchestration layer

### OpenAI Vision
- strong multimodal reasoning and OCR fallback quality
- practical for cloud-assisted MVP path
- good when paired with local preprocessing filters and ROI cropping for latency/cost control

### Gemini Vision
- strong multimodal and ecosystem fit (Google stack, Android-friendly integrations)
- useful for screen understanding + structured extraction prompts

### Claude Vision
- strong long-context reasoning and high-quality explanation output
- very effective for coding-assistant responses from screenshots/errors

### Solos AirGo projects
- relevant as a wearable hardware/app ecosystem reference for voice-first smart glasses UX
- key lesson: keep output short on-glasses and push detail to companion app

### Open-source wearable AI projects
Examples to study for architecture patterns and implementation ideas:
- Open Interpreter (tool execution agent)
- Omi (wearable/ambient assistant direction)
- BasedHardware Whomane project (open wearable hardware path)
- Owl (privacy/local-first wearable assistant)
- MentraOS (smart glasses OS/community experiments)

## 8) Recommended Stack

### Fast MVP stack (lowest integration friction)

- **Capture:** smart glasses camera → phone app bridge
- **Orchestration API:** Python FastAPI
- **Vision:** OpenAI Vision (primary), Claude/Gemini fallback routing
- **OCR:** PaddleOCR local first, LLM OCR fallback
- **Memory (MVP):** SQLite + lightweight vector DB (FAISS/Chroma)
- **Memory (production):** Postgres for durable multi-stream state + Redis for queue/cache workloads
- **Speech:** device-native STT/TTS where possible
- **Queueing:** Redis or in-process async queue for frame tasks
- **Observability:** latency traces per stage + prompt/result logging

### Scale-up stack (production-minded)

- edge runtime for local detection + OCR
- multi-model router (cost/latency/quality policy)
- background summarizer writing durable memory snapshots
- safety layer for hallucination-sensitive commands

## 9) Fastest MVP Path (2–4 weeks)

1. **Week 1:** phone capture app + single-frame submit + OpenAI Vision response + TTS return
2. **Week 2:** add local OCR fast path + simple memory (recent observations/tasks)
3. **Week 3:** add coding workflow mode (error extraction + command suggestions)
4. **Week 4:** latency tuning, fallback model routing, polished recruiter demo flows

Success criteria for MVP:
- sub-2.5 seconds median for short scene Q&A
- ≤1.2 seconds end-to-end fast OCR-first path median on clear text
- stable “camera → answer” loop for 10+ minute live demo

## 10) Risks

- **Latency spikes** from network/API load
- **OCR failures** on angled/low-light reflective screens
- **Hallucinated coding fixes** without repo context grounding
- **Battery/thermal constraints** on wearable + phone
- **Privacy/compliance risks** for bystander capture and screen content
- **Provider dependency risk** (single-model lock-in)

Mitigations:
- multi-model fallback + timeout budget policy
- confidence scoring before action suggestions
- local redaction and explicit capture indicators
- user confirmation gates before executing commands

## 11) Recruiter-Demo Worthy Features

- Real-time “What am I looking at?” scene assistant
- Live OCR “read this error and propose next command”
- Coding triage mode: screenshot terminal → root cause + fix plan
- Context-aware follow-ups using memory (“continue previous task”)
- Latency dashboard overlay showing per-stage timings
- Voice-first + glanceable display UX (short answer on glasses, full detail on phone)

## 12) Practical Architecture Recommendation

If the goal is fastest credible delivery:

1. build **cloud-assisted hybrid** first (local OCR + cloud vision reasoning)
2. keep wearable client thin; move orchestration to phone/backend
3. add memory early (task continuity is a major differentiator)
4. ship coding-assistant mode as primary “wow” demo use case

This path maximizes speed-to-demo while preserving an upgrade path toward more on-device intelligence.
