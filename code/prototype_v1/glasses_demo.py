from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import subprocess
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
PROJECT_DOTENV_PATH = PROJECT_ROOT / ".env"
RESULTS_DIR = BASE_DIR / "results"
CODING_CONTEXT_SCRIPT = BASE_DIR / "coding_context_pack.py"
RESUME_NOW_SCRIPT = BASE_DIR / "resume_now.py"
CONTEXT_FUSION_SCRIPT = BASE_DIR / "context_fusion.py"
RESUME_NOW_OUTPUT = RESULTS_DIR / "resume_now.json"
OUTPUT_PATH = RESULTS_DIR / "glasses_demo.json"
DISPLAY_MOCK_PATH = BASE_DIR / "glasses_display_mock.html"
TERMINAL_ERROR_OUTPUT = RESULTS_DIR / "terminal_error_context.json"
CODING_CONTEXT_OUTPUT = RESULTS_DIR / "coding_context_pack.json"
CONTEXT_FUSION_OUTPUT = RESULTS_DIR / "context_fusion.json"
PROJECT_MEMORY_PATH = PROJECT_ROOT / "AGENTS.md"
PROJECT_PROGRESS_PATH = RESULTS_DIR / "project_progress.json"
TASK_STATE_PATH = RESULTS_DIR / "task_state.json"
TASK_COMPLETION_PATH = RESULTS_DIR / "task_completion.json"
CHATGPT_CONTEXT_PAYLOAD_PATH = RESULTS_DIR / "chatgpt_context_payload.json"
GUIDANCE_RESPONSE_PATH = RESULTS_DIR / "guidance_response.json"
CHATGPT_REQUEST_PATH = RESULTS_DIR / "chatgpt_request.json"
CHATGPT_RESPONSE_RAW_PATH = RESULTS_DIR / "chatgpt_response_raw.json"

# Load project-root environment variables early so OpenAI settings are available
# before any guidance request logic executes.
try:
    load_dotenv(dotenv_path=PROJECT_DOTENV_PATH, override=False)
except Exception:
    pass

SCENARIO_GUIDANCE = {
    "normal": {
        "level": "info",
        "headline": "Continue Implementation",
        "recommended_action": "Continue the next implementation step.",
    },
    "error": {
        "level": "critical",
        "headline": "Resolve Error First",
        "recommended_action": "Review and resolve the current error before continuing.",
    },
    "git": {
        "level": "high",
        "headline": "Review Git Changes",
        "recommended_action": "Review your git changes before continuing.",
    },
    "switch": {
        "level": "low",
        "headline": "Possible Task Switch",
        "recommended_action": "Confirm whether you want to continue the current task.",
    },
    "stuck": {
        "level": "medium",
        "headline": "Possible Blocker",
        "recommended_action": "Break the task into a smaller next step.",
    },
}

GUIDANCE_PRIORITY_RANK = {
    "critical": 5,
    "high": 4,
    "medium": 3,
    "low": 2,
    "info": 1,
}

FILE_FOCUS_GUIDANCE: dict[str, dict[str, Any]] = {
    "api.py": {
        "current_focus": "FastAPI endpoint development",
        "suggested_checks": [
            "Verify endpoint request/response schema consistency.",
            "Confirm fallback behavior and HTTP status handling.",
            "Run a quick local /latest smoke test before tunnel testing.",
        ],
    },
    "context_fusion.py": {
        "current_focus": "Context fusion development",
        "suggested_checks": [
            "Confirm source selection order remains Error > Git > Snapshot.",
            "Validate missing input files are handled without crashes.",
            "Check fused output fields for active_file and guidance consistency.",
        ],
    },
    "glasses_display_mock.html": {
        "current_focus": "Display/UI development",
        "suggested_checks": [
            "Verify polling updates guidance and active-file lines every cycle.",
            "Confirm API URL override and same-origin fallback both work.",
            "Test visual fallback when active file context is unavailable.",
        ],
    },
    "active_editor_context.py": {
        "current_focus": "VS Code signal development",
        "suggested_checks": [
            "Validate active_editor_state.json parsing and invalid JSON fallback.",
            "Confirm output schema remains stable for context fusion input.",
            "Check timestamps and event_type values update as expected.",
        ],
    },
    "ngrok_demo_launcher.py": {
        "current_focus": "Deployment guidance",
        "suggested_checks": [
            "Verify ngrok tunnel is online and /latest responds over HTTPS.",
            "Confirm final display URL includes a reachable API /latest path.",
            "Re-run normal/error/git scenarios and verify remote display updates.",
        ],
    },
}

GENERIC_FILE_FOCUS = {
    "current_focus": "General development",
    "suggested_checks": [
        "Review the current file changes and ensure intent is clear.",
        "Run a focused smoke test for the module you are editing.",
        "Confirm output artifacts match expected schema and freshness.",
    ],
}

REPO_NAME = "custom_meta_ai_glasses"

MILESTONE_SEQUENCE = [
    "V8.1 Project Memory",
    "V8.2 Smarter Prompt Generation",
    "V8.3 One-Command Refresh",
    "V8.4 Live Auto Refresh",
    "V8.5 Decision Engine",
    "V8.6 Task Continuity",
    "V8.7 Prompt Library",
    "V8.8 Architecture-Aware Decisions",
    "V8.9 Multi-Step Task Tracking",
]

DEFAULT_CURRENT_MILESTONE = "V8.6 Task Continuity"

VALID_TASK_COMPLETION_STATUSES = {"completed", "in_progress", "blocked", "unknown"}
VALID_REASON_CODES = {
    "milestone_validation_passed",
    "terminal_error_blocker",
    "active_task_no_completion_evidence",
    "weak_context",
    "stale_project_memory",
    "git_changes_need_review",
}

ARCHITECTURE_RELATIONSHIPS: dict[str, dict[str, list[str]]] = {
    "active_editor_context.py": {
        "upstream": [],
        "downstream": ["context_fusion.py"],
    },
    "context_fusion.py": {
        "upstream": ["active_editor_context.py"],
        "downstream": ["glasses_demo.py"],
    },
    "glasses_demo.py": {
        "upstream": ["context_fusion.py"],
        "downstream": ["resume_now.json"],
    },
    "resume_now.json": {
        "upstream": ["glasses_demo.py"],
        "downstream": ["FastAPI"],
    },
    "fastapi": {
        "upstream": ["resume_now.json"],
        "downstream": ["glasses_display_mock.html"],
    },
    "glasses_display_mock.html": {
        "upstream": ["FastAPI"],
        "downstream": ["Phone / Glasses Display"],
    },
}

TASK_TRACKING_MAP: dict[str, dict[str, Any]] = {
    "api.py": {
        "current_task": "FastAPI endpoint development",
        "last_completed_step": "Active file awareness integrated into payload",
        "next_recommended_step": "Verify endpoint output matches payload",
        "task_confidence": 0.92,
    },
    "context_fusion.py": {
        "current_task": "Context fusion development",
        "last_completed_step": "Active editor integration",
        "next_recommended_step": "Validate downstream payload consumers",
        "task_confidence": 0.9,
    },
    "glasses_display_mock.html": {
        "current_task": "Display UI development",
        "last_completed_step": "Active file context rendering",
        "next_recommended_step": "Validate prompt panel usability",
        "task_confidence": 0.9,
    },
    "ngrok_demo_launcher.py": {
        "current_task": "Deployment workflow",
        "last_completed_step": "Tunnel launch automation",
        "next_recommended_step": "Verify endpoint accessibility",
        "task_confidence": 0.88,
    },
}


def _load_project_memory_summary() -> dict[str, str]:
    summary = {
        "project_name": REPO_NAME,
        "architecture": "Architecture summary unavailable",
        "milestone": "Milestone unavailable",
    }

    if not PROJECT_MEMORY_PATH.exists() or not PROJECT_MEMORY_PATH.is_file():
        return summary

    try:
        text = PROJECT_MEMORY_PATH.read_text(encoding="utf-8")
    except OSError:
        return summary

    lines = text.splitlines()
    architecture_lines: list[str] = []
    in_architecture = False

    for index, raw in enumerate(lines):
        line = raw.strip()
        lower = line.lower()

        if lower == "project:" and index + 1 < len(lines):
            summary["project_name"] = _as_text(lines[index + 1].strip(), fallback=summary["project_name"])

        if lower == "current architecture:":
            in_architecture = True
            continue

        if in_architecture:
            if not line:
                continue
            if line.endswith(":") and lower != "current architecture:":
                in_architecture = False
                continue
            architecture_lines.append(line)

        if lower == "current milestone:" and index + 1 < len(lines):
            summary["milestone"] = _as_text(lines[index + 1].strip(), fallback=summary["milestone"])

    if architecture_lines:
        summary["architecture"] = " ".join(architecture_lines)

    return summary


def _select_prompt_mode(payload: dict[str, Any]) -> str:
    guidance = payload.get("guidance_priority") if isinstance(payload.get("guidance_priority"), dict) else {}
    guidance_source = _as_text(guidance.get("source"), fallback="").lower()
    has_terminal_error = bool(payload.get("has_terminal_error", False))

    active_file = payload.get("active_file") if isinstance(payload.get("active_file"), dict) else {}
    active_file_name = _as_text(active_file.get("active_file_name"), fallback="")
    active_file_lower = active_file_name.lower()

    if has_terminal_error or "terminal_error" in guidance_source:
        return "error_resolution"

    if active_file_lower == "glasses_display_mock.html":
        return "display_ui"

    if active_file_lower == "ngrok_demo_launcher.py" or "deploy" in guidance_source or "tunnel" in guidance_source:
        return "deployment"

    if "git_intelligence" in guidance_source:
        if active_file_lower in {"api.py", "context_fusion.py", "active_editor_context.py"}:
            return "file_development"
        return "git_review"

    if active_file_name:
        return "file_development"

    return "file_development"


def _is_deployment_file(active_file_name: str, guidance_source: str) -> bool:
    name = active_file_name.lower()
    deployment_names = {
        "ngrok_demo_launcher.py",
        "deploy.py",
        "deployment.py",
        "launch.py",
    }
    if name in deployment_names:
        return True

    deployment_tokens = ["deploy", "deployment", "ngrok", "tunnel", "launcher"]
    if any(token in name for token in deployment_tokens):
        return True

    return any(token in guidance_source for token in deployment_tokens)


def _is_ui_related_file(active_file_name: str, prompt_mode: str, current_focus: str) -> bool:
    name = active_file_name.lower()
    if name == "glasses_display_mock.html":
        return True

    ui_tokens = ["display", "ui", "dashboard", ".html"]
    if any(token in name for token in ui_tokens):
        return True

    if prompt_mode == "display_ui":
        return True

    return "display/ui" in current_focus.lower() or "ui" in current_focus.lower()


def _has_recent_implementation_change(active_file: dict[str, Any], prompt_mode: str, current_focus: str) -> bool:
    if bool(active_file.get("is_dirty", False)):
        return True

    event_type = _as_text(active_file.get("event_type"), fallback="").lower()
    if event_type:
        return True

    if prompt_mode == "display_ui":
        return True

    return "display/ui" in current_focus.lower() or "development" in current_focus.lower()


def _select_next_step_decision(payload: dict[str, Any]) -> tuple[str, str]:
    guidance = payload.get("guidance_priority") if isinstance(payload.get("guidance_priority"), dict) else {}
    guidance_source = _as_text(guidance.get("source"), fallback="").lower()
    active_file = payload.get("active_file") if isinstance(payload.get("active_file"), dict) else {}
    active_file_name = _as_text(active_file.get("active_file_name"), fallback="")
    prompt_mode = _as_text(payload.get("prompt_mode"), fallback="")
    current_focus = _as_text(payload.get("current_focus"), fallback="General development")

    has_terminal_error = bool(payload.get("has_terminal_error", False)) or "terminal_error" in guidance_source
    if has_terminal_error:
        decision = (
            "fix_error",
            "Terminal traceback or command failure is present and must be resolved before implementation continues.",
        )
        return _apply_architecture_reasoning(active_file_name, decision)

    has_git_priority = "git_intelligence" in guidance_source
    if has_git_priority:
        decision = (
            "review_git",
            "Git changes are present (modified, staged, or untracked) and should be reviewed before the next implementation step.",
        )
        return _apply_architecture_reasoning(active_file_name, decision)

    if _is_deployment_file(active_file_name, guidance_source):
        decision = (
            "deployment_validation",
            "Deployment-related file is active, so validate launch flow, tunnel availability, and endpoint access next.",
        )
        return _apply_architecture_reasoning(active_file_name, decision)

    if _is_ui_related_file(active_file_name, prompt_mode, current_focus) and _has_recent_implementation_change(active_file, prompt_mode, current_focus):
        decision = (
            "test_changes",
            "UI/display implementation context is active with recent change signals, so validating rendering and polling is the highest-value next step.",
        )
        return _apply_architecture_reasoning(active_file_name, decision)

    if active_file_name:
        decision = (
            "continue_implementation",
            "No blocking error or Git-priority signal is present, so continue implementing the active file task.",
        )
        return _apply_architecture_reasoning(active_file_name, decision)

    decision = (
        "continue_implementation",
        "No higher-priority signal is present, so continue implementation.",
    )
    return _apply_architecture_reasoning(active_file_name, decision)


def _build_architecture_context(payload: dict[str, Any]) -> dict[str, Any]:
    active_file = payload.get("active_file") if isinstance(payload.get("active_file"), dict) else {}
    active_file_name = _as_text(active_file.get("active_file_name"), fallback="")
    current_component = active_file_name or _as_text(payload.get("current_file"), fallback="") or "unknown"
    key = current_component.lower()

    relationships = ARCHITECTURE_RELATIONSHIPS.get(key, {"upstream": [], "downstream": []})
    upstream = relationships.get("upstream", []) if isinstance(relationships.get("upstream"), list) else []
    downstream = relationships.get("downstream", []) if isinstance(relationships.get("downstream"), list) else []

    return {
        "current_component": current_component,
        "upstream_dependencies": [str(item) for item in upstream if str(item).strip()],
        "downstream_dependencies": [str(item) for item in downstream if str(item).strip()],
    }


def _apply_architecture_reasoning(active_file_name: str, decision: tuple[str, str]) -> tuple[str, str]:
    name = active_file_name.lower()
    decision_name, reason = decision

    if name == "context_fusion.py":
        extra = " Changes may affect: glasses_demo.py, prompt generation, and display output."
        if extra.strip() not in reason:
            reason = reason + extra

    return decision_name, reason


def _build_mode_prompt(mode: str, payload: dict[str, Any], project_memory: dict[str, str]) -> str:
    guidance = payload.get("guidance_priority") if isinstance(payload.get("guidance_priority"), dict) else {}
    active_file = payload.get("active_file") if isinstance(payload.get("active_file"), dict) else {}

    guidance_headline = _as_text(guidance.get("headline"), fallback="Resume guidance")
    recommended_next_action = _as_text(
        payload.get("recommended_next_action"),
        fallback=_as_text(guidance.get("recommended_action"), fallback="Continue current implementation."),
    )
    next_step_decision = _as_text(payload.get("next_step_decision"), fallback="continue_implementation")
    decision_reason = _as_text(payload.get("decision_reason"), fallback="No explicit decision reason available.")
    decision_confidence = float(payload.get("decision_confidence", 0.0) or 0.0)
    decision_confidence_text = f"{max(0.0, min(1.0, decision_confidence)) * 100:.0f}%"
    decision_factors = payload.get("decision_factors") if isinstance(payload.get("decision_factors"), list) else []
    decision_factors_text = "\n".join([f"- {str(item).strip()}" for item in decision_factors if str(item).strip()])
    if not decision_factors_text:
        decision_factors_text = "- Context signals unavailable"
    project_progress = payload.get("project_progress") if isinstance(payload.get("project_progress"), dict) else {}
    last_completed_milestone = _as_text(project_progress.get("last_completed_milestone"), fallback="Unknown")
    current_milestone = _as_text(project_progress.get("current_milestone"), fallback="Unknown")
    suggested_next_milestone = _as_text(project_progress.get("suggested_next_milestone"), fallback="Unknown")
    architecture_context = payload.get("architecture_context") if isinstance(payload.get("architecture_context"), dict) else {}
    active_file_name = _as_text(active_file.get("active_file_name"), fallback="unavailable")
    current_component = _as_text(architecture_context.get("current_component"), fallback=active_file_name)
    upstream_list = architecture_context.get("upstream_dependencies") if isinstance(architecture_context.get("upstream_dependencies"), list) else []
    downstream_list = architecture_context.get("downstream_dependencies") if isinstance(architecture_context.get("downstream_dependencies"), list) else []
    upstream_text = ", ".join([str(item).strip() for item in upstream_list if str(item).strip()]) or "None"
    downstream_text = ", ".join([str(item).strip() for item in downstream_list if str(item).strip()]) or "None"
    task_tracking = payload.get("task_tracking") if isinstance(payload.get("task_tracking"), dict) else {}
    task_current = _as_text(task_tracking.get("current_task"), fallback="General development")
    task_last_step = _as_text(task_tracking.get("last_completed_step"), fallback="No completed step recorded")
    task_next_step = _as_text(task_tracking.get("next_recommended_step"), fallback="Continue current implementation")
    current_focus = _as_text(payload.get("current_focus"), fallback="General development")
    checks = payload.get("suggested_checks") if isinstance(payload.get("suggested_checks"), list) else []
    checks_block = "\n".join([f"- {str(item).strip()}" for item in checks if str(item).strip()])

    common_header = (
        f"Project: {_as_text(project_memory.get('project_name'), fallback=REPO_NAME)}\n"
        "Project Memory:\n"
        f"- Architecture: {_as_text(project_memory.get('architecture'), fallback='Architecture summary unavailable')}\n"
        f"- Current Milestone: {_as_text(project_memory.get('milestone'), fallback='Milestone unavailable')}\n\n"
        f"Current active file: {active_file_name}\n"
        f"Current focus: {current_focus}\n"
        f"Guidance headline: {guidance_headline}\n"
        f"Recommended next action: {recommended_next_action}\n\n"
        f"Recommended next step: {next_step_decision}\n"
        f"Reason: {decision_reason}\n\n"
        f"Decision Confidence:\n{decision_confidence_text}\n\n"
        f"Reasoning Factors:\n{decision_factors_text}\n\n"
        "Project Progress:\n"
        f"- Last completed milestone: {last_completed_milestone}\n"
        f"- Current milestone: {current_milestone}\n"
        f"- Suggested next milestone: {suggested_next_milestone}\n\n"
        "Architecture Impact:\n"
        f"Current Component: {current_component}\n"
        f"Upstream: {upstream_text}\n"
        f"Downstream: {downstream_text}\n\n"
        "Task Continuity:\n"
        f"Current task: {task_current}\n"
        f"Last completed step: {task_last_step}\n"
        f"Next recommended step: {task_next_step}\n\n"
    )

    safety_block = (
        "Safety constraints:\n"
        "- Do not modify unrelated files.\n"
        "- Report findings before making changes unless explicitly asked.\n"
        "- Preserve existing architecture.\n"
        "- Keep changes minimal."
    )

    mode_body = {
        "error_resolution": (
            "Task Mode: Error Resolution\n"
            "Please debug the current failure.\n"
            "- Identify root cause first.\n"
            "- Explain why the failure occurs.\n"
            "- Propose the smallest safe fix.\n"
            "- Validate with focused checks before broader changes.\n"
        ),
        "git_review": (
            "Task Mode: Git Review\n"
            "Please inspect the current modified/staged changes.\n"
            "- Summarize what changed.\n"
            "- Identify risks/regressions.\n"
            "- Recommend the next commit step.\n"
            "- Do not make code changes yet.\n"
        ),
        "display_ui": (
            "Task Mode: Display/UI Development\n"
            "Please verify display behavior for the glasses UI.\n"
            "- Verify rendering of guidance and active-file context.\n"
            "- Verify polling and state refresh behavior.\n"
            "- Verify mobile and desktop behavior remain intact.\n"
        ),
        "deployment": (
            "Task Mode: Deployment\n"
            "Please verify launch and tunnel deployment flow.\n"
            "- Verify launcher sequence and process health.\n"
            "- Verify tunnel accessibility.\n"
            "- Verify key API/display endpoints respond correctly.\n"
        ),
        "file_development": (
            "Task Mode: File Development\n"
            "Please focus on the currently active file.\n"
            "- Explain its current purpose in the architecture.\n"
            "- Recommend the next implementation step.\n"
            "- Keep changes aligned with existing architecture.\n"
        ),
    }.get(mode, "Task Mode: File Development\nPlease continue with focused file-level implementation.\n")

    checks_section = "Suggested checks:\n" + (checks_block if checks_block else "- No suggested checks available.") + "\n\n"

    return common_header + mode_body + "\n" + checks_section + safety_block


def _build_prompt_library(payload: dict[str, Any], project_memory: dict[str, str]) -> dict[str, str]:
    active_file = payload.get("active_file") if isinstance(payload.get("active_file"), dict) else {}
    architecture_context = payload.get("architecture_context") if isinstance(payload.get("architecture_context"), dict) else {}
    task_tracking = payload.get("task_tracking") if isinstance(payload.get("task_tracking"), dict) else {}
    project_progress = payload.get("project_progress") if isinstance(payload.get("project_progress"), dict) else {}

    current_file = _as_text(active_file.get("active_file_name"), fallback="unavailable")
    language = _as_text(active_file.get("language_id"), fallback="unknown")
    current_focus = _as_text(payload.get("current_focus"), fallback="General development")
    decision = _as_text(payload.get("next_step_decision"), fallback="continue_implementation")
    decision_reason = _as_text(payload.get("decision_reason"), fallback="No decision reason available")

    current_component = _as_text(architecture_context.get("current_component"), fallback=current_file)
    upstream = architecture_context.get("upstream_dependencies") if isinstance(architecture_context.get("upstream_dependencies"), list) else []
    downstream = architecture_context.get("downstream_dependencies") if isinstance(architecture_context.get("downstream_dependencies"), list) else []
    upstream_text = ", ".join([str(item).strip() for item in upstream if str(item).strip()]) or "None"
    downstream_text = ", ".join([str(item).strip() for item in downstream if str(item).strip()]) or "None"

    current_task = _as_text(task_tracking.get("current_task"), fallback=current_focus)
    last_step = _as_text(task_tracking.get("last_completed_step"), fallback="No completed step recorded")
    next_step = _as_text(task_tracking.get("next_recommended_step"), fallback="Continue implementation")

    current_milestone = _as_text(project_progress.get("current_milestone"), fallback="Unknown")
    next_milestone = _as_text(project_progress.get("suggested_next_milestone"), fallback="Unknown")

    common_context = (
        f"Project: {_as_text(project_memory.get('project_name'), fallback=REPO_NAME)}\n"
        f"Current active file: {current_file}\n"
        f"File language: {language}\n"
        f"Current focus: {current_focus}\n"
        f"Current task: {current_task}\n"
        f"Last completed step: {last_step}\n"
        f"Next recommended step: {next_step}\n"
        f"Current milestone: {current_milestone}\n"
        f"Suggested next milestone: {next_milestone}\n"
        f"Decision: {decision}\n"
        f"Decision reason: {decision_reason}\n"
        f"Architecture component: {current_component}\n"
        f"Upstream dependencies: {upstream_text}\n"
        f"Downstream dependencies: {downstream_text}\n"
    )

    implementation_prompt = (
        common_context
        + "\nTask: Implement the current task with minimal safe changes.\n"
        + "1. Propose a focused implementation plan.\n"
        + "2. Describe exact code changes for the active file first.\n"
        + "3. Keep architecture and existing behavior intact.\n"
    )

    validation_prompt = (
        common_context
        + "\nTask: Validate the current feature and report confidence in behavior.\n"
        + "1. List high-signal tests and checks for this file/workflow.\n"
        + "2. Identify likely regressions and edge cases.\n"
        + "3. Provide a concise pass/fail checklist.\n"
    )

    architecture_prompt = (
        common_context
        + "\nTask: Analyze architecture impact of the current work.\n"
        + "1. Explain upstream and downstream impact paths.\n"
        + "2. Identify payload/schema compatibility risks.\n"
        + "3. Recommend guardrails to prevent regressions.\n"
    )

    git_review_prompt = (
        common_context
        + "\nTask: Review git changes and risks before commit.\n"
        + "1. Summarize expected change scope by component.\n"
        + "2. Call out regression and integration risks.\n"
        + "3. Provide commit readiness criteria.\n"
    )

    return {
        "implementation_prompt": implementation_prompt,
        "validation_prompt": validation_prompt,
        "architecture_prompt": architecture_prompt,
        "git_review_prompt": git_review_prompt,
    }


def _build_actionable_prompt(payload: dict[str, Any], project_memory: dict[str, str]) -> str:
    active_file = payload.get("active_file") if isinstance(payload.get("active_file"), dict) else {}
    task_tracking = payload.get("task_tracking") if isinstance(payload.get("task_tracking"), dict) else {}
    architecture_context = payload.get("architecture_context") if isinstance(payload.get("architecture_context"), dict) else {}

    project_name = _as_text(project_memory.get("project_name"), fallback=REPO_NAME)
    current_file = _as_text(active_file.get("active_file_name"), fallback="unavailable")
    current_task = _as_text(task_tracking.get("current_task"), fallback=_as_text(payload.get("current_focus"), fallback="General development"))
    last_step = _as_text(task_tracking.get("last_completed_step"), fallback="No completed step recorded")
    next_step = _as_text(task_tracking.get("next_recommended_step"), fallback="Continue implementation")

    current_component = _as_text(architecture_context.get("current_component"), fallback=current_file)
    upstream = architecture_context.get("upstream_dependencies") if isinstance(architecture_context.get("upstream_dependencies"), list) else []
    downstream = architecture_context.get("downstream_dependencies") if isinstance(architecture_context.get("downstream_dependencies"), list) else []
    upstream_text = ", ".join([str(item).strip() for item in upstream if str(item).strip()]) or "None"
    downstream_text = ", ".join([str(item).strip() for item in downstream if str(item).strip()]) or "None"
    architecture_impact = (
        f"Component: {current_component}; Upstream: {upstream_text}; Downstream: {downstream_text}"
    )

    decision_reason = _as_text(payload.get("decision_reason"), fallback="No decision reason available")
    confidence_value = payload.get("decision_confidence", 0.0)
    try:
        confidence_ratio = float(confidence_value)
    except (TypeError, ValueError):
        confidence_ratio = 0.0
    confidence_pct = int(round(max(0.0, min(1.0, confidence_ratio)) * 100))

    completion_status = _as_text(payload.get("task_completion_status"), fallback="unknown").lower()
    completion_evidence = payload.get("completion_evidence") if isinstance(payload.get("completion_evidence"), list) else []
    completion_evidence_text = "; ".join([str(item).strip() for item in completion_evidence if str(item).strip()])
    if not completion_evidence_text:
        completion_evidence_text = "No completion evidence available"
    reason_code = _as_text(payload.get("reason_code"), fallback="weak_context")
    evidence_source = _as_text(payload.get("evidence_source"), fallback="none")
    evidence_timestamp = _as_text(payload.get("evidence_timestamp"), fallback="unknown")
    evidence_confidence = payload.get("evidence_confidence", 0.0)
    try:
        evidence_confidence_value = float(evidence_confidence)
    except (TypeError, ValueError):
        evidence_confidence_value = 0.0
    evidence_confidence_text = f"{max(0.0, min(1.0, evidence_confidence_value)):.2f}"

    project_progress = payload.get("project_progress") if isinstance(payload.get("project_progress"), dict) else {}
    current_milestone = _as_text(project_progress.get("current_milestone"), fallback="Unknown")
    next_milestone = _as_text(project_progress.get("suggested_next_milestone"), fallback=current_milestone)

    recommended_type = _as_text(payload.get("recommended_prompt_type"), fallback="implementation").lower()
    objective_map = {
        "implementation": "Objective: Produce an implementation-focused response with minimal safe code changes.",
        "validation": "Objective: Produce a validation-focused response with high-signal tests and checks.",
        "architecture": "Objective: Produce an architecture-focused response emphasizing architecture impact and compatibility.",
        "git_review": "Objective: Produce a git-review-focused response assessing change risk and commit readiness.",
    }
    objective_line = objective_map.get(
        recommended_type,
        objective_map["implementation"],
    )

    status_guidance_map = {
        "completed": f"Completion status: completed. Move to the next milestone: {next_milestone} (from {current_milestone}).",
        "blocked": "Completion status: blocked. Focus first on resolving the blocker before implementation continues.",
        "in_progress": "Completion status: in_progress. Focus on finishing the current next recommended step.",
        "unknown": "Completion status: unknown. Clarify task state and gather stronger completion evidence before planning broad changes.",
    }
    status_guidance = status_guidance_map.get(completion_status, status_guidance_map["unknown"])

    return (
        f"Project name: {project_name}\n"
        f"Current active file: {current_file}\n"
        f"Current task: {current_task}\n"
        f"Last completed step: {last_step}\n"
        f"Next recommended step: {next_step}\n"
        f"Architecture impact: {architecture_impact}\n"
        f"Decision reasoning: {decision_reason}\n"
        f"Confidence percentage: {confidence_pct}%\n\n"
        f"Task completion status: {completion_status}\n"
        f"Reason code: {reason_code}\n"
        f"Evidence source: {evidence_source}\n"
        f"Evidence timestamp: {evidence_timestamp}\n"
        f"Evidence confidence: {evidence_confidence_text}\n"
        f"Completion evidence: {completion_evidence_text}\n"
        f"{status_guidance}\n\n"
        f"{objective_line}\n\n"
        "Provide:\n"
        "1. Analysis\n"
        "2. Minimal safe changes\n"
        "3. Validation plan\n"
        "4. Risks\n"
    )


def _build_chatgpt_prompt_template() -> str:
    return (
        "You are the project guidance engine for Custom Meta AI Glasses.\n"
        "Use the provided context to produce concise, evidence-backed engineering guidance.\n\n"
        "Answer all of the following:\n"
        "1. What is the user currently working on?\n"
        "2. What was most recently completed?\n"
        "3. What is the highest-priority next step?\n"
        "4. Why is it the highest priority?\n"
        "5. What validation should occur next?\n"
        "6. Is the user blocked?\n"
        "7. If blocked, what should be fixed first?\n"
    )


def _build_chatgpt_context_payload(payload: dict[str, Any], project_memory: dict[str, str]) -> dict[str, Any]:
    active_file = payload.get("active_file") if isinstance(payload.get("active_file"), dict) else {}
    task_tracking = payload.get("task_tracking") if isinstance(payload.get("task_tracking"), dict) else {}
    project_progress = payload.get("project_progress") if isinstance(payload.get("project_progress"), dict) else {}
    architecture_context = payload.get("architecture_context") if isinstance(payload.get("architecture_context"), dict) else {}
    workflow_evidence = payload.get("workflow_evidence") if isinstance(payload.get("workflow_evidence"), dict) else {}

    coding_context = _safe_load_json(CODING_CONTEXT_OUTPUT)
    git_intelligence = coding_context.get("git_intelligence") if isinstance(coding_context.get("git_intelligence"), dict) else {}
    terminal_context = _safe_load_json(TERMINAL_ERROR_OUTPUT)

    decision_factors = payload.get("decision_factors") if isinstance(payload.get("decision_factors"), list) else []

    return {
        "active_file": {
            "active_file_name": _as_text(active_file.get("active_file_name"), fallback=""),
            "active_file_path": _as_text(active_file.get("active_file_path"), fallback=""),
            "language_id": _as_text(active_file.get("language_id"), fallback=""),
            "is_dirty": bool(active_file.get("is_dirty", False)),
        },
        "current_task": _as_text(task_tracking.get("current_task"), fallback="General development"),
        "task_completion_status": _as_text(payload.get("task_completion_status"), fallback="unknown"),
        "completion_evidence": [str(item).strip() for item in payload.get("completion_evidence", []) if str(item).strip()] if isinstance(payload.get("completion_evidence"), list) else [],
        "reason_code": _as_text(payload.get("reason_code"), fallback="weak_context"),
        "project_progress": project_progress,
        "architecture_context": architecture_context,
        "workflow_evidence": workflow_evidence,
        "git_intelligence": git_intelligence,
        "terminal_context": terminal_context,
        "decision_confidence": float(payload.get("decision_confidence", 0.0) or 0.0),
        "decision_factors": [str(item).strip() for item in decision_factors if str(item).strip()],
        "prompt_mode": _as_text(payload.get("prompt_mode"), fallback="file_development"),
        "project_memory": {
            "project_name": _as_text(project_memory.get("project_name"), fallback=REPO_NAME),
            "architecture": _as_text(project_memory.get("architecture"), fallback="Architecture summary unavailable"),
            "milestone": _as_text(project_memory.get("milestone"), fallback="Milestone unavailable"),
        },
        "chatgpt_prompt_template": _build_chatgpt_prompt_template(),
    }


def _build_mock_chatgpt_guidance_response(payload: dict[str, Any]) -> dict[str, Any]:
    status = _as_text(payload.get("task_completion_status"), fallback="unknown").lower()
    decision_reason = _as_text(payload.get("decision_reason"), fallback="No decision reason available")
    current_task = _as_text(
        (payload.get("task_tracking") or {}).get("current_task") if isinstance(payload.get("task_tracking"), dict) else "",
        fallback=_as_text(payload.get("current_focus"), fallback="General development"),
    )
    project_progress = payload.get("project_progress") if isinstance(payload.get("project_progress"), dict) else {}
    next_milestone = _as_text(project_progress.get("current_milestone"), fallback="next milestone")
    recommended_next_step = _as_text(payload.get("next_step_decision"), fallback="continue_implementation")

    blocked = status == "blocked"

    if blocked:
        summary = "User is blocked by a terminal error and needs blocker resolution first."
        recommended_next_step = "Resolve the terminal error and re-run the failing command before continuing implementation."
        reasoning = "Terminal evidence has highest priority and indicates an active blocker."
        validation_steps = [
            "Re-run the previously failing command and confirm it exits with code 0.",
            "Refresh context and verify task_completion_status is no longer blocked.",
            "Run targeted checks for the active file after blocker resolution.",
        ]
    elif status == "completed":
        summary = f"Current milestone work appears complete; move to {next_milestone}."
        recommended_next_step = f"Advance to {next_milestone} and begin the first implementation step."
        reasoning = "Milestone completion evidence indicates the current workstream is complete and should advance."
        validation_steps = [
            "Confirm milestone advancement in project_progress.json.",
            "Define the first concrete task for the new milestone.",
            "Run a smoke validation after the first milestone change.",
        ]
    elif status == "in_progress":
        summary = f"User is actively working on {current_task}."
        recommended_next_step = "Complete the current recommended task step before starting a new milestone."
        reasoning = "Active task evidence exists, but completion evidence is not yet present."
        validation_steps = [
            "Complete the next_recommended_step for the active task.",
            "Run focused checks for the active file workflow.",
            "Capture completion evidence for milestone advancement.",
        ]
    else:
        summary = "Context is weak; gather stronger signals before changing milestones."
        recommended_next_step = "Re-establish active task context and collect fresh workflow evidence."
        reasoning = "No strong completion or blocker signals were available."
        validation_steps = [
            "Confirm active file and task tracking signals are present.",
            "Refresh context fusion and verify workflow evidence fields.",
            "Re-run decision engine with updated signals.",
        ]

    confidence = float(payload.get("decision_confidence", 0.0) or 0.0)
    confidence = max(0.0, min(1.0, confidence))

    return {
        "summary": summary,
        "recommended_next_step": recommended_next_step,
        "reasoning": f"{reasoning} {decision_reason}".strip(),
        "validation_steps": validation_steps,
        "confidence": confidence,
        "blocked": blocked,
    }


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", stripped)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_guidance_response(candidate: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None

    summary = _as_text(candidate.get("summary"), fallback="")
    recommended_next_step = _as_text(candidate.get("recommended_next_step"), fallback="")
    reasoning = _as_text(candidate.get("reasoning"), fallback="")
    validation_steps_raw = candidate.get("validation_steps") if isinstance(candidate.get("validation_steps"), list) else []
    validation_steps = [str(item).strip() for item in validation_steps_raw if str(item).strip()]

    confidence_raw = candidate.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    blocked = bool(candidate.get("blocked", False))

    if not summary or not recommended_next_step or not reasoning:
        return None

    return {
        "summary": summary,
        "recommended_next_step": recommended_next_step,
        "reasoning": reasoning,
        "validation_steps": validation_steps,
        "confidence": confidence,
        "blocked": blocked,
    }


def _build_chatgpt_request_payload(chatgpt_context_payload: dict[str, Any]) -> dict[str, Any]:
    model = _as_text(os.getenv("OPENAI_MODEL"), fallback="gpt-4o-mini")
    prompt_template = _as_text(chatgpt_context_payload.get("chatgpt_prompt_template"), fallback="")

    user_content = (
        f"{prompt_template}\n\n"
        "Return JSON only using this exact schema:\n"
        "{\n"
        '  "summary": "",\n'
        '  "recommended_next_step": "",\n'
        '  "reasoning": "",\n'
        '  "validation_steps": [],\n'
        '  "confidence": 0.0,\n'
        '  "blocked": false\n'
        "}\n\n"
        "Context payload JSON:\n"
        f"{json.dumps(chatgpt_context_payload, ensure_ascii=False, indent=2)}"
    )

    return {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "You are an engineering workflow guidance engine. Respond with valid JSON only.",
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
    }


def _request_openai_guidance(chatgpt_request_payload: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    api_key = _as_text(os.getenv("OPENAI_API_KEY"), fallback="")
    if not api_key:
        return None, {
            "status": "skipped_no_api_key",
            "message": "OPENAI_API_KEY was not set",
        }

    request_body = json.dumps(chatgpt_request_payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url="https://api.openai.com/v1/chat/completions",
        method="POST",
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urlopen(request, timeout=45) as response:
            response_text = response.read().decode("utf-8")
    except HTTPError as exc:
        raw_text = ""
        try:
            raw_text = exc.read().decode("utf-8")
        except Exception:
            raw_text = ""
        return None, {
            "status": "http_error",
            "http_status": exc.code,
            "error": _as_text(raw_text, fallback=str(exc)),
        }
    except URLError as exc:
        return None, {
            "status": "network_error",
            "error": _as_text(getattr(exc, "reason", str(exc)), fallback=str(exc)),
        }
    except Exception as exc:
        return None, {
            "status": "unexpected_error",
            "error": str(exc),
        }

    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        return None, {
            "status": "invalid_json_response",
            "raw_text": response_text,
        }

    if not isinstance(parsed, dict):
        return None, {
            "status": "invalid_response_shape",
            "raw": parsed,
        }

    choices = parsed.get("choices") if isinstance(parsed.get("choices"), list) else []
    if not choices:
        return None, {
            "status": "missing_choices",
            "raw": parsed,
        }

    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content_text = _as_text(message.get("content"), fallback="")
    parsed_content = _extract_json_object(content_text)
    if parsed_content is None:
        return None, {
            "status": "content_parse_failed",
            "raw": parsed,
        }

    normalized = _normalize_guidance_response(parsed_content)
    if normalized is None:
        return None, {
            "status": "schema_validation_failed",
            "parsed_content": parsed_content,
            "raw": parsed,
        }

    return normalized, {
        "status": "ok",
        "raw": parsed,
    }


def _generate_guidance_response(payload: dict[str, Any], chatgpt_context_payload: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any]]:
    mock_response = _build_mock_chatgpt_guidance_response(payload)
    chatgpt_request_payload = _build_chatgpt_request_payload(chatgpt_context_payload)

    request_debug = {
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "api_key_present": bool(_as_text(os.getenv("OPENAI_API_KEY"), fallback="")),
        "model": _as_text(chatgpt_request_payload.get("model"), fallback="gpt-4o-mini"),
        "request": chatgpt_request_payload,
    }

    guidance_response, response_debug = _request_openai_guidance(chatgpt_request_payload)
    if guidance_response is None:
        return mock_response, "fallback_mock", {
            "request": request_debug,
            "response": response_debug,
            "fallback_reason": _as_text(response_debug.get("status"), fallback="unknown"),
        }

    return guidance_response, "openai", {
        "request": request_debug,
        "response": response_debug,
    }


def _detect_task_completion(payload: dict[str, Any], project_memory: dict[str, str]) -> dict[str, Any]:
    guidance = payload.get("guidance_priority") if isinstance(payload.get("guidance_priority"), dict) else {}
    guidance_source = _as_text(guidance.get("source"), fallback="").lower()
    workflow_evidence = payload.get("workflow_evidence") if isinstance(payload.get("workflow_evidence"), dict) else {}
    signal_freshness = payload.get("signal_freshness") if isinstance(payload.get("signal_freshness"), dict) else {}

    evidence_timestamp = _as_text(
        signal_freshness.get("context_fusion_generated_at"),
        fallback=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    validation_evidence_available = bool(payload.get("validation_evidence_available", False))
    terminal_evidence_available = bool(payload.get("terminal_evidence_available", False))
    git_evidence_available = bool(payload.get("git_evidence_available", False))

    evidence_source_parts: list[str] = []
    if terminal_evidence_available:
        evidence_source_parts.append("terminal_error_context")
    if validation_evidence_available:
        evidence_source_parts.append("validation_signals")
    if git_evidence_available:
        evidence_source_parts.append("git_intelligence")
    if _as_text(workflow_evidence.get("selected_source"), fallback=""):
        evidence_source_parts.append(_as_text(workflow_evidence.get("selected_source"), fallback=""))
    evidence_source = ",".join(dict.fromkeys(evidence_source_parts)) if evidence_source_parts else "none"

    has_terminal_error = bool(payload.get("has_terminal_error", False)) or "terminal_error" in guidance_source
    completion_evidence: list[str] = []

    project_progress = payload.get("project_progress") if isinstance(payload.get("project_progress"), dict) else {}
    runtime_milestone = _normalize_milestone_name(_as_text(project_progress.get("current_milestone"), fallback=""))
    memory_milestone = _normalize_milestone_name(_as_text(project_memory.get("milestone"), fallback=""))
    stale_memory = bool(runtime_milestone and memory_milestone and runtime_milestone != memory_milestone)
    if stale_memory:
        completion_evidence.append(
            f"stale_project_memory: AGENTS milestone {memory_milestone} differs from runtime milestone {runtime_milestone}."
        )

    if has_terminal_error:
        completion_evidence.append("Terminal error context is active")
        return {
            "task_completion_status": "blocked",
            "completion_evidence": completion_evidence,
            "reason_code": "terminal_error_blocker" if not stale_memory else "stale_project_memory",
            "evidence_source": evidence_source or "terminal_error_context",
            "evidence_timestamp": evidence_timestamp,
            "evidence_confidence": 0.98,
            "additional_reason_codes": ["terminal_error_blocker"],
        }

    active_file = payload.get("active_file") if isinstance(payload.get("active_file"), dict) else {}
    active_file_name = _as_text(active_file.get("active_file_name"), fallback="")
    task_tracking = payload.get("task_tracking") if isinstance(payload.get("task_tracking"), dict) else {}
    current_task = _as_text(task_tracking.get("current_task"), fallback="")
    decision_name = _as_text(payload.get("next_step_decision"), fallback="")
    decision_reason = _as_text(payload.get("decision_reason"), fallback="").lower()

    current_milestone = runtime_milestone

    previous_completion = _safe_load_json(TASK_COMPLETION_PATH)
    recent_validation = previous_completion.get("recent_validation") if isinstance(previous_completion.get("recent_validation"), dict) else {}
    validation_milestone = _normalize_milestone_name(_as_text(recent_validation.get("milestone_passed"), fallback=""))

    payload_milestone = _normalize_milestone_name(_as_text(payload.get("milestone_passed"), fallback=""))

    if current_milestone and validation_milestone and validation_milestone == current_milestone:
        completion_evidence.append(f"Validation evidence indicates milestone passed: {current_milestone}")
    if current_milestone and payload_milestone and payload_milestone == current_milestone:
        completion_evidence.append(f"Payload indicates milestone passed: {current_milestone}")
    if current_milestone and any(token in decision_reason for token in ["milestone passed", "validation passed", "verified complete"]):
        completion_evidence.append(f"Decision reason includes completion evidence for {current_milestone}")
    if completion_evidence:
        return {
            "task_completion_status": "completed",
            "completion_evidence": completion_evidence,
            "reason_code": "milestone_validation_passed" if not stale_memory else "stale_project_memory",
            "evidence_source": evidence_source or "validation_signals",
            "evidence_timestamp": evidence_timestamp,
            "evidence_confidence": 0.9,
            "additional_reason_codes": ["milestone_validation_passed"],
        }

    git_risk = _as_text(workflow_evidence.get("git_risk_level"), fallback="low").lower()
    if git_evidence_available and git_risk in {"medium", "high"}:
        completion_evidence.append(f"Git risk level {git_risk} requires review before completion can be asserted")
        return {
            "task_completion_status": "in_progress",
            "completion_evidence": completion_evidence,
            "reason_code": "git_changes_need_review" if not stale_memory else "stale_project_memory",
            "evidence_source": evidence_source or "git_intelligence",
            "evidence_timestamp": evidence_timestamp,
            "evidence_confidence": 0.82,
            "additional_reason_codes": ["git_changes_need_review"],
        }

    has_active_context = bool(active_file_name) or bool(current_task)
    if has_active_context:
        in_progress_reason = "active task present without completion evidence"
        if decision_name:
            in_progress_reason = f"{in_progress_reason}; decision={decision_name}"
        completion_evidence.append(in_progress_reason)
        return {
            "task_completion_status": "in_progress",
            "completion_evidence": completion_evidence,
            "reason_code": "active_task_no_completion_evidence" if not stale_memory else "stale_project_memory",
            "evidence_source": evidence_source or "active_task_context",
            "evidence_timestamp": evidence_timestamp,
            "evidence_confidence": 0.72,
            "additional_reason_codes": ["active_task_no_completion_evidence"],
        }

    completion_evidence.append("insufficient active file/task context")
    return {
        "task_completion_status": "unknown",
        "completion_evidence": completion_evidence,
        "reason_code": "weak_context" if not stale_memory else "stale_project_memory",
        "evidence_source": evidence_source or "none",
        "evidence_timestamp": evidence_timestamp,
        "evidence_confidence": 0.45,
        "additional_reason_codes": ["weak_context"],
    }


def _advance_project_progress_if_completed(progress: dict[str, str], status: str, evidence: list[str]) -> dict[str, str]:
    if status != "completed":
        return progress

    current = _normalize_milestone_name(_as_text(progress.get("current_milestone"), fallback=""))
    if not current:
        return progress

    previous_completion = _safe_load_json(TASK_COMPLETION_PATH)
    if _normalize_milestone_name(_as_text(previous_completion.get("last_completed_milestone"), fallback="")) == current:
        return progress

    current_index = _milestone_index(current)
    if current_index < 0:
        return progress

    next_index = min(current_index + 1, len(MILESTONE_SEQUENCE) - 1)
    next_current = MILESTONE_SEQUENCE[next_index]
    next_suggested = MILESTONE_SEQUENCE[min(next_index + 1, len(MILESTONE_SEQUENCE) - 1)]

    updated = {
        "last_completed_milestone": current,
        "current_milestone": next_current,
        "suggested_next_milestone": next_suggested,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    PROJECT_PROGRESS_PATH.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence.append(f"Advanced project milestone from {current} to {next_current}")
    return updated


def _apply_completion_to_decision(payload: dict[str, Any], assessment: dict[str, Any]) -> None:
    status = _as_text(assessment.get("task_completion_status"), fallback="unknown")
    reason_code = _as_text(assessment.get("reason_code"), fallback="weak_context")

    if status == "blocked":
        payload["next_step_decision"] = "fix_error"
        payload["decision_reason"] = "Task is blocked by terminal error evidence and must be resolved before implementation continues."
        return

    if status == "completed":
        progress = payload.get("project_progress") if isinstance(payload.get("project_progress"), dict) else {}
        next_milestone = _as_text(progress.get("current_milestone"), fallback="next milestone")
        payload["next_step_decision"] = "advance_milestone"
        payload["decision_reason"] = f"Current milestone is complete based on evidence; proceed with {next_milestone}."
        task_tracking = payload.get("task_tracking") if isinstance(payload.get("task_tracking"), dict) else {}
        if task_tracking:
            task_tracking["next_recommended_step"] = f"Start implementation for {next_milestone}"
            payload["task_tracking"] = task_tracking
        return

    if reason_code == "git_changes_need_review":
        payload["next_step_decision"] = "review_git"
        payload["decision_reason"] = "Git evidence indicates medium/high change risk, so review changes before continuing implementation."
        return

    if status == "in_progress" and _as_text(payload.get("next_step_decision"), fallback="") == "continue_implementation":
        payload["next_step_decision"] = "complete_current_task"
        payload["decision_reason"] = "Active task is in progress with no completion evidence yet; complete the current recommended step first."
        return

    if status == "unknown":
        payload["decision_reason"] = f"{_as_text(payload.get('decision_reason'), fallback='') or 'No decision reason available'} Context strength is low, so task completion status remains unknown."

    if reason_code == "stale_project_memory":
        payload["decision_reason"] = f"{payload['decision_reason']} Runtime progress remains source of truth because AGENTS milestone is stale."


def _write_task_completion(assessment: dict[str, Any], payload: dict[str, Any]) -> None:
    status = _as_text(assessment.get("task_completion_status"), fallback="unknown")
    normalized_status = status if status in VALID_TASK_COMPLETION_STATUSES else "unknown"
    reason_code = _as_text(assessment.get("reason_code"), fallback="weak_context")
    normalized_reason_code = reason_code if reason_code in VALID_REASON_CODES else "weak_context"

    evidence = assessment.get("completion_evidence") if isinstance(assessment.get("completion_evidence"), list) else []
    evidence_source = _as_text(assessment.get("evidence_source"), fallback="none")
    evidence_timestamp = _as_text(
        assessment.get("evidence_timestamp"),
        fallback=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    evidence_confidence_raw = assessment.get("evidence_confidence", 0.0)
    try:
        evidence_confidence = float(evidence_confidence_raw)
    except (TypeError, ValueError):
        evidence_confidence = 0.0
    evidence_confidence = max(0.0, min(1.0, evidence_confidence))

    progress = payload.get("project_progress") if isinstance(payload.get("project_progress"), dict) else {}
    record = {
        "task_completion_status": normalized_status,
        "reason_code": normalized_reason_code,
        "evidence_source": evidence_source,
        "evidence_timestamp": evidence_timestamp,
        "evidence_confidence": evidence_confidence,
        "completion_evidence": [str(item).strip() for item in evidence if str(item).strip()],
        "current_milestone": _as_text(progress.get("current_milestone"), fallback=""),
        "last_completed_milestone": _as_text(progress.get("last_completed_milestone"), fallback=""),
    }

    previous = _safe_load_json(TASK_COMPLETION_PATH)
    if isinstance(previous.get("recent_validation"), dict):
        record["recent_validation"] = previous.get("recent_validation")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    TASK_COMPLETION_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_text(value: Any, fallback: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text if text else fallback


def _run_script(script_path: Path, args: list[str] | None = None) -> dict[str, Any]:
    command = [sys.executable, str(script_path), *(args or [])]
    if not script_path.exists() or not script_path.is_file():
        warning = f"Warning: Script not found: {script_path}"
        print(warning)
        return {
            "script": script_path.name,
            "ok": False,
            "returncode": None,
            "warning": warning,
        }

    result = subprocess.run(
        command,
        cwd=str(BASE_DIR),
        check=False,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        warning = f"Warning: {script_path.name} exited with code {result.returncode}."
        print(warning)
        stderr = (result.stderr or "").strip()
        if stderr:
            print(stderr)
    return {
        "script": script_path.name,
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
    }


def _build_demo_payload(script_results: list[dict[str, Any]], resume_payload: dict[str, Any], speak_enabled: bool) -> dict[str, Any]:
    guidance = resume_payload.get("guidance_priority", {}) if isinstance(resume_payload.get("guidance_priority"), dict) else {}
    return {
        "speak_enabled": speak_enabled,
        "script_results": [
            {
                "script": item.get("script", ""),
                "ok": bool(item.get("ok", False)),
                "returncode": item.get("returncode"),
            }
            for item in script_results
        ],
        "guidance": {
            "headline": _as_text(guidance.get("headline"), fallback="Resume guidance"),
            "recommended_action": _as_text(
                guidance.get("recommended_action"),
                fallback=_as_text(resume_payload.get("recommended_next_action"), fallback="Continue current implementation."),
            ),
            "level": _as_text(guidance.get("level"), fallback="info"),
        },
        "current_file": _as_text(resume_payload.get("current_file"), fallback=""),
        "display_mock_path": str(DISPLAY_MOCK_PATH),
        "resume_output_path": str(RESUME_NOW_OUTPUT),
    }


def _print_demo_summary(payload: dict[str, Any]) -> None:
    guidance = payload.get("guidance", {}) if isinstance(payload.get("guidance"), dict) else {}
    print("GLASSES DEMO")
    print()
    print(f"Guidance headline: {_as_text(guidance.get('headline'), fallback='Resume guidance')}")
    print(f"Recommended action: {_as_text(guidance.get('recommended_action'), fallback='Continue current implementation.')}")
    print(f"Guidance level: {_as_text(guidance.get('level'), fallback='info')}")
    print(f"Current file: {_as_text(payload.get('current_file'), fallback='')}")
    print(f"Display mock path: {_as_text(payload.get('display_mock_path'), fallback='')}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate demo guidance payloads for glasses display testing.")
    parser.add_argument("--speak", action="store_true", help="Enable spoken guidance in default mode.")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Select highest-priority guidance from available real sources.",
    )
    parser.add_argument(
        "--use-real-git",
        action="store_true",
        help="Use guidance from results/coding_context_pack.json when git risk is medium/high.",
    )
    parser.add_argument(
        "--use-real-errors",
        action="store_true",
        help="Use guidance from results/terminal_error_context.json when a terminal error is present.",
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIO_GUIDANCE.keys()),
        help="Generate deterministic resume payload for a specific scenario.",
    )
    return parser.parse_args()


def _build_scenario_resume_payload(scenario: str) -> dict[str, Any]:
    guidance = SCENARIO_GUIDANCE[scenario]
    return {
        "recommended_next_action": guidance["recommended_action"],
        "current_file": "",
        "guidance_priority": {
            "level": guidance["level"],
            "headline": guidance["headline"],
            "recommended_action": guidance["recommended_action"],
        },
    }


def _active_file_defaults() -> dict[str, Any]:
    return {
        "active_file_name": "",
        "active_file_path": "",
        "language_id": "",
        "is_dirty": False,
        "event_type": "",
    }


def _load_active_file_context() -> tuple[bool, dict[str, Any]]:
    fusion_payload = _safe_load_json(CONTEXT_FUSION_OUTPUT)
    if not fusion_payload:
        return False, _active_file_defaults()

    if not bool(fusion_payload.get("active_file_available", False)):
        return False, _active_file_defaults()

    active_file = fusion_payload.get("active_file") if isinstance(fusion_payload.get("active_file"), dict) else {}
    if not active_file:
        return False, _active_file_defaults()

    return True, {
        "active_file_name": _as_text(active_file.get("active_file_name"), fallback=""),
        "active_file_path": _as_text(active_file.get("active_file_path"), fallback=""),
        "language_id": _as_text(active_file.get("language_id"), fallback=""),
        "is_dirty": bool(active_file.get("is_dirty", False)),
        "event_type": _as_text(active_file.get("event_type"), fallback=""),
    }


def _milestone_index(name: str) -> int:
    lowered = name.strip().lower()
    for index, milestone in enumerate(MILESTONE_SEQUENCE):
        if milestone.lower() == lowered:
            return index
    return -1


def _normalize_milestone_name(name: str) -> str:
    text = _as_text(name, fallback="")
    if not text:
        return ""

    exact_index = _milestone_index(text)
    if exact_index >= 0:
        return MILESTONE_SEQUENCE[exact_index]

    lowered = text.lower()
    for milestone in MILESTONE_SEQUENCE:
        if lowered in milestone.lower() or milestone.lower() in lowered:
            return milestone

    return ""


def _load_project_progress(project_memory: dict[str, str]) -> dict[str, str]:
    stored = _safe_load_json(PROJECT_PROGRESS_PATH)

    stored_current = _normalize_milestone_name(_as_text(stored.get("current_milestone"), fallback=""))
    memory_current = _normalize_milestone_name(_as_text(project_memory.get("milestone"), fallback=""))

    current = DEFAULT_CURRENT_MILESTONE
    current_index = _milestone_index(current)

    if stored_current:
        current = stored_current
        current_index = _milestone_index(current)
    elif memory_current:
        current = memory_current
        current_index = _milestone_index(current)

    if current_index < 0:
        current = DEFAULT_CURRENT_MILESTONE
        current_index = _milestone_index(current)

    last_completed = MILESTONE_SEQUENCE[current_index - 1] if current_index > 0 else ""
    suggested_next = MILESTONE_SEQUENCE[current_index + 1] if current_index < len(MILESTONE_SEQUENCE) - 1 else current

    progress = {
        "last_completed_milestone": last_completed,
        "current_milestone": current,
        "suggested_next_milestone": suggested_next,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    PROJECT_PROGRESS_PATH.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
    return progress


def _build_task_tracking(active_file_name: str, current_focus: str) -> dict[str, Any]:
    mapping = TASK_TRACKING_MAP.get(active_file_name, {})

    task_tracking = {
        "current_task": _as_text(mapping.get("current_task"), fallback=current_focus or "General development"),
        "last_completed_step": _as_text(
            mapping.get("last_completed_step"),
            fallback="Active file context and guidance payload integrated",
        ),
        "next_recommended_step": _as_text(
            mapping.get("next_recommended_step"),
            fallback="Validate the current payload and continue implementation",
        ),
        "task_confidence": float(mapping.get("task_confidence", 0.75) or 0.75),
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    TASK_STATE_PATH.write_text(json.dumps(task_tracking, ensure_ascii=False, indent=2), encoding="utf-8")
    return task_tracking


def _compute_decision_confidence(payload: dict[str, Any], decision_name: str) -> tuple[float, list[str]]:
    factors: list[str] = []

    guidance = payload.get("guidance_priority") if isinstance(payload.get("guidance_priority"), dict) else {}
    guidance_source = _as_text(guidance.get("source"), fallback="").lower()
    has_terminal_error = bool(payload.get("has_terminal_error", False)) or "terminal_error" in guidance_source

    active_file = payload.get("active_file") if isinstance(payload.get("active_file"), dict) else {}
    active_file_name = _as_text(active_file.get("active_file_name"), fallback="")
    has_active_file = bool(active_file_name)
    if has_active_file:
        factors.append("Active file detected")

    if has_terminal_error:
        factors.append("Terminal error detected")
        return 0.97, factors
    factors.append("No terminal errors")

    task_tracking = payload.get("task_tracking") if isinstance(payload.get("task_tracking"), dict) else {}
    has_task = bool(_as_text(task_tracking.get("current_task"), fallback=""))
    has_task_steps = bool(_as_text(task_tracking.get("last_completed_step"), fallback="")) and bool(
        _as_text(task_tracking.get("next_recommended_step"), fallback="")
    )
    if has_task:
        factors.append("Current task identified")
    if has_task_steps:
        factors.append("Clear task continuity")

    architecture_context = payload.get("architecture_context") if isinstance(payload.get("architecture_context"), dict) else {}
    has_architecture = bool(_as_text(architecture_context.get("current_component"), fallback=""))
    if has_architecture:
        factors.append("Architecture context available")

    prompt_mode = _as_text(payload.get("prompt_mode"), fallback="")
    if prompt_mode:
        factors.append("Prompt mode identified")

    git_priority = "git_intelligence" in guidance_source
    conflicting_signal = git_priority and decision_name not in {"review_git"}
    if conflicting_signal:
        factors.append("Conflicting signals detected")
    else:
        factors.append("No conflicting signals")

    score = 0.52
    if has_active_file:
        score += 0.12
    if has_task:
        score += 0.1
    if has_task_steps:
        score += 0.08
    if has_architecture:
        score += 0.08
    if prompt_mode:
        score += 0.07
    if not conflicting_signal:
        score += 0.08

    score = max(0.0, min(1.0, score))
    return score, factors


def _select_recommended_prompt_type(payload: dict[str, Any]) -> str:
    active_file = payload.get("active_file") if isinstance(payload.get("active_file"), dict) else {}
    active_file_name = _as_text(active_file.get("active_file_name"), fallback="").lower()

    if active_file_name == "context_fusion.py":
        return "architecture"
    if active_file_name == "api.py":
        return "implementation"
    if active_file_name == "glasses_display_mock.html":
        return "validation"

    decision = _as_text(payload.get("next_step_decision"), fallback="")
    if decision == "review_git":
        return "git_review"

    return "implementation"


def _with_active_file_context(resume_payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(resume_payload) if isinstance(resume_payload, dict) else {}
    fusion_payload = _safe_load_json(CONTEXT_FUSION_OUTPUT)
    active_file_available, active_file = _load_active_file_context()

    payload["active_file_available"] = active_file_available
    payload["active_file"] = active_file

    if active_file_available and _as_text(active_file.get("active_file_name"), fallback=""):
        payload["current_file"] = _as_text(active_file.get("active_file_name"), fallback="")

    payload["active_file_display"] = {
        "current_file": f"Current file: {_as_text(active_file.get('active_file_name'), fallback='unavailable') if active_file_available else 'unavailable'}",
        "language": f"Language: {_as_text(active_file.get('language_id'), fallback='unknown') if active_file_available else 'unknown'}",
        "dirty": f"Dirty: {bool(active_file.get('is_dirty', False)) if active_file_available else False}",
    }

    file_name = _as_text(active_file.get("active_file_name"), fallback="") if active_file_available else ""
    file_focus = FILE_FOCUS_GUIDANCE.get(file_name, GENERIC_FILE_FOCUS)
    payload["current_focus"] = _as_text(file_focus.get("current_focus"), fallback=GENERIC_FILE_FOCUS["current_focus"])
    payload["task_tracking"] = _build_task_tracking(file_name, payload["current_focus"])

    checks = file_focus.get("suggested_checks") if isinstance(file_focus.get("suggested_checks"), list) else []
    payload["suggested_checks"] = [str(item).strip() for item in checks if str(item).strip()]
    if not payload["suggested_checks"]:
        payload["suggested_checks"] = list(GENERIC_FILE_FOCUS["suggested_checks"])

    payload["workflow_evidence"] = fusion_payload.get("workflow_evidence") if isinstance(fusion_payload.get("workflow_evidence"), dict) else {}
    payload["signal_freshness"] = fusion_payload.get("signal_freshness") if isinstance(fusion_payload.get("signal_freshness"), dict) else {}
    payload["validation_evidence_available"] = bool(fusion_payload.get("validation_evidence_available", False))
    payload["terminal_evidence_available"] = bool(fusion_payload.get("terminal_evidence_available", False))
    payload["git_evidence_available"] = bool(fusion_payload.get("git_evidence_available", False))

    project_memory = _load_project_memory_summary()
    payload["project_progress"] = _load_project_progress(project_memory)
    payload["architecture_context"] = _build_architecture_context(payload)

    payload["prompt_mode"] = _select_prompt_mode(payload)
    decision, reason = _select_next_step_decision(payload)
    payload["next_step_decision"] = decision
    payload["decision_reason"] = reason

    completion_assessment = _detect_task_completion(payload, project_memory)
    completion_status = _as_text(completion_assessment.get("task_completion_status"), fallback="unknown")
    completion_evidence = completion_assessment.get("completion_evidence") if isinstance(completion_assessment.get("completion_evidence"), list) else []
    payload["project_progress"] = _advance_project_progress_if_completed(payload["project_progress"], completion_status, completion_evidence)
    completion_assessment["completion_evidence"] = completion_evidence
    payload.update(
        {
            "task_completion_status": completion_status,
            "completion_evidence": completion_evidence,
            "reason_code": _as_text(completion_assessment.get("reason_code"), fallback="weak_context"),
            "evidence_source": _as_text(completion_assessment.get("evidence_source"), fallback="none"),
            "evidence_timestamp": _as_text(completion_assessment.get("evidence_timestamp"), fallback=""),
            "evidence_confidence": float(completion_assessment.get("evidence_confidence", 0.0) or 0.0),
        }
    )
    _apply_completion_to_decision(payload, completion_assessment)

    confidence, factors = _compute_decision_confidence(payload, _as_text(payload.get("next_step_decision"), fallback=decision))
    payload["decision_confidence"] = confidence
    payload["decision_factors"] = factors
    payload["recommended_prompt_type"] = _select_recommended_prompt_type(payload)
    payload["prompt_library"] = _build_prompt_library(payload, project_memory)
    payload["actionable_prompt"] = _build_actionable_prompt(payload, project_memory)

    chatgpt_context_payload = _build_chatgpt_context_payload(payload, project_memory)
    guidance_response, guidance_source, openai_debug = _generate_guidance_response(payload, chatgpt_context_payload)
    payload["guidance_response"] = guidance_response
    payload["guidance_source"] = guidance_source
    payload["recommended_next_action"] = _as_text(
        guidance_response.get("recommended_next_step"),
        fallback=_as_text(payload.get("recommended_next_action"), fallback="Continue current implementation."),
    )
    guidance_priority = payload.get("guidance_priority") if isinstance(payload.get("guidance_priority"), dict) else {}
    if guidance_priority:
        guidance_priority["headline"] = _as_text(guidance_priority.get("headline"), fallback="ChatGPT Guidance")
        guidance_priority["recommended_action"] = payload["recommended_next_action"]
        guidance_priority["message"] = _as_text(guidance_response.get("summary"), fallback="Guidance generated from mock ChatGPT layer")
        payload["guidance_priority"] = guidance_priority

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CHATGPT_CONTEXT_PAYLOAD_PATH.write_text(json.dumps(chatgpt_context_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    GUIDANCE_RESPONSE_PATH.write_text(json.dumps(guidance_response, ensure_ascii=False, indent=2), encoding="utf-8")
    CHATGPT_REQUEST_PATH.write_text(json.dumps(openai_debug.get("request", {}), ensure_ascii=False, indent=2), encoding="utf-8")
    CHATGPT_RESPONSE_RAW_PATH.write_text(json.dumps(openai_debug.get("response", {}), ensure_ascii=False, indent=2), encoding="utf-8")

    payload["ai_prompt"] = _build_mode_prompt(payload["prompt_mode"], payload, project_memory)
    _write_task_completion(completion_assessment, payload)

    return payload


def _build_terminal_error_resume_payload() -> dict[str, Any] | None:
    payload = _safe_load_json(TERMINAL_ERROR_OUTPUT)
    if not payload or payload.get("has_terminal_error") is not True:
        return None

    guidance = payload.get("guidance_priority")
    if not isinstance(guidance, dict):
        return None

    level = _as_text(guidance.get("level"), fallback="critical")
    headline = _as_text(guidance.get("headline"), fallback="Resolve Error First")
    recommended_action = _as_text(
        guidance.get("recommended_action"),
        fallback=_as_text(payload.get("recommended_action"), fallback="Review and resolve the current error before continuing."),
    )

    return {
        "has_terminal_error": True,
        "recommended_next_action": recommended_action,
        "current_file": "",
        "guidance_priority": {
            "level": level,
            "source": "terminal_error_context",
            "headline": headline,
            "recommended_action": recommended_action,
        },
    }


def _build_git_intelligence_resume_payload() -> dict[str, Any] | None:
    payload = _safe_load_json(CODING_CONTEXT_OUTPUT)
    git_info = payload.get("git_intelligence") if isinstance(payload, dict) else None
    if not isinstance(git_info, dict):
        return None

    risk_level = _as_text(git_info.get("risk_level")).lower()
    if risk_level not in {"medium", "high"}:
        return None

    recommended_action = _as_text(
        git_info.get("recommendation"),
        fallback="Review your git changes before continuing.",
    )

    return {
        "recommended_next_action": recommended_action,
        "current_file": "",
        "guidance_priority": {
            "level": "high",
            "source": "git_intelligence",
            "headline": "Review Git Changes",
            "recommended_action": recommended_action,
        },
    }


def _guidance_level(payload: dict[str, Any]) -> str:
    guidance = payload.get("guidance_priority") if isinstance(payload, dict) else None
    if not isinstance(guidance, dict):
        return "info"
    return _as_text(guidance.get("level"), fallback="info").lower()


def _guidance_rank(payload: dict[str, Any]) -> int:
    return GUIDANCE_PRIORITY_RANK.get(_guidance_level(payload), 1)


def main() -> None:
    args = _parse_args()
    speak_enabled = bool(args.speak)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    _run_script(CONTEXT_FUSION_SCRIPT)

    if args.auto:
        candidates: list[dict[str, Any]] = []

        terminal_resume_payload = _build_terminal_error_resume_payload()
        if terminal_resume_payload:
            terminal_guidance = terminal_resume_payload.get("guidance_priority", {})
            if isinstance(terminal_guidance, dict):
                terminal_guidance["level"] = "critical"
                terminal_guidance["source"] = "terminal_error_context"
            candidates.append(
                {
                    "source": "terminal_error_context",
                    "script": "terminal_error_context",
                    "resume_payload": terminal_resume_payload,
                }
            )

        git_resume_payload = _build_git_intelligence_resume_payload()
        if git_resume_payload:
            candidates.append(
                {
                    "source": "git_intelligence",
                    "script": "git_intelligence",
                    "resume_payload": git_resume_payload,
                }
            )

        if args.scenario:
            scenario_resume_payload = _build_scenario_resume_payload(args.scenario)
            candidates.append(
                {
                    "source": "scenario",
                    "script": f"scenario:{args.scenario}",
                    "resume_payload": scenario_resume_payload,
                }
            )

        if candidates:
            selected = max(candidates, key=lambda item: _guidance_rank(item["resume_payload"]))
            selected_resume_payload = _with_active_file_context(selected["resume_payload"])

            RESUME_NOW_OUTPUT.write_text(json.dumps(selected_resume_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            demo_payload = _build_demo_payload(
                script_results=[
                    {
                        "script": selected["script"],
                        "ok": True,
                        "returncode": 0,
                    }
                ],
                resume_payload=selected_resume_payload,
                speak_enabled=speak_enabled,
            )
            demo_payload["source"] = selected["source"]
            OUTPUT_PATH.write_text(json.dumps(demo_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            print(f"Selected Source: {selected['source']}")
            _print_demo_summary(demo_payload)
            print()
            print(f"Wrote: {RESUME_NOW_OUTPUT}")
            print(f"Wrote: {OUTPUT_PATH}")
            return

        print("Source: fallback")

    if args.use_real_git:
        real_git_resume_payload = _build_git_intelligence_resume_payload()
        if real_git_resume_payload:
            real_git_resume_payload = _with_active_file_context(real_git_resume_payload)
            RESUME_NOW_OUTPUT.write_text(json.dumps(real_git_resume_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            demo_payload = _build_demo_payload(
                script_results=[
                    {
                        "script": "git_intelligence",
                        "ok": True,
                        "returncode": 0,
                    }
                ],
                resume_payload=real_git_resume_payload,
                speak_enabled=speak_enabled,
            )
            demo_payload["source"] = "git_intelligence"
            OUTPUT_PATH.write_text(json.dumps(demo_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            print("Source: git_intelligence")
            _print_demo_summary(demo_payload)
            print()
            print(f"Wrote: {RESUME_NOW_OUTPUT}")
            print(f"Wrote: {OUTPUT_PATH}")
            return

        print("Source: fallback")

    if args.use_real_errors:
        real_error_resume_payload = _build_terminal_error_resume_payload()
        if real_error_resume_payload:
            real_error_resume_payload = _with_active_file_context(real_error_resume_payload)
            RESUME_NOW_OUTPUT.write_text(json.dumps(real_error_resume_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            demo_payload = _build_demo_payload(
                script_results=[
                    {
                        "script": "terminal_error_context",
                        "ok": True,
                        "returncode": 0,
                    }
                ],
                resume_payload=real_error_resume_payload,
                speak_enabled=speak_enabled,
            )
            demo_payload["source"] = "terminal_error_context"
            OUTPUT_PATH.write_text(json.dumps(demo_payload, ensure_ascii=False, indent=2), encoding="utf-8")

            print("Source: terminal_error_context")
            _print_demo_summary(demo_payload)
            print()
            print(f"Wrote: {RESUME_NOW_OUTPUT}")
            print(f"Wrote: {OUTPUT_PATH}")
            return

        print("Source: fallback")

    if args.scenario:
        resume_payload = _with_active_file_context(_build_scenario_resume_payload(args.scenario))
        RESUME_NOW_OUTPUT.write_text(json.dumps(resume_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        demo_payload = _build_demo_payload(
            script_results=[
                {
                    "script": f"scenario:{args.scenario}",
                    "ok": True,
                    "returncode": 0,
                }
            ],
            resume_payload=resume_payload,
            speak_enabled=speak_enabled,
        )
        demo_payload["scenario"] = args.scenario
        OUTPUT_PATH.write_text(json.dumps(demo_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"GLASSES DEMO (scenario: {args.scenario})")
        _print_demo_summary(demo_payload)
        print()
        print(f"Wrote: {RESUME_NOW_OUTPUT}")
        print(f"Wrote: {OUTPUT_PATH}")
        return

    script_results = []
    script_results.append(_run_script(CODING_CONTEXT_SCRIPT))
    script_results.append(_run_script(RESUME_NOW_SCRIPT, ["--speak"] if speak_enabled else []))

    resume_payload = _safe_load_json(RESUME_NOW_OUTPUT)
    if not resume_payload:
        print(f"Warning: Could not load resume output from {RESUME_NOW_OUTPUT}")
    else:
        resume_payload = _with_active_file_context(resume_payload)
        RESUME_NOW_OUTPUT.write_text(json.dumps(resume_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    demo_payload = _build_demo_payload(script_results, resume_payload, speak_enabled)
    OUTPUT_PATH.write_text(json.dumps(demo_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    _print_demo_summary(demo_payload)
    print()
    print(f"Wrote: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
