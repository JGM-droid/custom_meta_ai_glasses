from __future__ import annotations

from pathlib import Path


DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"


def _dashboard_source() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


# Narrow regression coverage for two combined slices in the Project Workspace:
#
# 1. The Human-Reviewed Checkpoint Proposal UI itself, exposing the existing,
#    already-tested Phase C2 Checkpoint Proposal backend
#    (see test_checkpoint_proposals_phasec2.py) without changing that backend
#    contract in any way.
# 2. The market-facing terminology slice on top of it: "Captured" /
#    "Suggested Next Step" / "Confirm & Add" / "Dismiss" / "Confirmed & Added"
#    replace raw backend words (ai/inferred/result/apply/reject/proposal) in
#    the primary UI, while the backend endpoints, statuses, and fields those
#    words describe are completely unchanged.
#
# These tests do not re-prove Phase C2 store/API behavior itself (revision
# conflicts, state transitions, cross-project reference rejection, etc.);
# they prove the dashboard wires the existing endpoints correctly and keeps
# the "AI/Activity-derived information must not silently mutate canonical
# Project Memory" rule true - and visible in honest, non-technical language -
# in the UI code path.


def test_checkpoint_updates_section_is_now_suggested_next_steps_contract():
    source = _dashboard_source()
    assert ">Suggested Next Steps<" in source
    assert ">Checkpoint Updates<" not in source
    # Must be adjacent to Now/Next so canonical vs proposed state can be
    # compared directly, and must carry an explicit non-canonical disclaimer -
    # the same established pattern already used for Ask AI vs Get Context.
    assert "Review a suggested next step before adding it to this project." in source
    assert 'id="workspaceCheckpointProposals"' in source
    assert 'id="workspaceCheckpointProposalsStatus"' in source


def test_history_activity_cards_use_captured_presentation_contract():
    source = _dashboard_source()
    history_fn_start = source.index("function renderWorkspaceHistory(activities) {")
    history_fn_end = source.index("\n    function extractSuggestedNextAction", history_fn_start)
    history_fn_body = source[history_fn_start:history_fn_end]

    # "Captured" is the primary label on every History card, regardless of
    # source - it must never be conflated with "confirmed".
    assert 'capturedLabel.textContent = "Captured";' in history_fn_body
    assert "capturedLabel.className = \"workspace-captured-label\";" in history_fn_body
    assert "card.appendChild(capturedLabel);" in history_fn_body


def test_history_raw_provenance_labels_moved_to_details_disclosure_contract():
    source = _dashboard_source()
    history_fn_start = source.index("function renderWorkspaceHistory(activities) {")
    history_fn_end = source.index("\n    function extractSuggestedNextAction", history_fn_start)
    history_fn_body = source[history_fn_start:history_fn_end]

    # Raw ai/inferred/result-style words must not be assigned to the primary
    # label/summary elements - only into the collapsed Details disclosure.
    assert 'typeChip.textContent = normalize(activity.activity_type)' not in history_fn_body
    assert 'sourceChip.textContent = normalize(activity.source_type)' not in history_fn_body
    assert 'confidenceChip.textContent = normalize(activity.confirmation_status)' not in history_fn_body

    details_index = history_fn_body.index('details.className = "workspace-details-disclosure";')
    detail_fields_index = history_fn_body.index("`Type: ${normalizeOrFallback(activity.activity_type")
    assert detail_fields_index > details_index
    assert "`Source: ${normalizeOrFallback(activity.source_type" in history_fn_body
    assert "`Status: ${normalizeOrFallback(activity.confirmation_status" in history_fn_body
    assert 'detailsSummary.textContent = "Details";' in history_fn_body

    # Human-readable provenance line uses the source_type -> plain-language
    # mapping, not the raw backend word.
    assert "provenanceLine.textContent = `${humanSourceLabel(activity.source_type)} · ${formatShortDate(occurredAt)}`;" in history_fn_body


def test_human_source_label_never_returns_raw_backend_words_contract():
    source = _dashboard_source()
    fn_start = source.index("function humanSourceLabel(sourceType) {")
    fn_end = source.index("\n    }", fn_start)
    fn_body = source[fn_start:fn_end]

    assert 'if (value === "ai") return "From Investigation";' in fn_body
    assert 'if (value === "user") return "Reported by user";' in fn_body
    assert 'if (value === "system") return "System note";' in fn_body
    # None of the return values are the raw enum words themselves.
    for raw_word in ['return "ai"', 'return "inferred"', 'return "result"']:
        assert raw_word not in fn_body


def test_suggest_as_next_step_affordance_on_history_activities_contract():
    source = _dashboard_source()
    assert 'proposeBtn.textContent = "Suggest as Next Step";' in source
    assert 'proposeBtn.className = "workspace-propose-btn";' in source
    # Wired from renderWorkspaceHistory's per-activity loop, not a separate
    # freestanding entry point - Phase 3 scope only.
    assert "proposeBtn.addEventListener(\"click\", () => {" in source
    assert "showProposalForm({" in source
    assert "sourceActivityId: activity.activity_id," in source
    # The raw Activity UUID must not be the primary thing shown when the
    # draft opens - a human source label is used instead.
    assert "sourceLabel: humanActivityReferenceLabel(activity)," in source


def test_propose_prefill_reuses_existing_activity_text_no_model_call_contract():
    source = _dashboard_source()
    # Must derive the suggested next_action purely from text the D2 Activity
    # projection already wrote (api.py's
    # `_project_completed_investigation_activity`, "Recommended next action:
    # <text>" in `details`) - no new AI/model call for proposal generation.
    assert "function extractSuggestedNextAction(activity) {" in source
    assert "const match = detailText.match(/Recommended next action:\\s*(.+)$/);" in source
    assert "return normalize(activity.summary);" in source
    assert "suggestedNextAction: extractSuggestedNextAction(activity)," in source

    # The field must remain a plain editable textarea, not a locked/read-only
    # preview - the user must be able to review and change it before create.
    assert 'id="workspaceProposalNextAction" class="workspace-ask-input" rows="3" maxlength="1000" placeholder="What should happen next?" required></textarea>' in source
    assert "workspaceProposalNextAction.value = suggestedNextAction;" in source


def test_showproposalform_does_not_surface_raw_activity_uuid_contract():
    source = _dashboard_source()
    fn_start = source.index("function showProposalForm({")
    fn_end = source.index("\n    function hideProposalForm", fn_start)
    fn_body = source[fn_start:fn_end]

    assert "`Based on: ${sourceLabel" in fn_body
    assert "Source: Activity ${sourceActivityId}" not in fn_body


def test_create_proposal_preserves_source_activity_id_and_reuses_existing_endpoint_contract():
    source = _dashboard_source()
    assert 'const API_PROJECT_CHECKPOINT_PROPOSALS_URL = (projectId) => `${API_ORIGIN}/projects/${projectId}/checkpoint-proposals`;' in source
    assert "async function submitCreateCheckpointProposal(event) {" in source
    assert "const response = await fetch(API_PROJECT_CHECKPOINT_PROPOSALS_URL(projectId), {" in source
    assert 'method: "POST",' in source

    # expected_project_revision must come from the actually-loaded canonical
    # project detail, never a client-guessed/hardcoded value - this is what
    # lets the existing backend revision check do its job.
    assert "expected_project_revision: workspaceOpenProjectDetail.revision," in source
    # source_activity_ids provenance must flow through from whichever Activity
    # (if any) the draft was opened from.
    assert "source_activity_ids: workspaceProposalSourceActivityId ? [workspaceProposalSourceActivityId] : []," in source
    assert "proposed_checkpoint_patch: { next_action: nextAction }," in source


def test_create_proposal_does_not_client_side_mutate_checkpoint_contract():
    source = _dashboard_source()
    creation_fn_start = source.index("async function submitCreateCheckpointProposal(event) {")
    creation_fn_end = source.index("\n    }\n", creation_fn_start)
    creation_fn_body = source[creation_fn_start:creation_fn_end]

    # Creating a suggestion must never assign into the canonical Now/Next DOM
    # directly (no optimistic fake mutation) - the only path back to Now/Next
    # is a real re-fetch of the Project via refreshProjectAndProposals, which
    # renders whatever the server actually returns.
    assert "workspaceNext.textContent =" not in creation_fn_body
    assert "workspaceNow.textContent =" not in creation_fn_body
    assert "await refreshProjectAndProposals(projectId);" in creation_fn_body


def test_pending_suggestion_shows_current_and_suggested_values_and_confirm_note_contract():
    source = _dashboard_source()
    fn_start = source.index("function renderCheckpointProposals(proposals) {")
    fn_end = source.index("\n    async function refreshProjectAndProposals", fn_start)
    fn_body = source[fn_start:fn_end]

    assert "const currentCheckpoint = (workspaceOpenProjectDetail && workspaceOpenProjectDetail.checkpoint) || {};" in fn_body

    # Pending headline and required minimum wording per the approved slice.
    assert 'headline.textContent = "Suggested Next Step";' in fn_body
    assert "`Current next step: ${normalizeOrFallback(currentCheckpoint.next_action" in fn_body
    assert 'confirmNote.textContent = "Nothing changes until you confirm.";' in fn_body
    assert 'confirmNote.className = "workspace-confirm-note";' in fn_body

    # "Based on: <human label>" provenance, not a raw source_activity_id/UUID
    # in the primary card body.
    assert "`Based on: ${humanActivityReferenceLabel(sourceActivity)}`" in fn_body

    # Status is used only to select which branch renders (still internally
    # "pending"/"applied"/"rejected", matching the backend contract exactly)
    # - it is not itself displayed as the primary word.
    assert 'if (proposal.status === "pending") {' in fn_body
    assert 'headline.textContent = "Confirmed & Added";' in fn_body
    assert 'headline.textContent = "Dismissed";' in fn_body

    # Full technical provenance (raw status, reason, source Activity ids,
    # proposal id) remains available, just behind a Details disclosure.
    assert 'details.className = "workspace-details-disclosure";' in fn_body
    assert "`Status: ${normalizeOrFallback(proposal.status" in fn_body
    assert "`Source Activity: ${sourceIds.join" in fn_body


def test_apply_wiring_refreshes_canonical_now_next_contract():
    source = _dashboard_source()
    assert 'const API_PROJECT_CHECKPOINT_PROPOSAL_APPLY_URL = (projectId, proposalId) => `${API_ORIGIN}/projects/${projectId}/checkpoint-proposals/${proposalId}/apply`;' in source
    assert "async function applyCheckpointProposal(proposalId) {" in source
    assert "applyBtn.addEventListener(\"click\", () => applyCheckpointProposal(proposal.proposal_id));" in source
    assert 'applyBtn.textContent = "Confirm & Add";' in source

    apply_fn_start = source.index("async function applyCheckpointProposal(proposalId) {")
    apply_fn_end = source.index("\n    async function rejectCheckpointProposal", apply_fn_start)
    apply_fn_body = source[apply_fn_start:apply_fn_end]

    assert 'method: "POST"' in apply_fn_body
    # No optimistic client-side mutation before the server confirms success.
    assert "workspaceNext.textContent =" not in apply_fn_body
    # Canonical state (which repaints Now/Next via renderWorkspaceNowNext) is
    # re-fetched from the server after every attempt, success or failure.
    assert "await refreshProjectAndProposals(projectId);" in apply_fn_body
    # Required minimum customer-facing success wording.
    assert "Confirmed & Added. This is now part of your project." in apply_fn_body


def test_apply_conflict_handling_is_explicit_and_non_destructive_contract():
    source = _dashboard_source()
    apply_fn_start = source.index("async function applyCheckpointProposal(proposalId) {")
    apply_fn_end = source.index("\n    async function rejectCheckpointProposal", apply_fn_start)
    apply_fn_body = source[apply_fn_start:apply_fn_end]

    # A 409 (revision_conflict from the existing backend contract) must be
    # handled explicitly with a concise, human-readable message - not treated
    # like a generic error, and never retried/rebased automatically.
    assert 'if (response.status === 409) {' in apply_fn_body
    assert (
        "This project changed after this suggestion was created. "
        "Nothing was overwritten. Review the latest project state before confirming."
    ) in apply_fn_body
    # Still refreshes canonical state afterward so the UI reflects the real
    # (unchanged-by-this-attempt) revision/status rather than going stale.
    assert apply_fn_body.count("await refreshProjectAndProposals(projectId);") == 1


def test_reject_wiring_leaves_checkpoint_unchanged_contract():
    source = _dashboard_source()
    assert 'const API_PROJECT_CHECKPOINT_PROPOSAL_REJECT_URL = (projectId, proposalId) => `${API_ORIGIN}/projects/${projectId}/checkpoint-proposals/${proposalId}/reject`;' in source
    assert "async function rejectCheckpointProposal(proposalId) {" in source
    assert "rejectBtn.addEventListener(\"click\", () => rejectCheckpointProposal(proposal.proposal_id));" in source
    assert 'rejectBtn.textContent = "Dismiss";' in source

    reject_fn_start = source.index("async function rejectCheckpointProposal(proposalId) {")
    reject_fn_end = source.index("\n    function renderWorkspaceAskResult", reject_fn_start)
    reject_fn_body = source[reject_fn_start:reject_fn_end]

    assert 'method: "POST"' in reject_fn_body
    assert "workspaceNext.textContent =" not in reject_fn_body
    assert "Dismissed. This suggestion was not added to your project." in reject_fn_body
    assert "await refreshProjectAndProposals(projectId);" in reject_fn_body


def test_checkpoint_proposals_load_within_same_isolation_guarded_fetch_as_history_contract():
    source = _dashboard_source()
    # Proposals must be fetched inside openWorkspaceProject's existing
    # Promise.all + loadToken staleness guard, exactly like
    # activities/sessions/contextPack already are - this is what prevents a
    # rapid project switch from painting Project A's suggestions into an
    # Inspector that has since moved on to Project B.
    open_fn_start = source.index("async function openWorkspaceProject(projectId, { forceReset = false } = {}) {")
    open_fn_end = source.index("\n    async function askWorkspaceProjectQuestion", open_fn_start)
    open_fn_body = source[open_fn_start:open_fn_end]

    assert "const [projectDetail, activities, sessions, contextPack, proposals] = await Promise.all([" in open_fn_body
    assert "fetchJsonOrThrow(API_PROJECT_CHECKPOINT_PROPOSALS_URL(projectId), \"Unable to load checkpoint proposals\")," in open_fn_body
    assert "if (loadToken !== workspaceLoadingToken) return;" in open_fn_body
    assert "renderCheckpointProposals(workspaceProposalsCache);" in open_fn_body
    # Activities are cached too so a "Based on: ..." source label can be
    # resolved after a later Confirm & Add / Dismiss refresh without an
    # extra fetch (Activities don't change on those actions).
    assert "workspaceActivitiesCache = Array.isArray(activities) ? activities : [];" in open_fn_body


def test_project_switch_clears_but_background_poll_preserves_proposal_draft_contract():
    source = _dashboard_source()
    open_fn_start = source.index("async function openWorkspaceProject(projectId, { forceReset = false } = {}) {")
    open_fn_end = source.index("\n    async function askWorkspaceProjectQuestion", open_fn_start)
    open_fn_body = source[open_fn_start:open_fn_end]

    # hideProposalForm() must be gated by the same projectChanged||forceReset
    # condition already used to protect Ask views (see
    # test_workspace_ask_views_survive_background_poll_of_same_project_contract
    # in test_dashboard_project_workspace_contract.py) - a background poll of
    # the *same* open project must never call it, but an actual project
    # switch (or explicit Open) must.
    guarded_block_start = open_fn_body.index("if (projectChanged || forceReset) {")
    guarded_block_end = open_fn_body.index("\n      }", guarded_block_start)
    guarded_block = open_fn_body[guarded_block_start:guarded_block_end]
    assert "hideProposalForm();" in guarded_block

    # And it must not appear anywhere outside that guarded block within
    # openWorkspaceProject (i.e. not unconditionally called on every poll).
    unguarded_body = open_fn_body[:guarded_block_start] + open_fn_body[guarded_block_end:]
    assert "hideProposalForm()" not in unguarded_body


def test_refresh_after_proposal_action_is_project_scoped_contract():
    source = _dashboard_source()
    assert "async function refreshProjectAndProposals(projectId) {" in source
    refresh_fn_start = source.index("async function refreshProjectAndProposals(projectId) {")
    refresh_fn_end = source.index("\n    async function submitCreateCheckpointProposal", refresh_fn_start)
    refresh_fn_body = source[refresh_fn_start:refresh_fn_end]

    # If the user has since switched to a different Project while an
    # apply/reject/create refresh was in flight, the stale response must not
    # be painted into the now-different open Inspector.
    assert "if (projectId !== workspaceSelectedProjectId) return;" in refresh_fn_body
    assert "workspaceOpenProjectDetail = projectDetail;" in refresh_fn_body
    assert "renderWorkspaceNowNext(projectDetail, null);" in refresh_fn_body


def test_no_apply_reject_wording_remains_in_primary_ui_contract():
    source = _dashboard_source()
    # The old customer-facing button labels/status wording must be fully
    # gone; the backend endpoint names/functions/URLs (which legitimately
    # still say "apply"/"reject" internally) are exempt and checked
    # separately above.
    assert '>Apply<' not in source
    assert '>Reject<' not in source
    assert "applyBtn.textContent = \"Apply\";" not in source
    assert "rejectBtn.textContent = \"Reject\";" not in source
