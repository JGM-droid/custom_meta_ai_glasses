from __future__ import annotations

from pathlib import Path


DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"


def _dashboard_source() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


def _default_view_source(source: str) -> str:
    marker = '<details id="advancedDebugDetails"'
    if marker not in source:
        return source
    return source.split(marker, maxsplit=1)[0]


def test_advanced_debug_details_exists_and_is_collapsed_by_default_contract():
    source = _dashboard_source()
    assert '<details id="advancedDebugDetails">' in source
    assert '<summary>Advanced Technical Details</summary>' in source
    assert '<details id="advancedDebugDetails" open>' not in source


def test_full_analysis_only_inside_advanced_debug_details_contract():
    source = _dashboard_source()
    details_index = source.index('<details id="advancedDebugDetails">')
    full_analysis_index = source.index('id="full_analysis"')
    assert full_analysis_index > details_index


def test_metrics_snapshot_only_inside_advanced_debug_details_contract():
    source = _dashboard_source()
    details_index = source.index('<details id="advancedDebugDetails">')
    metrics_index = source.index('id="metrics_snapshot"')
    assert metrics_index > details_index


def test_resume_previous_task_only_inside_advanced_debug_details_contract():
    source = _dashboard_source()
    details_index = source.index('<details id="advancedDebugDetails">')
    resume_index = source.index('id="resume_previous_task"')
    assert resume_index > details_index


def test_default_view_has_single_canonical_current_task_display_contract():
    source = _default_view_source(_dashboard_source())
    assert source.count('>Investigation Session<') == 1


def test_default_view_has_single_canonical_next_action_display_contract():
    source = _default_view_source(_dashboard_source())
    assert source.count('>Recommended AI Action<') == 1


def test_default_view_has_single_canonical_confidence_display_contract():
    source = _default_view_source(_dashboard_source())
    assert source.count('>Verify the Fix<') == 1


def test_default_view_has_single_canonical_glasses_guidance_display_contract():
    source = _default_view_source(_dashboard_source())
    assert source.count('>Compact Glasses View<') == 1


def test_optional_result_cards_hidden_when_empty_contract():
    source = _dashboard_source()
    assert '.demo-result-card[data-empty="true"] {' in source
    assert 'id="followUpCaptureCard" class="demo-result-card compact" data-empty="true"' in source
    assert 'id="gitRecommendationCard" class="demo-result-card" data-empty="true"' in source


def test_latest_result_is_canonical_for_diagnosis_and_immediate_action_contract():
    source = _default_view_source(_dashboard_source())
    assert source.count('>Diagnosis<') == 0
    assert source.count('>Immediate Action<') == 0


# Product-framing/hierarchy coverage: the dashboard's architectural center is
# the persistent Project, not the glasses/Investigation demo path (see
# AGENTS.md and docs/PROJECT_MEMORY_ARCHITECTURE.md). These tests pin that
# the page's own framing and section order actually reflect that, rather than
# leaving it true only in the backend/data model.


def test_page_title_and_hero_lead_with_persistent_project_assistant_contract():
    source = _dashboard_source()
    assert "<title>Persistent AI Project Assistant</title>" in source
    assert "<title>AI Glasses Live Analysis Dashboard</title>" not in source
    assert '<section class="hero">' in source
    assert "<h1>Persistent AI Project Assistant</h1>" in source
    assert "Keep durable project state, evidence, history, and next actions across work sessions." in source


def test_project_workspace_is_first_functional_section_contract():
    source = _dashboard_source()
    hero_index = source.index('<section class="hero">')
    workspace_index = source.index('<section class="workspace-shell" id="projectWorkspaceSection">')
    investigation_index = source.index('<section class="investigation-demo">')
    glasses_view_index = source.index('<section class="glasses-view">')

    # Hero, then Project Workspace, then the Investigation/glasses cluster -
    # not duplicated anywhere else in the file.
    assert hero_index < workspace_index < investigation_index < glasses_view_index
    assert source.count('<section class="workspace-shell" id="projectWorkspaceSection">') == 1
    assert source.count('id="workspaceProjectsList"') == 1


def test_project_explainer_copy_exists_near_my_projects_contract():
    source = _dashboard_source()
    my_projects_index = source.index("<h3>My Projects</h3>")
    explainer_index = source.index(
        "A Project keeps the current state, next action, evidence, and history for one ongoing piece of work."
    )
    projects_list_index = source.index('id="workspaceProjectsList"')
    # The explanatory sentence must sit between the heading and the list it
    # explains, in plain language (no LLM/architecture jargon).
    assert my_projects_index < explainer_index < projects_list_index


def test_investigation_cluster_is_framed_as_evidence_within_a_project_contract():
    source = _dashboard_source()
    workspace_start_index = source.index('<section class="workspace-shell" id="projectWorkspaceSection">')
    lead_note_index = source.index(
        "Evidence and Investigations below can be captured on their own or linked to a Project above."
    )
    investigation_index = source.index('<section class="investigation-demo">')
    # The framing note must come after Project Workspace and immediately
    # before the Investigation/glasses cluster it is introducing.
    assert workspace_start_index < lead_note_index < investigation_index


def test_all_major_sections_still_present_after_reorder_contract():
    source = _dashboard_source()
    for marker in [
        '<section class="hero">',
        '<section class="workspace-shell" id="projectWorkspaceSection">',
        '<section class="investigation-demo">',
        'id="recommendedActionSection"',
        'id="verifyFixSection"',
        'id="nextStepSection"',
        '<section class="glasses-view">',
        '<section class="advanced-debug">',
    ]:
        assert marker in source

    # No section was accidentally duplicated by the move.
    assert source.count("<section") == source.count("</section>")
