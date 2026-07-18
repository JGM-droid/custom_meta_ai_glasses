from __future__ import annotations


class InvestigationAnalysisContractError(RuntimeError):
    pass


class InvestigationAnalysisRequestBuildError(InvestigationAnalysisContractError):
    pass


class InvestigationAnalysisIdentityMismatchError(InvestigationAnalysisRequestBuildError):
    pass


class InvestigationAnalysisMissingEvidenceError(InvestigationAnalysisRequestBuildError):
    pass


class InvestigationAnalysisUnsupportedEvidenceError(InvestigationAnalysisRequestBuildError):
    pass


class InvestigationAnalysisResponseValidationError(InvestigationAnalysisContractError):
    pass


class InvestigationAnalysisProviderError(InvestigationAnalysisContractError):
    pass


class InvestigationAnalysisProviderConfigurationError(InvestigationAnalysisProviderError):
    pass


class InvestigationAnalysisProviderMissingApiKeyError(InvestigationAnalysisProviderConfigurationError):
    pass


class InvestigationAnalysisProviderImageError(InvestigationAnalysisProviderError):
    pass


class InvestigationAnalysisProviderMissingImageError(InvestigationAnalysisProviderImageError):
    pass


class InvestigationAnalysisProviderUnsupportedImageError(InvestigationAnalysisProviderImageError):
    pass


class InvestigationAnalysisProviderTimeoutError(InvestigationAnalysisProviderError):
    pass


class InvestigationAnalysisProviderAuthenticationError(InvestigationAnalysisProviderError):
    pass


class InvestigationAnalysisProviderRateLimitError(InvestigationAnalysisProviderError):
    pass


class InvestigationAnalysisProviderConnectionError(InvestigationAnalysisProviderError):
    pass


class InvestigationAnalysisProviderRefusalError(InvestigationAnalysisProviderError):
    pass


class InvestigationAnalysisProviderMalformedResponseError(InvestigationAnalysisProviderError):
    pass


class InvestigationAnalysisProviderUnexpectedError(InvestigationAnalysisProviderError):
    pass
