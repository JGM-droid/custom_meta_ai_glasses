from pathlib import Path
from datetime import datetime


def save_latest_fix(image_name, analysis_text):
    """Save the latest analysis in a developer-friendly markdown report."""
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
            "## Full AI Analysis",
            "",
            analysis_text,
            "",
            "## Copy/Paste Fix",
            "",
            analysis_text,
            "",
            "## Next Step",
            "",
            "Use the guidance above to apply the fix, then run the next capture to validate the result.",
            "",
        ]
    )

    report_path.write_text(content, encoding="utf-8")
