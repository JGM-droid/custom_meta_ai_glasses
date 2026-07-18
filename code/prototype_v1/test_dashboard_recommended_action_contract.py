from __future__ import annotations

from pathlib import Path


DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"


def _dashboard_source() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


def _default_view_source(source: str) -> str:
    marker = '<details id="advancedDebugDetails"'
    return source.split(marker, maxsplit=1)[0] if marker in source else source


def test_recommended_ai_action_section_exists_contract():
    source = _dashboard_source()
    assert 'id="recommendedActionSection"' in source
    assert '>Recommended AI Action<' in source


def test_copilot_prompt_is_primary_result_output_contract():
    source = _dashboard_source()
    assert 'id="copilotPromptText"' in source
    assert 'id="copilotPromptEmpty"' in source
    assert 'id="copyCopilotPromptBtn"' in source


def test_copy_copilot_prompt_button_exists_contract():
    source = _dashboard_source()
    assert '>Copy Copilot Prompt<' in source
    assert 'aria-label="Copy Copilot Prompt"' in source


def test_empty_prompt_state_does_not_render_fake_prompt_contract():
    source = _dashboard_source()
    assert 'Run an investigation to generate a Copilot prompt.' in source
    assert 'copilotPromptText.style.display = "none";' in source


def test_why_this_should_work_renders_only_when_meaningful_contract():
    source = _dashboard_source()
    assert 'id="whyThisShouldWorkCard"' in source
    assert 'whyThisShouldWorkCard.dataset.empty = "false";' in source
    assert 'whyThisShouldWorkCard.dataset.empty = "true";' in source


def test_confidence_not_rendered_in_default_recommendation_explanation_contract():
    source = _default_view_source(_dashboard_source())
    assert 'Confidence / Uncertainty' not in source


def test_verification_items_are_deduplicated_contract():
    source = _dashboard_source()
    assert 'function dedupeTextItems(items) {' in source
    assert 'verificationItems = dedupeTextItems(verificationItems).slice(0, 4);' in source


def test_follow_up_capture_instruction_renders_when_requested_contract():
    source = _dashboard_source()
    assert 'Take another picture after testing so the AI can verify the result.' in source
    assert 'followUpCaptureCard.dataset.empty = "false";' in source


def test_one_primary_next_step_is_shown_contract():
    source = _dashboard_source()
    assert 'id="primaryNextStep"' in source
    assert 'primaryNextStep.textContent = normalizeOrFallback(view.primaryNextStep);' in source


def test_git_recommendation_visibility_and_copy_contract():
    source = _dashboard_source()
    assert 'id="gitRecommendationCard"' in source
    assert 'gitRecommendationCard.dataset.empty = "false";' in source
    assert 'gitRecommendationCard.dataset.empty = "true";' in source
    assert 'id="copyGitCommandsBtn"' in source


def test_glasses_view_does_not_render_full_copilot_prompt_contract():
    source = _dashboard_source()
    default_source = _default_view_source(source)
    compact_view_start = default_source.index('<section class="glasses-view">')
    compact_view_end = default_source.index('<section class="advanced-debug">')
    compact_view_markup = default_source[compact_view_start:compact_view_end]
    assert 'id="copilotPromptText"' not in compact_view_markup


def test_technical_result_fields_remain_inside_advanced_technical_details_contract():
    source = _dashboard_source()
    details_index = source.index('<details id="advancedDebugDetails">')
    for token in ['id="demoDiagnosis"', 'id="demoObservations"', 'id="demoConfidenceValue"', 'id="full_analysis"']:
        assert source.index(token) > details_index


def test_advanced_technical_details_collapsed_by_default_contract():
    source = _dashboard_source()
    assert '<details id="advancedDebugDetails">' in source
    assert '<details id="advancedDebugDetails" open>' not in source


def test_copy_interactions_use_clipboard_api_with_fallback_contract():
    source = _dashboard_source()
    assert 'navigator.clipboard && window.isSecureContext' in source
    assert 'document.execCommand("copy")' in source
    assert 'Copy failed. Select and copy manually.' in source


def test_product_view_model_mapping_function_exists_contract():
    source = _dashboard_source()
    assert 'function normalizeDemoProductView(snapshot) {' in source
    assert 'const pa = (snapshot && snapshot.product_action && typeof snapshot.product_action === "object") ? snapshot.product_action : {};' in source
