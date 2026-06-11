from __future__ import annotations

from pathlib import Path
import json
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
INPUT_PATH = RESULTS_DIR / "terminal_capture.txt"
OUTPUT_PATH = RESULTS_DIR / "terminal_error_context.json"


def _empty_payload(summary: str, recommended_action: str) -> dict[str, Any]:
    return {
        "has_terminal_error": False,
        "error_type": "",
        "matched_keywords": [],
        "summary": summary,
        "recommended_action": recommended_action,
        "guidance_priority": {
            "level": "info",
            "source": "terminal_error_context",
            "headline": "No Terminal Error",
            "message": summary,
            "recommended_action": recommended_action,
        },
    }


def _detect_terminal_error(text: str) -> dict[str, Any]:
    lowered = text.lower()

    detection_rules = [
        {
            "error_type": "ModuleNotFoundError",
            "keywords": ["modulenotfounderror", "no module named"],
            "recommended_action": "Install the missing package or activate the correct virtual environment.",
            "headline": "Missing Python Module",
            "message": "Terminal output indicates a missing module.",
            "level": "critical",
        },
        {
            "error_type": "ImportError",
            "keywords": ["importerror"],
            "recommended_action": "Install the missing package or activate the correct virtual environment.",
            "headline": "Import Error Detected",
            "message": "Terminal output indicates an import error.",
            "level": "critical",
        },
        {
            "error_type": "SyntaxError",
            "keywords": ["syntaxerror"],
            "recommended_action": "Open the file shown in the traceback and fix the syntax error.",
            "headline": "Syntax Error Detected",
            "message": "Terminal output indicates a syntax error.",
            "level": "critical",
        },
        {
            "error_type": "PermissionError",
            "keywords": ["permissionerror"],
            "recommended_action": "Check file permissions or run the command from an allowed location.",
            "headline": "Permission Issue",
            "message": "Terminal output indicates a permissions issue.",
            "level": "critical",
        },
        {
            "error_type": "FileNotFoundError",
            "keywords": ["filenotfounderror"],
            "recommended_action": "Check that the file path exists and rerun the command.",
            "headline": "Missing File Path",
            "message": "Terminal output indicates a missing file path.",
            "level": "high",
        },
        {
            "error_type": "PortInUse",
            "keywords": ["port already in use", "address already in use"],
            "recommended_action": "Stop the process using the port or choose a different port.",
            "headline": "Port Conflict",
            "message": "Terminal output indicates the selected port is already in use.",
            "level": "high",
        },
        {
            "error_type": "CommandNotFound",
            "keywords": ["command not found", "not recognized as an internal or external command"],
            "recommended_action": "Check the command spelling or whether the tool is installed and on PATH.",
            "headline": "Command Not Found",
            "message": "Terminal output indicates an unknown command.",
            "level": "high",
        },
        {
            "error_type": "Traceback",
            "keywords": ["traceback"],
            "recommended_action": "Review the terminal output and resolve the reported error.",
            "headline": "Python Traceback Detected",
            "message": "Terminal output includes a traceback.",
            "level": "critical",
        },
        {
            "error_type": "GenericError",
            "keywords": ["failed", "error"],
            "recommended_action": "Review the terminal output and resolve the reported error.",
            "headline": "Terminal Error Detected",
            "message": "Terminal output includes a generic error signal.",
            "level": "medium",
        },
    ]

    matched_keywords: list[str] = []
    for keyword in [
        "traceback",
        "modulenotfounderror",
        "importerror",
        "syntaxerror",
        "permissionerror",
        "filenotfounderror",
        "port already in use",
        "address already in use",
        "no module named",
        "command not found",
        "not recognized as an internal or external command",
        "failed",
        "error",
    ]:
        if keyword in lowered:
            matched_keywords.append(keyword)

    for rule in detection_rules:
        if any(keyword in lowered for keyword in rule["keywords"]):
            return {
                "has_terminal_error": True,
                "error_type": rule["error_type"],
                "matched_keywords": matched_keywords,
                "summary": f"Detected terminal error signals: {', '.join(rule['keywords'])}.",
                "recommended_action": rule["recommended_action"],
                "guidance_priority": {
                    "level": rule["level"],
                    "source": "terminal_error_context",
                    "headline": rule["headline"],
                    "message": rule["message"],
                    "recommended_action": rule["recommended_action"],
                },
            }

    return _empty_payload(
        summary="No terminal error signals detected in terminal_capture.txt.",
        recommended_action="Continue current implementation.",
    )


def _write_output(payload: dict[str, Any]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _print_summary(payload: dict[str, Any]) -> None:
    print("Terminal Error Context")
    print(f"Has terminal error: {payload.get('has_terminal_error', False)}")
    print(f"Error type: {payload.get('error_type', '')}")
    print(f"Recommended action: {payload.get('recommended_action', '')}")
    print(f"Wrote: {OUTPUT_PATH}")


def main() -> None:
    if not INPUT_PATH.exists() or not INPUT_PATH.is_file():
        print(
            "terminal_capture.txt not found. Create code/prototype_v1/results/terminal_capture.txt and paste recent terminal output into it."
        )
        payload = _empty_payload(
            summary="No terminal capture file found.",
            recommended_action="Create terminal_capture.txt with recent terminal output, then rerun this script.",
        )
        _write_output(payload)
        _print_summary(payload)
        return

    try:
        terminal_text = INPUT_PATH.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        payload = _empty_payload(
            summary="Could not read terminal_capture.txt.",
            recommended_action="Check file permissions and rerun this script.",
        )
        _write_output(payload)
        _print_summary(payload)
        return

    payload = _detect_terminal_error(terminal_text)
    _write_output(payload)
    _print_summary(payload)


if __name__ == "__main__":
    main()
