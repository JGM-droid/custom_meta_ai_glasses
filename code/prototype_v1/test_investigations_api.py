from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

import api
import investigations.result_store as investigation_result_store
from investigations import InvestigationModelResult
from investigations.models import InvestigationRetainedResult
from investigations.service import build_glasses_projection


client = TestClient(api.app)


@pytest.fixture(autouse=True)
def _isolate_investigation_latest_json(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", tmp_path / "investigation_latest.json")


def _image_part(name: str, content: bytes, content_type: str = "image/png") -> tuple[str, io.BytesIO, str]:
    return (name, io.BytesIO(content), content_type)


def _post_investigation(files: list[tuple[str, io.BytesIO, str]], **overrides: str):
    data = {
        "schema_version": "1.0",
        "session_id": "session-123",
        "idempotency_key": "idem-123",
        "user_explanation": "  explain   this   issue  ",
    }
    data.update(overrides)
    multipart = [("images", file_part) for file_part in files]
    return client.post("/investigations/analyze", data=data, files=multipart)


def _setup_fake_openai(monkeypatch, *, response_content: str | None = None, raised: Exception | None = None):
    state: dict[str, Any] = {
        "calls": [],
        "api_keys": [],
        "response_content": response_content
        if response_content is not None
        else json.dumps(
            {
                "diagnosis": "Investigation indicates likely terminal/API mismatch.",
                "required_next_action": "Capture one clearer image of the exact terminal error line.",
            }
        ),
        "raised": raised,
    }

    class _FakeCompletions:
        def create(self, **kwargs):
            state["calls"].append(kwargs)
            if state["raised"] is not None:
                raise state["raised"]

            message = type("Message", (), {"content": state["response_content"]})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class _FakeChat:
        def __init__(self):
            self.completions = _FakeCompletions()

    class _FakeOpenAI:
        def __init__(self, api_key: str):
            state["api_keys"].append(api_key)
            self.chat = _FakeChat()

    monkeypatch.setattr(api, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(api, "_load_openai_api_key", lambda: "test-key")
    monkeypatch.setattr(api, "_vision_model_name", lambda: "gpt-4o-mini")

    def _fake_prepare_image(image_bytes: bytes):
        token = image_bytes.decode("utf-8", errors="replace")
        return f"encoded-{token}", {"processed_size": [10, 10]}

    monkeypatch.setattr(api, "_prepare_image_for_openai", _fake_prepare_image)
    monkeypatch.setattr(api, "_extract_json_object", lambda text: text)
    monkeypatch.setattr(api, "_load_investigation_context_snapshot_from_context_fusion", lambda: None)
    return state


def _extract_outgoing_content(state: dict[str, Any]) -> list[dict[str, Any]]:
    assert len(state["calls"]) == 1
    call = state["calls"][0]
    messages = call["messages"]
    assert isinstance(messages, list)
    user_message = messages[1]
    content = user_message["content"]
    assert isinstance(content, list)
    return content


def test_valid_two_image_request(monkeypatch):
    _setup_fake_openai(monkeypatch)
    response = _post_investigation(
        [
            _image_part("first.png", b"first-image"),
            _image_part("second.png", b"second-image"),
        ]
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "analyzed"
    assert payload["image_count"] == 2
    assert payload["image_order"] == ["1:first.png", "2:second.png"]
    assert payload["used_user_explanation"] == "explain this issue"
    assert payload["diagnosis"] == "Investigation indicates likely terminal/API mismatch."
    assert payload["required_next_action"] == "Capture one clearer image of the exact terminal error line."


def test_valid_three_image_request(monkeypatch):
    _setup_fake_openai(monkeypatch)
    response = _post_investigation(
        [
            _image_part("one.png", b"1"),
            _image_part("two.png", b"22"),
            _image_part("three.png", b"333"),
        ]
    )

    assert response.status_code == 200
    assert response.json()["image_count"] == 3


def test_image_order_preserved(monkeypatch):
    _setup_fake_openai(monkeypatch)
    response = _post_investigation(
        [
            _image_part("b.png", b"bbb"),
            _image_part("a.png", b"aaa"),
        ]
    )

    assert response.status_code == 200
    assert response.json()["image_order"] == ["1:b.png", "2:a.png"]


def test_duplicate_filenames_preserve_explicit_order(monkeypatch):
    _setup_fake_openai(monkeypatch)
    response = _post_investigation(
        [
            _image_part("capture.png", b"first-capture"),
            _image_part("capture.png", b"second-capture"),
        ]
    )

    assert response.status_code == 200
    assert response.json()["image_order"] == ["1:capture.png", "2:capture.png"]


def test_explanation_whitespace_normalized(monkeypatch):
    _setup_fake_openai(monkeypatch)
    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ],
        user_explanation="  line one\n\n   line   two  "
    )

    assert response.status_code == 200
    assert response.json()["used_user_explanation"] == "line one line two"


def test_unsupported_schema_version():
    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ],
        schema_version="2.0",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported schema_version. Use 1.0."


def test_too_few_images():
    response = _post_investigation([_image_part("only.png", b"1")])

    assert response.status_code == 400
    assert response.json()["detail"] == "At least 2 images are required."


def test_too_many_images():
    response = _post_investigation(
        [
            _image_part("one.png", b"1"),
            _image_part("two.png", b"2"),
            _image_part("three.png", b"3"),
            _image_part("four.png", b"4"),
        ]
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "At most 3 images are allowed."


def test_unsupported_mime_type():
    response = _post_investigation(
        [
            _image_part("first.gif", b"gif-data", content_type="image/gif"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported content type. Use image/jpeg or image/png."


def test_empty_image():
    response = _post_investigation(
        [
            _image_part("first.png", b""),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Uploaded image file is empty."


def test_missing_session_id():
    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ],
        session_id="   ",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "session_id is required."


def test_missing_idempotency_key():
    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ],
        idempotency_key="  ",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "idempotency_key is required."


def test_existing_routes_still_registered():
    route_paths = {route.path for route in api.app.routes}
    assert "/vision/analyze" in route_paths
    assert "/latest" in route_paths
    assert "/glasses/latest" in route_paths
    assert "/investigations/analyze" in route_paths
    assert "/investigations/latest" in route_paths
    assert "/investigations/latest/glasses" in route_paths
    assert "/investigations" in route_paths


def test_valid_two_field_json_maps_to_public_response(monkeypatch):
    _setup_fake_openai(
        monkeypatch,
        response_content=json.dumps(
            {
                "diagnosis": "The latest image suggests the process is blocked on auth.",
                "required_next_action": "Capture one image showing the full auth error message and HTTP status.",
            }
        ),
    )

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "analyzed"
    assert payload["diagnosis"] == "The latest image suggests the process is blocked on auth."
    assert payload["required_next_action"] == "Capture one image showing the full auth error message and HTTP status."


def test_single_openai_invocation_for_two_images(monkeypatch):
    state = _setup_fake_openai(monkeypatch)

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 200
    assert len(state["calls"]) == 1


def test_investigation_latest_result_path_is_isolated_per_test(tmp_path: Path):
    assert api.INVESTIGATION_LATEST_JSON.parent == tmp_path
    assert api.INVESTIGATION_LATEST_JSON.name == "investigation_latest.json"


def test_single_openai_invocation_for_three_images(monkeypatch):
    state = _setup_fake_openai(monkeypatch)

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
            _image_part("third.png", b"3"),
        ]
    )

    assert response.status_code == 200
    assert len(state["calls"]) == 1


def test_outgoing_multimodal_structure_and_order_for_two_images(monkeypatch):
    state = _setup_fake_openai(monkeypatch)

    response = _post_investigation(
        [
            _image_part("first.png", b"first"),
            _image_part("second.png", b"second"),
        ]
    )

    assert response.status_code == 200
    content = _extract_outgoing_content(state)
    assert len([item for item in content if item.get("type") == "text"]) == 1
    images = [item for item in content if item.get("type") == "image_url"]
    assert len(images) == 2
    assert images[0]["image_url"]["url"].endswith("encoded-first")
    assert images[1]["image_url"]["url"].endswith("encoded-second")


def test_outgoing_multimodal_structure_and_order_for_three_images(monkeypatch):
    state = _setup_fake_openai(monkeypatch)

    response = _post_investigation(
        [
            _image_part("one.png", b"one"),
            _image_part("two.png", b"two"),
            _image_part("three.png", b"three"),
        ]
    )

    assert response.status_code == 200
    content = _extract_outgoing_content(state)
    images = [item for item in content if item.get("type") == "image_url"]
    assert len(images) == 3
    assert images[0]["image_url"]["url"].endswith("encoded-one")
    assert images[1]["image_url"]["url"].endswith("encoded-two")
    assert images[2]["image_url"]["url"].endswith("encoded-three")


def test_normalized_user_explanation_included_in_outgoing_text(monkeypatch):
    state = _setup_fake_openai(monkeypatch)

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ],
        user_explanation="  one\n\n two   three  ",
    )

    assert response.status_code == 200
    content = _extract_outgoing_content(state)
    text_item = [item for item in content if item.get("type") == "text"][0]
    assert "user_explanation: one two three" in str(text_item.get("text"))


def test_context_snapshot_included_compact_when_available(monkeypatch):
    state = _setup_fake_openai(monkeypatch)
    monkeypatch.setattr(
        api,
        "_load_investigation_context_snapshot_from_context_fusion",
        lambda: {
            "active_branch": "master",
            "modified_files": 2,
            "staged_files": 1,
            "has_terminal_error": True,
            "selected_source": "terminal_error_context",
            "active_file": {"active_file_name": "api.py"},
            "development_context": {"active_function": "investigations_analyze()"},
            "primary_guidance": {"headline": "Resolve error"},
            "guidance_priority": {"level": "critical"},
            "git_risk_context": {"risk_level": "high"},
            "validation_evidence_available": True,
            "signal_freshness": {"context_fusion_generated_at": "2026-07-17T00:00:00+00:00", "snapshot_seconds": 12},
            "extra_field": "ignored",
        },
    )

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 200
    content = _extract_outgoing_content(state)
    text_item = [item for item in content if item.get("type") == "text"][0]
    text = str(text_item.get("text"))
    assert '"active_branch": "master"' in text
    assert '"extra_field"' not in text


def test_missing_context_does_not_block_analysis(monkeypatch):
    state = _setup_fake_openai(monkeypatch)
    monkeypatch.setattr(api, "_load_investigation_context_snapshot_from_context_fusion", lambda: None)

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 200
    assert len(state["calls"]) == 1


def test_stale_context_marked_as_stale(monkeypatch):
    state = _setup_fake_openai(monkeypatch)
    monkeypatch.setattr(
        api,
        "_load_investigation_context_snapshot_from_context_fusion",
        lambda: {
            "active_branch": "master",
            "signal_freshness": {"snapshot_seconds": 720},
        },
    )

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 200
    content = _extract_outgoing_content(state)
    text = str([item for item in content if item.get("type") == "text"][0].get("text"))
    assert '"context_staleness": "stale"' in text


def test_missing_diagnosis_returns_502(monkeypatch):
    _setup_fake_openai(monkeypatch, response_content=json.dumps({"required_next_action": "x"}))

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 502


def test_missing_required_next_action_returns_502(monkeypatch):
    _setup_fake_openai(monkeypatch, response_content=json.dumps({"diagnosis": "x"}))

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 502


def test_empty_diagnosis_returns_502(monkeypatch):
    _setup_fake_openai(
        monkeypatch,
        response_content=json.dumps({"diagnosis": "   ", "required_next_action": "Capture logs"}),
    )

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 502


def test_empty_required_next_action_returns_502(monkeypatch):
    _setup_fake_openai(
        monkeypatch,
        response_content=json.dumps({"diagnosis": "Likely issue", "required_next_action": "   "}),
    )

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 502


def test_extra_model_fields_return_502(monkeypatch):
    _setup_fake_openai(
        monkeypatch,
        response_content=json.dumps(
            {
                "diagnosis": "Likely issue",
                "required_next_action": "Capture one clearer error image.",
                "extra": "not allowed",
            }
        ),
    )

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 502


def test_malformed_json_returns_502(monkeypatch):
    _setup_fake_openai(monkeypatch, response_content="not-json")

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 502


def test_missing_api_key_returns_503(monkeypatch):
    _setup_fake_openai(monkeypatch)
    monkeypatch.setattr(api, "_load_openai_api_key", lambda: "")

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 503


def test_openai_timeout_returns_504(monkeypatch):
    _setup_fake_openai(monkeypatch, raised=TimeoutError("timed out"))

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 504


def test_never_invokes_openai_once_per_image(monkeypatch):
    state = _setup_fake_openai(monkeypatch)

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
            _image_part("third.png", b"3"),
        ]
    )

    assert response.status_code == 200
    assert len(state["calls"]) == 1


def test_context_engine_exception_does_not_block_analysis(monkeypatch):
    state = _setup_fake_openai(monkeypatch)

    def _raise_context_error():
        raise RuntimeError("context unavailable")

    monkeypatch.setattr(api, "_load_investigation_context_snapshot_from_context_fusion", _raise_context_error)

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 200
    assert len(state["calls"]) == 1


def test_required_next_action_accepts_multi_verb_single_workflow():
    result = InvestigationModelResult.model_validate(
        {
            "diagnosis": "Likely mismatch in expected endpoint response.",
            "required_next_action": "Open the terminal, run pytest, and inspect the first failing test.",
        }
    )
    assert result.required_next_action == "Open the terminal, run pytest, and inspect the first failing test."


def test_required_next_action_accepts_command_line_action():
    result = InvestigationModelResult.model_validate(
        {
            "diagnosis": "Tests indicate a reproducible failure.",
            "required_next_action": "Run .\\venv\\Scripts\\python.exe -m pytest -q code\\prototype_v1\\test_investigations_api.py and inspect the first failure.",
        }
    )
    assert "python.exe -m pytest" in result.required_next_action


def test_required_next_action_accepts_file_path_action():
    result = InvestigationModelResult.model_validate(
        {
            "diagnosis": "Routing mismatch likely in investigation endpoint.",
            "required_next_action": "Open api.py, locate the investigation route, and verify the configured model name.",
        }
    )
    assert "api.py" in result.required_next_action


def test_required_next_action_accepts_one_action_with_supporting_detail():
    result = InvestigationModelResult.model_validate(
        {
            "diagnosis": "Evidence is partial due to cropped error output.",
            "required_next_action": "Capture the complete traceback and include the HTTP status in the same screenshot.",
        }
    )
    assert "HTTP status" in result.required_next_action


def test_required_next_action_accepts_numbered_or_bulleted_single_workflow_formatting():
    result = InvestigationModelResult.model_validate(
        {
            "diagnosis": "Need clearer evidence from one workflow step.",
            "required_next_action": "1. Open the terminal and run pytest.\n2. Inspect the first failing test in the same run.",
        }
    )
    assert result.required_next_action.startswith("1. Open")


def test_required_next_action_rejects_either_or_alternative():
    try:
        InvestigationModelResult.model_validate(
            {
                "diagnosis": "Competing actions detected.",
                "required_next_action": "Either restart the server or reinstall the package.",
            }
        )
    except ValidationError:
        return
    raise AssertionError("Expected ValidationError for explicit either/or alternative.")


def test_required_next_action_rejects_option_1_option_2():
    try:
        InvestigationModelResult.model_validate(
            {
                "diagnosis": "Competing options detected.",
                "required_next_action": "Option 1: change the model. Option 2: disable validation.",
            }
        )
    except ValidationError:
        return
    raise AssertionError("Expected ValidationError for explicit option 1 / option 2 alternatives.")


def test_required_next_action_rejects_alternatively_competition():
    try:
        InvestigationModelResult.model_validate(
            {
                "diagnosis": "Conflicting fallback offered.",
                "required_next_action": "Capture the full error output. Alternatively, delete the file instead.",
            }
        )
    except ValidationError:
        return
    raise AssertionError("Expected ValidationError for explicit alternatively competing action.")


def test_required_next_action_rejects_multiple_independent_alternatives():
    try:
        InvestigationModelResult.model_validate(
            {
                "diagnosis": "Competing branches are present.",
                "required_next_action": "You can either capture another image or ignore the error.",
            }
        )
    except ValidationError:
        return
    raise AssertionError("Expected ValidationError for multiple independent alternatives.")


def test_successful_in_process_generated_request(monkeypatch):
    _setup_fake_openai(monkeypatch)
    response = _post_investigation(
        [
            _image_part("generated-1.png", b"png-a"),
            _image_part("generated-2.png", b"png-b"),
        ],
        user_explanation=" generated   explanation ",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["image_order"] == ["1:generated-1.png", "2:generated-2.png"]
    assert payload["used_user_explanation"] == "generated explanation"


def _retained_path(tmp_path: Path) -> Path:
    return tmp_path / "investigation_latest.json"


def _seed_retained_file(path: Path, *, diagnosis: str = "Seed diagnosis", required_next_action: str = "Seed action") -> None:
    retained = InvestigationRetainedResult(
        schema_version="1.0",
        projection_version="1.0",
        investigation_id="inv_seed1234",
        session_id="session-seed",
        status="analyzed",
        diagnosis=diagnosis,
        required_next_action=required_next_action,
        image_count=2,
        image_order=["1:first.png", "2:second.png"],
        used_user_explanation="seed explanation",
        completed_at_utc=datetime.now(timezone.utc),
        context_used=False,
        context_staleness="unknown",
        context_signal_age_seconds=None,
        copilot_prompt="Seed prompt",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(retained.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")


def test_analyze_persists_retained_result_and_latest_projection(monkeypatch, tmp_path):
    state = _setup_fake_openai(monkeypatch)
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", _retained_path(tmp_path))

    post_response = _post_investigation(
        [
            _image_part("first.png", b"a"),
            _image_part("second.png", b"b"),
        ]
    )
    assert post_response.status_code == 200
    assert len(state["calls"]) == 1

    latest_response = client.get("/investigations/latest")
    assert latest_response.status_code == 200
    payload = latest_response.json()
    assert payload["investigation_id"].startswith("inv_")
    assert payload["diagnosis"] == "Investigation indicates likely terminal/API mismatch."
    assert payload["required_next_action"] == "Capture one clearer image of the exact terminal error line."
    assert payload["freshness_state"] in {"fresh", "unknown"}
    assert "Instructions for GitHub Copilot" in payload["copilot_prompt"]


def test_analyze_failure_does_not_overwrite_previous_retained_result(monkeypatch, tmp_path):
    retained_path = _retained_path(tmp_path)
    _seed_retained_file(retained_path, diagnosis="existing-diagnosis", required_next_action="existing-action")
    before = retained_path.read_text(encoding="utf-8")

    _setup_fake_openai(monkeypatch, raised=TimeoutError("timed out"))
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", retained_path)

    post_response = _post_investigation(
        [
            _image_part("first.png", b"a"),
            _image_part("second.png", b"b"),
        ]
    )
    assert post_response.status_code == 504
    assert retained_path.read_text(encoding="utf-8") == before


def test_atomic_store_replace_failure_preserves_previous_valid_result_and_cleans_temp(monkeypatch, tmp_path):
    retained_path = _retained_path(tmp_path)
    _seed_retained_file(retained_path, diagnosis="original-diagnosis", required_next_action="original-action")
    original_text = retained_path.read_text(encoding="utf-8")

    failing_result = InvestigationRetainedResult(
        schema_version="1.0",
        projection_version="1.0",
        investigation_id="inv_replace_fail",
        session_id="session-replace-fail",
        status="analyzed",
        diagnosis="new-diagnosis-that-should-not-replace",
        required_next_action="new-action-that-should-not-replace",
        image_count=2,
        image_order=["1:first.png", "2:second.png"],
        used_user_explanation="new explanation",
        completed_at_utc=datetime.now(timezone.utc),
        context_used=False,
        context_staleness="unknown",
        context_signal_age_seconds=None,
        copilot_prompt="new prompt",
    )

    def _raise_replace(_src: str, _dst: str) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(investigation_result_store.os, "replace", _raise_replace)

    try:
        investigation_result_store.save_latest_investigation_result(retained_path, failing_result)
    except investigation_result_store.InvestigationStoreError:
        pass
    else:
        raise AssertionError("Expected InvestigationStoreError when atomic replace fails.")

    assert retained_path.read_text(encoding="utf-8") == original_text
    temp_candidates = list(retained_path.parent.glob(f"{retained_path.name}.*.tmp"))
    assert temp_candidates == []


def test_persistence_write_error_returns_500(monkeypatch, tmp_path):
    _setup_fake_openai(monkeypatch)
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", _retained_path(tmp_path))

    def _raise_save(*_args, **_kwargs):
        raise api.InvestigationStoreError("disk full")

    monkeypatch.setattr(api, "save_latest_investigation_result", _raise_save)

    post_response = _post_investigation(
        [
            _image_part("first.png", b"a"),
            _image_part("second.png", b"b"),
        ]
    )
    assert post_response.status_code == 500
    assert post_response.json()["detail"] == "Investigation result persistence failed."


def test_latest_returns_404_when_no_retained_result(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", _retained_path(tmp_path))
    response = client.get("/investigations/latest")
    assert response.status_code == 404
    assert response.json()["detail"] == "No retained investigation result exists."


def test_latest_returns_500_for_malformed_retained_json(monkeypatch, tmp_path):
    retained_path = _retained_path(tmp_path)
    retained_path.parent.mkdir(parents=True, exist_ok=True)
    retained_path.write_text("{ malformed", encoding="utf-8")
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", retained_path)

    response = client.get("/investigations/latest")
    assert response.status_code == 500
    assert response.json()["detail"] == "Retained investigation result is unavailable."


def test_latest_projection_stale_state_respected(monkeypatch, tmp_path):
    retained_path = _retained_path(tmp_path)
    retained_path.parent.mkdir(parents=True, exist_ok=True)
    retained = InvestigationRetainedResult(
        schema_version="1.0",
        projection_version="1.0",
        investigation_id="inv_stale1",
        session_id="session-stale",
        status="analyzed",
        diagnosis="Likely stale diagnosis",
        required_next_action="Inspect stale path",
        image_count=2,
        image_order=["1:a.png", "2:b.png"],
        used_user_explanation="stale",
        completed_at_utc=datetime.now(timezone.utc) - timedelta(seconds=95),
        context_used=True,
        context_staleness="stale",
        context_signal_age_seconds=480,
        copilot_prompt="prompt",
    )
    retained_path.write_text(json.dumps(retained.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", retained_path)
    monkeypatch.setenv("INVESTIGATION_RESULT_STALE_SECONDS", "30")

    response = client.get("/investigations/latest")
    assert response.status_code == 200
    payload = response.json()
    assert payload["freshness_state"] == "stale"
    assert payload["age_seconds"] >= 90


def test_latest_retrieval_performs_zero_openai_calls(monkeypatch, tmp_path):
    retained_path = _retained_path(tmp_path)
    _seed_retained_file(retained_path)
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", retained_path)

    called = {"count": 0}

    class _NoUseOpenAI:
        def __init__(self, *_args, **_kwargs):
            called["count"] += 1

    monkeypatch.setattr(api, "OpenAI", _NoUseOpenAI)

    response = client.get("/investigations/latest")
    assert response.status_code == 200
    assert called["count"] == 0


def test_glasses_latest_requires_token_when_configured(monkeypatch, tmp_path):
    retained_path = _retained_path(tmp_path)
    _seed_retained_file(retained_path)
    monkeypatch.setattr(api, "INVESTIGATION_LATEST_JSON", retained_path)
    monkeypatch.setattr(api, "GLASSES_API_TOKEN", "secret-token")

    unauthorized = client.get("/investigations/latest/glasses")
    assert unauthorized.status_code == 401

    authorized = client.get("/investigations/latest/glasses", params={"token": "secret-token"})
    assert authorized.status_code == 200
    payload = authorized.json()
    assert "diagnosis_short" in payload
    assert "required_next_action_short" in payload


def test_glasses_projection_truncates_and_flags_uncertainty():
    retained = InvestigationRetainedResult(
        schema_version="1.0",
        projection_version="1.0",
        investigation_id="inv_uncertain",
        session_id="session-uncertain",
        status="analyzed",
        diagnosis="This is likely a partial failure and may involve stale state with insufficient evidence to confirm root cause.",
        required_next_action=(
            "Capture one complete terminal stack trace and the exact endpoint response body before changing implementation details "
            "to keep the fix deterministic and bounded."
        ),
        image_count=2,
        image_order=["1:a.png", "2:b.png"],
        used_user_explanation="uncertain explanation",
        completed_at_utc=datetime.now(timezone.utc),
        context_used=False,
        context_staleness="unknown",
        context_signal_age_seconds=None,
        copilot_prompt="copilot prompt",
    )

    projection = build_glasses_projection(retained, stale_seconds=900)
    assert projection.uncertainty_flag is True
    assert len(projection.diagnosis_short) <= 120
    assert len(projection.required_next_action_short) <= 140


def test_frontend_investigation_panel_uses_latest_endpoint_and_safe_text_rendering():
    html = Path(api.DISPLAY_HTML).read_text(encoding="utf-8")
    assert "/investigations/latest" in html
    assert "textContent = diagnosis" in html
    assert "textContent = requiredNextAction" in html
    assert "investigationDiagnosisEl.innerHTML" not in html
    assert "investigationNextActionEl.innerHTML" not in html