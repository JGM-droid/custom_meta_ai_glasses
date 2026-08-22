from __future__ import annotations

from pathlib import Path


DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"


def _dashboard_source() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


# Narrow regression coverage for the Active Capture Project slice's browser
# UI: distinguishing the Viewed Project (workspaceSelectedProjectId - this
# tab's currently open Project, ephemeral) from the Active Capture Project
# (activeProjectId - which Project new evidence/Investigations are
# attributed to), reusing the existing PUT/GET/DELETE /projects/active
# endpoints. This file does not re-prove the backend contract itself (see
# test_active_capture_project.py); it proves the dashboard wires it
# correctly and keeps Viewing/Active conceptually and visually separate.


def test_viewing_a_project_never_calls_set_active_contract():
    # Opening/viewing a Project (openWorkspaceProject, including on every
    # background poll tick) must never itself call PUT
    # /projects/active/{id} - only an explicit "Work on this Project" click
    # (toggleActiveProject) may do that.
    source = _dashboard_source()
    open_fn_start = source.index("async function openWorkspaceProject(projectId, { forceReset = false } = {}) {")
    open_fn_end = source.index("\n    // Paints the", open_fn_start)
    open_fn_body = source[open_fn_start:open_fn_end]
    assert "API_SET_ACTIVE_PROJECT_URL" not in open_fn_body
    assert "PUT" not in open_fn_body

    load_fn_start = source.index("async function loadWorkspaceProjects() {")
    load_fn_end = source.index("\n    async function openWorkspaceProject", load_fn_start)
    load_fn_body = source[load_fn_start:load_fn_end]
    assert "API_SET_ACTIVE_PROJECT_URL" not in load_fn_body


def test_background_refresh_only_reads_active_project_never_writes_contract():
    # loadActiveProjectId (called from loadWorkspaceProjects on the existing
    # poll cycle) must be read-only: GET only, never PUT/DELETE.
    source = _dashboard_source()
    fn_start = source.index("async function loadActiveProjectId() {")
    fn_end = source.index("\n    async function loadWorkspaceProjects", fn_start)
    fn_body = source[fn_start:fn_end]
    assert "fetch(API_ACTIVE_PROJECT_URL, { cache: \"no-store\" })" in fn_body
    assert "method:" not in fn_body


def test_active_project_toggle_uses_existing_endpoints_only_contract():
    source = _dashboard_source()
    assert "const API_ACTIVE_PROJECT_URL = `${API_ORIGIN}/projects/active`;" in source
    assert "const API_SET_ACTIVE_PROJECT_URL = (projectId) => `${API_ORIGIN}/projects/active/${projectId}`;" in source

    fn_start = source.index("async function toggleActiveProject() {")
    fn_end = source.index("\n    async function askWorkspaceProjectQuestion", fn_start)
    fn_body = source[fn_start:fn_end]
    assert "await fetch(API_SET_ACTIVE_PROJECT_URL(projectId), { method: \"PUT\" })" in fn_body
    assert "await fetch(API_ACTIVE_PROJECT_URL, { method: \"DELETE\" })" in fn_body


def test_viewing_and_active_are_visually_distinguishable_contract():
    source = _dashboard_source()
    assert 'workspaceProjectHeaderState.textContent = isActive ? "● Active Project" : "Viewing";' in source
    assert 'workspaceProjectHeaderState.classList.toggle("is-active", isActive);' in source
    assert '.project-state-badge.is-active {' in source


def test_work_on_this_project_and_stop_working_labels_contract():
    # Product language: human terms only, no "ActiveProjectPointer",
    # "canonical pointer", or raw project_id exposed as UI copy.
    source = _dashboard_source()
    assert 'id="workspaceActiveProjectBtn" class="active-project-btn"' in source
    assert '"Work on this Project"' in source
    assert '"Stop Working on Project"' in source
    for banned in ["ActiveProjectPointer", "canonical pointer", "scope binding"]:
        assert banned not in source


def test_exactly_one_sidebar_row_gets_the_active_dot_contract():
    # The dot is conditional on activeProjectId matching that specific row's
    # project_id - not a badge stamped on every row.
    source = _dashboard_source()
    render_fn_start = source.index("function renderWorkspaceProjectsList(projects) {")
    render_fn_end = source.index("\n    function renderDemoProjectOptions", render_fn_start)
    render_fn_body = source[render_fn_start:render_fn_end]
    assert "if (activeProjectId && project.project_id === activeProjectId) {" in render_fn_body
    assert 'sidebar-project-row-active-dot' in render_fn_body


def test_demo_selector_defaults_to_active_project_but_explicit_choice_wins_contract():
    source = _dashboard_source()
    fn_start = source.index("function renderDemoProjectOptions() {")
    fn_end = source.index("\n    function renderWorkspaceHistory", fn_start)
    fn_body = source[fn_start:fn_end]
    assert '`${projectLabel} — Active`' in fn_body
    assert "!demoProjectSelectTouchedByUser" in fn_body

    assert 'demoProjectSelect.addEventListener("change", () => {' in source
    assert "demoProjectSelectTouchedByUser = true;" in source
    assert "demoProjectSelectTouchedByUser = false;" in source


def test_active_project_state_survives_background_poll_without_reset_contract():
    # activeProjectId is never cleared/reset just because a poll tick ran -
    # it is only ever changed by loadActiveProjectId() (re-reading current
    # server state) or toggleActiveProject() (an explicit user action).
    source = _dashboard_source()
    assignments = [
        "activeProjectId = project?.project_id || null;",
        "activeProjectId = null;",
        "activeProjectId = wasActive ? null : projectId;",
    ]
    for assignment in assignments:
        assert assignment in source
