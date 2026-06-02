from pathlib import Path
from datetime import datetime
import re

SECTION_NAMES = (
    "Observed Issue",
    "Likely Cause",
    "Recommended Fix",
    "Validation Step",
    "Next Action",
)
SECTION_PATTERN = "|".join(re.escape(section_name) for section_name in SECTION_NAMES)
SECTION_LABEL_PATTERN = re.compile(
    rf"^\s*(?:#+\s*)?(?:\d+[\).\s-]*)?(?P<label>{SECTION_PATTERN})\s*:?\s*(?P<body>.*)$",
    flags=re.IGNORECASE,
)


def save_latest_fix(image_name, analysis_text):
    """Save the latest analysis in a developer-friendly markdown report."""
    section_lookup = {section_name.lower(): section_name for section_name in SECTION_NAMES}
    section_buffers = {section_name: [] for section_name in SECTION_NAMES}

    current_section = None
    for line in analysis_text.splitlines():
        match = SECTION_LABEL_PATTERN.match(line)
        if match:
            current_section = section_lookup.get(match.group("label").strip().lower())
            if not current_section:
                continue
            body = match.group("body").strip()
            if body:
                section_buffers[current_section].append(body)
            continue

        if current_section:
            stripped_line = line.strip()
            if stripped_line:
                section_buffers[current_section].append(stripped_line)

    extracted_sections = {
        section_name: "\n".join(lines).strip()
        for section_name, lines in section_buffers.items()
    }

    fallback_recommended_fix = next(
        (paragraph.strip() for paragraph in analysis_text.split("\n\n") if paragraph.strip()),
        "",
    )
    if not extracted_sections["Recommended Fix"] and fallback_recommended_fix:
        extracted_sections["Recommended Fix"] = fallback_recommended_fix
    for section_name in SECTION_NAMES:
        if not extracted_sections[section_name]:
            extracted_sections[section_name] = "No information provided."

    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    report_path = results_dir / "latest_fix.md"
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")

    content = "\n".join(
        [
            "# Latest Fix Report",
            "",
            f"- Timestamp: {timestamp}",
            f"- Image Analyzed: {image_name}",
            "",
            "## Observed Issue",
            "",
            extracted_sections["Observed Issue"],
            "",
            "## Likely Cause",
            "",
            extracted_sections["Likely Cause"],
            "",
            "## Recommended Fix",
            "",
            extracted_sections["Recommended Fix"],
            "",
            "## Validation Step",
            "",
            extracted_sections["Validation Step"],
            "",
            "## Next Action",
            "",
            extracted_sections["Next Action"],
            "",
        ]
    )

    report_path.write_text(content, encoding="utf-8")
