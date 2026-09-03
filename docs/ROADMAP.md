# Roadmap

## Completed

- Task Continuity
- Progress Tracking
- Stuck Detection
- Resume Previous Task
- Smart Intervention
- Metrics Snapshot
- Demo Mode
- Demo Scenario Runner

## In Progress

- Documentation hardening for architecture communication and scenario-based validation.

## Planned

- Voice Readout
- Hosted Glasses Web App
- Meta Ray-Ban Display Integration

## Future Research

- Workflow interruption recovery quality evaluation across broader scenarios.
- Wearable interaction patterns for concise, glanceable guidance.
- Human-AI collaboration patterns for stateful workflow execution.

## Implemented MVP Critical Path

- Project-scoped, retry-safe **Record progress** on desktop and Android.
- A required preview separates the user-authored note from any suggested Project change.
- Save creates one append-only user Activity and zero provider calls.
- Optional changes to Where We Left Off, Blockers, or Next create a separate pending Checkpoint Proposal; Apply/Reject remains explicit.
- Deterministic Project-scoped identities make equivalent retries, concurrent requests, response loss, and restart reconstruction converge without duplicate Activity or Proposal records.
- This capability reuses existing Project Memory owners and adds no Progress store, generic Interaction store, automatic Apply, or AI progress scoring. See ADR-058.

## Approved Post-MVP Direction - Persistent Goal-Oriented Project Assistant

Status: APPROVED ROADMAP. This section records direction, not implemented functionality, and does not unfreeze the completed Universal Project Workspace MVP. `docs/PROJECT_MEMORY_ARCHITECTURE.md` ADR-052 through ADR-057 are authoritative. The focused foundation is `docs/PROJECT_INTERACTION_FOUNDATION.md`.

The product is a persistent multimodal Project Workspace, not "ChatGPT running on glasses." A Project represents a durable user objective: repair an AC, restore a vehicle, redesign a room, build a PC, plan a garden or trip, research a purchase, remodel a bathroom, develop software, or learn a craft. The application owns Project identity, state, checkpoints, history, evidence, decisions, current step, next actions, references, and approved memory changes.

The general model is:

```text
PROJECT
  -> PROJECT INTERACTION
  -> CONTEXT RETRIEVAL
  -> AI + TOOLS / MEDIA RETRIEVAL
  -> STRUCTURED RESULT / ARTIFACT
  -> USER DECISION
  -> PROJECT MEMORY
```

Investigation remains one Project Interaction. Candidate future families are INVESTIGATE, EXPLORE, RESEARCH, COMPARE, GUIDE, PLAN, EXPLAIN, and LOOK/ANALYZE EVIDENCE. They are not approved implementation scope yet.

The approved foundation keeps Project Interaction as a lightweight orchestration/correlation boundary over existing Project Memory rather than adding a universal store or workflow engine. The first proposed proof is backend-first Room Redesign `EXPLORE`: deterministic Project Context retrieval, one provider-neutral call, strict `OPTION_SET | INFORMATION_REQUEST`, ordered AI/inferred Idea Activities, explicit user Decision Activities, existing Idea promotion, and Checkpoint Proposal Apply for any canonical direction change. This milestone is documented but not implemented or authorized by this design task.

### Canonical creative use case - Room Redesign

A `Room Redesign` Project may start with room photos and a request for warmer, more modern decorating ideas. The AI can produce candidate concepts such as Warm Modern, Dark Contemporary, and Minimal Natural. They are Ideas/proposals, not Project truth. The user may Save, Dismiss, Compare, Keep for later, or explicitly promote a selected direction into the Project plan.

Later furniture research uses bounded relevant context such as the selected style, room photos, known dimensions, existing furniture, colors, budget, and prior decisions. Candidate resources remain proposals until the user chooses what enters Project state. Returning days later should reconstruct without conversational re-explanation:

```text
WHERE WE LEFT OFF
Warm Modern direction selected.

DECIDED
Keep existing desk and flooring.

CONSIDERING
Oak side table; cream rug; floor lamp.

NEXT
Choose seating and finalize furniture placement.
```

## Glasses-Native Project Workspace

The Meta Ray-Ban Display is a first-class glanceable/actionable projection and controller for the same application-owned Project Memory. The phone remains the richer secondary field interface.

```text
Glasses / Phone
  <-> Project Workspace
  <-> Project Memory + Context Engine
  <-> Project Interaction / Guidance Engine
  <-> AI Provider + Retrieval / Media Tools
```

The first major glasses-native closed loop is:

```text
Select Project
-> Where We Left Off
-> Capture Evidence
-> Add Context
-> Analyze
-> AI suggestion + Next Action
-> user trust action
-> proposed Project change
-> validated Project Memory update
-> refreshed HUD state
```

AI suggestion, user assessment, proposed Project change, and canonical update remain separate stages.

### Structured guidance

Planned application-level response families:

- INSTRUCTION: title, summary, steps, current step, warnings, available actions.
- REFERENCE: image/diagram/video, caption, source, relevant step.
- ANNOTATED EVIDENCE: captured image, identified component/location, marker, explanation.
- DECISION: recommendation, alternatives, reasoning summary, trust/approval actions.
- PROJECT UPDATE: changes, completed actions, current state, next action, proposed memory changes.
- QUESTION / INFORMATION REQUEST: needed evidence, capture instruction, continuation identity.

The same semantic result should render concisely on glasses and richly on phone/desktop.

### Instructional media retrieval

Approved future results include written instructions, images, technical diagrams, annotated user images, source references, instructional videos, and appropriate product/reference results. Retrieval uses relevant Project context: identity, equipment/object/model, current task and step, previous evidence, selected style/constraints, findings, and decisions. Core architecture remains provider/source agnostic; YouTube is not hard-coded.

Meta Display supports third-party video playback, so instructional-video playback is a legitimate prototype target. YouTube playback is `NOT YET VERIFIED`. Research gates include search/Data API access, playback/embed restrictions, authentication, advertising/policy obligations, playable URL/stream availability, technical/legal suitability for direct glasses playback, alternative instructional sources, and a provider-neutral source boundary.

### Implementation sequence

Glasses foundation:

1. Reliable supported Display interaction/capture mechanism.
2. Project identity plus Where We Left Off / Next.
3. Glasses-side evidence action.
4. Evidence count/status.
5. Analyze action.
6. Concise structured AI result.
7. Trust actions: Keep as hypothesis, Add evidence, Return.
8. Refreshed Project state.

Only after that foundation:

9. History.
10. Roadmap/step navigation.
11. References.
12. Instructional diagrams/images.
13. Annotated evidence.
14. Project-scoped media retrieval.
15. Instructional video.
16. Richer Project navigation.

Project-level Apply/Reject may remain on the phone initially. Until Meta exposes supported glasses microphone/voice-command access, open-ended spoken context remains phone-assisted. Near term, glasses own navigation, Now/Next, evidence actions, Analyze, concise guidance, and supported trust/navigation actions; phone owns open-ended context, detailed review, rich approvals, and complex media/search controls.

## DAT 0.8 Capture Capability Gate - 2026-08-23

Status: `NOT PRODUCT-READY AS THE RELIABLE DAT 0.8 CAPTURE FOUNDATION`.

Verified public Display support includes text, high-level buttons/onClick, clickable rows, lists, scrolling, dynamic screen replacement, images, video, and supported Android callbacks. The inspected public DAT 0.8 API does not expose physical camera-button events, raw Neural Band/EMG, raw touchpad taps/swipes, custom Hey Meta callbacks, glasses microphone/audio streaming, or application-controlled Band/glasses haptics.

Physical capability-handoff observation:

- Four accepted Display/Band callbacks.
- Four successful `PhotoData` captures.
- Display restored on the same session after every capture.
- Explicit Project id remained `30c6f249-95b6-4dd1-83aa-ba71cefbf383`.
- The existing Investigation draft accepts only three evidence items.
- The fourth capture was not retained as evidence, although the HUD reported `Photo added`.

ADR-056 removed the three-evidence test limitation and corrected HUD success so only accepted evidence reports `Photo added`. The subsequent physical retest received seven Display/Band callbacks and issued seven capture requests. Four returned `PhotoData` and became four ordered accepted Investigation evidence items; three failed inside `Stream.capturePhoto()` after approximately ten seconds. Display restored after all seven attempts, explicit Project attribution stayed stable, and no duplicate evidence was observed. The required five consecutive callbacks -> five `PhotoData` results -> five exactly-once evidence items threshold was therefore not met.

The max-five contract and dynamic evidence UX are valid, but the current supported DAT 0.8 Display capability-handoff mechanism is not reliable enough to serve as the production capture foundation. The interaction path is proven; capture reliability is blocked on the current SDK/runtime. The rejected Display handoff spike implementation, dependency, and spike-only tests were removed; they are not part of the retained max-five production batch. Do not add retries, reflection, internal APIs, gallery polling, accessibility interception, Bluetooth interception, or unsupported workarounds.

This capability gate blocks only productizing Band-triggered glasses capture on DAT 0.8. It does not block generalized goal-oriented Projects; Project Interaction families; structured guidance; phone/desktop guidance; Project-scoped instructional media, diagrams, and references; read-only glasses Now/Next Project projections; or supported Display-triggered non-camera actions. Glasses-native capture remains a separately gated capability.

Immediate local captured-photo HUD preview is blocked on DAT 0.8 because its public Display image component accepts a supported HTTPS URI, not `PhotoData`, bitmap, bytes, `content://`, or `file://`. An already-accepted HTTPS evidence source could support a later presentation prototype without creating another image store.

### Status Update - 2026-09-02: HUD/Band Capture Reinstated as an Explicit MVP Requirement

Human product decision (explicit, informed): despite the reliability finding above being unchanged and unresolved - still DAT 0.8.0, no DAT 0.9 evaluation performed - HUD/Band-triggered photo capture is now a required part of the MVP wearable workflow (`New Project -> Use glasses -> capture visual context from glasses -> continue Project workflow`).

This is **not** a reversal of the reliability finding and **not** a resurrection of the rejected `feature/glasses-display-capture` branch/spike (which predated Project attribution entirely). It is a fresh implementation inside the current Project-aware architecture:

- The Capture action lives in `ProjectContinuityHudController`'s existing Ready/Stale render states (Android) - the same single Display this controller already owns via `attachTo(session)`; no second Display attachment was added.
- A tap only *requests* a capture; `StreamViewModel` (the existing single DeviceSession/Stream owner) performs the actual `capturePhoto()` call and reports success/failure back. The HUD never calls the capture API directly.
- Explicit `project_id` attribution is inherited for free: the HUD only offers Capture once attached to a specific explicit Project's session, and the request routes through that same already-attributed session - there is no second, parallel capture path to keep in sync.
- Failures are shown honestly on the HUD (`Capture failed: <message>`) with a manual retry button. No automatic retries, polling, or other workarounds mask the known reliability gap - a real capture attempt can still fail, and the user will see that plainly rather than the HUD silently doing nothing or looping.
- The phone-side Capture button (`StreamScreen`'s existing `CaptureButton` -> the same `capturePhoto()`) remains available as the reliable fallback; HUD capture is additive, not a replacement.

Known residual risk: the underlying `Stream.capturePhoto()` reliability issue this gate documented (4 of 7 physical attempts succeeded) is unchanged. Accepting HUD/Band capture as MVP scope means accepting that some fraction of glasses-triggered captures will visibly fail and need a retry tap, not that the SDK-level issue has been fixed.

### Physical Validation - 2026-09-02

The above was extended with a text-only Use/Retake confirmation step (`Photo captured — use this image?` / Use / Retake) so a HUD capture is never silently appended to Investigation evidence - it stays pending until an explicit Use tap, mirroring how a phone-side capture already stays pending until the user acts on it.

**Known limitation, not a bug**: this confirmation is text-only - the captured image's pixels are previewed on the phone (the existing live video/share flow), never on the glasses' own Display. DAT 0.8's Display image component only accepts a supported HTTPS URI (confirmed at the protobuf wire-format level: `ViewImage.image_uri`), never `PhotoData`/`Bitmap`/bytes/`content://`/`file://`, so a real on-lens photo preview would require uploading the pending capture to a new backend endpoint before Use/Retake is even decided - explicitly out of scope for this MVP milestone (no backend upload/persistence was added).

A second physical issue surfaced during device testing: a transient DAT Display `sendContent()` failure/timeout during an in-flight capture (DAT's own `HeartbeatMonitor`/`DisplaySession` logs showed a ~5-10s connectivity stall overlapping the capture) could leave the HUD screen permanently stale - bound to an older render generation than the state machine had already advanced past, so every subsequent tap (Capture, Refresh, Continue on phone alike) was silently rejected by the existing replay-protection check. Fixed with a bounded one-retry resync of the Display's *current* state (`ProjectContinuityHudController.renderCurrentStateWithOneRetry`/`retryOnceThenReport`) - never a capture retry, never an unbounded loop.

Full physical acceptance passed on real glasses: first capture failed and the HUD recovered and stayed usable; subsequent captures succeeded; Capturing / AwaitingConfirmation (Use / Retake) states all rendered correctly; Use correctly added the photo to Investigation evidence; Retake correctly discarded it without consuming a slot; repeated captures kept working without a session restart.

## Next Isolated Research Task - DAT 0.9 Capability Evaluation

Do not upgrade as part of the max-five production batch. A separately authorized, read-only-first evaluation should determine:

- Which DAT 0.9 artifacts are officially available.
- Migration changes from DAT 0.8, including any consolidated Camera capability.
- Display/camera coexistence and capability-ownership changes.
- `capturePhoto` behavior and relevant reliability fixes.
- Bitmap, local-image, or other supported Display image-source changes.
- `buttonGroup` and other Display interaction changes.
- Compatibility with the current CameraAccess application and one-DeviceSession architecture.
- Migration, build, runtime, and physical-regression risk.
- Whether Meta changelogs/issues identify the observed approximately ten-second capture timeout.
- Whether an upgrade could enable safe accepted-evidence HUD thumbnail rendering.

The evaluation must end in an evidence-backed upgrade recommendation or rejection. It must not upgrade dependencies, ship Band capture, or introduce a workaround without separate authorization.
