from __future__ import annotations

from pathlib import Path


DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"


def _dashboard_source() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


# Narrow regression coverage for the reference-matched visual pass: an
# icon-led, card-based sidebar/composer/Recent layout, while keeping every
# existing Project Memory contract (isolation, checkpoint semantics, Ask
# AI/Get Context, Suggested Next Step trust model) exactly as already
# proven by the other test_dashboard_*.py files.
#
# NOTE: this pass originally also introduced a light palette; that palette
# was superseded by the approved dark graphite direction one slice later.
# The palette lock itself now lives in
# test_dashboard_dark_theme_lock_contract.py - this file covers only the
# structural/layout changes from this pass, not color.
    assert "--surface: #ffffff;" in root_block
    assert "--ink: #1b1e27;" in root_block
    assert "#17181b" not in root_block
    assert "#1e2024" not in root_block


def test_sidebar_brand_has_tagline_contract():
    source = _dashboard_source()
    assert '<span class="sidebar-brand-title">Persistent AI<br>Project Assistant</span>' in source
    assert '<span class="sidebar-brand-tagline">Your projects, always in context.</span>' in source


def test_sidebar_project_row_uses_icon_and_left_accent_selection_contract():
    source = _dashboard_source()
    assert "sidebar-project-row-icon" in source
    assert ".sidebar-project-row.selected {" in source
    selected_start = source.index(".sidebar-project-row.selected {")
    selected_end = source.index("}", selected_start)
    selected_block = source[selected_start:selected_end]
    assert "border-left-color: var(--accent);" in selected_block


def test_continuity_cards_have_bordered_surface_treatment_contract():
    # "Where you left off" / "Next" are soft bordered cards (matching the
    # reference's two side-by-side panels), not bare text under a heading.
    source = _dashboard_source()
    rule_start = source.index(".workspace-continuity .workspace-block {")
    rule_end = source.index("}", rule_start)
    rule_block = source[rule_start:rule_end]
    assert "border: 1px solid var(--border-hairline);" in rule_block
    assert "background: var(--surface);" in rule_block


def test_composer_has_reference_matched_label_and_chip_actions_contract():
    source = _dashboard_source()
    assert '<div class="composer-label">Capture / Ask</div>' in source
    assert 'class="composer-subtitle"' in source
    assert 'class="composer-chip" type="button">📷 Start Investigation<' in source
    assert 'class="composer-chip" type="button">💬 Get Context<' in source
    assert 'class="composer-chip" type="button">📝 Add Note<' in source
    assert 'class="composer-icon-btn primary" type="button" aria-label="Ask AI"' in source


def test_add_note_uses_existing_generic_activity_endpoint_no_new_backend_contract():
    # Add Note must reuse the exact existing generic
    # POST /projects/{id}/activities endpoint (already used server-side by
    # the D2 investigation projection) with source_type "user" and
    # confirmation_status "reported" - the same trust-model language
    # already established for user-authored Activities - not a new
    # backend capability.
    source = _dashboard_source()
    assert "async function submitComposerNote() {" in source
    fn_start = source.index("async function submitComposerNote() {")
    fn_end = source.index("\n    function resetDemoView", fn_start)
    fn_body = source[fn_start:fn_end]
    assert "await fetch(API_PROJECT_ACTIVITIES_URL(workspaceSelectedProjectId), {" in fn_body
    assert '"activity_type": "note"' not in fn_body  # payload is built as a JS object, not a raw JSON string
    assert 'activity_type: "note",' in fn_body
    assert 'source_type: "user",' in fn_body
    assert 'confirmation_status: "reported",' in fn_body
    assert 'workspaceAddNoteBtn.addEventListener("click", submitComposerNote);' in source


def test_voice_input_remains_honestly_disabled_contract():
    source = _dashboard_source()
    assert 'id="workspaceComposerMicBtn"' in source
    mic_start = source.index('id="workspaceComposerMicBtn"')
    mic_end = source.index(">", mic_start)
    mic_tag = source[mic_start:mic_end]
    assert "disabled" in mic_tag
    assert "coming soon" in mic_tag.lower() or "not yet available" in mic_tag.lower()


def test_no_fake_navigation_or_unbacked_ui_contract():
    # The reference image includes a "TOOLS" nav section (Templates, Notes &
    # Snippets, Voice Shortcuts, Integrations) and a user profile footer -
    # none of these have any backing functionality/auth system in this app,
    # so they were deliberately not copied rather than added as dead links.
    source = _dashboard_source()
    for banned in ["Voice Shortcuts", "Notes &amp; Snippets", "Notes & Snippets", 'id="userProfileFooter"']:
        assert banned not in source
