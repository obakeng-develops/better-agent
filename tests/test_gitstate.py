import subprocess
import time

from better_agent.gitstate import git_state


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_git_state_reports_branch_changes_and_commits(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
        "--allow-empty", "-m", "first")
    (tmp_path / "new.txt").write_text("x")

    state = git_state(str(tmp_path), int((time.time() - 3600) * 1000))
    assert state["branch"] == "main"
    assert state["changes"] == ["?? new.txt"]
    assert [c.split(" ", 1)[1] for c in state["commits"]] == ["first"]


def test_git_state_is_none_outside_a_repo(tmp_path):
    assert git_state(str(tmp_path), None) is None
    assert git_state(None, None) is None
