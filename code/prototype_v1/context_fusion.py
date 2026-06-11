from __future__ import annotations

import ast
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from active_editor_context import build_active_editor_context, write_active_editor_context
except Exception:
    build_active_editor_context = None  # type: ignore[assignment]
    write_active_editor_context = None  # type: ignore[assignment]


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent.parent
RESULTS_DIR = BASE_DIR / "results"
TERMINAL_ERROR_PATH = RESULTS_DIR / "terminal_error_context.json"
CODING_CONTEXT_PATH = RESULTS_DIR / "coding_context_pack.json"
SESSION_SNAPSHOT_PATH = RESULTS_DIR / "coding_session_snapshot.json"
ACTIVE_EDITOR_CONTEXT_PATH = RESULTS_DIR / "active_editor_context.json"
ACTIVE_EDITOR_STATE_PATH = RESULTS_DIR / "active_editor_state.json"
OUTPUT_PATH = RESULTS_DIR / "context_fusion.json"


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _as_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_text(value: Any, fallback: str = "unknown") -> str:
    text = str(value).strip() if value is not None else ""
    return text if text else fallback


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _signal_freshness_seconds(path: Path) -> int | None:
    if not path.exists() or not path.is_file():
        return None

    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None

    delta = datetime.now(timezone.utc) - modified
    return max(0, int(delta.total_seconds()))


def _signal_freshness_payload() -> dict[str, Any]:
    return {
        "terminal_error_seconds": _signal_freshness_seconds(TERMINAL_ERROR_PATH),
        "coding_context_seconds": _signal_freshness_seconds(CODING_CONTEXT_PATH),
        "snapshot_seconds": _signal_freshness_seconds(SESSION_SNAPSHOT_PATH),
        "active_editor_seconds": _signal_freshness_seconds(ACTIVE_EDITOR_CONTEXT_PATH),
        "context_fusion_generated_at": _utc_now_iso(),
    }


def _workflow_evidence_payload(
    selected_source: str,
    terminal_error: dict[str, Any],
    coding_context: dict[str, Any],
    snapshot: dict[str, Any],
) -> tuple[dict[str, Any], bool, bool, bool]:
    terminal_evidence_available = bool(terminal_error) and bool(terminal_error.get("has_terminal_error", False))

    git_intelligence = coding_context.get("git_intelligence") if isinstance(coding_context.get("git_intelligence"), dict) else {}
    git_risk = _as_text(git_intelligence.get("risk_level"), "low").lower()
    git_evidence_available = git_risk in {"medium", "high"}

    progress_context = coding_context.get("progress_context") if isinstance(coding_context.get("progress_context"), dict) else {}
    milestone_context = coding_context.get("milestone_context") if isinstance(coding_context.get("milestone_context"), dict) else {}
    validation_evidence_available = bool(progress_context.get("progress_detected", False)) or bool(
        milestone_context.get("completed_milestones")
    )

    workflow_evidence = {
        "selected_source": selected_source,
        "source_reason": {
            "terminal_error_context": "Terminal error signal took priority.",
            "coding_context_pack": "Git risk signal took priority.",
            "snapshot_context": "Working-tree change signal took priority.",
            "fallback": "No higher-priority signal available.",
        }.get(selected_source, "No higher-priority signal available."),
        "snapshot_modified_files": _as_int(snapshot.get("modified_files"), 0),
        "snapshot_staged_files": _as_int(snapshot.get("staged_files"), 0),
        "git_risk_level": git_risk,
        "validation_summary": _as_text(progress_context.get("reason"), fallback="No validation summary"),
    }
    return workflow_evidence, validation_evidence_available, terminal_evidence_available, git_evidence_available


def _default_guidance(source: str, headline: str, message: str, recommended_action: str, level: str = "info") -> dict[str, str]:
    return {
        "level": level,
        "source": source,
        "headline": headline,
        "message": message,
        "recommended_action": recommended_action,
    }


def _load_terminal_error_context() -> dict[str, Any]:
    payload = _safe_load_json(TERMINAL_ERROR_PATH)
    if not payload:
        return {}

    guidance = payload.get("guidance_priority")
    if isinstance(guidance, dict):
        payload["guidance_priority"] = guidance
    else:
        payload["guidance_priority"] = _default_guidance(
            source="terminal_error_context",
            headline="No Terminal Error",
            message="No terminal error context is available.",
            recommended_action="Continue current implementation.",
        )
    return payload


def _load_coding_context() -> dict[str, Any]:
    payload = _safe_load_json(CODING_CONTEXT_PATH)
    if not payload:
        return {}
    return payload


def _load_snapshot_context() -> dict[str, Any]:
    payload = _safe_load_json(SESSION_SNAPSHOT_PATH)
    if not payload:
        return {}
    return payload


def _load_active_editor_context() -> dict[str, Any]:
    payload = _safe_load_json(ACTIVE_EDITOR_CONTEXT_PATH)
    if not payload:
        return {}
    return payload


def _to_repo_relative(path_text: Any) -> str:
    raw = str(path_text or "").strip()
    if not raw:
        return ""

    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        except (OSError, ValueError):
            return candidate.name

    return Path(raw).as_posix()


def _git_risk_context(coding_context: dict[str, Any], active_file: dict[str, Any]) -> dict[str, Any]:
    git_info = coding_context.get("git_intelligence") if isinstance(coding_context.get("git_intelligence"), dict) else {}
    risk_level = _as_text(git_info.get("risk_level"), "low").lower()
    recommendation = _as_text(git_info.get("recommendation"), "Review git state")
    reason = _as_text(git_info.get("reason"), "Git changes require attention.")
    next_command = _as_text(git_info.get("next_command"), "")
    changed_files = coding_context.get("changed_files") if isinstance(coding_context.get("changed_files"), list) else []

    active_file_name = _as_text(active_file.get("active_file_name"), "")
    active_file_path = _to_repo_relative(active_file.get("active_file_path"))

    active_file_involved = False
    for item in changed_files:
        if not isinstance(item, dict):
            continue
        changed_path = _to_repo_relative(item.get("path"))
        if not changed_path:
            continue
        if active_file_path and changed_path == active_file_path:
            active_file_involved = True
            break
        if active_file_name and Path(changed_path).name == active_file_name:
            active_file_involved = True
            break

    blocking = risk_level == "severe" or (risk_level == "high" and active_file_involved)
    advisory = risk_level in {"low", "medium", "high", "severe"} and bool(recommendation)

    return {
        "risk_level": risk_level,
        "recommendation": recommendation,
        "reason": reason,
        "next_command": next_command,
        "active_file_involved": active_file_involved,
        "blocking": blocking,
        "advisory": advisory,
    }


def _run_git_command(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(REPO_ROOT),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""

    if result.returncode != 0:
        return ""
    return result.stdout or ""


def _parse_changed_lines_from_diff(diff_text: str) -> list[int]:
    changed_lines: set[int] = set()
    hunk_pattern = re.compile(r"@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@")

    for line in diff_text.splitlines():
        match = hunk_pattern.search(line)
        if not match:
            continue

        start = _as_int(match.group(1), 0)
        count = _as_int(match.group(2), 1)
        if start <= 0:
            continue
        if count <= 0:
            changed_lines.add(start)
            continue

        for item in range(start, start + count):
            changed_lines.add(item)

    return sorted(changed_lines)


def _change_context_payload(active_file: dict[str, Any]) -> dict[str, Any]:
    active_file_name = _as_text(active_file.get("active_file_name"), fallback="")
    active_file_path = _as_text(active_file.get("active_file_path"), fallback="")

    context = {
        "file_status": "clean",
        "changed_lines": [],
        "recently_modified": False,
        "change_confidence": 0.0,
    }
    if not active_file_name and not active_file_path:
        return context

    relative_path = _to_repo_relative(active_file_path or active_file_name)
    if not relative_path:
        relative_path = active_file_name
    if not relative_path:
        return context

    status_output = _run_git_command(["status", "--porcelain", "--", relative_path])
    status_lines = [line for line in status_output.splitlines() if line.strip()]
    if not status_lines:
        context["change_confidence"] = 0.9
        return context

    staged = False
    modified = False
    untracked = False
    for line in status_lines:
        code = line[:2]
        if code == "??":
            untracked = True
            continue
        index_state = code[:1]
        worktree_state = code[1:2]
        if index_state and index_state != " ":
            staged = True
        if worktree_state and worktree_state != " ":
            modified = True

    if staged:
        file_status = "staged"
    elif modified:
        file_status = "modified"
    elif untracked:
        file_status = "untracked"
    else:
        file_status = "clean"

    changed_lines: set[int] = set()
    if file_status in {"modified", "staged"}:
        staged_diff = _run_git_command(["diff", "--cached", "-U0", "--", relative_path])
        unstaged_diff = _run_git_command(["diff", "-U0", "--", relative_path])
        for item in _parse_changed_lines_from_diff(staged_diff):
            changed_lines.add(item)
        for item in _parse_changed_lines_from_diff(unstaged_diff):
            changed_lines.add(item)

    sorted_lines = sorted(changed_lines)[:250]
    context["file_status"] = file_status
    context["changed_lines"] = sorted_lines
    context["recently_modified"] = file_status != "clean"
    if file_status == "clean":
        context["change_confidence"] = 0.9
    elif file_status in {"modified", "staged"} and sorted_lines:
        context["change_confidence"] = 0.92
    elif file_status == "untracked":
        context["change_confidence"] = 0.82
    else:
        context["change_confidence"] = 0.7

    return context


def _refresh_active_editor_context() -> None:
    """Refresh active_editor_context.json from active_editor_state.json when helpers are importable."""
    if not callable(build_active_editor_context) or not callable(write_active_editor_context):
        return

    try:
        context = build_active_editor_context()
        if isinstance(context, dict):
            write_active_editor_context(context)
    except Exception:
        # Context fusion must remain resilient even if active editor refresh fails.
        return


def _active_file_payload(active_editor_context: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    if not active_editor_context:
        return False, {
            "active_file_name": "",
            "active_file_path": "",
            "language_id": "",
            "is_dirty": False,
            "event_type": "",
        }

    return True, {
        "active_file_name": _as_text(active_editor_context.get("active_file_name"), ""),
        "active_file_path": _as_text(active_editor_context.get("active_file_path"), ""),
        "language_id": _as_text(active_editor_context.get("language_id"), ""),
        "is_dirty": bool(active_editor_context.get("is_dirty", False)),
        "event_type": _as_text(active_editor_context.get("event_type"), ""),
    }


def _line_from_active_editor_context(active_editor_context: dict[str, Any], active_editor_state: dict[str, Any]) -> int:
    keys = (
        "line_number",
        "cursor_line",
        "active_line",
        "selection_start_line",
        "line",
        "position_line",
    )

    for source in (active_editor_context, active_editor_state):
        for key in keys:
            if key in source:
                value = _as_int(source.get(key), 0)
                if value > 0:
                    return value
    return 0


def _safe_read_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _python_symbol_context(source: str, line_number: int) -> tuple[str, str, float]:
    if not source.strip():
        return "", "", 0.0

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "", "", 0.1

    symbols: list[dict[str, Any]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.class_stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> Any:
            start = int(getattr(node, "lineno", 0) or 0)
            end = int(getattr(node, "end_lineno", start) or start)
            symbols.append({
                "kind": "class",
                "name": node.name,
                "start": start,
                "end": end,
                "class": node.name,
            })
            self.class_stack.append(node.name)
            self.generic_visit(node)
            self.class_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
            start = int(getattr(node, "lineno", 0) or 0)
            end = int(getattr(node, "end_lineno", start) or start)
            symbols.append({
                "kind": "function",
                "name": node.name,
                "start": start,
                "end": end,
                "class": self.class_stack[-1] if self.class_stack else "",
            })
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
            start = int(getattr(node, "lineno", 0) or 0)
            end = int(getattr(node, "end_lineno", start) or start)
            symbols.append({
                "kind": "function",
                "name": node.name,
                "start": start,
                "end": end,
                "class": self.class_stack[-1] if self.class_stack else "",
            })
            self.generic_visit(node)

    Visitor().visit(tree)
    if not symbols:
        return "", "", 0.1

    if line_number > 0:
        containing = [
            item
            for item in symbols
            if int(item.get("start", 0)) <= line_number <= int(item.get("end", 0))
        ]
        if containing:
            containing.sort(key=lambda item: (int(item.get("end", 0)) - int(item.get("start", 0)), 0 if item.get("kind") == "function" else 1))
            best = containing[0]
            active_function = f"{_as_text(best.get('name'), '')}()" if _as_text(best.get("kind"), "") == "function" else ""
            active_class = _as_text(best.get("class"), "") if _as_text(best.get("kind"), "") == "function" else _as_text(best.get("name"), "")
            return active_function, active_class, 0.95

        symbols.sort(key=lambda item: abs(line_number - int(item.get("start", 0))))
        nearest = symbols[0]
        active_function = f"{_as_text(nearest.get('name'), '')}()" if _as_text(nearest.get("kind"), "") == "function" else ""
        active_class = _as_text(nearest.get("class"), "") if _as_text(nearest.get("kind"), "") == "function" else _as_text(nearest.get("name"), "")
        return active_function, active_class, 0.75

    functions = [item for item in symbols if _as_text(item.get("kind"), "") == "function"]
    if functions:
        first = sorted(functions, key=lambda item: int(item.get("start", 0)))[0]
        return f"{_as_text(first.get('name'), '')}()", _as_text(first.get("class"), ""), 0.45

    first_class = sorted(symbols, key=lambda item: int(item.get("start", 0)))[0]
    return "", _as_text(first_class.get("name"), ""), 0.35


def _html_or_js_symbol_context(source: str, line_number: int) -> tuple[str, str, float]:
    if not source.strip():
        return "", "", 0.0

    function_symbols: list[tuple[int, str]] = []
    section_symbols: list[tuple[int, str]] = []
    lines = source.splitlines()

    func_patterns = [
        re.compile(r"function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
        re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\([^)]*\)\s*=>"),
        re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*function\s*\("),
    ]
    section_pattern = re.compile(r"<(section|main|article|header|footer|nav|div)\b([^>]*)>", re.IGNORECASE)
    id_pattern = re.compile(r"id\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
    class_pattern = re.compile(r"class\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)

    for index, line in enumerate(lines, start=1):
        for pattern in func_patterns:
            match = pattern.search(line)
            if match:
                function_symbols.append((index, f"{match.group(1)}()"))
                break

        section_match = section_pattern.search(line)
        if section_match:
            attrs = section_match.group(2) or ""
            label = ""
            id_match = id_pattern.search(attrs)
            class_match = class_pattern.search(attrs)
            if id_match:
                label = f"#{id_match.group(1)}"
            elif class_match:
                label = f".{class_match.group(1).split()[0]}"
            else:
                label = section_match.group(1).lower()
            section_symbols.append((index, label))

    if line_number > 0 and function_symbols:
        nearest_func = sorted(function_symbols, key=lambda item: abs(line_number - item[0]))[0]
        nearest_class = ""
        if section_symbols:
            nearest_section = sorted(section_symbols, key=lambda item: abs(line_number - item[0]))[0]
            nearest_class = nearest_section[1]
        return nearest_func[1], nearest_class, 0.7

    if function_symbols:
        nearest_class = section_symbols[0][1] if section_symbols else ""
        return function_symbols[0][1], nearest_class, 0.45

    if section_symbols:
        return "", section_symbols[0][1], 0.35

    return "", "", 0.1


def _development_context_payload(
    active_file: dict[str, Any],
    active_editor_context: dict[str, Any],
    active_editor_state: dict[str, Any],
) -> dict[str, Any]:
    active_file_name = _as_text(active_file.get("active_file_name"), fallback="")
    active_file_path = _as_text(active_file.get("active_file_path"), fallback="")
    language = _as_text(active_file.get("language_id"), fallback="")
    line_number = _line_from_active_editor_context(active_editor_context, active_editor_state)

    context = {
        "active_file": active_file_name,
        "active_function": "",
        "active_class": "",
        "line_number": line_number,
        "language": language,
        "symbol_confidence": 0.0,
    }

    if not active_file_path:
        return context

    file_path = Path(active_file_path)
    if not file_path.is_absolute():
        file_path = (REPO_ROOT / file_path).resolve()

    source = _safe_read_text(file_path)
    if not source:
        return context

    active_function = ""
    active_class = ""
    confidence = 0.1

    language_lower = language.lower()
    suffix = file_path.suffix.lower()

    if language_lower == "python" or suffix == ".py":
        active_function, active_class, confidence = _python_symbol_context(source, line_number)
    elif language_lower in {"javascript", "typescript", "html"} or suffix in {".js", ".ts", ".html"}:
        active_function, active_class, confidence = _html_or_js_symbol_context(source, line_number)

    context["active_function"] = active_function
    context["active_class"] = active_class
    context["symbol_confidence"] = round(max(0.0, min(1.0, float(confidence))), 2)
    return context


def _snapshot_guidance(snapshot: dict[str, Any]) -> dict[str, str]:
    modified_files = _as_int(snapshot.get("modified_files"), 0)
    staged_files = _as_int(snapshot.get("staged_files"), 0)

    if modified_files > 0 or staged_files > 0:
        return _default_guidance(
            source="snapshot_context",
            headline="Review Working Tree",
            message="Local changes are present in the working tree.",
            recommended_action="Review the modified and staged files before continuing.",
            level="medium",
        )

    return _default_guidance(
        source="snapshot_context",
        headline="Continue Implementation",
        message="No local file churn is present in the snapshot.",
        recommended_action="Continue current implementation.",
        level="info",
    )


def _git_guidance(coding_context: dict[str, Any]) -> dict[str, str]:
    guidance = coding_context.get("guidance_priority")
    if isinstance(guidance, dict):
        return {
            "level": _as_text(guidance.get("level"), "info"),
            "source": _as_text(guidance.get("source"), "git_intelligence"),
            "headline": _as_text(guidance.get("headline"), "Review Git State"),
            "message": _as_text(guidance.get("message"), "Git risk requires attention."),
            "recommended_action": _as_text(guidance.get("recommended_action"), "Review git status before continuing."),
        }

    git_intelligence = coding_context.get("git_intelligence") if isinstance(coding_context.get("git_intelligence"), dict) else {}
    risk_level = _as_text(git_intelligence.get("risk_level"), "low").lower()
    recommendation = _as_text(git_intelligence.get("recommendation"), "Review Git State")
    reason = _as_text(git_intelligence.get("reason"), "Git changes require attention.")
    next_command = _as_text(git_intelligence.get("next_command"), "")

    recommended_action = recommendation
    if next_command:
        recommended_action = f"{recommendation}. Run: {next_command}"

    return {
        "level": "critical" if risk_level == "severe" else "high" if risk_level == "high" else "info",
        "source": "git_intelligence",
        "headline": recommendation,
        "message": reason,
        "recommended_action": recommended_action,
    }


def _select_context(
    terminal_error: dict[str, Any],
    coding_context: dict[str, Any],
    snapshot: dict[str, Any],
    git_risk: dict[str, Any],
) -> tuple[str, dict[str, str]]:
    has_terminal_error = bool(terminal_error.get("has_terminal_error", False))
    if has_terminal_error:
        guidance = terminal_error.get("guidance_priority") if isinstance(terminal_error.get("guidance_priority"), dict) else {}
        return "terminal_error_context", {
            "level": _as_text(guidance.get("level"), "critical"),
            "source": _as_text(guidance.get("source"), "terminal_error_context"),
            "headline": _as_text(guidance.get("headline"), "Terminal Error Detected"),
            "message": _as_text(guidance.get("message"), _as_text(terminal_error.get("summary"), "Terminal error detected.")),
            "recommended_action": _as_text(guidance.get("recommended_action"), _as_text(terminal_error.get("recommended_action"), "Resolve the terminal error first.")),
        }

    if bool(git_risk.get("blocking", False)):
        return "coding_context_pack", _git_guidance(coding_context)

    modified_files = _as_int(snapshot.get("modified_files"), 0)
    staged_files = _as_int(snapshot.get("staged_files"), 0)
    if modified_files > 0 or staged_files > 0:
        return "snapshot_context", _snapshot_guidance(snapshot)

    return "fallback", _default_guidance(
        source="fallback",
        headline="Continue Implementation",
        message="No higher-priority local signal is available.",
        recommended_action="Continue current implementation.",
        level="info",
    )


def _build_primary_guidance(
    selected_source: str,
    guidance_priority: dict[str, str],
    active_file: dict[str, Any],
    git_risk: dict[str, Any],
) -> dict[str, Any]:
    active_file_name = _as_text(active_file.get("active_file_name"), fallback="")

    if selected_source == "terminal_error_context":
        return {
            "headline": _as_text(guidance_priority.get("headline"), fallback="Resolve Error First"),
            "recommended_action": _as_text(guidance_priority.get("recommended_action"), fallback="Resolve the terminal error first."),
            "reason": _as_text(guidance_priority.get("message"), fallback="Terminal error is blocking current work."),
            "blocking": True,
            "source": "terminal_error_context",
            "level": "critical",
        }

    if bool(git_risk.get("blocking", False)):
        return {
            "headline": "Review Risky Git Changes",
            "recommended_action": _as_text(git_risk.get("recommendation"), fallback="Review risky git changes before continuing."),
            "reason": _as_text(git_risk.get("reason"), fallback="Git risk is blocking active-file work."),
            "blocking": True,
            "source": "git_intelligence",
            "level": "high",
        }

    if active_file_name:
        return {
            "headline": "Continue Active File Work",
            "recommended_action": f"Continue work in {active_file_name}.",
            "reason": "No blocking signal overrides the current active file.",
            "blocking": False,
            "source": "active_file",
            "level": "info",
        }

    return {
        "headline": "Continue Implementation",
        "recommended_action": "Continue the current implementation task.",
        "reason": "No blocking signal overrides current implementation work.",
        "blocking": False,
        "source": "fallback",
        "level": "info",
    }


def _build_advisory_guidance(git_risk: dict[str, Any], validation_evidence_available: bool) -> list[dict[str, str]]:
    advisories: list[dict[str, str]] = []

    if bool(git_risk.get("advisory", False)) and not bool(git_risk.get("blocking", False)):
        message = _as_text(git_risk.get("reason"), fallback="Git changes should be reviewed soon.")
        next_command = _as_text(git_risk.get("next_command"), fallback="")
        if next_command:
            message = f"{message} Run: {next_command}"
        advisories.append(
            {
                "type": "git_review",
                "level": "warning",
                "message": message,
            }
        )

    if not validation_evidence_available:
        advisories.append(
            {
                "type": "validation_missing",
                "level": "warning",
                "message": "Recent validation evidence is missing; run a focused check after the next implementation step.",
            }
        )

    return advisories


def _build_payload() -> dict[str, Any]:
    _refresh_active_editor_context()

    terminal_error = _load_terminal_error_context()
    coding_context = _load_coding_context()
    snapshot = _load_snapshot_context()
    active_editor_context = _load_active_editor_context()
    active_editor_state = _safe_load_json(ACTIVE_EDITOR_STATE_PATH)
    active_file_available, active_file = _active_file_payload(active_editor_context)
    development_context = _development_context_payload(active_file, active_editor_context, active_editor_state)
    change_context = _change_context_payload(active_file)
    git_risk = _git_risk_context(coding_context, active_file)

    selected_source, guidance_priority = _select_context(terminal_error, coding_context, snapshot, git_risk)
    workflow_evidence, validation_evidence_available, terminal_evidence_available, git_evidence_available = _workflow_evidence_payload(
        selected_source,
        terminal_error,
        coding_context,
        snapshot,
    )
    primary_guidance = _build_primary_guidance(selected_source, guidance_priority, active_file, git_risk)
    advisory_guidance = _build_advisory_guidance(git_risk, validation_evidence_available)

    return {
        "timestamp": _utc_now_iso(),
        "active_branch": _as_text(
            snapshot.get("git_branch")
            or coding_context.get("branch")
            or coding_context.get("git_branch"),
            "unknown",
        ),
        "modified_files": _as_int(snapshot.get("modified_files"), 0),
        "staged_files": _as_int(snapshot.get("staged_files"), 0),
        "has_terminal_error": bool(terminal_error.get("has_terminal_error", False)),
        "active_file_available": active_file_available,
        "active_file": active_file,
        "development_context": development_context,
        "change_context": change_context,
        "selected_source": selected_source,
        "guidance_priority": guidance_priority,
        "primary_guidance": primary_guidance,
        "advisory_guidance": advisory_guidance,
        "git_risk_context": git_risk,
        "workflow_evidence": workflow_evidence,
        "signal_freshness": _signal_freshness_payload(),
        "validation_evidence_available": validation_evidence_available,
        "terminal_evidence_available": terminal_evidence_available,
        "git_evidence_available": git_evidence_available,
    }


def _write_output(payload: dict[str, Any]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    payload = _build_payload()
    _write_output(payload)
    active_file = payload.get("active_file") if isinstance(payload.get("active_file"), dict) else {}
    active_file_name = _as_text(active_file.get("active_file_name"), "unavailable")
    print("Context Fusion Engine")
    print(f"Selected source: {payload['selected_source']}")
    print(f"Active branch: {payload['active_branch']}")
    print(f"Modified files: {payload['modified_files']}")
    print(f"Staged files: {payload['staged_files']}")
    print("Active File:")
    print(f"- {active_file_name}")
    print(f"Wrote: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()