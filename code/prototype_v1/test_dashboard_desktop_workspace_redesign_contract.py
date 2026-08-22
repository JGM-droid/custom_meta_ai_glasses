from __future__ import annotations

from pathlib import Path


DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"


def _dashboard_source() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


# Narrow regression coverage for the desktop product-shell redesign slice:
# a composer-centered, project-first workspace layered over the exact same
# Project Memory DOM/JS/state proven by test_dashboard_project_workspace_contract.py
# and test_dashboard_checkpoint_proposal_contract.py. This file proves the
# new *hierarchy* (composer -> continuity -> Recent -> Project Details) - it
# does not re-prove Ask/Suggested-Next-Step/proposal mechanics themselves.


def test_composer_is_primary_and_reuses_existing_ask_elements_contract():
    source = _dashboard_source()
    composer_start = source.index('<div class="workspace-composer"')
    composer_end = source.index("</div>", source.index('class="workspace-block" style="margin-top: 8px;">\n              <h4>AI Answer', composer_start))
    composer_html = source[composer_start:composer_end]

    # The composer reuses the exact existing Ask input/buttons - no second
    # input element, no new backend behavior invented for the redesign.
    assert 'id="workspaceAskInput"' in composer_html
    assert 'id="workspaceAskBtn"' in composer_html
    assert 'id="workspaceAskAiBtn"' in composer_html
    assert "What are you working on?" in composer_html
    assert source.count('id="workspaceAskInput"') == 1

    # The grounded AI answer stays visible near the composer (not buried in
    # Project Details) as the direct feedback loop for Ask AI.
    assert 'id="workspaceAskAiAnswer"' in composer_html


def test_composer_offers_add_evidence_entry_to_investigation_contract():
    # Reference-matched redesign: this is now a labeled chip ("Start
    # Investigation") in the composer's action row, matching the attached
    # reference's three-chip layout, rather than a long compound label.
    source = _dashboard_source()
    assert 'id="workspaceOpenInvestigationBtn"' in source
    assert "Start Investigation" in source
    assert 'workspaceOpenInvestigationBtn.addEventListener("click", () => {' in source
    assert "projectDetailsDisclosure.open = true;" in source


def test_continuity_row_relabels_now_without_uppercase_shouting_contract():
    source = _dashboard_source()
    continuity_start = source.index('<div class="workspace-continuity"')
    continuity_end = source.index("</div>\n\n          <section class=\"workspace-recent\"", continuity_start)
    continuity_html = source[continuity_start:continuity_end]

    assert "<h4>Where you left off</h4>" in continuity_html
    assert 'id="workspaceNow"' in continuity_html
    assert "<h4>Next</h4>" in continuity_html
    assert 'id="workspaceNext"' in continuity_html

    # Plain sentence case, not raw backend word / not styled as a loud
    # uppercase dashboard label.
    assert "WHERE YOU LEFT OFF" not in continuity_html
    assert ">Now<" not in continuity_html


def test_recent_section_surfaces_captured_and_suggested_next_step_terminology_contract():
    source = _dashboard_source()
    recent_start = source.index('<section class="workspace-recent"')
    recent_end = source.index("</section>", recent_start)
    recent_html = source[recent_start:recent_end]

    assert "<h3>Recent</h3>" in recent_html
    # Reuses the exact existing proposals + history feeds/state, just grouped
    # together under one "Recent" heading instead of split into separate
    # "Suggested Next Steps" (order 8) / "History" (order 9) dashboard blocks.
    assert 'id="workspaceCheckpointProposals"' in recent_html
    assert 'id="workspaceHistory"' in recent_html
    assert 'id="workspaceProposalForm"' in recent_html
    assert "Suggested Next Steps" in recent_html
    assert "History" in recent_html


def test_project_details_is_collapsed_progressive_disclosure_contract():
    source = _dashboard_source()
    assert '<details class="project-details" id="projectDetailsDisclosure"' in source
    assert '<details class="project-details" id="projectDetailsDisclosure" open' not in source
    assert "<summary>Project Details</summary>" in source

    details_start = source.index('<details class="project-details" id="projectDetailsDisclosure"')
    details_end = source.index("</details>", source.index('id="nextStepSection"', details_start))
    details_html = source[details_start:details_end]

    # Legacy/secondary content lives inside Project Details: full
    # Investigations/Evidence, deep Ask grounding detail, and the
    # Investigation Session capture form + result panels - none of it
    # competes visually with composer/continuity/Recent on first load.
    for marker in [
        'id="workspaceInvestigations"',
        'id="workspaceAskContext"',
        'id="workspaceAskWhy"',
        'id="workspaceAskDebug"',
        'class="investigation-demo"',
        'id="recommendedActionSection"',
        'id="verifyFixSection"',
        'id="nextStepSection"',
    ]:
        assert marker in details_html


def test_project_header_shows_goal_contract():
    source = _dashboard_source()
    assert 'id="workspaceProjectHeaderGoal"' in source
    assert 'const workspaceProjectHeaderGoal = document.getElementById("workspaceProjectHeaderGoal");' in source
    assert "workspaceProjectHeaderGoal.textContent = normalize(projectDetail?.goal);" in source


def test_workspace_shell_uses_neutral_surface_not_bright_gradient_contract():
    # Presentation-readiness redesign: the Project workspace no longer has
    # its own bordered/shadowed "panel" background - it blends directly
    # into the dark app background (--app-bg), matching the calm,
    # minimal-card-noise direction. Composer/Recent surfaces still use
    # var(--surface*) tokens individually where a raised surface is wanted.
    source = _dashboard_source()
    shell_css_start = source.rindex(".workspace-shell {", 0, source.index('<aside id="projectsSidebar"'))
    shell_css_block = source[shell_css_start:shell_css_start + 400]
    assert "background: transparent;" in shell_css_block
    assert "linear-gradient" not in shell_css_block
