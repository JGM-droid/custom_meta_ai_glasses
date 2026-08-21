from __future__ import annotations

from pathlib import Path


DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"


def _dashboard_source() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


def test_project_workspace_section_exists_contract():
    source = _dashboard_source()
    assert 'id="projectWorkspaceSection"' in source
    assert '>Project Workspace<' in source
    assert '>My Projects<' in source
    assert '>Project Inspector<' in source


def test_project_inspector_labels_exist_contract():
    source = _dashboard_source()
    for label in [
        '>Now<',
        '>Next<',
        '>History<',
        '>Investigations / Evidence<',
        '>Ask This Project<',
        '>Why This Context?<',
    ]:
        assert label in source


def test_workspace_uses_project_api_endpoints_contract():
    source = _dashboard_source()
    assert 'const API_PROJECTS_URL = `${API_ORIGIN}/projects`;' in source
    assert 'const API_PROJECT_CONTEXT_QUERY_URL = (projectId) => `${API_ORIGIN}/projects/${projectId}/context/query`;' in source
    assert 'const API_PROJECT_DETAIL_URL = (projectId) => `${API_ORIGIN}/projects/${projectId}`;' in source
    assert 'const API_PROJECT_ACTIVITIES_URL = (projectId) => `${API_ORIGIN}/projects/${projectId}/activities`;' in source
    assert 'const API_PROJECT_INVESTIGATIONS_URL = (projectId) => `${API_ORIGIN}/projects/${projectId}/investigation-sessions`;' in source
    assert 'const API_PROJECT_ASK_URL = (projectId) => `${API_ORIGIN}/projects/${projectId}/ask`;' in source


def test_workspace_ask_and_ask_ai_contract():
    source = _dashboard_source()
    assert '>Get Context<' in source
    assert '>Ask AI<' in source
    assert '>AI Answer (Grounded)<' in source
    assert 'Get Context shows selected project context only. Ask AI uses AI reasoning over that selected project context.' in source
    assert 'Context loaded for selected project (no AI answer generation).' in source
    assert 'AI answer loaded (reasoning over selected project context only).' in source


def test_workspace_interpretability_fields_render_contract():
    source = _dashboard_source()
    assert 'Detected question class:' in source
    assert 'Categories included:' in source
    assert 'Categories excluded:' in source
    assert 'Retrieval limits:' in source
    assert 'Fallback used:' in source


def test_workspace_project_switching_and_isolation_guards_contract():
    source = _dashboard_source()
    assert 'let workspaceSelectedProjectId = "";' in source
    assert 'let workspaceLoadingToken = 0;' in source
    assert 'const loadToken = ++workspaceLoadingToken;' in source
    assert 'if (loadToken !== workspaceLoadingToken) return;' in source
    assert 'openWorkspaceProject(project.project_id, { forceReset: true });' in source


def test_workspace_ask_views_survive_background_poll_of_same_project_contract():
    # Background polling (loadWorkspaceProjects, on a setInterval) reopens the
    # already-selected project on every cycle to keep Now/Next/History/
    # Investigations fresh. It must not silently wipe an Ask AI answer or Get
    # Context result the user is currently looking at just because a poll
    # tick fired. Only an actual project change, or an explicit Open click,
    # may clear those views.
    source = _dashboard_source()

    # A tracking variable distinct from workspaceSelectedProjectId is required:
    # loadWorkspaceProjects() reassigns workspaceSelectedProjectId to the
    # target project *before* calling openWorkspaceProject, so comparing
    # against workspaceSelectedProjectId inside openWorkspaceProject could
    # never detect a change.
    assert 'let workspaceAskViewsProjectId = "";' in source

    assert 'async function openWorkspaceProject(projectId, { forceReset = false } = {}) {' in source
    assert 'const projectChanged = projectId !== workspaceAskViewsProjectId;' in source
    assert 'if (projectChanged || forceReset) {' in source
    assert 'resetWorkspaceAskViews();\n        workspaceAskViewsProjectId = projectId;' in source

    # The background-poll call site must NOT force a reset.
    assert 'await openWorkspaceProject(workspaceSelectedProjectId);' in source
    assert 'await openWorkspaceProject(workspaceSelectedProjectId, { forceReset: true });' not in source

    # The explicit "Open" button click must force a reset.
    assert 'openWorkspaceProject(project.project_id, { forceReset: true });' in source
