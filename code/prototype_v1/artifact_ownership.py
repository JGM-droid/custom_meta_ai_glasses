from __future__ import annotations

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent.parent

# The first entry is the canonical writer. Additional entries are retained
# writers that must remain quarantined from the normal runtime.
ARTIFACT_WRITERS: dict[str, tuple[str, ...]] = {
    "results/active_editor_state.json": (
        "vscode_extension/active-file-signal/extension.js",
    ),
    "results/active_editor_state.tmp.json": (
        "vscode_extension/active-file-signal/extension.js",
    ),
    "results/active_editor_context.json": ("code/prototype_v1/active_editor_context.py",),
    "results/coding_context_pack.json": ("code/prototype_v1/coding_context_pack.py",),
    "results/milestone_history.json": ("code/prototype_v1/coding_context_pack.py",),
    "results/coding_session_snapshot.json": ("code/prototype_v1/coding_session_snapshot.py",),
    "results/context_fusion.json": ("code/prototype_v1/context_fusion.py",),
    "results/terminal_error_context.json": ("code/prototype_v1/terminal_error_context.py",),
    "results/latest_response.json": ("code/prototype_v1/fix_writer.py",),
    "results/session_memory.json": ("code/prototype_v1/memory_manager.py",),
    "results/session_recovery.json": ("code/prototype_v1/session_recovery.py",),
    "results/resume_now.json": (
        "code/prototype_v1/glasses_demo.py",
        "code/prototype_v1/resume_now.py",
    ),
    "results/glasses_demo.json": ("code/prototype_v1/glasses_demo.py",),
    "results/project_progress.json": ("code/prototype_v1/glasses_demo.py",),
    "results/task_state.json": ("code/prototype_v1/glasses_demo.py",),
    "results/task_completion.json": ("code/prototype_v1/glasses_demo.py",),
    "results/chatgpt_context_payload.json": ("code/prototype_v1/glasses_demo.py",),
    "results/guidance_response.json": ("code/prototype_v1/glasses_demo.py",),
    "results/chatgpt_request.json": ("code/prototype_v1/glasses_demo.py",),
    "results/chatgpt_response_raw.json": ("code/prototype_v1/glasses_demo.py",),
    "results/developer_validation_log.json": ("code/prototype_v1/glasses_demo.py",),
    "results/usability_report.json": ("code/prototype_v1/glasses_demo.py",),
    "results/last_known_hud_payload.json": ("code/prototype_v1/api.py",),
    "results/vision_context.json": ("code/prototype_v1/api.py",),
    "results/https_tunnel_readiness.json": ("code/prototype_v1/https_tunnel_readiness.py",),
    "results/https_tunnel_test_runner.json": ("code/prototype_v1/https_tunnel_test_runner.py",),
    "results/network_display_test.json": ("code/prototype_v1/network_display_test.py",),
    "results/demo_server_status.json": ("code/prototype_v1/demo_server_manager.py",),
    "results/demo_context/<scenario>/coding_context_pack.json": (
        "code/prototype_v1/dev_demo_scenarios.py",
    ),
    "results/demo_context/<scenario>/session_recovery.json": (
        "code/prototype_v1/dev_demo_scenarios.py",
    ),
}


def find_multiple_writers(repo_root: Path = REPO_ROOT) -> dict[str, tuple[str, ...]]:
    conflicts: dict[str, tuple[str, ...]] = {}
    for artifact, writers in ARTIFACT_WRITERS.items():
        existing_writers = tuple(writer for writer in writers if (repo_root / writer).is_file())
        if len(existing_writers) > 1:
            conflicts[artifact] = existing_writers
    return conflicts


def warn_if_multiple_writers(repo_root: Path = REPO_ROOT) -> None:
    for artifact, writers in find_multiple_writers(repo_root).items():
        canonical, *additional = writers
        print(
            f"Warning: multiple JSON writers detected for {artifact}. "
            f"Canonical writer: {canonical}; quarantined writer(s): {', '.join(additional)}"
        )
