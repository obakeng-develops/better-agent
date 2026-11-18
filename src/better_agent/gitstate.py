"""Live git state for a session's project, read when a pack is rendered."""

from __future__ import annotations

import subprocess


def _git(project: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", project, *args], capture_output=True, text=True, check=True, timeout=5
    ).stdout


def git_state(project: str | None, since_ms: int | None) -> dict | None:
    """Branch, uncommitted changes, and commits since the session started.

    None when the project isn't a git repo, or git isn't installed.
    """
    if not project:
        return None
    try:
        branch = _git(project, "branch", "--show-current").strip() or "(detached HEAD)"
        changes = _git(project, "status", "--porcelain").splitlines()
        commits = (
            _git(project, "log", "--oneline", f"--since=@{since_ms // 1000}").splitlines()
            if since_ms else []
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return {"branch": branch, "changes": changes, "commits": commits}
