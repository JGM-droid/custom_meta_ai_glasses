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
    assert 'openWorkspaceProject(project.project_id);' in source
