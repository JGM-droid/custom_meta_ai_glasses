from __future__ import annotations

from pathlib import Path


DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"


def _dashboard_source() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


# Narrow regression coverage for the Human-Reviewed Checkpoint Proposal UI
# slice: exposing the existing, already-tested Phase C2 Checkpoint Proposal
# backend (see test_checkpoint_proposals_phasec2.py) through the Project
# Workspace, without changing that backend contract in any way.
#
# These tests do not re-prove Phase C2 store/API behavior itself (revision
# conflicts, state transitions, cross-project reference rejection, etc.);
# they prove the dashboard wires the existing endpoints correctly and keeps
# the "AI/Activity-derived information must not silently mutate canonical
# Project Memory" rule visible in the UI code path.


def test_checkpoint_updates_section_exists_and_is_visually_separated_contract():
    source = _dashboard_source()
    assert ">Checkpoint Updates<" in source
    # Must be adjacent to Now/Next so canonical vs proposed state can be
    # compared directly, and must carry an explicit non-canonical disclaimer -
    # the same established pattern already used for Ask AI vs Get Context.
    assert "Proposed changes shown here are NOT canonical. Now/Next above only change when you explicitly click Apply on a pending proposal." in source
    assert 'id="workspaceCheckpointProposals"' in source
    assert 'id="workspaceCheckpointProposalsStatus"' in source


def test_propose_as_next_action_affordance_on_history_activities_contract():
    source = _dashboard_source()
    assert 'proposeBtn.textContent = "Propose as Next Action";' in source
    assert 'proposeBtn.className = "workspace-propose-btn";' in source
    # Wired from renderWorkspaceHistory's per-activity loop, not a separate
    # freestanding "create proposal" entry point - Phase 3 scope only.
    assert "proposeBtn.addEventListener(\"click\", () => {" in source
    assert "showProposalForm({" in source
    assert "sourceActivityId: activity.activity_id," in source


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

    # Creating a proposal must never assign into the canonical Now/Next DOM
    # directly (no optimistic fake mutation) - the only path back to Now/Next
    # is a real re-fetch of the Project via refreshProjectAndProposals, which
    # renders whatever the server actually returns.
    assert "workspaceNext.textContent =" not in creation_fn_body
    assert "workspaceNow.textContent =" not in creation_fn_body
    assert "await refreshProjectAndProposals(projectId);" in creation_fn_body


def test_pending_proposal_rendering_shows_current_vs_proposed_and_provenance_contract():
    source = _dashboard_source()
    assert "function renderCheckpointProposals(proposals) {" in source
    # Current vs proposed comparison, not just the proposed value alone.
    assert "const currentCheckpoint = (workspaceOpenProjectDetail && workspaceOpenProjectDetail.checkpoint) || {};" in source
    assert "current: ${compactText(currentValue, 160)} -> proposed:" in source
    # Status is rendered explicitly (pending/applied/rejected), not inferred.
    assert 'statusChip.className = `workspace-chip status-${normalize(proposal.status) || "pending"}`;' in source
    # Source Activity provenance is shown when present.
    assert "Source Activity: ${sourceIds.join(\", \")}" in source
    # Apply/Reject are only offered while a proposal is actually pending -
    # applied/rejected proposals are terminal per the existing backend
    # contract and must not offer actions that would 409.
    assert 'if (proposal.status === "pending") {' in source


def test_apply_wiring_refreshes_canonical_now_next_contract():
    source = _dashboard_source()
    assert 'const API_PROJECT_CHECKPOINT_PROPOSAL_APPLY_URL = (projectId, proposalId) => `${API_ORIGIN}/projects/${projectId}/checkpoint-proposals/${proposalId}/apply`;' in source
    assert "async function applyCheckpointProposal(proposalId) {" in source
    assert "applyBtn.addEventListener(\"click\", () => applyCheckpointProposal(proposal.proposal_id));" in source

    apply_fn_start = source.index("async function applyCheckpointProposal(proposalId) {")
    apply_fn_end = source.index("\n    async function rejectCheckpointProposal", apply_fn_start)
    apply_fn_body = source[apply_fn_start:apply_fn_end]

    assert 'method: "POST"' in apply_fn_body
    # No optimistic client-side mutation before the server confirms success.
    assert "workspaceNext.textContent =" not in apply_fn_body
    # Canonical state (which repaints Now/Next via renderWorkspaceNowNext) is
    # re-fetched from the server after every attempt, success or failure.
    assert "await refreshProjectAndProposals(projectId);" in apply_fn_body


def test_apply_conflict_handling_is_explicit_and_non_destructive_contract():
    source = _dashboard_source()
    apply_fn_start = source.index("async function applyCheckpointProposal(proposalId) {")
    apply_fn_end = source.index("\n    async function rejectCheckpointProposal", apply_fn_start)
    apply_fn_body = source[apply_fn_start:apply_fn_end]

    # A 409 (revision_conflict from the existing backend contract) must be
    # handled explicitly with a concise, human-readable message - not treated
    # like a generic error, and never retried/rebased automatically.
    assert 'if (response.status === 409) {' in apply_fn_body
    assert "Canonical Project state has changed since this proposal was created. Nothing was overwritten; refreshed below." in apply_fn_body
    # Still refreshes canonical state afterward so the UI reflects the real
    # (unchanged-by-this-attempt) revision/status rather than going stale.
    assert apply_fn_body.count("await refreshProjectAndProposals(projectId);") == 1


def test_reject_wiring_leaves_checkpoint_unchanged_contract():
    source = _dashboard_source()
    assert 'const API_PROJECT_CHECKPOINT_PROPOSAL_REJECT_URL = (projectId, proposalId) => `${API_ORIGIN}/projects/${projectId}/checkpoint-proposals/${proposalId}/reject`;' in source
    assert "async function rejectCheckpointProposal(proposalId) {" in source
    assert "rejectBtn.addEventListener(\"click\", () => rejectCheckpointProposal(proposal.proposal_id));" in source

    reject_fn_start = source.index("async function rejectCheckpointProposal(proposalId) {")
    reject_fn_end = source.index("\n    function renderWorkspaceAskResult", reject_fn_start)
    reject_fn_body = source[reject_fn_start:reject_fn_end]

    assert 'method: "POST"' in reject_fn_body
    assert "workspaceNext.textContent =" not in reject_fn_body
    assert "Proposal rejected. Checkpoint unchanged." in reject_fn_body
    assert "await refreshProjectAndProposals(projectId);" in reject_fn_body


def test_checkpoint_proposals_load_within_same_isolation_guarded_fetch_as_history_contract():
    source = _dashboard_source()
    # Proposals must be fetched inside openWorkspaceProject's existing
    # Promise.all + loadToken staleness guard, exactly like
    # activities/sessions/contextPack already are - this is what prevents a
    # rapid project switch from painting Project A's proposals into an
    # Inspector that has since moved on to Project B.
    open_fn_start = source.index("async function openWorkspaceProject(projectId, { forceReset = false } = {}) {")
    open_fn_end = source.index("\n    async function askWorkspaceProjectQuestion", open_fn_start)
    open_fn_body = source[open_fn_start:open_fn_end]

    assert "const [projectDetail, activities, sessions, contextPack, proposals] = await Promise.all([" in open_fn_body
    assert "fetchJsonOrThrow(API_PROJECT_CHECKPOINT_PROPOSALS_URL(projectId), \"Unable to load checkpoint proposals\")," in open_fn_body
    assert "if (loadToken !== workspaceLoadingToken) return;" in open_fn_body
    assert "renderCheckpointProposals(workspaceProposalsCache);" in open_fn_body


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
