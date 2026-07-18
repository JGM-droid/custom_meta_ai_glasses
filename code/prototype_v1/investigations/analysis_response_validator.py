from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from .analysis_contract_errors import InvestigationAnalysisResponseValidationError
from .models import InvestigationAnalysisResponse


def validate_structured_analysis_response(payload: Mapping[str, Any] | InvestigationAnalysisResponse) -> InvestigationAnalysisResponse:
    try:
        if isinstance(payload, InvestigationAnalysisResponse):
            # Re-validate through model dump to enforce canonical validation behavior.
            return InvestigationAnalysisResponse.model_validate(payload.model_dump(mode="python"))
        return InvestigationAnalysisResponse.model_validate(dict(payload))
    except (TypeError, ValidationError) as exc:
        raise InvestigationAnalysisResponseValidationError("Structured analysis response validation failed.") from exc
