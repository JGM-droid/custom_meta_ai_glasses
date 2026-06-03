from __future__ import annotations

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
OUTPUT_PATH = RESULTS_DIR / "glasses_test_checklist.txt"


def build_checklist_text() -> str:
    lines = [
        "First Glasses Test Checklist",
        "",
        "1. Start API server in a terminal:",
        "   python -m uvicorn api:app --host 127.0.0.1 --port 8001 --app-dir code/prototype_v1",
        "2. Run one-command demo:",
        "   python code/prototype_v1/glasses_demo.py",
        "3. Optional voice check:",
        "   python code/prototype_v1/glasses_demo.py --speak",
        "4. Open display mock:",
        "   code/prototype_v1/glasses_display_mock.html",
        "5. Put on glasses.",
        "6. Verify voice guidance is understandable.",
        "7. Verify display guidance is glanceable.",
        "8. Rerun demo command and confirm guidance updates on display.",
        "",
        "Success Criteria",
        "- Can hear guidance",
        "- Can read guidance quickly",
        "- Voice and display match",
        "- One-command demo updates the display",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    text = build_checklist_text()
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    print(text, end="")
    print(f"Wrote: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
