from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Protocol

import openai
from openai import OpenAI

from .analysis_contract_errors import (
    InvestigationAnalysisResponseValidationError,
    InvestigationAnalysisProviderAuthenticationError,
    InvestigationAnalysisProviderConfigurationError,
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
from .analysis_response_validator import validate_structured_analysis_response
from .models import (
    InvestigationAnalysisEvidenceAttachment,
    InvestigationAnalysisRequestPackage,
    InvestigationAnalysisResponse,
    SUPPORTED_ANALYSIS_REQUEST_IMAGE_MIME_TYPES,
)

_INVESTIGATION_OPENAI_MODEL_ENV = "INVESTIGATION_OPENAI_MODEL"
_INVESTIGATION_OPENAI_TIMEOUT_ENV = "INVESTIGATION_OPENAI_TIMEOUT_SECONDS"
_INVESTIGATION_SESSIONS_ROOT_ENV = "INVESTIGATION_SESSIONS_ROOT"
_OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
_DEFAULT_MODEL = "gpt-4.1-mini"
_DEFAULT_TIMEOUT_SECONDS = 45.0


@dataclass(frozen=True)
class InvestigationOpenAIProviderConfig:
    api_key: str
    model: str
    timeout_seconds: float
    sessions_root: Path

    @classmethod
    def from_env(cls) -> "InvestigationOpenAIProviderConfig":
        api_key = str(os.environ.get(_OPENAI_API_KEY_ENV) or "").strip()
        if not api_key:
            raise InvestigationAnalysisProviderMissingApiKeyError("OPENAI_API_KEY is required for provider execution.")

        model = str(
            os.environ.get(_INVESTIGATION_OPENAI_MODEL_ENV)
            or os.environ.get("OPENAI_VISION_MODEL")
            or _DEFAULT_MODEL
        ).strip()
        if not model:
            raise InvestigationAnalysisProviderConfigurationError("Investigation OpenAI model configuration is required.")

        raw_timeout = str(os.environ.get(_INVESTIGATION_OPENAI_TIMEOUT_ENV) or "").strip()
        if not raw_timeout:
            timeout_seconds = _DEFAULT_TIMEOUT_SECONDS
        else:
            try:
                timeout_seconds = float(raw_timeout)
            except ValueError as exc:
                raise InvestigationAnalysisProviderConfigurationError(
                    f"{_INVESTIGATION_OPENAI_TIMEOUT_ENV} must be numeric."
                ) from exc
        if timeout_seconds <= 0:
            raise InvestigationAnalysisProviderConfigurationError(
                f"{_INVESTIGATION_OPENAI_TIMEOUT_ENV} must be greater than zero."
            )

        configured_root = str(os.environ.get(_INVESTIGATION_SESSIONS_ROOT_ENV) or "").strip()
        if configured_root:
            sessions_root = Path(configured_root)
        else:
            sessions_root = Path(__file__).resolve().parents[1] / "results" / "investigation_sessions"

        return cls(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            sessions_root=sessions_root,
        )


@dataclass(frozen=True)
class InvestigationProviderDiagnostics:
    provider: str
    model: str
    analysis_attempt_id: str
    evidence_count: int
    elapsed_ms: int
    success: bool
    failure_category: str | None


class InvestigationAnalysisProvider(Protocol):
    def analyze(self, request_package: InvestigationAnalysisRequestPackage) -> InvestigationAnalysisResponse:
        ...


class OpenAIInvestigationAnalysisProvider:
    def __init__(
        self,
        *,
        config: InvestigationOpenAIProviderConfig,
        client_factory=OpenAI,
    ):
        self._config = config
        self._client_factory = client_factory
        self.last_diagnostics: InvestigationProviderDiagnostics | None = None

    def analyze(self, request_package: InvestigationAnalysisRequestPackage) -> InvestigationAnalysisResponse:
        start = perf_counter()
        try:
            client = self._client_factory(api_key=self._config.api_key)
            response = client.responses.parse(
                model=self._config.model,
                instructions=request_package.deterministic_system_instructions,
                input=self._build_input_messages(request_package),
                text_format=InvestigationAnalysisResponse,
                timeout=self._config.timeout_seconds,
            )
            parsed = getattr(response, "output_parsed", None)
            if parsed is None:
                if _response_contains_refusal(response):
                    raise InvestigationAnalysisProviderRefusalError("Provider refused the analysis request.")
                raise InvestigationAnalysisProviderMalformedResponseError(
                    "Provider response did not contain structured output."
                )

            validated = validate_structured_analysis_response(parsed)
            self.last_diagnostics = InvestigationProviderDiagnostics(
                provider="openai",
                model=self._config.model,
                analysis_attempt_id=request_package.analysis_attempt_id,
                evidence_count=len(request_package.ordered_evidence_inputs),
                elapsed_ms=int((perf_counter() - start) * 1000),
                success=True,
                failure_category=None,
            )
            return validated
        except InvestigationAnalysisProviderRefusalError:
            self._set_failure_diagnostics(request_package, start, "refusal")
            raise
        except InvestigationAnalysisProviderMalformedResponseError:
            self._set_failure_diagnostics(request_package, start, "malformed_output")
            raise
        except Exception as exc:
            mapped = self._map_provider_exception(exc)
            self._set_failure_diagnostics(request_package, start, _error_category(mapped))
            raise mapped from exc

    def _build_input_messages(self, request_package: InvestigationAnalysisRequestPackage) -> list[dict[str, object]]:
        explanation = request_package.normalized_explanation_text or "[none provided]"
        content: list[dict[str, object]] = [
            {
                "type": "input_text",
                "text": request_package.deterministic_context_instructions,
            },
            {
                "type": "input_text",
                "text": f"normalized_explanation_text: {explanation}",
            },
        ]

        for attachment in request_package.ordered_evidence_inputs:
            data_url = self._image_data_url(
                session_id=request_package.session_id,
                attachment=attachment,
            )
            content.append(
                {
                    "type": "input_image",
                    "image_url": data_url,
                }
            )

        return [{"role": "user", "content": content}]

    def _image_data_url(
        self,
        *,
        session_id: str,
        attachment: InvestigationAnalysisEvidenceAttachment,
    ) -> str:
        media_type = str(attachment.media_type or "").strip().lower()
        if media_type not in SUPPORTED_ANALYSIS_REQUEST_IMAGE_MIME_TYPES:
            raise InvestigationAnalysisProviderUnsupportedImageError("Unsupported image MIME type for provider request.")

        workspace = (self._config.sessions_root / session_id).resolve(strict=False)
        storage_ref = str(attachment.storage_ref or "").strip().replace("\\", "/")
        if not storage_ref:
            raise InvestigationAnalysisProviderMissingImageError("Attachment storage_ref is required.")
        if storage_ref.startswith("/"):
            raise InvestigationAnalysisProviderUnsupportedImageError("Attachment storage_ref must be relative.")

        candidate = (workspace / storage_ref).resolve(strict=False)
        if workspace not in candidate.parents and candidate != workspace:
            raise InvestigationAnalysisProviderUnsupportedImageError("Attachment storage_ref escapes session workspace.")

        if not candidate.exists() or not candidate.is_file():
            raise InvestigationAnalysisProviderMissingImageError("Attachment image file is missing.")

        try:
            payload_bytes = candidate.read_bytes()
        except OSError as exc:
            raise InvestigationAnalysisProviderMissingImageError("Attachment image file could not be read.") from exc

        if not payload_bytes:
            raise InvestigationAnalysisProviderMissingImageError("Attachment image file is empty.")

        encoded = base64.b64encode(payload_bytes).decode("ascii")
        return f"data:{media_type};base64,{encoded}"

    @staticmethod
    def _map_provider_exception(exc: Exception) -> Exception:
        if isinstance(exc, InvestigationAnalysisProviderConfigurationError):
            return exc
        if isinstance(exc, InvestigationAnalysisProviderMissingApiKeyError):
            return exc
        if isinstance(exc, InvestigationAnalysisProviderMissingImageError):
            return exc
        if isinstance(exc, InvestigationAnalysisProviderUnsupportedImageError):
            return exc
        if isinstance(exc, InvestigationAnalysisResponseValidationError):
            return InvestigationAnalysisProviderMalformedResponseError("Provider response failed structured validation.")

        if isinstance(exc, openai.APITimeoutError):
            return InvestigationAnalysisProviderTimeoutError("OpenAI provider request timed out.")
        if isinstance(exc, openai.AuthenticationError):
            return InvestigationAnalysisProviderAuthenticationError("OpenAI authentication failed.")
        if isinstance(exc, openai.RateLimitError):
            return InvestigationAnalysisProviderRateLimitError("OpenAI rate limit exceeded.")
        if isinstance(exc, openai.APIConnectionError):
            return InvestigationAnalysisProviderConnectionError("OpenAI connection failed.")

        if isinstance(exc, openai.PermissionDeniedError):
            return InvestigationAnalysisProviderRefusalError("OpenAI denied the provider request.")

        return InvestigationAnalysisProviderUnexpectedError("Unexpected provider failure during analysis.")

    def _set_failure_diagnostics(
        self,
        request_package: InvestigationAnalysisRequestPackage,
        start: float,
        failure_category: str,
    ) -> None:
        self.last_diagnostics = InvestigationProviderDiagnostics(
            provider="openai",
            model=self._config.model,
            analysis_attempt_id=request_package.analysis_attempt_id,
            evidence_count=len(request_package.ordered_evidence_inputs),
            elapsed_ms=int((perf_counter() - start) * 1000),
            success=False,
            failure_category=failure_category,
        )


def _response_contains_refusal(response: object) -> bool:
    outputs = getattr(response, "output", None)
    if not isinstance(outputs, list):
        return False

    for output in outputs:
        if getattr(output, "type", None) != "message":
            continue
        content_items = getattr(output, "content", None)
        if not isinstance(content_items, list):
            continue
        for item in content_items:
            if getattr(item, "type", None) == "refusal":
                return True
    return False


def _error_category(exc: Exception) -> str:
    if isinstance(exc, InvestigationAnalysisProviderTimeoutError):
        return "timeout"
    if isinstance(exc, InvestigationAnalysisProviderAuthenticationError):
        return "authentication"
    if isinstance(exc, InvestigationAnalysisProviderRateLimitError):
        return "rate_limit"
    if isinstance(exc, InvestigationAnalysisProviderConnectionError):
        return "connection"
    if isinstance(exc, InvestigationAnalysisProviderRefusalError):
        return "refusal"
    if isinstance(exc, InvestigationAnalysisProviderMalformedResponseError):
        return "malformed_output"
    if isinstance(exc, InvestigationAnalysisProviderMissingImageError):
        return "missing_image"
    if isinstance(exc, InvestigationAnalysisProviderUnsupportedImageError):
        return "unsupported_image"
    if isinstance(exc, InvestigationAnalysisProviderMissingApiKeyError):
        return "missing_api_key"
    if isinstance(exc, InvestigationAnalysisProviderConfigurationError):
        return "invalid_configuration"
    return "unexpected"
