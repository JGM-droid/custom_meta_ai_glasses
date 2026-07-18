from __future__ import annotations

from pathlib import Path


DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"


def _dashboard_source() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


def test_start_button_allows_single_image_selection_contract():
    source = _dashboard_source()
    assert 'const DEMO_MIN_IMAGES = 1;' in source
    assert 'const DEMO_MAX_IMAGES = 3;' in source
    assert 'const hasValidCount = count >= DEMO_MIN_IMAGES && count <= DEMO_MAX_IMAGES;' in source
    assert 'return Boolean(String(demoExplanation.value || "").trim());' in source


def test_selection_is_managed_outside_native_input_files():
    source = _dashboard_source()
    assert 'let demoSelectedImages = [];' in source
    assert 'id="demoSelectedImages"' in source
    assert 'function handleDemoImageBrowseChange() {' in source
    assert 'demoSelectedImages.push({ key, file });' in source
    assert 'demoImages.value = "";' in source


def test_second_and_third_browse_actions_preserve_existing_selection_contract():
    source = _dashboard_source()
    assert 'for (const file of incomingFiles) {' in source
    assert 'if (demoSelectedImages.length >= DEMO_MAX_IMAGES) {' in source
    assert 'renderSelectedDemoImages();' in source


def test_fourth_image_rejected_with_clear_message_contract():
    source = _dashboard_source()
    assert 'setDemoStatus("You can select up to 3 images.", "err");' in source


def test_duplicate_selection_is_ignored_contract():
    source = _dashboard_source()
    assert 'if (demoSelectedImages.some((entry) => entry.key === key)) {' in source
    assert 'setDemoStatus("That image is already selected.", "warn");' in source


def test_per_image_removal_keeps_remaining_selection_contract():
    source = _dashboard_source()
    assert 'function removeDemoImageAt(index) {' in source
    assert 'demoSelectedImages.splice(index, 1);' in source
    assert 'data-demo-remove-index' in source


def test_reset_clears_managed_selection_and_stops_polling_contract():
    source = _dashboard_source()
    assert 'function resetDemoView() {' in source
    assert 'stopDemoPolling();' in source
    assert 'demoSelectedImages = [];' in source
    assert 'activeDemoId = null;' in source
    assert 'demoStartInFlight = false;' in source


def test_form_data_uses_managed_selection_order_contract():
    source = _dashboard_source()
    assert 'const files = demoSelectedImages.map((entry) => entry.file);' in source
    assert 'demoSelectedImages.forEach((entry) => formData.append("images", entry.file));' in source


def test_one_image_message_and_validation_contract():
    source = _dashboard_source()
    assert 'setDemoStatus("Select at least 1 image.", "err");' in source
    assert 'setDemoStatus("Explanation is invalid.", "err");' in source
