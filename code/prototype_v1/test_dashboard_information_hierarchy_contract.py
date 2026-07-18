from __future__ import annotations

from pathlib import Path


DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"


def _dashboard_source() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


def _default_view_source(source: str) -> str:
    marker = '<details id="advancedDebugDetails"'
    if marker not in source:
        return source
    return source.split(marker, maxsplit=1)[0]


def test_advanced_debug_details_exists_and_is_collapsed_by_default_contract():
    source = _dashboard_source()
    assert '<details id="advancedDebugDetails">' in source
    assert '<summary>Advanced Technical Details</summary>' in source
    assert '<details id="advancedDebugDetails" open>' not in source


def test_full_analysis_only_inside_advanced_debug_details_contract():
    source = _dashboard_source()
    details_index = source.index('<details id="advancedDebugDetails">')
    full_analysis_index = source.index('id="full_analysis"')
    assert full_analysis_index > details_index


def test_metrics_snapshot_only_inside_advanced_debug_details_contract():
    source = _dashboard_source()
    details_index = source.index('<details id="advancedDebugDetails">')
    metrics_index = source.index('id="metrics_snapshot"')
    assert metrics_index > details_index


def test_resume_previous_task_only_inside_advanced_debug_details_contract():
    source = _dashboard_source()
    details_index = source.index('<details id="advancedDebugDetails">')
    resume_index = source.index('id="resume_previous_task"')
    assert resume_index > details_index


def test_default_view_has_single_canonical_current_task_display_contract():
    source = _default_view_source(_dashboard_source())
    assert source.count('>Investigation Session<') == 1


def test_default_view_has_single_canonical_next_action_display_contract():
    source = _default_view_source(_dashboard_source())
    assert source.count('>Recommended AI Action<') == 1


def test_default_view_has_single_canonical_confidence_display_contract():
    source = _default_view_source(_dashboard_source())
    assert source.count('>Verify the Fix<') == 1


def test_default_view_has_single_canonical_glasses_guidance_display_contract():
    source = _default_view_source(_dashboard_source())
    assert source.count('>Compact Glasses View<') == 1


def test_optional_result_cards_hidden_when_empty_contract():
    source = _dashboard_source()
    assert '.demo-result-card[data-empty="true"] {' in source
    assert 'id="followUpCaptureCard" class="demo-result-card compact" data-empty="true"' in source
    assert 'id="gitRecommendationCard" class="demo-result-card" data-empty="true"' in source


def test_latest_result_is_canonical_for_diagnosis_and_immediate_action_contract():
    source = _default_view_source(_dashboard_source())
    assert source.count('>Diagnosis<') == 0
    assert source.count('>Immediate Action<') == 0
