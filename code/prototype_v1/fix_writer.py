from pathlib import Path
from datetime import datetime
import re
import json


SECTION_ORDER = [
    "Observed Issue",
    "Likely Cause",
    "Recommended Fix",
    "Validation Step",
    "Next Action",
]

SECTION_ALIASES = {
    "Observed Issue": {
        "observed issue",
        "issue",
        "observed problem",
        "problem",
        "observation",
    },
    "Likely Cause": {
        "likely cause",
        "cause",
        "root cause",
        "possible cause",
    },
    "Recommended Fix": {
        "recommended fix",
        "fix",
        "recommendation",
        "proposed fix",
        "solution",
    },
    "Validation Step": {
        "validation step",
        "validation",
        "verification",
        "verify",
        "test step",
    },
    "Next Action": {
        "next action",
        "next step",
        "follow up",
        "follow-up",
    },
}


def _normalize_label(label):
    return re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()


def _to_canonical_section(label):
    normalized = _normalize_label(label)
    for section, aliases in SECTION_ALIASES.items():
        alias_normalized = {_normalize_label(a) for a in aliases}
        if normalized in alias_normalized:
            return section
    return None


def _extract_structured_sections(analysis_text):
    sections = {name: "" for name in SECTION_ORDER}
    text = (analysis_text or "").strip()
    if not text:
        return sections

    lines = text.splitlines()
    current_section = None
    buffer = []

    def flush_buffer():
        nonlocal buffer
        if current_section and buffer:
            value = "\n".join(buffer).strip()
            if value:
                if sections[current_section]:
                    sections[current_section] += "\n\n" + value
                else:
                    sections[current_section] = value
        buffer = []

    for raw_line in lines:
        # Match markdown headings like: ## Recommended Fix
        heading_match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", raw_line)
        if heading_match:
            maybe_section = _to_canonical_section(heading_match.group(1))
            if maybe_section:
                flush_buffer()
                current_section = maybe_section
                continue

        # Match bold labels like: **Likely Cause**
        bold_match = re.match(r"^\s*\*\*(.+?)\*\*\s*:?\s*$", raw_line)
        if bold_match:
            maybe_section = _to_canonical_section(bold_match.group(1))
            if maybe_section:
                flush_buffer()
                current_section = maybe_section
                continue

        # Match inline labels like: Validation Step: Re-run with...
        inline_match = re.match(r"^\s*([A-Za-z][A-Za-z \-]{2,})\s*:\s*(.*)$", raw_line)
        if inline_match:
            maybe_section = _to_canonical_section(inline_match.group(1))
            if maybe_section:
                flush_buffer()
                current_section = maybe_section
                inline_value = inline_match.group(2).strip()
                if inline_value:
                    buffer.append(inline_value)
                continue

        if current_section:
            buffer.append(raw_line)

    flush_buffer()
    return sections


def save_latest_fix(image_name, analysis_text):
    """Save the latest analysis in a developer-friendly markdown report."""
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    report_path = results_dir / "latest_fix.md"
    response_json_path = results_dir / "latest_response.json"
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    parsed_sections = _extract_structured_sections(analysis_text)

    fallback_text = "Not explicitly provided by AI response."
    raw_text = (analysis_text or "").strip()

    # If no structured sections were detected, preserve raw analysis text.
    if not any(parsed_sections.values()) and raw_text:
        parsed_sections["Observed Issue"] = raw_text

    for section_name in SECTION_ORDER:
        if not parsed_sections[section_name]:
            parsed_sections[section_name] = fallback_text

    content = "\n".join(
        [
            "# Latest Fix Report",
            "",
            f"- Timestamp: {timestamp}",
            f"- Image Analyzed: {image_name}",
            "",
            "## Observed Issue",
            "",
            parsed_sections["Observed Issue"],
            "",
            "## Likely Cause",
            "",
            parsed_sections["Likely Cause"],
            "",
            "## Recommended Fix",
            "",
            parsed_sections["Recommended Fix"],
            "",
            "## Validation Step",
            "",
            parsed_sections["Validation Step"],
            "",
            "## Next Action",
            "",
            parsed_sections["Next Action"],
            "",
        ]
    )

    report_path.write_text(content, encoding="utf-8")

    response_payload = {
        "timestamp": timestamp,
        "image_analyzed": image_name,
        "observed_issue": parsed_sections["Observed Issue"],
        "likely_cause": parsed_sections["Likely Cause"],
        "recommended_fix": parsed_sections["Recommended Fix"],
        "validation_step": parsed_sections["Validation Step"],
        "next_action": parsed_sections["Next Action"],
        "full_analysis": raw_text,
    }
    response_json_path.write_text(
        json.dumps(response_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
