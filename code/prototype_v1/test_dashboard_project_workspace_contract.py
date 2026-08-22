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


def test_create_project_form_exists_with_required_and_optional_fields_contract():
    source = _dashboard_source()

    assert 'id="workspaceCreateProjectBtn"' in source
    assert '>Create Project<' in source
    assert 'id="workspaceCreateProjectForm"' in source
    # Hidden until the user opts in; this is not a redesign of the read-only
    # inspector default view.
    assert 'id="workspaceCreateProjectForm" class="workspace-create-project-form" style="display: none;">' in source

    # Required fields per the approved scope: name and goal only.
    assert 'id="workspaceCreateProjectName" class="workspace-ask-input" type="text" maxlength="200" placeholder="Project name" required>' in source
    assert 'id="workspaceCreateProjectGoal" class="workspace-ask-input" type="text" maxlength="1000" placeholder="What is this project for?" required>' in source

    # Optional initial checkpoint fields, reusing the existing checkpoint
    # contract's own field names/limits (current_objective, next_action) -
    # not marked required.
    assert 'id="workspaceCreateProjectObjective" class="workspace-ask-input" type="text" maxlength="400"' in source
    assert 'id="workspaceCreateProjectNextAction" class="workspace-ask-input" type="text" maxlength="1000"' in source
    objective_input_line = next(line for line in source.splitlines() if 'id="workspaceCreateProjectObjective"' in line)
    next_action_input_line = next(line for line in source.splitlines() if 'id="workspaceCreateProjectNextAction"' in line)
    assert "required" not in objective_input_line
    assert "required" not in next_action_input_line

    assert 'id="workspaceCreateProjectSubmitBtn"' in source
    assert 'id="workspaceCreateProjectCancelBtn"' in source
    assert 'id="workspaceCreateProjectStatus"' in source

    # Backend-only concepts must not be surfaced as user-facing fields/labels
    # in the Create Project form itself. Scoped to the form's own markup
    # (rather than the whole file) because Checkpoint Proposals are a
    # separate, intentionally-exposed feature elsewhere in the Workspace -
    # see test_checkpoint_updates_section_exists_contract and friends below.
    form_start = source.index('<form id="workspaceCreateProjectForm"')
    form_end = source.index("</form>", form_start)
    create_project_form_html = source[form_start:form_end].lower()
    for hidden_concept in ["revision", "checkpoint proposal", "schema_version", "activity store"]:
        assert hidden_concept not in create_project_form_html


def test_create_project_reuses_existing_post_projects_endpoint_contract():
    source = _dashboard_source()

    # No new/duplicate endpoint constant - reuses the existing POST /projects
    # surface exactly as-is.
    assert source.count('const API_PROJECTS_URL = `${API_ORIGIN}/projects`;') == 1
    assert 'async function submitCreateWorkspaceProject(event) {' in source
    assert 'const response = await fetch(API_PROJECTS_URL, {' in source
    assert 'method: "POST",' in source

    # name/goal are always sent; checkpoint is only attached when the optional
    # objective/next_action fields were actually filled in.
    assert 'const payload = { name, goal };' in source
    assert 'if (currentObjective) checkpoint.current_objective = currentObjective;' in source
    assert 'if (nextAction) checkpoint.next_action = nextAction;' in source
    assert 'payload.checkpoint = checkpoint;' in source


def test_create_project_success_opens_new_project_and_clears_previous_ask_views_contract():
    source = _dashboard_source()

    # On success, selecting the new project id before the existing
    # loadWorkspaceProjects()/openWorkspaceProject() refresh pipeline is what
    # makes the project-changed check (see
    # test_workspace_ask_views_survive_background_poll_of_same_project_contract)
    # clear the previously selected project's Ask AI answer / Selected Project
    # Context / Why This Context / debug pack - no separate reset call is
    # duplicated here.
    assert 'const created = await response.json();' in source
    assert 'hideCreateProjectForm();' in source
    assert 'workspaceSelectedProjectId = created.project_id;' in source
    assert 'await loadWorkspaceProjects();' in source


def test_create_project_validation_and_error_handling_contract():
    source = _dashboard_source()

    assert 'if (!name) {' in source
    assert 'setWorkspaceStatus(workspaceCreateProjectStatus, "Name is required.", true);' in source
    assert 'if (!goal) {' in source
    assert 'setWorkspaceStatus(workspaceCreateProjectStatus, "Goal is required.", true);' in source

    # Server errors must surface a concise message and must not leave the
    # form stuck disabled/loading.
    assert 'async function parseErrorResponseMessage(response, fallback) {' in source
    assert 'let workspaceCreateProjectInFlight = false;' in source
    assert 'workspaceCreateProjectInFlight = false;' in source
    assert 'workspaceCreateProjectSubmitBtn.disabled = false;' in source
    assert 'workspaceCreateProjectCancelBtn.disabled = false;' in source
