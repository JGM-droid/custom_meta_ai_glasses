from pathlib import Path
import subprocess


def _run_git_command(command: list[str], repo_root: Path) -> str:
    """Run a git command safely and return short text output."""
    try:
        result = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )

        output = result.stdout.strip()
        error = result.stderr.strip()

        if output:
            return output

        if error:
            return error

        return "No output."

    except Exception as exc:
        return f"Unable to run command: {exc}"


def get_repo_root() -> Path:
    """Return the project root based on this file location."""
    return Path(__file__).resolve().parents[2]


def get_git_branch(repo_root: Path) -> str:
    return _run_git_command(
        ["git", "branch", "--show-current"],
        repo_root,
    )


def get_git_status(repo_root: Path) -> str:
    return _run_git_command(
        ["git", "status", "--short"],
        repo_root,
    )


def get_recent_git_log(repo_root: Path) -> str:
    return _run_git_command(
        ["git", "log", "--oneline", "-5"],
        repo_root,
    )


def build_repo_context() -> str:
    repo_root = get_repo_root()

    branch = get_git_branch(repo_root)
    status = get_git_status(repo_root)
    recent_log = get_recent_git_log(repo_root)

    return f"""
Repository root: {repo_root}

Current branch:
{branch}

Git status:
{status}

Recent commits:
{recent_log}
""".strip()


if __name__ == "__main__":
    print(build_repo_context())