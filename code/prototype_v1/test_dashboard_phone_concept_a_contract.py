from __future__ import annotations

from pathlib import Path


DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"


def _dashboard_source() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


# Narrow regression coverage for the "Concept A / Card hierarchy" phone
# redesign: the approved mockup is expressed entirely as presentation - the
# same Project Workspace DOM, ids, and event handlers already proven by
# test_dashboard_project_workspace_contract.py,
# test_dashboard_checkpoint_proposal_contract.py, and
# test_dashboard_active_capture_project_contract.py, restyled and
# reordered only inside the existing @media (max-width: 720px) phone
# breakpoint. Desktop's own rules (outside that media query) are untouched.


def _phone_media_block(source: str) -> str:
    # The phone media query is placed last in the stylesheet, after every
    # base (non-media) rule, so it wins equal-specificity cascade ties
    # against later-declared base rules. See the comment directly above
    # "@media (max-width: 720px) {" in dashboard.html for why.
    start = source.index("@media (max-width: 720px) {")
    end = source.index("</style>", start)
    return source[start:end]


def test_phone_media_query_is_last_in_stylesheet_contract():
    # CSS resolves equal-specificity ties by source order. Many phone
    # overrides below target selectors (.workspace-composer,
    # .workspace-continuity, .composer-chip, the pending-suggestion card,
    # etc.) that also have unconditional base rules declared elsewhere in
    # the stylesheet. If the @media (max-width: 720px) block were not the
    # last thing before </style>, a later base rule of equal specificity
    # would silently win at phone widths and these overrides would never
    # actually render in a browser, even though every string-matching
    # assertion in this file would still pass. Pin the position so that
    # regression can't reappear silently.
    source = _dashboard_source()
    style_close = source.index("</style>")
    phone_media_start = source.rindex("@media (max-width: 720px) {")
    between = source[phone_media_start:style_close]
    # Only the phone block's own content (and nothing else with a competing
    # top-level rule) should sit between its start and the stylesheet close.
    assert between.count("@media") == 1
    assert source.index("@media (max-width: 720px) {") == phone_media_start


def test_desktop_section_order_values_unchanged_contract():
    # Desktop keeps composer -> continuity -> recent -> details, exactly as
    # before this slice - these are base (non-media-query) rules.
    source = _dashboard_source()
    for selector, order in [
        (".workspace-composer {", "order: 0;"),
        (".workspace-continuity {", "order: 1;"),
        (".workspace-recent {", "order: 2;"),
        (".project-details {", "order: 3;"),
    ]:
        rule_start = source.index(selector)
        rule_end = source.index("}", rule_start)
        assert order in source[rule_start:rule_end]

    # No leftover inline order styles on these elements - order now comes
    # from the base CSS rules above, which the phone media query can cleanly
    # override without !important.
    for banned in [
        'class="workspace-composer" style="order:',
        'class="workspace-continuity" style="order:',
        'class="workspace-recent" style="order:',
        'id="projectDetailsDisclosure" style="order:',
    ]:
        assert banned not in source


def test_phone_reorders_where_you_left_off_and_next_before_composer_contract():
    # Approved priority for phone: Where You Left Off -> Next -> composer ->
    # Suggested Next Steps -> Recent Activity -> secondary (Project Details).
    # These overrides live only inside the phone media query - desktop's
    # base rules (asserted separately above) are untouched.
    source = _dashboard_source()
    phone_block = _phone_media_block(source)

    def order_of(selector: str) -> str:
        rule_start = phone_block.index(selector)
        rule_end = phone_block.index("}", rule_start)
        rule = phone_block[rule_start:rule_end]
        marker = "order:"
        i = rule.index(marker) + len(marker)
        return rule[i : rule.index(";", i)].strip()

    continuity_order = int(order_of(".workspace-continuity {"))
    composer_order = int(order_of(".workspace-composer {"))
    recent_order = int(order_of(".workspace-recent {"))
    details_order = int(order_of(".project-details {"))

    assert continuity_order < composer_order < recent_order < details_order


def test_no_fake_settings_tab_or_navigation_contract():
    # The approved mockup shows a bottom "Projects / Settings" tab bar, but
    # this app has no Settings surface - adding one would be fake
    # navigation. Intentionally omitted; see the deliverable report.
    source = _dashboard_source()
    for banned in ["tabbar", "tab-bar", ">Settings<", "Settings tab"]:
        assert banned not in source


def test_composer_controls_repositioned_only_inside_phone_media_query_contract():
    # #workspaceComposerMicBtn / #workspaceAskAiBtn keep their exact ids and
    # handlers; only their position (absolute, inside the composer box
    # corners) is phone-specific.
    source = _dashboard_source()
    phone_block = _phone_media_block(source)
    assert "#workspaceComposerMicBtn {" in phone_block
    assert "#workspaceAskAiBtn {" in phone_block
    mic_start = phone_block.index("#workspaceComposerMicBtn {")
    mic_end = phone_block.index("}", mic_start)
    assert "position: absolute;" in phone_block[mic_start:mic_end]

    # These ids must not be redefined with position:absolute anywhere
    # outside the phone media query (desktop keeps the normal in-row flow).
    desktop_block = source[: source.index("@media (max-width: 720px) {")]
    assert "#workspaceComposerMicBtn {" not in desktop_block
    assert "#workspaceAskAiBtn {" not in desktop_block


def test_sidebar_row_card_treatment_scoped_to_phone_contract():
    source = _dashboard_source()
    phone_block = _phone_media_block(source)
    assert ".sidebar-project-row {" in phone_block
    row_start = phone_block.index(".sidebar-project-row {")
    row_end = phone_block.index("}", row_start)
    assert "background: var(--surface);" in phone_block[row_start:row_end]

    # The base (desktop) .sidebar-project-row rule must not itself declare a
    # background - desktop keeps its existing flat list treatment.
    desktop_block = source[: source.index("@media (max-width: 720px) {")]
    base_row_start = desktop_block.index(".sidebar-project-row {")
    base_row_end = desktop_block.index("}", base_row_start)
    assert "background: var(--surface);" not in desktop_block[base_row_start:base_row_end]


def test_suggested_next_step_amber_treatment_scoped_to_phone_contract():
    # Desktop keeps its existing quieter left-accent-bar pending-suggestion
    # treatment; only phone gets the mockup's amber-tinted card.
    source = _dashboard_source()
    phone_block = _phone_media_block(source)
    assert 'workspace-proposal-item[data-status="pending"] {' in phone_block
    pending_start = phone_block.index('workspace-proposal-item[data-status="pending"] {')
    pending_end = phone_block.index("}", pending_start)
    assert "background: var(--warn-quiet);" in phone_block[pending_start:pending_end]

    desktop_block = source[: source.index("@media (max-width: 720px) {")]
    base_pending_start = desktop_block.index('.workspace-proposal-item[data-status="pending"] {')
    base_pending_end = desktop_block.index("}", base_pending_start)
    assert "background: var(--warn-quiet);" not in desktop_block[base_pending_start:base_pending_end]
    assert "border-left: 2px solid var(--accent);" in desktop_block[base_pending_start:base_pending_end]


def test_active_project_control_ids_unchanged_contract():
    # The Active Capture Project control (workspaceActiveProjectBtn) and its
    # state badge must keep the exact ids/behavior this phone redesign
    # builds on top of - no new pointer/state system.
    source = _dashboard_source()
    for marker in [
        'id="workspaceActiveProjectBtn" class="active-project-btn"',
        'id="workspaceProjectHeaderState" class="project-state-badge"',
        "function toggleActiveProject() {",
        "function renderActiveProjectControl(projectId) {",
    ]:
        assert marker in source


def test_functional_ids_survive_the_phone_restyle_contract():
    source = _dashboard_source()
    for element_id in [
        "workspaceProjectsList",
        "workspaceCreateProjectBtn",
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
        "phoneBackToProjectsBtn",
    ]:
        assert f'id="{element_id}"' in source
