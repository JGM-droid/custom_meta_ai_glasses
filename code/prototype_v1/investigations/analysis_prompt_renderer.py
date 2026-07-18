from __future__ import annotations

from .models import InvestigationAnalysisEvidenceAttachment

PROMPT_RENDERER_VERSION = "1.0"


def _sequence_role(index: int, total: int) -> str:
    if index == 0:
        return "earliest_view"
    if index == total - 1:
        return "latest_view"
    return "intermediate_view"


def render_deterministic_analysis_instructions(
    *,
    normalized_explanation_text: str | None,
    ordered_evidence_inputs: list[InvestigationAnalysisEvidenceAttachment],
) -> tuple[str, str]:
    total = len(ordered_evidence_inputs)
    explanation = (normalized_explanation_text or "").strip()
    explanation_text = explanation if explanation else "[none provided]"

    system_instructions = (
        "You are analyzing one technical investigation composed of multiple captures. "
        "Treat all captures as one investigation. "
        "Use the explanation text as the user's hypothesis or question. "
        "Compare evidence across captures and keep sequence awareness. "
        "Do not invent facts not visible in evidence. "
        "State uncertainty explicitly when evidence is incomplete. "
        "Return a concise immediate recommended action suitable for glasses display, "
        "with short supporting diagnosis and observations."
    )

    evidence_lines: list[str] = []
    for index, item in enumerate(ordered_evidence_inputs):
        evidence_lines.append(
            (
                f"- capture_index={index}; role={_sequence_role(index, total)}; "
                f"evidence_id={item.evidence_id}; media_type={item.media_type}; "
                f"storage_ref={item.storage_ref}"
            )
        )

    context_instructions = (
        "investigation_context:\n"
        f"- explanation: {explanation_text}\n"
        "- guidance: produce concise actionable output with explicit uncertainty when needed\n"
        "ordered_captures:\n"
        + "\n".join(evidence_lines)
    )

    return system_instructions, context_instructions
