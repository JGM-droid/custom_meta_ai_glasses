# Roadmap

## Canonical Re-Baseline (2026-09-12) — Current Authority

This section is authoritative for CURRENT MILESTONE / NEXT MILESTONE / BLOCKERS / DEFERRED tracking. It supersedes the older "Current / Next" heading immediately below (kept as historical phase-completion detail, not as the live tracker) for that purpose. See `docs/PROJECT_MEMORY_ARCHITECTURE.md`'s "Canonical Architecture Re-Baseline (2026-09-12)" section for the full reference architecture, proven/unproven findings, and cleanup decisions this re-baseline is built on.

### Stage sequence (current state to a genuinely usable product)

- **STAGE 0 - Architecture Cleanup / Re-baseline** - **COMPLETE.** Confirmed-safe legacy cleanup, canonical reference architecture written down, this roadmap re-baselined. See `docs/PROJECT_MEMORY_ARCHITECTURE.md` for the full cleanup decisions (legacy `memory_manager.py` dependency documented and deferred; `project_knowledge.py` classified REUSE/EVOLVE; Checkpoint-must-not-compete warning recorded; Context Retriever defects documented for a later milestone; route-file maintainability recorded as debt).
- **STAGE 1 - Current Project State / Salience Gate** - **COMPLETE / PASSED.** The final planned architecture falsification experiment. See `docs/PROJECT_MEMORY_ARCHITECTURE.md`'s "Stage 1 Result" section for the verified winning design (deterministic eligibility/blocker/resolved-area handling, AI salience selection replacing recency for global continuation, targeted retrieval unchanged for topic-specific questions), boundedness evidence, and the one recorded future scaling caveat (salience-candidate input size, not currently blocking). Architecture exploration on the memory/context path is now closed - it reopens only if Stage 2 implementation falsifies a foundational assumption, not for new optimization ideas (see the Roadmap Discipline Rule in `AGENTS.md`).
- **STAGE 2 - Integrated Persistent Memory Shadow Slice** - **COMPLETE / SHADOW MODE, NOT YET AUTHORITATIVE.** Implemented the Stage 1-proven design as real, production-integrated shadow code: durable facts/constraints/preferences with assertion modality and provenance (`ProjectMemoryRecord`, `ProjectMemoryStore`); Decisions using subject+slot semantics with history-preserving, modality-aware supersession; append-only Progress events with a derived current projection; one bounded extraction call per eligible conversation turn (`ProjectMemoryExtractionService`), fired after the conversation lock releases so a slow provider call never blocks concurrent turns, with shadow failures isolated from the real turn; derived (never persisted) Current Project State (`ProjectCurrentStateService`) with blocker preservation, resolved-area collapsing, and bounded AI salience selection for global continuation questions; targeted deterministic-first retrieval for scoped/topic-specific questions, unchanged from the prior gate. Verified via 19 deterministic unit tests (including an ABC Apartments multi-scope structural test), 10 fake-provider tests, 6 real-provider modality checks, and a real-backend 12-turn Living Room E2E scenario - see `docs/PROJECT_MEMORY_ARCHITECTURE.md`'s "Stage 2 Result" section for the full result, the one correctness fix found along the way (a resolved-scope-collapsing heuristic gap), and the one recorded known limitation (compound-statement slot-splitting). Records reuse `ProjectActivity`'s existing `source_type`/provenance fields rather than a second attribution system, keeping future actor/scope/time attribution possible without redefining what a Project event is. Runs alongside, not instead of, the existing Context Retriever/Checkpoint/Project Knowledge path - not yet wired into normal conversation (Stage 4). Groundwork for the Editable Project Workspace requirement is in place (modality-aware supersession, history-preserving cancellation) without implementing the correction/mutation UX itself. No accounts/roles/permissions/collaboration UI in this stage.
- **STAGE 3 - Visual Evidence Continuity** - durable Evidence descriptions, description-first retrieval, selective original-image re-fetch, in production.
- **STAGE 4 - Real Conversation Integration** - wire the proven memory/context path into `ProjectConversation`; resolve Checkpoint/Project Knowledge/Context Retriever ownership so there is exactly one source of truth for "what's currently true," not parallel ones. Must preserve the principle "the user talks naturally; the Workspace becomes structured automatically" - no user-facing form-filling or manual memory operation. Route-file maintainability debt is loosely scheduled here, only if the same file is already being touched substantively.
- **STAGE 5 - Realistic Usability Acceptance** - run the Persistent Project Usability Acceptance spec ("Living Room Long-Horizon Acceptance," `docs/PROJECT_MEMORY_ARCHITECTURE.md`) through the actual real application, not a toy unit test or a narrow provider eval. Extend the existing question set with cross-cutting retrieval questions that exercise Project History + Current Project State + targeted retrieval together, not just conversational recall - e.g. "What did I work on most recently?", "What have I completed?", "What changed?", "What have we done regarding the TV area?", "What remains in this part of the Project?".
- **STAGE 6 - Phone / Glasses Dogfood** - only after Stage 5 passes on desktop/backend. Validate the same continuity through Android and glasses where physically required.
- **STAGE 7 - Product Validation / Collaboration Direction** - expose to external users; determine whether multi-user shared Projects are valuable; evaluate high-value verticals (e.g. construction/field work, illustrative only); evaluate whether glasses materially improve the workflow; evaluate actor-based queries ("what did Jesse do last," "who reported this") once more than one contributor is real. Multi-user collaboration, construction/field-work validation, and actor-based queries are all recorded future directions only - not scheduled for implementation before this stage, and not authorized by this entry.

### Blockers

- None blocking Stage 3. Stage 2's shadow-memory implementation is complete (see `docs/PROJECT_MEMORY_ARCHITECTURE.md`'s "Stage 2 Result") - no foundational assumption was falsified, so architecture exploration on the memory/context path remains closed.
- A prior, still-unaddressed finding (`docs/research/MULTI_AGENT_PRODUCT_REVIEW.md`, 2026-08-23): the core value proposition may already be commoditized by free bundled ChatGPT/Claude Project memory features. Not a technical blocker to Stages 0-6, but a standing risk that should inform how much further investment precedes Stage 7's real external-user validation.

### Deferred / Backlog

- Full Context Retriever redesign (closed keyword classifier, `next_action`+`fallback` zero-activity defect, fixed recency window) - deferred to Stage 2/4, not fixed piecemeal.
- Legacy `memory_manager.py` migration - deferred until its owning legacy single-image endpoint is itself intentionally revisited; not expanded in the meantime.
- Monolithic API route file split - deferred, loosely to Stage 4; not pursued as standalone cleanup.
- Embeddings/vector retrieval infrastructure - not justified by any evidence gathered to date; revisit only if a future measured need arises (see `docs/research/PERSISTENT_PROJECT_MEMORY_REFERENCES.md`'s Revisit Triggers).
- Local/self-hosted LLM - not justified by any evidence gathered to date.
- Multi-user/shared-Project collaboration - recorded future direction, Stage 7 or later only.
- UI redesign - out of scope for the memory/context work entirely; tracked separately if pursued.
- Salience-ranking candidate-list narrowing/indexing - not currently needed (proven bounded up to 2,000 records/234 workstreams); future escalation trigger only if a real Project develops very large numbers of simultaneously active workstreams, per `docs/PROJECT_MEMORY_ARCHITECTURE.md`'s Stage 1 Result.
- Editable Project Workspace implementation (natural-language corrections becoming authoritative Project updates) - requirement recorded in `docs/PROJECT_MEMORY_ARCHITECTURE.md`, not scheduled for implementation before Stage 2's shadow-memory foundation exists to build it on.

## Current / Next — Conversational Project Assistant

**Current: Phase 2 — Android conversation-first UI, PHYSICALLY ACCEPTED on real hardware (2026-09-08).** A user turn may reference up to five existing accepted Project image Evidence records in caller order. Conversation persists typed references only; the orchestrator resolves same-Project Evidence through the existing Investigation stores and sends bytes only for images explicitly attached to the current turn. Text-only follow-ups receive bounded prior text and Project context but do not automatically resend prior image bytes. See "Phase 2 Physical Validation" below for the accepted real-glasses/real-phone loop. Existing ADR-060 guidance, Investigation, Explore, Proposal, VisualArtifact, desktop, and glasses paths remain runnable and unmigrated - this acceptance proves the Phase 2 vertical slice only, not migration/retirement of those paths, and not production readiness, security, or cloud deployment.

**Phase 3A — conversational Explore + persistent conversation image thumbnails, PHYSICALLY VALIDATED on real hardware (2026-09-08).** The first slice of Phase 3 is complete: the existing Explore capability (ideas/options) is now reachable as an in-conversation intent via the orchestrator's own native provider tool-calling, with a genuine Explore failure ending the assistant turn cleanly as FAILED rather than a silent empty turn or a raw leaked provider exception. Separately, persistent conversation image turns (both phone-attached and accepted-glasses Evidence) now render an actual tappable thumbnail with a full-screen viewer, sourced on demand from the same canonical Evidence content the legacy Investigation panel already reads - the conversation still only stores the Evidence reference, never image bytes - so the image survives conversation reload, app relaunch, and reopening the Project later. See "Phase 3A Physical Validation" below.

**Phase 3B — VisualArtifact integrated into ProjectConversation, PHYSICALLY ACCEPTED on real hardware with a real provider (2026-09-08).** The natural follow-up after Explore options appear in conversation - "I like option three. Show me what that would look like in my room." - connects the already-existing VisualArtifact generation capability to the conversation surface via one more native-tool-calling capability intent, following the same "conversation references, capability owns" pattern already used for Explore and Evidence. A small typed `AssistantCapabilityIntent` (NONE/EXPLORE/VISUALIZE_OPTION) replaced what would otherwise have been a second one-off boolean, now that two real capabilities exist. Generation only occurs on explicit visual-generation intent from the user's own words, never automatically because Explore returned ideas; the resulting visualization is a distinct, labeled, tappable reference in the conversation, resolved on demand from canonical VisualArtifactStore. Two earlier real-acceptance attempts did not succeed first: the first found the model answering an already-explicit visualize request with prose and a false "I'm preparing/proceeding..." claim instead of calling the tool, traced to the system prompt itself discouraging tool use and repaired at the prompt/instruction level (never application-side keyword routing); the second attempt still failed for an unrelated reason - the backend process actually serving requests had been running since before that prompt repair was even written to disk and had never been restarted, so neither attempt had ever really exercised the fix. After restarting the backend onto current code, the third attempt passed in full. See "Phase 3B Physical Validation" below.

**Phase 3C — Investigation integrated into ProjectConversation, PHYSICALLY ACCEPTED on real hardware with a real provider (2026-09-09).** A natural troubleshooting request ("Why isn't this working?") is now a third native-tool-calling capability intent (`AssistantCapabilityIntent.INVESTIGATE`, the third member anticipated when the enum was introduced), dispatched through the exact existing session-based Investigation pipeline `ProjectAIResultPlanner.route()`'s own TROUBLESHOOT branch already uses - never a second Investigation implementation, and never route()'s own LLM classification call (the conversation's native tool-calling already decided this). Evidence attached to the current message takes deterministic precedence over any older, unrelated Project session with usable evidence; when no current-turn evidence exists, the same existing reusable-session detection and text-only fallback apply unchanged. A session/evidence-backed result attaches a new typed `ConversationInvestigationReferencePart`; a text-only result stays plain text with no fabricated reference, exactly like GENERAL_GUIDANCE's own ephemeral outputs. Investigation output remains inference only - no canonical Project mutation, and the existing trust (Continue/Disagree/More Evidence) flow is untouched and not yet reachable from conversation. One small, explicitly-scoped extension was required: conversation-attached Evidence carries no explanation text (the explanation lives in the message itself), so a new `InvestigationEvidenceStore.set_evidence_explanation` backfills that one field on the exact existing evidence record already referenced - never a new session, evidence record, or association.
The first real-acceptance attempt (a phone-camera photo of dirty shoes) failed before Investigation routing was even exercised, on an unrelated pre-existing gap: an ordinary modern phone-camera JPEG exceeded the backend's Evidence upload limit (413), traced to a client-side normalization gap (no dimension/byte-budget bound on phone-camera/gallery images) rather than a Phase 3C defect or the backend limit itself; fixed client-side in the single shared `InvestigationCaptureNormalizer.normalizeImageEvidenceForBackend` boundary. The second and third attempts (same shoes phrasing) found and repaired a real model tool-selection gap in two passes - the `investigate_project_issue` tool description/system-prompt was first too narrow (scoped to mechanical malfunction, missing restoration/degradation phrasing) and then, after widening it, too broad (over-firing on ordinary descriptive/how-to questions); a 12-scenario real-provider routing evaluation (not a large framework - kept intentionally small) measured both the gap and the over-correction before calibrating the final boundary: INVESTIGATE requires the user to be trying to determine a cause/reason, not merely requesting cleaning/restoration/how-to steps. The fourth attempt (a real breaker-panel photo captured with the glasses, "breaker issues" Project) passed in full and is the accepted physical proof: real glasses Evidence -> INVESTIGATE selected -> the existing Investigation analysis pipeline actually executed against the real image -> session reached COMPLETED with a real result -> exactly one `ConversationInvestigationReferencePart` persisted -> rendered back into the same ProjectConversation - confirmed via backend-state inspection (session/result/activity records), not inferred from response prose. One known, low-severity routing edge case and one trust-guard defect found during that same run's follow-up turns are recorded in the Phase 3C Closeout backlog below.

**Conversational Project Progression - Slice 1, IMPLEMENTED, AUTOMATED-TEST-VALIDATED, AND REAL-PROVIDER END-TO-END VERIFIED (2026-09-09).** The originally-planned "Proposal becomes a conversational capability/card" milestone evolved, on architecture review, into a different interaction model: ProjectConversation now progresses from a user's grounded, real-world-reported outcome ("I did that and it worked") without a repeated, visible Apply/Reject Proposal step on the common path - see ADR-062 in `docs/PROJECT_MEMORY_ARCHITECTURE.md` for the full authoritative design. `CheckpointProposal` remains the sole, unchanged internal trusted mutation primitive; this is not a new `AssistantCapabilityIntent` and not a new mutation path. Slice 1 scopes eligible targets to Investigation-originated outstanding claims only, reuses the existing `ProjectInvestigationTrustService.decide()` (the same CONTINUE/DISAGREE machinery the legacy trust UI already calls) verbatim, and auto-applies only a narrow, explicitly-documented low-consequence field policy. Ordinary-conversation-originated progression, Explore/VisualArtifact-originated progression, the ADR-044 Action Artifact/cross-agent outcome-reporting case, and Workstreams/scopes are intentionally deferred, not implemented, and not precluded by this slice's design. Accepted by explicit user decision following one instrumented real-provider end-to-end run through the actual HTTP API (real diagnostic turn -> real confirmation turn -> `report_investigation_progress` tool selection -> trust-service auto-apply -> inspected resulting Project/Checkpoint/trust state); a separate physical acceptance test, unlike Phase 3C's own discipline, was explicitly waived by the user for this slice and is not outstanding.

**Phase 5 (desktop slice) — Desktop ProjectConversation parity, IMPLEMENTED AND REAL CROSS-DEVICE ACCEPTANCE PASSED (2026-09-09).** The browser dashboard (`dashboard.html`, static HTML/JS with no build step, served by the same backend at `GET /dashboard`) now renders and sends through the exact same backend-owned `ProjectConversation` Android uses (`GET`/`POST /projects/{id}/conversation`, `POST /projects/{id}/conversation/messages`) - no desktop-specific conversation store, no second idempotency scheme. The panel is now the dashboard's primary composer (`order: 0`), with the legacy Ask AI/Get Context/Add Note/Start Investigation composer preserved unmodified but demoted into a collapsed "More workspace tools" disclosure. Renders TEXT, Evidence, Investigation, and VisualArtifact reference content parts (matching exactly what the Android client itself understands - EXPLORE_REFERENCE gets no distinct treatment on either client, since its TEXT part already carries the formatted content). Project selection is tab-scoped via `sessionStorage`, kept entirely separate from the pre-existing global Active Capture Project pointer, so opening a Project on desktop never affects what Android or any other client is viewing. A single message exceeding the backend's real 4000-character `ConversationSendRequest.text` limit is refused client-side with a clear message rather than silently truncated or having that limit raised. A dashboard-caching defect found during this validation - `GET /dashboard` returned no `Cache-Control` header, so browsers could heuristically cache a stale copy of the page across an ordinary refresh - was root-caused and fixed by adding `Cache-Control: no-store` to that one response; confirmed via raw HTTP headers/body and a genuine browser reload, with no regression (825/825 backend tests unchanged). Real cross-device acceptance subsequently passed on real hardware: browser-created ProjectConversation turns appeared in the Android app under the same "Desktop Parity Verify" Project; a distinctive message sent from Android ("Cross device verification this message was sent from the Android app") and its assistant response then appeared in the browser after an ordinary refresh - directly demonstrating desktop -> shared ProjectConversation -> Android and Android -> shared ProjectConversation -> desktop in both directions.
This was implemented on an explicit, detailed direct user request, ahead of this document's own "Locked sequence" below reaching Phase 5 in order. Recorded here for the same reason every other phase in this document is recorded after the fact: a future agent must be able to reconstruct that this was a deliberate, human-directed sequencing choice, not silent architecture drift.

Locked sequence: Phase 0 architecture authority -> Phase 1A text conversation spine -> Phase 1B multimodal conversation -> Phase 2 Android conversation-first UI -> Phase 3 conversational Explore/Investigation/Proposal capabilities and cards -> Phase 4 VisualArtifact conversation integration -> Phase 5 desktop and glasses shared conversation projection -> Phase 6 retirement of old primary workflow UX only after parity.

### Recorded Backlog — Phase 3B Closeout (2026-09-08)

Recorded for future scheduling, not implemented by this closeout:

- **Conversation Media UX**: diagnose/fix automatic EXIF/HEIC/orientation-correct rendering for BOTH Source Evidence images and generated VisualArtifacts shown in conversation, so both display upright without manual rotation - confirmed during Phase 3B physical acceptance (2026-09-08) that a generated visualization can display sideways with no way to correct it. Add manual rotate-left/right controls in the full-screen viewer as a fallback for either kind of image. Do not mutate canonical Evidence or VisualArtifact bytes merely for display unless the architecture later requires it.
- **Project Recency/Navigation**: Projects Home should default-sort by most recent meaningful activity (conversation activity, accepted Evidence, Project state changes, decisions, Investigations, generated artifacts) rather than creation order; merely opening/viewing a Project must not bump its recency; ordering must be deterministic on ties; eventually surface user-friendly "Updated ..." text.
- **Post-MVP External Tools & Live Research**: natural conversation should be able to invoke live internet research/search, using multimodal Evidence to inform the query (e.g. "Find this hammer cheaper somewhere else," "Find dressers like option 3 under $500"), with results returned inside the same persistent ProjectConversation, sources/links and useful structured metadata preserved, and a provider-neutral application boundary (OpenAI may be the first implementation). External/web results remain inferred/external information and never automatically mutate canonical Project Memory. Later extensible to richer tools/connectors/actions - not a generalized agent framework now.
- **Capability Execution Status UX** (found during the Phase 3B real-acceptance-test failure repair): for long-running capabilities such as VisualArtifact generation, the UI should show an application-owned visible state ("Generating visualization…") with honest success/failure/retry states, never inferred from or relying on assistant prose to imply that execution is happening. Today's VisualArtifact bridge is fully synchronous within one request/response, so there is no in-progress window yet to represent - this becomes concretely actionable if/when generation becomes asynchronous, or as a UX polish item regardless.
- **Conversation Microphone UX** (found during the Phase 3B real-acceptance-test session): current dictation is unclear about whether recording is active, and short natural pauses can prematurely stop it. Desired future behavior: tap-to-start with an obvious active/listening state, an explicit user-controlled Stop/tap-to-stop control, tolerance for brief natural pauses, and an editable transcription before Send - similar to modern conversational voice/dictation interactions. Not implemented by this closeout.
- **Backend startup/stale-listener protection** (found during the Phase 3B second real-acceptance-test failure, 2026-09-08): the canonical `start_assistant.py` supervisor can lose a port-8001 bind race to a leftover process from an earlier, uncleaned start without any visible warning, silently leaving real traffic served by stale, un-reloaded code indefinitely (uvicorn runs without `--reload`). The second real-acceptance failure traced entirely to this - the backend serving the test predated the Phase 3B code by over an hour. Desired future behavior: the supervisor should detect that the process actually holding the port is not the one it just started (or is older than the source files it's serving) and fail loudly rather than reporting a healthy "API: already running." Not implemented by this closeout - the immediate incident was resolved operationally (stale processes stopped, canonical stack restarted from current code).

### Recorded Backlog — Phase 3C Closeout (2026-09-09)

Recorded for future scheduling, not implemented by this closeout:

- **Prior Visual Evidence Continuity**: found during the "breaker issues" physical acceptance follow-up - once a user's later turn explicitly refers back to a previously-attached image ("are you able to tell from the picture I sent?") with no current-turn Evidence, no mechanism today re-supplies that prior image to any capability; `bounded_prior_conversation` carries text only. The Context Retriever should eventually be able to selectively identify and re-supply the specific relevant prior visual Evidence such a turn refers to, never by blindly resending every historical image in the conversation. Not implemented by this closeout - Phase 3C's visual-grounding honesty guard (see Explore fix above) only prevents the assistant from pretending it re-examined the image; it does not give the assistant the ability to actually do so.
- **Glasses Composer Preview**: found during the same physical run - a glasses-adopted Evidence attachment renders no pending/loading state in the conversation composer during its async stage-and-adopt round trip, and even once set, its `ConversationAttachmentUiState` carries an empty local URI (unlike phone/gallery attachments, which use a real local content URI), so the composer's pre-send thumbnail can never show a real image preview for glasses captures - only a "Glasses photo" placeholder label appears, and only after the async adoption completes. The photo renders correctly in conversation history once persisted; this is a live-composer preview gap only, not a data-correctness defect. Add an immediate local capture-preview state and real thumbnail support for glasses-adopted evidence later.
- **Routing edge case - "What is this?"**: the 12-scenario real-provider routing evaluation (2026-09-08/09) found "What is this?" with an attached image still over-routes to `AssistantCapabilityIntent.INVESTIGATE` despite being an explicit negative example in both the tool description and system prompt - the one case the final calibration pass did not resolve. Accepted as known, low-severity debt; do not continue tuning Phase 3C's INVESTIGATE boundary for this single case.

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

### Rich Project Intelligence V1 - ADR-059

Status: APPROVED ROADMAP, next after the current glasses Investigation + trust UX milestone (see "Physical Validation - 2026-09-03" below). Not implemented by this documentation update. `docs/PROJECT_MEMORY_ARCHITECTURE.md` ADR-059 is authoritative; this entry summarizes sequencing. **The dispatch mechanism this entry originally described (explicit user/client choice of response family) is amended by ADR-060 - see "Bounded Response Planner Correction" below.**

**Historical sequencing note:** ADR-061 now supersedes this as the next primary product architecture. The implemented response families and typed results remain reusable compatibility capabilities during the conversational strangler migration.

Problem: the existing Investigation result contract (evidence + context -> hypothesis -> recommended next action) is correct for diagnosis but produces low-value output for design/planning/creative Project tasks - e.g. Room Redesign currently returns generic guidance such as "declutter surfaces, add wall art" instead of reasoned alternatives.

Goal: AI responses appropriate to the Project task, while preserving application-owned Project Memory, explicit trust, Project isolation, and provider-neutral architecture - rich ChatGPT-like intelligence on phone/desktop, concise orientation/execution projection on glasses.

Approved direction:

```text
Project Memory
-> deterministic/selective Context Retriever
-> bounded Response Planner
-> typed structured AI result (ProjectAIResult)
-> rich phone/desktop renderer
-> user selection/trust
-> proposed Project Memory update (existing Idea/Decision/Checkpoint Proposal mechanism)
-> explicit validation/apply where required
-> concise HUD projection
```

The Response Planner is the named realization of the "Project Guidance Engine" boundary `docs/PROJECT_INTERACTION_FOUNDATION.md` already describes. It selects, from explicit user intent and Project context, exactly one of three V1 response families - `TROUBLESHOOT` (existing Investigation, unchanged), `EXPLORE_PLAN` (evolves the existing `EXPLORE`/`OPTION_SET` foundation with observations, multiple options each carrying rationale/tradeoffs/proposed changes, a recommended option and reason, next steps, and follow-up questions), `GENERAL_GUIDANCE` (new minimal safe fallback). No larger taxonomy is approved yet, and the Planner must not itself execute mutations.

`ProjectAIResult` is the shared envelope (`result_id`, `project_id`, `result_type`, `summary`, `hud_projection`, `evidence_refs`, `suggested_project_updates`, typed payload) rather than one large mostly-nullable schema. Exact per-family payload schemas, the Planner's internal selection mechanism, and intent/router persistence are explicitly deferred to a focused design milestone.

Selecting a rich option must never silently become canonical truth: AI proposal -> user selection/trust -> the existing Idea/Decision/Checkpoint Proposal mechanism -> validated canonical state, exactly as Investigation/Explore already require. The selected direction then influences future retrieval and guidance, the same way a selected Room Redesign style already does above.

Glasses remain a concise Project Navigator/execution interface and must not render the entire rich response - e.g. before selection: "3 design ideas ready. AI recommends Warm Modern. Review on phone."; after selection: "Plan: Warm Modern. Next: Measure wall behind bed." A direct "See details on phone" path remains distinct from trust actions (Looks right/Add more info/Not quite).

On-demand rich media ("Visualize this option", using Project evidence images as generation context for a selected option) is a separately gated later slice - not automatic, not V1.

First vertical-slice acceptance target (proves the architecture before generalizing): Room Redesign - multiple Project photos + user context -> `EXPLORE_PLAN` selected -> rich structured response with approximately 3 meaningful options -> rich phone UI renders options/reasoning -> one option selected -> selection creates the appropriate Project proposal/decision using existing trust architecture -> canonical Project state records the validated direction -> Project Navigator subsequently shows the selected direction plus a useful Next -> glasses show only the concise projection. At the same time, verify AC Repair still receives an appropriate `TROUBLESHOOT`-shaped response rather than room-design-style alternatives, from the same Planner.

Requires an evaluation set of roughly 20-40 representative Project scenarios (troubleshooting, design/planning, general guidance) assessing response-family selection correctness, grounding in supplied evidence/context, usefulness/specificity, hallucination/unsupported assumptions, option differentiation, next-step quality, Project isolation, structured-output validation, and latency/token/cost behavior. Passing unit tests alone does not prove AI quality.

Sequencing (extends the "Implemented MVP Critical Path" above and the Glasses foundation sequence below; does not reopen the frozen Universal Project Workspace MVP):

1. Physically accept the current glasses Investigation + trust UX milestone (below).
2. Commit/checkpoint the proven cross-device flow.
3. Rich Project Intelligence V1 architecture/contracts (this entry) - focused design milestone for exact schemas.
4. Room Redesign vertical slice: Response Planner selection -> rich structured result -> rich phone UI -> selection -> Project Memory -> HUD projection.
5. Validate AC Repair troubleshooting behavior against the same Planner.
6. Rich Project Intelligence evaluation/hardening against the scenario set above.
7. Optional on-demand rich media/visualization slice.
8. Continue remaining bounded MVP/release hardening per existing roadmap priority, including the separately tracked DAT capture reliability issue below.

Not part of this direction: building the feature now; a universal chat transcript as canonical memory; model output directly mutating Project state; bypassing Proposal/Apply/trust controls; a vector/graph database without demonstrated need; a large response-family taxonomy; automatic image generation for every result; replacing deterministic Project orientation with AI; overloading the HUD with phone/desktop content; solving DAT capture reliability as part of this milestone; or deleting the existing Investigation/Explore mechanisms.

### Bounded Response Planner Correction - ADR-060 (2026-09-04)

Status: APPROVED ROADMAP direction only; not implemented by this documentation update. `docs/PROJECT_MEMORY_ARCHITECTURE.md` ADR-060 is authoritative; this entry summarizes the correction and sequencing.

**Historical sequencing note:** ADR-061 preserves this implemented router as a compatibility component but supersedes it as the target primary interaction model and supersedes its prohibition on persistent Project conversation storage.

**Why this changed:** the physical Room Redesign acceptance test run against the uncommitted Android implementation of the sequencing above surfaced a product/architecture defect in ADR-059's original dispatch rule, not an implementation bug. The natural physical flow (glasses Capture -> Use -> Continue on phone -> add explanation/context -> Analyze) always produced a basic diagnostic `TROUBLESHOOT` "AI suggestion," never the newly built `EXPLORE_PLAN` rich options, because reaching `EXPLORE_PLAN` required the user to notice and tap a separate explicit "Or explore design/planning ideas instead" alternative next to Analyze, or find an independent, always-visible "DESIGN & PLANNING GUIDANCE" composer elsewhere on the same screen. Exposing the response-family choice to the user this way required them to understand internal application architecture (TROUBLESHOOT vs. EXPLORE_PLAN vs. GENERAL_GUIDANCE) that ADR-059 never intended to surface, and it defeated the point of building Rich Project Intelligence in the first place.

**What changes:** response-family selection becomes application-owned bounded intelligent routing instead of explicit user/client dispatch. The user experience becomes one natural conversational action - Project context + current evidence + a natural typed request -> a bounded Response Planner -> the appropriate one of `TROUBLESHOOT` / `EXPLORE_PLAN` / `GENERAL_GUIDANCE` (no larger taxonomy) -> the existing typed result renderer. The primary action's label becomes neutral ("Get guidance," replacing "Analyze investigation" wherever it is the entry point). The explicit "Or explore design/planning ideas instead" button and the separate always-visible "DESIGN & PLANNING GUIDANCE" composer are removed from the intended architecture - there is exactly one natural guidance entry point per Project Interaction. A Project is never permanently typed to one family: the same Project can receive different families for different requests over time (e.g. a Room Redesign Project can still receive `TROUBLESHOOT` for "this drawer won't close").

**What does not change:** the three ADR-059 response families, the `ProjectAIResult` envelope, the Select -> Proposal -> Apply trust boundary, the bounded phone-rich/glasses-concise HUD split, Project Memory ownership, explicit `project_id`, Project isolation, provider neutrality, the existing Investigation/`TROUBLESHOOT`, `EXPLORE_PLAN`, and `GENERAL_GUIDANCE` implementations, and the already-validated stale-HUD Capture/Use/Retake repair (an unrelated defect, not reconsidered by this correction).

**Planner contract (see ADR-060 for the full decision):** narrow deterministic Context Pack in (Project identity/goal, checkpoint, recent relevant Activities/Investigations/Explore interactions, evidence presence, current request text - never full Project history, never a chat transcript store); typed routing metadata out only (`response_family`, `confidence`, `brief_reason`, `needs_clarification`) that is never persisted and never mutates canonical Project state. A technical planner failure is a retryable routing failure, never silently downgraded to `GENERAL_GUIDANCE`; `GENERAL_GUIDANCE` is chosen only when the Planner positively determines it is appropriate, or after one concise clarifying question when genuinely uncertain. The confidence policy governing proceed / clarify / `GENERAL_GUIDANCE` is intentionally not fixed yet - it must come from the routing evaluation set (extending ADR-059's existing 20-40 scenario requirement to also score family-selection accuracy), not an arbitrary constant. `TROUBLESHOOT` selected with no existing Investigation session is backend-owned session creation/reuse; Android must not invent this lifecycle. Glasses/HUD-initiated Analyze remains `TROUBLESHOOT`-only for V1 (no open-ended glasses intent composer exists yet); intelligent routing applies to the phone's single unified entry point only.

**Bounded sequencing (supersedes this milestone's earlier numbered sequencing above where they conflict):**

1. ADR-060 and this documentation update.
2. Backend planner/router contract (extends `ProjectAIResultPlanner`; no new canonical store).
3. Routing evaluation set and confidence policy (extends the existing ADR-059 evaluation requirement).
4. Android unified "Get guidance" flow (replaces the explicit-choice UX).
5. Automated and instrumented QA, including regression coverage that the existing Investigation/`TROUBLESHOOT` path and the stale-HUD repair remain intact.
6. One realistic physical Room Redesign acceptance retest.
7. Checkpoint only after that acceptance succeeds.

Not part of this direction: implementation now; expanding the response family list beyond these three; a universal chat-transcript memory; the Planner mutating Project state; a fixed/guessed confidence threshold; or any change to ADR-059's three response families, `ProjectAIResult` envelope, or trust boundary.

### Persistent Provider-Neutral Project Conversation - ADR-061 (2026-09-04)

Status: **APPROVED TARGET ARCHITECTURE; Phase 0, Phase 1A, and Phase 1B accepted; Phase 2 physically accepted on real hardware 2026-09-08 (see "Phase 2 Physical Validation" below); Phase 3A (conversational Explore + persistent image thumbnails) physically validated on real hardware 2026-09-08 (see "Phase 3A Physical Validation" below); Phase 3B (VisualArtifact conversation integration) implemented and automated-test-validated 2026-09-08, physical validation still pending.** `docs/PROJECT_MEMORY_ARCHITECTURE.md` ADR-061 is authoritative.

The primary product interaction becomes one persistent conversation per Project: `Project -> ProjectConversation -> ConversationTurn -> application-owned Assistant Orchestrator -> bounded application capabilities/tools -> Provider Adapter`. Conversation follows the Project across phone, desktop, and glasses, while Project Memory remains separate canonical truth. Turns use provider-neutral semantic content parts and typed references to authoritative Evidence, Activities, Investigations, VisualArtifacts, Proposals, Decisions, and other Project resources; they do not duplicate those records. Provider-native message/thread/tool formats are never canonical persistence. The model provider provides intelligence; the application provides continuity.

ADR-061 supersedes only ADR-057/Foundation and ADR-059/ADR-060 clauses that rejected persistent conversation storage. It preserves bounded selective retrieval, explicit `project_id`, isolation, provenance, idempotency, application validation, Proposal -> Apply, explicit trust for important state changes, and explicit user gating for expensive image generation. Existing response families remain compatible during migration but become internal capabilities rather than visible user modes: Explore for options, Investigation for evidence-backed diagnosis, and ordinary assistant answering for general guidance.

### Phase 2 Physical Validation - 2026-09-08: ADR-061 Conversation-First Capture Loop

Physically proven on real Meta glasses and a real Android phone:

```text
Project Conversation
-> Use Glasses
-> connect/stream
-> Capture
-> real photo preview on phone
-> Use/Retake available (both glasses HUD and phone)
-> Use from HUD
-> phone shows accepted-photo state
-> Continue to Project
-> exact photo reaches the same Project Conversation exactly once
-> voice question
-> multimodal AI response
-> glasses return cleanly
```

This validates the Phase 2 conversation-first vertical slice end to end on real hardware. It does **not** mark production readiness, security review, or cloud deployment readiness, and it does not migrate or retire any existing guidance/Investigation/Explore/VisualArtifact workflow - those remain runnable and unmigrated per the locked sequence above, reachable exactly as before from their own existing (non-conversation) entry points.

**Known post-Phase-2 UX debt (tracked for Phase 3+, not yet implemented):**

- ~~Conversation image history UX: a persisted image turn currently renders only an attachment/count indicator, not an actual thumbnail.~~ Resolved in Phase 3A - see "Phase 3A Physical Validation" below.
- Richer multimodal assistant experience: current visual answers are correct but can be generic. Future conversational responses should draw more on Project context/evidence, and may offer visual inspiration/generated/reference imagery when explicitly requested or clearly appropriate - subject to the existing explicit user-gating/cost policy for image generation (ADR-061 preserves this unchanged; it is not relaxed by this validation).

### Phase 3A Physical Validation - 2026-09-08: Conversational Explore + Persistent Image Thumbnails

Physically proven on the same real Project Conversation used for Phase 2 acceptance:

```text
Project Conversation
-> natural request for design ideas (no explicit mode/screen choice)
-> orchestrator's native tool-calling routes the turn to the existing Explore capability
-> Explore options returned in-conversation
-> user reaction to a specific option, in the same conversation
-> previously captured source photo re-opened from conversation history
-> renders as an actual tappable thumbnail (not a text/count placeholder)
-> tap opens a full-screen viewer
-> Back returns to the same, unaffected conversation
```

Two closeout fixes landed alongside this validation, both preserving existing architecture rather than changing it:

- **Explore failure handling**: the conversation send endpoint previously had no explicit mapping for a genuine Explore-execution failure (`ProjectExploreError`), which would have surfaced as an unhandled 500. It now maps to a clean, categorized `503 conversation_explore_unavailable` response; the underlying assistant turn was already left cleanly FAILED (never an empty COMPLETED turn, never a duplicate Explore execution, never a Project Memory mutation) by the existing Assistant Orchestrator failure path - this closes the gap between that internal state and the HTTP response the client actually sees.
- **Persistent image thumbnails**: conversation turns still only ever store a typed reference to canonical Evidence (`PROJECT_RESOURCE_REFERENCE`); no second image store, no Bitmap/byte copy into conversation persistence, and no dependency on the transient in-memory capture Bitmap. Android resolves that reference to real image bytes on demand, through the same Project-isolated Evidence content route the legacy Investigation panel already used, and renders it with a lightweight session-lifetime rendering cache. This is why the image survives conversation reload, app relaunch, and reopening the Project later - it was never conversation-owned to begin with.

This validates the Phase 3A vertical slice end to end. It does **not** mark production readiness, security review, or cloud deployment readiness, and it does not start VisualArtifact or Investigation conversation integration - those remain the next, not-yet-started Phase 3B/3C slices.

### Phase 3B Physical Validation - 2026-09-08: Conversational VisualArtifact

Physically proven, with a real OpenAI provider, on the same real Project Conversation used for Phase 2/3A acceptance:

```text
Project Conversation (existing dresser Evidence + 3-option Explore result already present)
-> "I like option three. Show me what that would look like in my room."
-> explicit visual intent recognized immediately - no confirmation round trip
-> VISUALIZE_OPTION capability intent
-> existing VisualArtifactService invoked, existing dresser Evidence used, option 3 context preserved
-> generated visualization appears in the SAME conversation, labeled "AI visualization"
-> tap opens a full-screen viewer
-> Back returns to the same, unaffected conversation
-> no legacy Explore/VisualArtifact workflow opened
```

This was the third real attempt. The first two did not pass, for two unrelated reasons, both since resolved:

- **First attempt** - a real model answered an already-explicit visualize request with prose and a false "I'm preparing/proceeding..." claim instead of calling the tool, because the system prompt itself discouraged tool use ("Return a natural text reply", unconditionally). Repaired at the prompt/instruction level inside the OpenAI adapter only - never application-side keyword routing, never a change to the typed `AssistantCapabilityIntent` dispatch.
- **Second attempt** - failed again, but for an unrelated reason: the backend process actually serving the request had been running since before the first repair was even written to disk (uvicorn runs without `--reload`, so it never picked up any Phase 3B code at all). Resolved operationally by stopping the stale/duplicate processes and restarting the canonical backend from current code - see "Backend startup/stale-listener protection" above for the recorded follow-up hardening.

One UX defect was observed and is **not** a Phase 3B acceptance blocker: the generated visualization displayed sideways with no way to correct it - folded into the Conversation Media UX backlog item above, now covering both Source Evidence and generated VisualArtifacts.

This validates the Phase 3B vertical slice end to end, with a real provider. It does **not** mark production readiness, security review, or cloud deployment readiness, and it does not start Phase 3C (Investigation conversation integration), which remains the next, not-yet-started slice.

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
7. Trust actions: Looks right, Add more info, Not quite.
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

### Physical Validation - 2026-09-03: Investigation + Trust Loop

The full glasses <-> phone Investigation MVP cross-device loop (foundation items 1-8 above) is now physically proven:

```text
Glasses Project Navigator
-> Capture
-> Use / Retake
-> Continue on phone
-> existing active Investigation panel opens directly
-> add typed/voice context
-> Analyze on phone
-> canonical Investigation result
-> return/reconnect to glasses
-> concise AI suggestion / suggested next step / trust flow
```

Two implementation refinements are part of this milestone, both preserving existing architecture/trust semantics rather than changing them:

- The Continue-on-phone destination decision no longer depends on the Investigation ViewModel's asynchronous eligibility signal, which proved unreliable to time against a real physical tap. It now depends on the glasses HUD controller's own synchronous capture-accepted event, reset at explicit Project/session boundaries - a deterministic fix, not a new architecture.
- Trust-action wording was simplified for both surfaces (glasses HUD and phone): "Keep as hypothesis / Add evidence / Return" -> "Looks right / Add more info / Not quite" (see foundation item 7 above, refining ADR-049's provisional CONTINUE/DISAGREE/MORE EVIDENCE terminology). Underlying trust decisions, persistence, and the Idea/Decision/Checkpoint Proposal mechanism are unchanged - only user-facing copy and confirmation visibility changed. Phone Analyze (via the existing Investigation panel) is now the primary Analyze trigger; HUD-initiated Analyze remains available as secondary, not required for the primary path.

This validates the loop's interaction path end to end. It does **not** mark the overall product MVP/release complete, and it does not change the DAT 0.8 Capture Capability Gate finding below: `Stream.capturePhoto()` reliability remains a separate, known, unresolved hardening issue tracked independently of this loop's completion.

The HUD Project Navigator requirement (foundation items 2-6, 8 above) is preserved unchanged by this milestone: the glasses provide bounded orientation over the active Project only - where we are now/where we left off, recent important progress, current guidance/finding where useful, Next, limited evidence/activity, and actions for continuing work (Capture, Continue on phone, See details) - never a full Project Detail surface.

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
