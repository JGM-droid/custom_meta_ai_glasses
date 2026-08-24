from __future__ import annotations

from pathlib import Path


DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"


def _dashboard_source() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


# Narrow regression coverage for the presentation-readiness redesign's phone
# navigation model: a genuine two-screen Projects-list <-> Project-detail
# flow, replacing the old off-canvas overlay drawer. This is a pure
# presentation/view-state layer over the exact same
# workspaceSelectedProjectId / workspaceProjectsCache data and fetch calls
# already proven by test_dashboard_project_workspace_contract.py - no second
# data path, no JS device/width detection.


def test_old_overlay_drawer_is_fully_retired_contract():
    source = _dashboard_source()
    for marker in [
        'id="projectsDrawerToggle"',
        'id="projectsDrawerCloseBtn"',
        'id="projectsDrawerBackdrop"',
        'id="homeOpenProjectsBtn"',
        "function openProjectsDrawer(",
        "function closeProjectsDrawer(",
        "openProjectsDrawer()",
        "closeProjectsDrawer()",
    ]:
        assert marker not in source


def test_phone_nav_view_toggle_functions_exist_contract():
    source = _dashboard_source()
    assert "function enterPhoneProjectDetail() {" in source
    assert 'appShellEl.classList.add("phone-nav-detail");' in source
    assert "function showPhoneProjectList() {" in source
    assert 'appShellEl.classList.remove("phone-nav-detail");' in source

    # Selecting a Project, and successfully creating one, both enter the
    # phone detail view (a no-op at desktop width via the media query, not
    # a JS width check).
    assert "enterPhoneProjectDetail();" in source
    select_count = source.count("enterPhoneProjectDetail();")
    assert select_count >= 2


def test_phone_back_button_returns_to_project_list_contract():
    source = _dashboard_source()
    assert 'id="phoneBackToProjectsBtn" class="phone-back-btn"' in source
    assert 'phoneBackToProjectsBtn.addEventListener("click", showPhoneProjectList);' in source

    # The back control lives inside the per-Project header, not the sidebar
    # - it navigates away from the currently open Project's detail view.
    header_start = source.index('<div class="project-header-bar">')
    header_end = source.index("</div>", header_start)
    assert 'id="phoneBackToProjectsBtn"' in source[header_start:header_end]


def test_sidebar_is_the_phone_home_screen_contract():
    source = _dashboard_source()
    # .workspace-home (the desktop empty state) is hidden at phone width -
    # the sidebar (brand + New Project + Projects list) fills that role
    # instead, matching a real "Projects list first" phone home rather than
    # a shrunk desktop hero.
    phone_media_start = source.index("@media (max-width: 720px)")
    phone_media_end = source.index("</style>", phone_media_start)
    phone_media_block = source[phone_media_start:phone_media_end]

    assert ".workspace-home {" in phone_media_block
    assert "display: none;" in phone_media_block
    assert ".projects-sidebar {" in phone_media_block
    assert "position: static;" in phone_media_block
    assert ".app-shell.phone-nav-detail .projects-sidebar {" in phone_media_block
    assert ".app-shell.phone-nav-detail .app-main {" in phone_media_block


def test_no_js_device_or_width_detection_contract():
    source = _dashboard_source()
    # Phone vs. desktop presentation must stay a pure CSS media-query
    # concern driven by a single view-state class - never a JS branch on
    # screen width or device type.
    for banned in ["navigator.userAgent", "matchMedia", "innerWidth <", "innerWidth<"]:
        assert banned not in source


def test_sidebar_project_row_text_shrinks_instead_of_overflowing_contract():
    # Regression: a long project name/goal inside the flex sidebar row
    # previously overflowed the 375px phone viewport because the text
    # wrapper was an inline <span> (no min-width:0 chain), so
    # white-space:nowrap + text-overflow:ellipsis never actually kicked in
    # in a narrow flex container. Pin the fix.
    source = _dashboard_source()
    row_start = source.index(".sidebar-project-row {")
    row_end = source.index("}", row_start)
    assert "min-width: 0;" in source[row_start:row_end]

    text_start = source.index(".sidebar-project-row-text {")
    text_end = source.index("}", text_start)
    text_block = source[text_start:text_end]
    assert "display: flex;" in text_block
    assert "flex-direction: column;" in text_block
    assert "min-width: 0;" in text_block

    for class_name in [".sidebar-project-row-name {", ".sidebar-project-row-goal {"]:
        rule_start = source.index(class_name)
        rule_end = source.index("}", rule_start)
        assert "min-width: 0;" in source[rule_start:rule_end]


def test_no_duplicate_phone_state_contract():
    source = _dashboard_source()
    # The phone list/detail flow reuses the exact same sidebar/list and
    # Project-workspace DOM as desktop - no second Projects list, no second
    # selected-project variable.
    assert source.count('id="workspaceProjectsList"') == 1
    assert source.count('let workspaceSelectedProjectId = "";') == 1
    assert source.count('id="projectWorkspaceSection"') == 1
    assert "mobileProjectsCache" not in source
    assert "phoneSelectedProjectId" not in source
    assert "phoneProjectsCache" not in source
