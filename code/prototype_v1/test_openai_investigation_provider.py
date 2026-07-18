from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import openai
import pytest

import investigations.openai_analysis_provider as provider_module
from investigations.analysis_contract_errors import (
    InvestigationAnalysisProviderAuthenticationError,
    InvestigationAnalysisProviderConnectionError,
    InvestigationAnalysisProviderMalformedResponseError,
    InvestigationAnalysisProviderMissingApiKeyError,
    InvestigationAnalysisProviderMissingImageError,
    InvestigationAnalysisProviderRateLimitError,
    InvestigationAnalysisProviderRefusalError,
    InvestigationAnalysisProviderTimeoutError,
    InvestigationAnalysisProviderUnexpectedError,
    InvestigationAnalysisProviderUnsupportedImageError,
)
from investigations.models import (
    INVESTIGATION_ANALYSIS_REQUEST_PACKAGE_SCHEMA_VERSION,
    INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
    InvestigationAnalysisEvidenceAttachment,
    InvestigationAnalysisRequestPackage,
    InvestigationAnalysisResponse,
)
from investigations.openai_analysis_provider import (
    InvestigationOpenAIProviderConfig,
    OpenAIInvestigationAnalysisProvider,
)


class _FakeParsedResponse:
    def __init__(self, *, output_parsed=None, output=None):
        self.output_parsed = output_parsed
        self.output = output or []


class _FakeResponses:
    def __init__(self, *, parsed_response=None, parse_exception=None):
        self.parsed_response = parsed_response
        self.parse_exception = parse_exception
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.parse_exception is not None:
            raise self.parse_exception
        return self.parsed_response


class _FakeClient:
    def __init__(self, responses: _FakeResponses):
        self.responses = responses


class _FakeClientFactory:
    def __init__(self, responses: _FakeResponses):
        self.responses = responses
        self.api_keys: list[str] = []

    def __call__(self, *, api_key: str):
        self.api_keys.append(api_key)
        return _FakeClient(self.responses)


def _response_payload() -> dict[str, object]:
    return {
        "schema_version": INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
        "concise_diagnosis": "Likely stale dependency lock mismatch.",
        "immediate_recommended_action": "Regenerate lockfile and run focused tests.",
        "supporting_observations": ["Capture one shows import error.", "Capture two shows version drift."],
        "confidence_or_uncertainty": "Likely, verify with one clean environment run.",
        "warning_or_blocker": "Do not perform broad upgrades before lockfile check.",
        "follow_up_capture_request": "Capture the next stack trace if issue persists.",
    }


def _build_request_package(tmp_path: Path) -> tuple[InvestigationAnalysisRequestPackage, Path]:
    session_id = str(uuid4())
    sessions_root = tmp_path / "investigation_sessions"
    session_root = sessions_root / session_id
    payload_dir = session_root / "evidence" / "payloads"
    payload_dir.mkdir(parents=True, exist_ok=True)

    first_bytes = b"jpeg-bytes"
    second_bytes = b"png-bytes"
    first_ref = "evidence/payloads/first.jpg"
    second_ref = "evidence/payloads/second.png"
    (session_root / first_ref).write_bytes(first_bytes)
    (session_root / second_ref).write_bytes(second_bytes)

    request = InvestigationAnalysisRequestPackage(
        schema_version=INVESTIGATION_ANALYSIS_REQUEST_PACKAGE_SCHEMA_VERSION,
        session_id=session_id,
        analysis_attempt_id=str(uuid4()),
        attempt_number=1,
        frozen_manifest_id=str(uuid4()),
        frozen_manifest_hash="a" * 64,
        normalized_explanation_text="Need to diagnose this failing build.",
        deterministic_system_instructions="System instructions for deterministic investigation.",
        deterministic_context_instructions="Context instructions for deterministic investigation.",
        ordered_evidence_inputs=[
            InvestigationAnalysisEvidenceAttachment(
                evidence_id=str(uuid4()),
                capture_timestamp_utc=None,
                media_type="image/jpeg",
                storage_ref=first_ref,
                evidence_metadata={"filename": "first.jpg"},
            ),
            InvestigationAnalysisEvidenceAttachment(
                evidence_id=str(uuid4()),
                capture_timestamp_utc=None,
                media_type="image/png",
                storage_ref=second_ref,
                evidence_metadata={"filename": "second.png"},
            ),
        ],
    )
    return request, sessions_root


def _provider(tmp_path: Path, responses: _FakeResponses):
    request, sessions_root = _build_request_package(tmp_path)
    factory = _FakeClientFactory(responses)
    config = InvestigationOpenAIProviderConfig(
        api_key="test-key",
        model="gpt-4.1-mini",
        timeout_seconds=12.5,
        sessions_root=sessions_root,
    )
    provider = OpenAIInvestigationAnalysisProvider(config=config, client_factory=factory)
    return provider, request, factory, responses


def test_valid_request_package_produces_responses_api_request(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, fake_responses = _provider(tmp_path, responses)

    provider.analyze(request)

    assert len(fake_responses.calls) == 1
    call = fake_responses.calls[0]
    assert call["model"] == "gpt-4.1-mini"
    assert call["text_format"] is InvestigationAnalysisResponse


def test_system_instructions_are_included(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, fake_responses = _provider(tmp_path, responses)

    provider.analyze(request)

    assert fake_responses.calls[0]["instructions"] == request.deterministic_system_instructions


def test_context_instructions_and_explanation_are_included(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, fake_responses = _provider(tmp_path, responses)

    provider.analyze(request)

    content = fake_responses.calls[0]["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert request.deterministic_context_instructions in content[0]["text"]
    assert "normalized_explanation_text:" in content[1]["text"]
    assert request.normalized_explanation_text in content[1]["text"]


def test_image_order_matches_request_package_order(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, fake_responses = _provider(tmp_path, responses)

    provider.analyze(request)

    content = fake_responses.calls[0]["input"][0]["content"]
    image_items = [item for item in content if item["type"] == "input_image"]
    first_url = image_items[0]["image_url"]
    second_url = image_items[1]["image_url"]

    assert ";base64," in first_url and ";base64," in second_url
    first_data = first_url.split(",", 1)[1]
    second_data = second_url.split(",", 1)[1]

    first_file = (request.ordered_evidence_inputs[0].storage_ref)
    second_file = (request.ordered_evidence_inputs[1].storage_ref)
    session_root = provider._config.sessions_root / request.session_id
    expected_first = base64.b64encode((session_root / first_file).read_bytes()).decode("ascii")
    expected_second = base64.b64encode((session_root / second_file).read_bytes()).decode("ascii")

    assert first_data == expected_first
    assert second_data == expected_second


def test_supported_jpeg_attachment_is_encoded_correctly(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, fake_responses = _provider(tmp_path, responses)

    provider.analyze(request)

    content = fake_responses.calls[0]["input"][0]["content"]
    image_items = [item for item in content if item["type"] == "input_image"]
    assert image_items[0]["image_url"].startswith("data:image/jpeg;base64,")


def test_supported_png_attachment_is_encoded_correctly(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, fake_responses = _provider(tmp_path, responses)

    provider.analyze(request)

    content = fake_responses.calls[0]["input"][0]["content"]
    image_items = [item for item in content if item["type"] == "input_image"]
    assert image_items[1]["image_url"].startswith("data:image/png;base64,")


def test_missing_image_is_rejected_before_provider_call(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, fake_responses = _provider(tmp_path, responses)
    missing_file = provider._config.sessions_root / request.session_id / request.ordered_evidence_inputs[0].storage_ref
    missing_file.unlink()

    with pytest.raises(InvestigationAnalysisProviderMissingImageError):
        provider.analyze(request)

    assert len(fake_responses.calls) == 0


def test_unsupported_mime_is_rejected_before_provider_call(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, fake_responses = _provider(tmp_path, responses)
    unsupported = request.ordered_evidence_inputs[0].model_copy(update={"media_type": "image/webp"})
    bad_request = request.model_copy(update={"ordered_evidence_inputs": [unsupported, request.ordered_evidence_inputs[1]]})

    with pytest.raises(InvestigationAnalysisProviderUnsupportedImageError):
        provider.analyze(bad_request)

    assert len(fake_responses.calls) == 0


def test_unsafe_storage_reference_is_rejected(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, fake_responses = _provider(tmp_path, responses)
    unsafe = request.ordered_evidence_inputs[0].model_copy(update={"storage_ref": "../escape.png"})
    bad_request = request.model_copy(update={"ordered_evidence_inputs": [unsafe, request.ordered_evidence_inputs[1]]})

    with pytest.raises(InvestigationAnalysisProviderUnsupportedImageError):
        provider.analyze(bad_request)

    assert len(fake_responses.calls) == 0


def test_api_key_is_read_from_configuration_and_never_embedded_in_models(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, factory, _fake_responses = _provider(tmp_path, responses)

    result = provider.analyze(request)

    assert factory.api_keys == ["test-key"]
    assert "test-key" not in str(request.model_dump(mode="json"))
    assert "test-key" not in str(result.model_dump(mode="json"))


def test_missing_api_key_produces_explicit_configuration_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("INVESTIGATION_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_VISION_MODEL", raising=False)

    with pytest.raises(InvestigationAnalysisProviderMissingApiKeyError):
        InvestigationOpenAIProviderConfig.from_env()


def test_configurable_model_is_passed_to_api(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, fake_responses = _provider(tmp_path, responses)

    provider.analyze(request)

    assert fake_responses.calls[0]["model"] == provider._config.model


def test_finite_timeout_is_applied(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, fake_responses = _provider(tmp_path, responses)

    provider.analyze(request)

    assert fake_responses.calls[0]["timeout"] == provider._config.timeout_seconds


def test_valid_structured_provider_response_returns_model(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, _fake_responses = _provider(tmp_path, responses)

    result = provider.analyze(request)

    assert isinstance(result, InvestigationAnalysisResponse)
    assert result.schema_version == INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION


def test_existing_production_validator_is_invoked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, _fake_responses = _provider(tmp_path, responses)

    called = {"count": 0}

    def _wrapped_validator(payload):
        called["count"] += 1
        return InvestigationAnalysisResponse.model_validate(payload)

    monkeypatch.setattr(provider_module, "validate_structured_analysis_response", _wrapped_validator)

    provider.analyze(request)

    assert called["count"] == 1


def test_blank_or_malformed_provider_response_is_rejected(tmp_path: Path):
    responses = _FakeResponses(
        parsed_response=_FakeParsedResponse(
            output_parsed={
                "schema_version": INVESTIGATION_ANALYSIS_RESPONSE_SCHEMA_VERSION,
                "concise_diagnosis": "   ",
                "immediate_recommended_action": "Run checks.",
                "supporting_observations": ["obs"],
                "confidence_or_uncertainty": "uncertain",
            }
        )
    )
    provider, request, _factory, _fake_responses = _provider(tmp_path, responses)

    with pytest.raises(InvestigationAnalysisProviderMalformedResponseError):
        provider.analyze(request)


def test_provider_timeout_maps_to_domain_timeout_error(tmp_path: Path):
    request_obj = httpx.Request("POST", "https://api.openai.com/v1/responses")
    responses = _FakeResponses(parse_exception=openai.APITimeoutError(request_obj))
    provider, request, _factory, _fake_responses = _provider(tmp_path, responses)

    with pytest.raises(InvestigationAnalysisProviderTimeoutError):
        provider.analyze(request)


def test_authentication_error_maps_correctly(tmp_path: Path):
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    resp = httpx.Response(401, request=req)
    responses = _FakeResponses(parse_exception=openai.AuthenticationError("bad key", response=resp, body=None))
    provider, request, _factory, _fake_responses = _provider(tmp_path, responses)

    with pytest.raises(InvestigationAnalysisProviderAuthenticationError):
        provider.analyze(request)


def test_rate_limit_error_maps_correctly(tmp_path: Path):
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    resp = httpx.Response(429, request=req)
    responses = _FakeResponses(parse_exception=openai.RateLimitError("too many", response=resp, body=None))
    provider, request, _factory, _fake_responses = _provider(tmp_path, responses)

    with pytest.raises(InvestigationAnalysisProviderRateLimitError):
        provider.analyze(request)


def test_connection_error_maps_correctly(tmp_path: Path):
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    responses = _FakeResponses(parse_exception=openai.APIConnectionError(message="conn", request=req))
    provider, request, _factory, _fake_responses = _provider(tmp_path, responses)

    with pytest.raises(InvestigationAnalysisProviderConnectionError):
        provider.analyze(request)


def test_refusal_or_blocked_response_is_handled_clearly(tmp_path: Path):
    refusal_item = SimpleNamespace(type="refusal", refusal="Safety blocked")
    message = SimpleNamespace(type="message", content=[refusal_item])
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=None, output=[message]))
    provider, request, _factory, _fake_responses = _provider(tmp_path, responses)

    with pytest.raises(InvestigationAnalysisProviderRefusalError):
        provider.analyze(request)


def test_unexpected_provider_error_is_wrapped_safely(tmp_path: Path):
    responses = _FakeResponses(parse_exception=ValueError("boom"))
    provider, request, _factory, _fake_responses = _provider(tmp_path, responses)

    with pytest.raises(InvestigationAnalysisProviderUnexpectedError):
        provider.analyze(request)


def test_request_package_is_not_mutated(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, _fake_responses = _provider(tmp_path, responses)

    before = request.model_dump(mode="json")
    provider.analyze(request)
    after = request.model_dump(mode="json")

    assert before == after


def test_no_result_is_persisted(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, _fake_responses = _provider(tmp_path, responses)

    provider.analyze(request)

    session_root = provider._config.sessions_root / request.session_id
    assert not (session_root / "finalization").exists()
    assert not (provider._config.sessions_root / "results").exists()


def test_no_session_attempt_lifecycle_mutation_occurs(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, _fake_responses = _provider(tmp_path, responses)

    provider.analyze(request)

    session_root = provider._config.sessions_root / request.session_id
    assert (session_root / "evidence" / "payloads" / "first.jpg").exists()
    assert (session_root / "evidence" / "payloads" / "second.png").exists()


def test_no_api_fastapi_ui_or_device_behavior_is_introduced(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, _factory, _fake_responses = _provider(tmp_path, responses)

    provider.analyze(request)

    session_root = provider._config.sessions_root / request.session_id
    assert not (session_root / "api").exists()
    assert not (session_root / "dashboard").exists()


def test_pytest_performs_no_live_openai_request(tmp_path: Path):
    responses = _FakeResponses(parsed_response=_FakeParsedResponse(output_parsed=_response_payload()))
    provider, request, factory, _fake_responses = _provider(tmp_path, responses)

    provider.analyze(request)

    assert factory.api_keys == ["test-key"]
