from __future__ import annotations

import io
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from investigations.session_store import InvestigationSessionStore
from projects import CheckpointProposalStore, ProjectActivityStore, ProjectStore


@pytest.fixture
def mvp_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    results = tmp_path / "results"
    projects_root = results / "projects"
    sessions_root = results / "investigation_sessions"
    project_store = ProjectStore(projects_root)
    activity_store = ProjectActivityStore(projects_root, project_store)
    proposal_store = CheckpointProposalStore(projects_root, project_store, activity_store)
    session_store = InvestigationSessionStore(sessions_root)
    monkeypatch.setattr(api, "PROJECT_STORE", project_store)
    monkeypatch.setattr(api, "PROJECT_ACTIVITY_STORE", activity_store)
    monkeypatch.setattr(api, "CHECKPOINT_PROPOSAL_STORE", proposal_store)
    monkeypatch.setattr(api, "SESSION_STORE", session_store)
    monkeypatch.setattr(api, "EVIDENCE_STORE", api.InvestigationEvidenceStore(session_store))
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", results / "investigation_latest.json")
    monkeypatch.setattr(api, "DEMO_INVESTIGATION_REGISTRY", api._DemoInvestigationRegistry())
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "")
    return TestClient(api.app), projects_root, sessions_root


def _activity(client, project_id, summary, activity_type, confirmation="confirmed", metadata=None):
    response = client.post(f"/projects/{project_id}/activities", json={
        "activity_type": activity_type, "source_type": "user",
        "confirmation_status": confirmation, "summary": summary, "metadata": metadata,
    })
    assert response.status_code == 201
    return response.json()


def _wait_demo(client, demo_id):
    for _ in range(80):
        snap = client.get(f"/demo/investigations/{demo_id}").json()
        if snap["status"] in {"completed", "failed"}:
            return snap
        time.sleep(.05)
    raise AssertionError("demo Investigation did not finish")


def test_complete_offline_mvp_story_survives_store_restart_and_isolates_projects(mvp_context, monkeypatch):
    client, projects_root, sessions_root = mvp_context
    monkeypatch.setattr(api, "OpenAI", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("offline MVP must not call AI")))
    project = client.post("/projects", json={
        "name": "AC Repair", "goal": "Restore reliable cooling",
        "checkpoint": {"current_objective": "Electrical diagnosis", "current_work": "Testing capacitor", "next_action": "Measure capacitance"},
    }).json()
    other = client.post("/projects", json={"name": "Software Project", "goal": "Ship safely"}).json()
    for summary, status in [("Inspect system", "completed"), ("Test capacitor", "current"), ("Repair fault", "upcoming"), ("Replace thermostat", "deferred")]:
        _activity(client, project["project_id"], summary, "milestone", metadata={"roadmap_status": status})
    orientation = client.get(f"/projects/{project['project_id']}/orientation").json()
    assert orientation["now"] == "Testing capacitor"
    assert orientation["roadmap"]["current"][0]["summary"] == "Test capacitor"

    files = [("images", ("meter.png", io.BytesIO(b"one"), "image/png")), ("images", ("unit.png", io.BytesIO(b"two"), "image/png"))]
    run = client.post("/demo/investigations", data={"mode": "dry_run", "project_id": project["project_id"], "user_explanation": "Capacitor and outdoor unit evidence"}, files=files)
    assert run.status_code == 202
    snapshot = _wait_demo(client, run.json()["demo_id"])
    assert snapshot["status"] == "completed" and snapshot["retained_result"]
    session_id = snapshot["session_id"]
    ai_activity = [a for a in client.get(f"/projects/{project['project_id']}/activities").json() if a["source_type"] == "ai"][0]
    assert ai_activity["confirmation_status"] == "inferred"

    continued = client.post(f"/projects/{project['project_id']}/investigation-sessions/{session_id}/trust-decision", json={"decision": "continue"})
    assert continued.status_code == 201
    assert continued.json()["trust_state"]["status"] == "working_hypothesis"
    assert continued.json()["checkpoint_proposal"]["status"] == "pending"
    assert client.get(f"/projects/{project['project_id']}/orientation").json()["next"] == "Measure capacitance"
    proposal_id = continued.json()["checkpoint_proposal"]["proposal_id"]
    assert client.post(f"/projects/{project['project_id']}/checkpoint-proposals/{proposal_id}/apply").status_code == 200
    assert client.get(f"/projects/{project['project_id']}/orientation").json()["next"] == snapshot["retained_result"]["required_next_action"]

    _activity(client, project["project_id"], "Capacitor measured below specification", "observation", "observed")
    _activity(client, project["project_id"], "Replace capacitor", "decision")
    _activity(client, project["project_id"], "Capacitor is below specification", "result")
    knowledge = client.get(f"/projects/{project['project_id']}/knowledge").json()
    assert knowledge["evidence"] and knowledge["decisions"] and knowledge["findings"] and knowledge["history"]
    assert any(x["activity_id"] == ai_activity["activity_id"] and x["confirmation_status"] == "inferred" for x in knowledge["recent_important_changes"])

    idea = client.post(f"/projects/{project['project_id']}/ideas", json={"summary": "Replace thermostat later"}).json()
    before_promotion = client.get(f"/projects/{project['project_id']}/orientation").json()
    assert idea["activity_id"] not in str(before_promotion["roadmap"])
    promoted = client.post(f"/projects/{project['project_id']}/ideas/{idea['activity_id']}/promote").json()
    assert promoted["roadmap_activity"]["metadata"]["promoted_from_activity_id"] == idea["activity_id"]
    after_promotion = client.get(f"/projects/{project['project_id']}/orientation").json()
    assert promoted["roadmap_activity"]["activity_id"] in {x["activity_id"] for x in after_promotion["roadmap"]["upcoming"]}
    assert idea["activity_id"] in {x["activity_id"] for x in client.get(f"/projects/{project['project_id']}/knowledge").json()["history"]}
    assert client.get(f"/projects/{other['project_id']}/knowledge").json()["history"] == []

    expected_orientation = after_promotion
    restarted_project_store = ProjectStore(projects_root)
    restarted_activity_store = ProjectActivityStore(projects_root, restarted_project_store)
    restarted_proposal_store = CheckpointProposalStore(projects_root, restarted_project_store, restarted_activity_store)
    restarted_session_store = InvestigationSessionStore(sessions_root)
    monkeypatch.setattr(api, "PROJECT_STORE", restarted_project_store)
    monkeypatch.setattr(api, "PROJECT_ACTIVITY_STORE", restarted_activity_store)
    monkeypatch.setattr(api, "CHECKPOINT_PROPOSAL_STORE", restarted_proposal_store)
    monkeypatch.setattr(api, "SESSION_STORE", restarted_session_store)
    monkeypatch.setattr(api, "EVIDENCE_STORE", api.InvestigationEvidenceStore(restarted_session_store))
    assert client.get(f"/projects/{project['project_id']}/orientation").json() == expected_orientation
    assert client.get(f"/projects/{project['project_id']}/knowledge").json()["findings"]
    assert client.get(f"/projects/{project['project_id']}/ideas").json()["ideas"][0]["activity_id"] == idea["activity_id"]


def test_mvp_demo_page_exposes_locked_workflow_without_touching_dashboard(mvp_context):
    client, *_ = mvp_context
    response = client.get("/mvp-demo")
    assert response.status_code == 200
    source = response.text
    for required in ["CURRENT PROJECT", "Needs Your Attention", "Where we are", "Roadmap", "Recent Important Changes", "Evidence", "Decisions", "Confirmed Findings", "Project history", "Ideas for this Project", "Get ideas", "Add to Roadmap", "Keep as working hypothesis", "I disagree", "Add more evidence", "AI suggestion", "Recommended next action"]:
        assert required in source
    assert '.set("mode","dry_run")' in source
    assert "/orientation" in source and "/knowledge" in source and "/ideas" in source and "/trust-decision" in source
    assert "/trust`" in source


def test_mvp_demo_bootstrap_is_repeatable_and_trust_controls_are_gated(mvp_context):
    client, projects_root, _ = mvp_context
    source = client.get("/mvp-demo").text

    assert "Open AC Repair MVP Demo" in source
    assert "AC Repair — MVP Demo" in source
    assert "ac-repair-mvp-v1" in source
    assert "findDemoProject" in source
    assert "demo_fixture_id" in source
    assert "async function bootstrap" in source
    assert 'data-decision="continue" disabled' in source
    assert 'data-decision="disagree" disabled' in source
    assert 'data-decision="more_evidence" disabled' in source
    assert "setTrustState(" in source and ".user_decision" in source
    assert "not confirmed Project truth" in source

    # The acceptance harness is bound to its pytest temp store, never the configured live store.
    assert projects_root.parent.name == "results"
    assert projects_root != api.PROJECTS_ROOT


def test_mvp_demo_reconstructs_canonical_trust_and_all_pending_proposals(mvp_context):
    client, *_ = mvp_context
    source = client.get("/mvp-demo").text

    assert "/checkpoint-proposals`" in source
    assert "function renderProposals" in source
    assert '"pending"===' in source
    assert ".proposed_checkpoint_patch" in source
    assert ".reason" in source
    assert "data-apply" in source and "data-reject" in source
    assert "Your assessment" in source
    assert "setTrustState(" in source and ".user_decision" in source


def test_mvp_demo_reloads_canonical_state_after_ambiguous_mutations(mvp_context):
    client, *_ = mvp_context
    source = client.get("/mvp-demo").text

    assert "async function canonicalMutation" in source
    assert "await load()" in source
    assert "await canonicalMutation" in source
    assert "canonicalTrust?.user_decision" in source
    assert '"applied"===' in source and '"rejected"===' in source
    assert "/trust-decision" in source
    assert "/apply`" in source and "/reject`" in source
    # A delayed Project A response cannot repaint Project B after navigation.
    assert "loadGeneration" in source
    assert "projectId===" in source


def test_mvp_demo_ignores_stale_loads_and_project_mutation_outcomes(mvp_context):
    client, *_ = mvp_context
    source = client.get("/mvp-demo").text

    # Every load, including a post-mutation canonical reload, supersedes older same-Project loads.
    assert "loadGeneration=0" in source
    assert "++loadGeneration" in source
    # Mutation errors and completion status cannot repaint a different Project after navigation.
    assert "function sayForProject" in source
    assert "sayForProject(" in source


def test_mvp_demo_coalesces_double_and_conflicting_mutation_clicks(mvp_context):
    client, *_ = mvp_context
    source = client.get("/mvp-demo").text

    assert "pendingMutations=new Set" in source
    assert "pendingMutations.has(" in source
    assert "pendingMutations.add(" in source
    assert "pendingMutations.delete(" in source
    assert "trustMutationKey=" in source and "proposalMutationKey=" in source
    assert "Boolean(" in source
    # Apply and Reject share the same proposal-scoped key; conflicting clicks coalesce.
    assert source.count("proposalMutationKey(") >= 3
    # Canonical recovery performs a read reload only; mutation is invoked exactly once.
    assert "async function canonicalMutation" in source


def test_mvp_demo_gates_investigation_and_idea_prerequisites(mvp_context):
    client, *_ = mvp_context
    source = client.get("/mvp-demo").text

    assert 'id="analyze" class="primary" disabled' in source
    assert 'id="explore" class="primary" disabled' in source
    assert "Boolean(projectId)" in source
    assert '$("explore").disabled=!ready' in source
    assert "Select a Project to run an Investigation." in source
    assert "Choose at least two images to run an Investigation." in source
    assert "Select a Project and describe the ideas you want." in source
    assert "Describe the ideas you want." in source
    assert '$("evidence").onchange=updatePrerequisites' in source
    assert '$("exploreIntent").addEventListener("input",updateExplorePrerequisites)' in source


def test_mvp_demo_prioritizes_attention_and_preserves_human_trust_semantics(mvp_context):
    client, *_ = mvp_context
    source = client.get("/mvp-demo").text

    assert source.index("Needs Your Attention") < source.index("Technical details and Project history")
    assert source.index('id="proposal"') < source.index('id="history"')
    assert "Suggested Project change" in source and "review required" in source
    assert "Apply to Project" in source and "Reject change" in source
    assert 'data-decision="continue" disabled' in source and "Keep as working hypothesis" in source
    assert 'data-decision="disagree" disabled' in source and "I disagree" in source
    assert 'data-decision="more_evidence" disabled' in source and "Add more evidence" in source
    assert "Keeping a working hypothesis does not update your Project" in source
    assert "Suggestions use the selected Project and remain unconfirmed" in source
    assert "data-decision" in source and "decision:" in source and "correction:" in source


def test_mvp_demo_projects_saved_explore_state_with_explicit_trust_boundaries(mvp_context):
    client, *_ = mvp_context
    source = client.get("/mvp-demo").text

    assert "What kind of ideas would you like?" in source
    assert "AI suggestions — unconfirmed" in source
    assert "Keep for consideration" in source
    assert "Dismiss" in source
    assert "Choose as preferred direction" in source
    assert "Add to Roadmap" in source
    assert "Preferred direction" in source
    assert "Suggested Project change" in source
    assert "Canonical Project state" in source
    assert "Roadmap:" in source
    assert "option.ordinal" in source


def test_mvp_demo_uses_canonical_explore_endpoints_and_recovers_after_mutations(mvp_context):
    client, *_ = mvp_context
    source = client.get("/mvp-demo").text

    assert "async function loadExplore" in source
    assert "async function runExplore" in source
    assert "async function mutateExplore" in source
    assert "`/projects/${selected}/interactions/explore`" in source
    assert "`/projects/${selected}/ideas/${ideaId}/disposition`" in source
    assert "`/projects/${selected}/ideas/${promoteId}/promote`" in source
    assert "await loadExplore();await load()" in source
    assert "exploreLoadGeneration" in source
    assert "projectId===selected" in source
    assert "crypto.randomUUID()" in source


def test_mvp_demo_explore_is_project_scoped_typed_only_and_reconstructs_on_reopen(mvp_context):
    client, *_ = mvp_context
    source = client.get("/mvp-demo").text

    assert 'id="exploreIntent"' in source
    assert "user_intent:intent" in source
    assert "input_refs:[]" in source
    assert '$("projectSelect").addEventListener("change",()=>{beginExploreLoad(projectId);loadExplore()' in source
    assert '$("refresh").addEventListener("click",()=>loadExplore().catch' in source
    assert "loadExplore();" in source
    ideas_start = source.index("Ideas for this Project")
    ideas_end = source.index("</article>", ideas_start)
    assert "photo" not in source[ideas_start:ideas_end].lower()


def test_mvp_demo_explore_clears_project_a_before_project_b_load_and_rejects_stale_results(mvp_context):
    client, *_ = mvp_context
    source = client.get("/mvp-demo").text

    assert "exploreProjectionProjectId=null" in source
    assert "function beginExploreLoad(selected)" in source
    assert "canonicalExplore=null;exploreProjectionProjectId=selected||null" in source
    assert "Loading ideas for the selected Project" in source
    assert 'document.querySelectorAll("[data-explore-idea],[data-explore-promote]")' in source
    assert "generation===exploreLoadGeneration&&projectId===selected" in source
    assert "projectId!==ownerProjectId||projection.project_id!==ownerProjectId" in source
    assert "Saved suggestions are temporarily unavailable for this Project." in source
    assert 'loadExplore().catch(()=>{})' in source


def test_mvp_demo_reconciles_ambiguous_explore_generation_and_mutations(mvp_context):
    client, *_ = mvp_context
    source = client.get("/mvp-demo").text

    assert "group.idempotency_key===idempotencyKey" in source
    assert "option.disposition===disposition" in source
    assert "option.idea.activity_id===promoteId&&option.promoted" in source
    assert "operationError&&!reconciled" in source
    assert "Project state reloaded; review current status below." in source
    assert "Ideas saved with this Project." in source
    assert "Choice saved with this Project." in source
    assert "Idea added to the Roadmap." in source
    assert "the request outcome is not yet verified" in source
    assert "the action outcome is not yet verified" in source


def test_mvp_demo_maps_backend_explore_state_to_supported_consumer_guidance(mvp_context):
    client, *_ = mvp_context
    source = client.get("/mvp-demo").text

    assert "function exploreGuidance(projection)" in source
    assert "Review the suggested Project change in Needs Your Attention." in source
    assert "Your preferred direction is saved. Add it to the Roadmap when you are ready." in source
    assert "Review the saved suggestions and choose what to keep, dismiss, or prefer." in source
    assert "projection.next_action" not in source
    assert "Create or review a suggested Project change" not in source
    assert "Retry Explore" not in source
    assert "Start Explore" not in source


def test_mvp_demo_programmatic_demo_open_loads_canonical_explore_state(mvp_context):
    client, *_ = mvp_context
    source = client.get("/mvp-demo").text

    assert 'const openDemoProject=$("bootstrap").onclick' in source
    assert '$("bootstrap").onclick=async event=>' in source
    assert 'await openDemoProject.call($("bootstrap"),event)' in source
    assert "await loadExplore().catch(()=>{})" in source
    # The canonical loader retains the same owner and stale-generation guards used by selection/reopen.
    assert "generation===exploreLoadGeneration&&projectId===selected" in source


def test_project_assistant_uses_only_explicit_existing_capabilities(mvp_context):
    source = (Path(__file__).with_name("mvp_demo.html")).read_text(encoding="utf-8")
    for label in ["Project Assistant", "Ask Project", "Continue where I left off", "Add photos", "Get ideas"]:
        assert label in source
    assert "`/projects/${selected}/ask`" in source
    assert "`/projects/${selected}/interactions/explore`" in source
    assert '$("addPhotos").addEventListener("click"' in source
    assert '$("getIdeasAction").addEventListener("click"' in source
    assert 'insertBefore($("projectAssistant"),document.querySelector(".grid").children[1])' in source
    assert "assistant/resolve" not in source
    assert "assistant/execute" not in source
    assert "intent classifier" not in source.lower()


def test_project_assistant_rejects_stale_ask_responses_and_preserves_unsupported_boundary(mvp_context):
    source = (Path(__file__).with_name("mvp_demo.html")).read_text(encoding="utf-8")
    assert "assistantAskGeneration" in source
    assert "projectId!==selected||generation!==assistantAskGeneration" in source
    assert 'beginAssistantProjectLoad(selected)' in source
    assert "External research, media, and instructions are not available yet." in source


def test_project_assistant_labels_ai_grounding_provenance_and_no_mutation(mvp_context):
    source = (Path(__file__).with_name("mvp_demo.html")).read_text(encoding="utf-8")
    assert "AI answer — based on saved Project information" in source
    assert "Grounded in saved Project information" in source
    assert "Partially grounded — some information may be missing" in source
    assert "Not enough saved Project information" in source
    assert 'answer.grounding_status==="partial"' in source
    assert 'answer.grounding_status==="insufficient_context"' in source
    assert "answer.uncertainty_note" in source
    assert "answer.references||[]" in source
    assert "answer.selected_context_summary" in source
    assert "This answer does not change your Project." in source


def test_project_assistant_invalidates_project_a_before_project_b_load(mvp_context):
    source = (Path(__file__).with_name("mvp_demo.html")).read_text(encoding="utf-8")
    assert "assistantCanonicalProjectId===projectId" in source
    assert "function beginAssistantProjectLoad(selected)" in source
    assert 'for(const id of["where","now","next"])' in source
    assert 'beginAssistantProjectLoad(selected);try{await selectProjectAndLoadCanonicalState' in source
    assert "if(projectId===selected&&selected){const canonical=await request" in source
    assert "assistantCanonicalProjectId=selected;canonicalProjectRevision=canonical.revision" in source
    assert 'if(assistantCanonicalProjectId!==projectId)return' in source


def test_project_switch_clears_pending_evidence_and_disables_analysis(mvp_context):
    source = (Path(__file__).with_name("mvp_demo.html")).read_text(encoding="utf-8")
    assert '$("evidence").value="";updatePrerequisites()' in source
    assert 'const e=$("evidence").files?.length||0' in source
    assert '$("analyze").disabled=!t' in source
    assert "projection.project_id!==ownerProjectId" in source


def test_record_progress_desktop_requires_preview_and_keeps_note_separate_from_project_change(mvp_context):
    source = (Path(__file__).with_name("mvp_demo.html")).read_text(encoding="utf-8")

    for label in ["Record progress", "What happened?", "Preview", "Save progress"]:
        assert label in source
    assert "Save what you did as a Project note." in source
    assert "that change stays separate and requires Apply to Project" in source
    assert "Suggested Project change — separate approval required" in source
    assert "No Project-state change proposed" in source
    assert 'labels={current_work:"Where we left off",blockers:"Blockers",next_action:"Next action"}' in source
    assert 'current={current_work:$(\'now\').textContent' in source
    assert '$("saveProgress").disabled=!matches||progressSaving' in source
    assert "progressPreview&&progressOwnerProjectId===projectId" in source


def test_record_progress_desktop_uses_explicit_project_revision_and_stable_retry_key(mvp_context):
    source = (Path(__file__).with_name("mvp_demo.html")).read_text(encoding="utf-8")

    assert "`/projects/${selected}/progress/preview`" in source
    assert "`/projects/${selected}/progress`" in source
    assert "expected_project_revision:revision" in source
    assert "idempotency_key:progressIdempotencyKey" in source
    assert "if(!progressIdempotencyKey||progressRequestFingerprint!==fingerprint)progressIdempotencyKey=crypto.randomUUID()" in source
    assert "Retry uses the same operation key." in source
    assert 'item.metadata?.interaction_type==="record_progress"' in source
    assert "item.metadata?.idempotency_key===key" in source


def test_record_progress_desktop_reloads_canonical_state_and_rejects_stale_project_results(mvp_context):
    source = (Path(__file__).with_name("mvp_demo.html")).read_text(encoding="utf-8")

    assert "projectId!==selected||generation!==progressGeneration" in source
    assert "preview.project_id!==selected" in source
    assert "progressOwnerProjectId!==selected" in source
    assert "await load();const [canonical,activities,proposals]=await Promise.all" in source
    assert "canonicalProjectRevision=canonical.revision" in source
    assert "canonicalProposals=proposals;renderProposals(proposals)" in source
    assert "resetProgressForm(true);" in source
    assert 'if(clearInputs)progressFields.forEach(id=>$(id).value="")' in source
    assert "revisionChanged=canonical.revision!==revision" in source
    assert 'resetProgressForm(false);say("The Project changed after this preview. Preview again before saving."' in source
