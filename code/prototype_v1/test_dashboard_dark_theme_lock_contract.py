from __future__ import annotations

from pathlib import Path


DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"


def _dashboard_source() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


# Foundation-cleanup slice: the dark graphite palette is the approved,
# authoritative visual direction (a prior slice briefly tried a light
# palette matching a since-disavowed reference image - see
# test_dashboard_reference_visual_pass_contract.py's note). This file
# exists specifically to make an accidental visual reversion - back to
# light, or to any conditional/runtime theme switching - fail loudly.
#
# The palette is deliberately just static :root literals with no
# prefers-color-scheme / data-theme / JS theme logic anywhere: this is a
# single-theme prototype, not a light/dark-aware product, and the tests
# below pin that fact as much as the specific colors.


def _root_block(source: str) -> str:
    root_start = source.index(":root {")
    root_end = source.index("\n    }", root_start)
    return source[root_start:root_end]


def test_app_bg_and_surface_are_dark_graphite_contract():
    source = _dashboard_source()
    root_block = _root_block(source)
    assert "--app-bg: #17181b;" in root_block
    assert "--surface: #1e2024;" in root_block
    assert "--ink: #ececee;" in root_block
    assert "--accent: #8ea1ff;" in root_block


def test_previous_light_palette_values_are_gone_contract():
    source = _dashboard_source()
    root_block = _root_block(source)
    # The light palette this replaces, pinned as explicitly absent so a
    # future edit can't silently drift back to it.
    assert "--app-bg: #f6f7f9;" not in root_block
    assert "--surface: #ffffff;" not in root_block
    assert "--ink: #1b1e27;" not in root_block
    assert "#ffffff" not in root_block
    assert "#f6f7f9" not in root_block


def test_no_conditional_or_runtime_theme_switching_contract():
    # This is a single deterministic theme: no prefers-color-scheme media
    # query, no data-theme attribute/mechanism, and no JS that reads system
    # theme or toggles a theme class/inline color style. (The prose string
    # "prefers-color-scheme" appears once, inside a code comment explaining
    # this absence - checked for separately, not banned outright.)
    source = _dashboard_source()
    for banned in [
        "@media (prefers-color-scheme",
        "data-theme=",
        "[data-theme",
        "matchMedia",
        "window.matchMedia",
    ]:
        assert banned not in source
    assert source.count("prefers-color-scheme") == 1  # only the explanatory comment


def test_no_hardcoded_light_escape_hatches_remain_contract():
    # These three spots previously hardcoded light colors directly (inline
    # style or literal hex in a CSS rule) instead of reading from the token
    # system, so they would have stayed light even after this palette flip.
    source = _dashboard_source()
    for banned in [
        "background: #fff;",
        "background: #f8fbff;",
        "background: #eafaf0;",
        "background: #fdeeec;",
        "border-color: #d8e4f3;",
    ]:
        assert banned not in source

    # And confirm they were converted to token references, not just deleted.
    assert 'style="margin-top: 10px; background: var(--surface); border-color: var(--border-hairline-strong); color: var(--ink);"' in source
    assert source.count("background: var(--surface-sunken);") >= 2  # the two Copilot/git textareas
    assert ".demo-state-pill.completed {" in source
    completed_start = source.index(".demo-state-pill.completed {")
    completed_end = source.index("}", completed_start)
    assert "background: var(--success-quiet);" in source[completed_start:completed_end]


def test_legacy_alias_tokens_removed_contract():
    # --bg/--panel/--text/--muted/--line/--ok were pure indirections to the
    # canonical tokens; every usage was migrated to the canonical name and
    # the aliases themselves removed rather than kept as a second
    # vocabulary for the same values.
    source = _dashboard_source()
    root_block = _root_block(source)
    for alias in ["--bg:", "--panel:", "--text:", "--muted:", "--line:", "--ok:"]:
        assert alias not in root_block
    for usage in ["var(--bg)", "var(--panel)", "var(--text)", "var(--muted)", "var(--line)", "var(--ok)"]:
        assert usage not in source


def test_dead_workspace_grid_css_removed_contract():
    source = _dashboard_source()
    assert "workspace-grid" not in source


def test_project_header_bar_h2_rule_not_duplicated_contract():
    source = _dashboard_source()
    assert source.count(".project-header-bar h2 {") == 1


def test_required_functional_ids_survive_the_theme_lock_contract():
    # The theme rewrite must not have touched any functional wiring - spot
    # check the ids each primary interaction depends on.
    source = _dashboard_source()
    for element_id in [
        "workspaceProjectsList",
        "workspaceCreateProjectBtn",
        "workspaceCreateProjectForm",
        "workspaceAskInput",
        "workspaceAskBtn",
        "workspaceAskAiBtn",
        "workspaceAddNoteBtn",
        "workspaceOpenInvestigationBtn",
        "workspaceComposerMicBtn",
        "workspaceNow",
        "workspaceNext",
        "workspaceCheckpointProposals",
        "workspaceHistory",
        "workspaceProposalForm",
        "workspaceInvestigations",
        "phoneBackToProjectsBtn",
        "demoStartBtn",
        "demoProjectSelect",
    ]:
        assert f'id="{element_id}"' in source
