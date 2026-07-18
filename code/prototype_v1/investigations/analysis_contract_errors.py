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
