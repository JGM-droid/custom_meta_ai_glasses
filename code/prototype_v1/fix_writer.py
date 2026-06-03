from pathlib import Path
from datetime import datetime
import re
import json
from difflib import SequenceMatcher


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


def _extract_task_continuity(analysis_text):
    text = (analysis_text or "").strip()
    if not text:
        return "Unknown"

    match = re.search(r"Task\s+continuity\s*:\s*(.+)", text, flags=re.IGNORECASE)
    if not match:
        return "Unknown"

    value = match.group(1).strip()
    return value if value else "Unknown"


def _extract_line_field(analysis_text, label, default="Unknown"):
    text = (analysis_text or "").strip()
    if not text:
        return default

    pattern = rf"{re.escape(label)}\s*:\s*([^\n]+)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return default

    value = match.group(1).strip()
    return value if value else default


def _extract_section_value(analysis_text, label, default="Unknown"):
    text = (analysis_text or "").strip()
    if not text:
        return default

    pattern = re.compile(
        rf"(?:^|\n){re.escape(label)}\s*:\s*([\s\S]*?)(?=\n[A-Z][A-Z ]{{2,}}\s*:|$)",
        flags=re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return default

    value = match.group(1).strip()
    if not value:
        return default

    first_line = value.splitlines()[0].strip()
    return first_line if first_line else default


def _extract_completed_steps(analysis_text):
    text = (analysis_text or "").strip()
    if not text:
        return []

    steps = []

    # Include the singular "Last completed step" when present.
    last_completed = _extract_line_field(analysis_text, "Last completed step", default="")
    if last_completed:
        steps.append(last_completed)

    # Include any explicit "Completed steps" section when present.
    section_match = re.search(
        r"(?:^|\n)Completed\s+steps\s*:\s*([\s\S]*?)(?=\n[A-Z][A-Z ]{2,}\s*:|$)",
        text,
        flags=re.IGNORECASE,
    )
    if section_match:
        section_text = section_match.group(1).strip()
        for line in section_text.splitlines():
            cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
            if cleaned:
                steps.append(cleaned)

    # Preserve order but remove duplicates.
    deduped = []
    seen = set()
    for step in steps:
        key = step.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(step)

    return deduped


def _truncate(text, max_len):
    value = (text or "").strip()
    if len(value) <= max_len:
        return value
    if max_len <= 1:
        return value[:max_len]
    return value[: max_len - 1].rstrip() + "…"


def _build_glasses_guidance(current_task, next_action, risk, confidence):
    task = current_task or "Unknown"
    next_step = next_action or "Unknown"
    risk_value = risk or "Unknown"
    confidence_value = confidence or "Unknown"

    concise = (
        f"Task {task}. Next {next_step}. Risk {risk_value}. Confidence {confidence_value}."
    )
    if len(concise) <= 150:
        return concise

    compressed = (
        f"Task {_truncate(task, 24)}; Next {_truncate(next_step, 48)}; "
        f"Risk {_truncate(risk_value, 20)}; Confidence {_truncate(confidence_value, 10)}."
    )
    if len(compressed) <= 150:
        return compressed

    return _truncate(compressed, 150)


def _normalize_similarity_text(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _steps_similar(step_a, step_b):
    a = _normalize_similarity_text(step_a)
    b = _normalize_similarity_text(step_b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.85


def _extract_task_and_next_step(analysis_text):
    task = _extract_line_field(analysis_text, "Current task", default="Unknown")
    next_step = _extract_section_value(analysis_text, "NEXT ACTION", default="")
    if not next_step:
        next_step = _extract_section_value(analysis_text, "NEXT", default="")
    return task, next_step


def _build_stuck_status(current_task, current_next_step):
    session_memory_path = Path(__file__).resolve().parent / "results" / "session_memory.json"
    current_task_norm = _normalize_similarity_text(current_task)
    repeated_count = 1 if current_next_step else 0

    if not session_memory_path.exists() or not current_task_norm or not current_next_step:
        return {
            "is_stuck": False,
            "reason": "Insufficient history for repeated next-step detection.",
            "repeated_next_step_count": repeated_count,
        }

    try:
        memory_payload = json.loads(session_memory_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "is_stuck": False,
            "reason": "Unable to read session history for stuck detection.",
            "repeated_next_step_count": repeated_count,
        }

    observations = memory_payload.get("observations", []) if isinstance(memory_payload, dict) else []
    if not isinstance(observations, list):
        observations = []

    for item in observations:
        if not isinstance(item, dict):
            continue
        prior_analysis = item.get("analysis", "")
        if not isinstance(prior_analysis, str):
            continue

        prior_task, prior_next_step = _extract_task_and_next_step(prior_analysis)
        if _normalize_similarity_text(prior_task) != current_task_norm:
            continue
        if _steps_similar(prior_next_step, current_next_step):
            repeated_count += 1

    is_stuck = repeated_count >= 2
    reason = (
        "Same or very similar next action is repeating for the current task."
        if is_stuck
        else "No repeated next action detected for the current task."
    )
    return {
        "is_stuck": is_stuck,
        "reason": reason,
        "repeated_next_step_count": repeated_count,
    }


def _build_resume_previous_task(current_task, completed_steps, next_step):
    session_memory_path = Path(__file__).resolve().parent / "results" / "session_memory.json"
    current_task_value = current_task or "Unknown"
    current_next_step = next_step or "Unknown"

    if not session_memory_path.exists():
        available = current_task_value != "Unknown" and (
            bool(completed_steps) or current_next_step != "Unknown"
        )
        return {
            "available": available,
            "task": current_task_value,
            "completed_steps": completed_steps,
            "next_step": current_next_step,
            "reason": (
                "Using current task progress because prior session memory was not found."
                if available
                else "No prior session memory found for resume suggestions."
            ),
        }

    try:
        memory_payload = json.loads(session_memory_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "available": False,
            "task": "Unknown",
            "completed_steps": [],
            "next_step": "Unknown",
            "reason": "Unable to read session memory for resume suggestions.",
        }

    active_task = memory_payload.get("active_task", {}) if isinstance(memory_payload, dict) else {}
    task_name = str(active_task.get("current_task", "Unknown") or "Unknown")
    next_recommended = str(active_task.get("next_recommended_step", "Unknown") or "Unknown")

    observations = memory_payload.get("observations", []) if isinstance(memory_payload, dict) else []
    if not isinstance(observations, list):
        observations = []

    resume_steps = []
    normalized_task = _normalize_similarity_text(task_name)
    for item in reversed(observations):
        if not isinstance(item, dict):
            continue
        analysis_text = item.get("analysis", "")
        if not isinstance(analysis_text, str):
            continue

        observed_task = _extract_line_field(analysis_text, "Current task", default="")
        if _normalize_similarity_text(observed_task) != normalized_task:
            continue

        observed_steps = _extract_completed_steps(analysis_text)
        if observed_steps:
            resume_steps = observed_steps
            break

    if not resume_steps and _normalize_similarity_text(current_task_value) == normalized_task:
        resume_steps = completed_steps

    if next_recommended == "Unknown" and _normalize_similarity_text(current_task_value) == normalized_task:
        next_recommended = current_next_step

    available = task_name != "Unknown" and (
        bool(resume_steps) or (next_recommended and next_recommended != "Unknown")
    )

    return {
        "available": available,
        "task": task_name,
        "completed_steps": resume_steps,
        "next_step": next_recommended if next_recommended else "Unknown",
        "reason": (
            "Resume data loaded from recent session memory."
            if available
            else "No useful previous task context available to resume."
        ),
    }


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
    task_continuity = _extract_task_continuity(analysis_text)
    current_task = _extract_line_field(analysis_text, "Current task")
    confidence = _extract_line_field(analysis_text, "Confidence")
    risk = _extract_line_field(analysis_text, "RISK", default="No major risk.")
    completed_steps = _extract_completed_steps(analysis_text)
    next_action_for_guidance = _extract_section_value(analysis_text, "NEXT ACTION")
    next_step_for_progress = _extract_section_value(analysis_text, "NEXT ACTION", default="")
    if not next_step_for_progress:
        next_step_for_progress = _extract_section_value(analysis_text, "NEXT", default="")
    if not next_step_for_progress:
        next_step_for_progress = "Unknown"

    task_progress = {
        "completed_steps": completed_steps,
        "next_step": next_step_for_progress,
        "step_count": len(completed_steps),
    }
    stuck_status = _build_stuck_status(current_task, next_step_for_progress)
    resume_previous_task = _build_resume_previous_task(
        current_task,
        completed_steps,
        next_step_for_progress,
    )

    glasses_guidance = _build_glasses_guidance(
        current_task,
        next_action_for_guidance,
        risk,
        confidence,
    )

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
        "completed_steps": completed_steps,
        "task_progress": task_progress,
        "stuck_status": stuck_status,
        "resume_previous_task": resume_previous_task,
        "task_continuity": task_continuity,
        "glasses_guidance": glasses_guidance,
        "full_analysis": raw_text,
    }
    response_json_path.write_text(
        json.dumps(response_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
