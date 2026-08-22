from __future__ import annotations

from pathlib import Path


DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"
API_PY_PATH = Path(__file__).resolve().parent / "api.py"


def _dashboard_source() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


# Narrow regression coverage for Slice 1 - Product Shell: restructuring the
# existing dashboard into a Project-first shell (persistent desktop sidebar /
# mobile drawer, a Home/no-Project state, and a reordered per-Project
# workspace), reusing the exact same DOM elements, JS state, and backend
# endpoints already proven by test_dashboard_project_workspace_contract.py,
# test_dashboard_checkpoint_proposal_contract.py, and the Phase B/C2/D1/D2
# backend test suites. This file proves the *shell* - it does not re-prove
# Ask/Suggested-Next-Step/proposal mechanics themselves, only that Slice 1's
# restructuring did not disturb them.
#
# IMPORTANT: this slice is the Viewed Project / UI shell only. "Active" is
# intentionally reserved for a future Active Capture Project slice - these
# tests also guard against that boundary being crossed early.


def test_desktop_sidebar_exists_and_is_persistent_contract():
    source = _dashboard_source()
    assert '<aside id="projectsSidebar" class="projects-sidebar">' in source
    # Persistent means: no `hidden` attribute, no JS-driven show/hide of the
    # sidebar element itself (unlike projectWorkspaceSection/workspaceHomeState
    # below) - only the mobile drawer open/close *class* toggles it off-canvas.
    assert '<aside id="projectsSidebar" class="projects-sidebar" hidden>' not in source
    assert ".projects-sidebar {" in source
    assert "position: sticky;" in source


def test_project_list_and_create_controls_live_in_sidebar_contract():
    source = _dashboard_source()
    sidebar_start = source.index('<aside id="projectsSidebar" class="projects-sidebar">')
    sidebar_end = source.index("</aside>")
    sidebar_html = source[sidebar_start:sidebar_end]

    for marker in [
        '<h3>My Projects</h3>',
        'id="workspaceCreateProjectBtn"',
        'id="workspaceCreateProjectForm"',
        'id="workspaceProjectsList"',
        'id="workspaceProjectsStatus"',
    ]:
        assert marker in sidebar_html

    # These are not duplicated anywhere else in the file - still exactly the
    # one existing Create Project form / Projects list, just relocated.
    assert source.count('id="workspaceCreateProjectForm"') == 1
    assert source.count('id="workspaceProjectsList"') == 1


def test_selected_project_can_be_opened_and_highlighted_contract():
    source = _dashboard_source()
    # Reuses the exact existing open/highlight wiring (Open / Open (Selected),
    # aria-current) - Slice 1 does not touch this mechanism, only adds a
    # drawer-close side effect on mobile after opening.
    assert 'openBtn.textContent = (workspaceSelectedProjectId === project.project_id) ? "Open (Selected)" : "Open";' in source
    assert 'openBtn.setAttribute("aria-current", workspaceSelectedProjectId === project.project_id ? "true" : "false");' in source
    assert "openWorkspaceProject(project.project_id, { forceReset: true });" in source
    assert "closeProjectsDrawer();" in source


def test_project_workspace_is_center_content_not_a_separate_section_contract():
    source = _dashboard_source()
    # Project Workspace must be a child of the center <main>, a sibling of
    # the sidebar (not the sidebar itself, not a disconnected 6th section
    # trailing after unrelated glasses/debug content as it was before this
    # slice).
    main_start = source.index('<main class="wrap app-main">')
    main_end = source.index("</main>")
    workspace_index = source.index('<section class="workspace-shell" id="projectWorkspaceSection" hidden>')
    assert main_start < workspace_index < main_end

    aside_start = source.index("<aside")
    aside_end = source.index("</aside>")
    assert not (aside_start < workspace_index < aside_end)


def test_home_no_project_state_exists_contract():
    source = _dashboard_source()
    assert '<section id="workspaceHomeState" class="workspace-home">' in source
    assert ">What are you working on?<" in source
    assert 'id="homeCreateProjectBtn"' in source
    assert 'id="homeOpenProjectsBtn"' in source
    # Reuses the exact existing Create Project entry point rather than a
    # second/duplicate creation flow.
    assert "showCreateProjectForm();" in source

    # Home and the Project Workspace are mutually exclusive, driven by the
    # same workspaceProjectsCache state already maintained elsewhere - no new
    # "view mode" data is introduced.
    assert "function updateWorkspaceViewMode() {" in source
    assert "const hasProjects = workspaceProjectsCache.length > 0;" in source
    assert "workspaceHomeState.hidden = hasProjects;" in source
    assert "projectWorkspaceSectionEl.hidden = !hasProjects;" in source


def test_mobile_drawer_and_toggle_exist_contract():
    source = _dashboard_source()
    assert 'id="projectsDrawerToggle" class="drawer-toggle"' in source
    assert 'id="projectsDrawerCloseBtn" class="drawer-close-btn"' in source
    assert 'id="projectsDrawerBackdrop" class="drawer-backdrop"' in source
    assert "function openProjectsDrawer() {" in source
    assert "function closeProjectsDrawer() {" in source
    assert 'projectsDrawerToggle.addEventListener("click", openProjectsDrawer);' in source
    assert 'projectsDrawerCloseBtn.addEventListener("click", closeProjectsDrawer);' in source
    assert 'projectsDrawerBackdrop.addEventListener("click", closeProjectsDrawer);' in source

    # Desktop-only vs. mobile-only visibility is a pure CSS media-query
    # concern - no JS branches on screen width / device type.
    assert "@media (max-width: 899px)" in source
    assert ".drawer-toggle {" in source
    for banned in ["navigator.userAgent", "matchMedia", "innerWidth <"]:
        assert banned not in source


def test_no_duplicate_mobile_state_or_endpoints_contract():
    source = _dashboard_source()
    # There must be exactly one Projects list, one selected-project variable,
    # and one set of Now/Next/History/etc elements - the phone-width
    # presentation is CSS-only over this same DOM/state, never a second copy.
    assert source.count('id="workspaceProjectsList"') == 1
    assert source.count('let workspaceSelectedProjectId = "";') == 1
    assert source.count('id="workspaceNow"') == 1
    assert source.count('id="workspaceNext"') == 1
    assert source.count('id="workspaceHistory"') == 1
    assert source.count('id="projectWorkspaceSection"') == 1
    assert "mobileProjectsCache" not in source
    assert "phoneSelectedProjectId" not in source


def test_now_next_ask_suggested_history_elements_remain_present_contract():
    source = _dashboard_source()
    for marker in [
        'id="workspaceNow"',
        'id="workspaceNext"',
        'id="workspaceAskInput"',
        'id="workspaceAskBtn"',
        'id="workspaceAskAiBtn"',
        'id="workspaceCheckpointProposals"',
        'id="workspaceProposalSubmitBtn"',
        'id="workspaceHistory"',
        'id="workspaceInvestigations"',
    ]:
        assert marker in source
    assert source.count('id="workspaceNow"') == 1
    assert source.count('id="workspaceHistory"') == 1


def test_project_switching_still_clears_draft_and_ask_state_contract():
    # Unchanged from the prior slice - Slice 1 must not touch this guard.
    source = _dashboard_source()
    open_fn_start = source.index('async function openWorkspaceProject(projectId, { forceReset = false } = {}) {')
    open_fn_end = source.index("\n    async function askWorkspaceProjectQuestion", open_fn_start)
    open_fn_body = source[open_fn_start:open_fn_end]

    guarded_block_start = open_fn_body.index("if (projectChanged || forceReset) {")
    guarded_block_end = open_fn_body.index("\n      }", guarded_block_start)
    guarded_block = open_fn_body[guarded_block_start:guarded_block_end]
    assert "resetWorkspaceAskViews();" in guarded_block
    assert "hideProposalForm();" in guarded_block

    unguarded_body = open_fn_body[:guarded_block_start] + open_fn_body[guarded_block_end:]
    assert "resetWorkspaceAskViews();" not in unguarded_body
    assert "hideProposalForm()" not in unguarded_body


def test_background_polling_behavior_remains_intact_contract():
    source = _dashboard_source()
    assert "setInterval(loadWorkspaceProjects, POLL_MS * 2);" in source
    assert "setInterval(fetchLatest, POLL_MS);" in source
    assert "setInterval(fetchRetainedLatestInvestigation, POLL_MS);" in source
    # loadWorkspaceProjects must still refresh view-mode/state on every poll
    # tick without resetting the currently-open Project's draft state (see
    # the project-switch guard test above; here we only check the new
    # updateWorkspaceViewMode() call is wired into the existing poll path).
    load_fn_start = source.index("async function loadWorkspaceProjects() {")
    load_fn_end = source.index("\n    async function openWorkspaceProject", load_fn_start)
    load_fn_body = source[load_fn_start:load_fn_end]
    assert "updateWorkspaceViewMode();" in load_fn_body


def test_no_backend_endpoint_changes_were_introduced_contract():
    # Slice 1 is presentation/navigation only - api.py must be byte-identical
    # in its route surface. This does not re-run the backend test suite (see
    # the full pytest run in CI/manual validation); it is a fast guard that
    # this specific test file's own assumptions about the backend didn't
    # silently require a new endpoint.
    api_source = API_PY_PATH.read_text(encoding="utf-8")
    for forbidden in [
        '@app.get("/projects/active/device',
        '@app.put("/projects/active/device',
        "device_id",
        "client_id",
    ]:
        assert forbidden not in api_source
