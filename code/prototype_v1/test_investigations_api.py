from __future__ import annotations

import io

from fastapi.testclient import TestClient

import api


client = TestClient(api.app)


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


def test_valid_two_image_request():
    response = _post_investigation(
        [
            _image_part("first.png", b"first-image"),
            _image_part("second.png", b"second-image"),
        ]
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "validated"
    assert payload["image_count"] == 2
    assert payload["image_order"] == ["1:first.png", "2:second.png"]
    assert payload["used_user_explanation"] == "explain this issue"
    assert payload["diagnosis"] == "Investigation session received and validated."
    assert payload["required_next_action"] == "Proceed to combined multimodal analysis integration."


def test_valid_three_image_request():
    response = _post_investigation(
        [
            _image_part("one.png", b"1"),
            _image_part("two.png", b"22"),
            _image_part("three.png", b"333"),
        ]
    )

    assert response.status_code == 200
    assert response.json()["image_count"] == 3


def test_image_order_preserved():
    response = _post_investigation(
        [
            _image_part("b.png", b"bbb"),
            _image_part("a.png", b"aaa"),
        ]
    )

    assert response.status_code == 200
    assert response.json()["image_order"] == ["1:b.png", "2:a.png"]


def test_duplicate_filenames_preserve_explicit_order():
    response = _post_investigation(
        [
            _image_part("capture.png", b"first-capture"),
            _image_part("capture.png", b"second-capture"),
        ]
    )

    assert response.status_code == 200
    assert response.json()["image_order"] == ["1:capture.png", "2:capture.png"]


def test_explanation_whitespace_normalized():
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


def test_new_endpoint_does_not_invoke_openai(monkeypatch):
    def _unexpected_openai_call(*args, **kwargs):
        raise AssertionError("OpenAI should not be invoked during Phase 1A validation.")

    monkeypatch.setattr(api, "_call_openai_vision", _unexpected_openai_call)

    response = _post_investigation(
        [
            _image_part("first.png", b"1"),
            _image_part("second.png", b"2"),
        ]
    )

    assert response.status_code == 200


def test_successful_in_process_generated_request():
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