from typer.testing import CliRunner

from better_agent.cli import app

runner = CliRunner()


def test_short_help_works_on_app_and_subcommands():
    assert runner.invoke(app, ["-h"]).exit_code == 0
    assert runner.invoke(app, ["list", "-h"]).exit_code == 0


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.startswith("bta ")


def test_n_is_not_bound_to_limit_or_note():
    # clig.dev reserves -n for --dry-run
    for cmd in (["list"], ["search", "x"], ["link", "a", "b"]):
        result = runner.invoke(app, [*cmd, "-n", "5"])
        assert result.exit_code == 2, cmd


def test_source_is_checked_the_same_everywhere(tmp_path, monkeypatch):
    monkeypatch.setenv("BTA_HOME", str(tmp_path))
    for cmd in (["import"], ["list"], ["search", "x"]):
        assert runner.invoke(app, [*cmd, "--source", "bogus"]).exit_code == 2, cmd
    assert not (tmp_path / "bta.db").exists()  # rejected before touching the db
    assert runner.invoke(app, ["list", "--source", "claude-code"]).exit_code == 0


def seed_two_sessions(tmp_path, monkeypatch):
    from better_agent import db as dbm
    from better_agent.models import SourceSession

    monkeypatch.setenv("BTA_HOME", str(tmp_path))
    conn = dbm.connect(tmp_path / "bta.db")
    ids = [
        dbm.upsert_session(conn, SourceSession(
            source="claude-code", source_id=sid, project="/p", branch=None, title=sid,
            model=None, created_at=1000, updated_at=2000,
        ))
        for sid in ("one", "two")
    ]
    conn.commit()
    return ids


def run_json(args):
    import json

    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_json_on_link_links_unlink_handoff(tmp_path, monkeypatch):
    a, b = seed_two_sessions(tmp_path, monkeypatch)

    assert run_json(["link", a, b, "--note", "n"]) == {
        "a": a, "b": b, "type": "related", "note": "n", "created": True,
    }
    assert run_json(["link", a, b])["created"] is False
    [link] = run_json(["links", a])
    assert link["session"]["id"] == b and link["type"] == "related"
    assert run_json(["unlink", a, b, "--force"]) == {"a": a, "b": b, "removed": 1}

    pack = run_json(["handoff", a])
    assert pack["session"] == a and pack["copied"] is False
    assert pack["pack"].startswith("# Context handoff: one")


def test_json_on_import(tmp_path, monkeypatch):
    from better_agent.sources import claude, opencode

    monkeypatch.setenv("BTA_HOME", str(tmp_path))
    monkeypatch.setattr(claude, "CLAUDE_DIR", tmp_path / "none")
    monkeypatch.setattr(opencode, "DB_PATH", tmp_path / "none.db")
    stats = run_json(["import"])
    assert [s["source"] for s in stats] == ["claude-code", "opencode"]
    assert all(s["skipped"] >= 0 and s["sessions"] == 0 for s in stats)


def test_search_retries_fts_syntax_errors_as_quoted_terms(tmp_path, monkeypatch):
    seed_two_sessions(tmp_path, monkeypatch)
    # an unbalanced quote is an FTS5 syntax error; the quoted retry must succeed
    assert run_json(["search", 'flux "capacitor']) == []


def test_status_messages_go_to_stderr(tmp_path, monkeypatch):
    a, b = seed_two_sessions(tmp_path, monkeypatch)
    for args in (["link", a, b], ["unlink", a, b, "-f"], ["links", a], ["search", "zzz"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, args
        assert result.stdout == "" and result.stderr, args


def test_every_command_has_help_examples():
    commands = ["import", "list", "search", "show", "link", "links", "unlink", "handoff", "switch"]
    for args in ([], *([c] for c in commands)):
        result = runner.invoke(app, [*args, "--help"])
        assert "Examples" in result.output and "bta " in result.output, args


def test_unlink_refuses_without_confirmation_when_not_interactive(tmp_path, monkeypatch):
    a, b = seed_two_sessions(tmp_path, monkeypatch)
    runner.invoke(app, ["link", a, b])
    result = runner.invoke(app, ["unlink", a, b])
    assert result.exit_code == 1 and "--force" in result.stderr
    assert len(run_json(["links", a])) == 1  # nothing removed


def test_unlink_with_no_links_needs_no_confirmation(tmp_path, monkeypatch):
    a, b = seed_two_sessions(tmp_path, monkeypatch)
    assert run_json(["unlink", a, b])["removed"] == 0


def test_packs_and_transcripts_print_verbatim(tmp_path, monkeypatch):
    from better_agent import db as dbm
    from better_agent.models import SourceMessage

    a, _ = seed_two_sessions(tmp_path, monkeypatch)
    conn = dbm.connect(tmp_path / "bta.db")
    long_line = "word " * 40 + "[bold]not markup[/bold]"
    dbm.replace_messages(conn, a, "claude-code", [SourceMessage(
        id="m1", role="user", parent_id=None, is_sidechain=False, model=None, created_at=1500,
        parts=[{"type": "text", "text": long_line}], text=long_line,
    )])
    conn.commit()

    assert long_line.strip() in runner.invoke(app, ["show", a, "--full"]).stdout
    assert "[bold]not markup[/bold]" in runner.invoke(app, ["handoff", a, "--max-chars", "99999"]).stdout


def switch_setup(tmp_path, monkeypatch):
    from better_agent import db as dbm
    from better_agent.models import SourceSession
    from better_agent.sources import claude, opencode

    monkeypatch.setenv("BTA_HOME", str(tmp_path))
    monkeypatch.setattr(claude, "CLAUDE_DIR", tmp_path / "none")
    monkeypatch.setattr(opencode, "DB_PATH", tmp_path / "none.db")
    monkeypatch.chdir(tmp_path)
    conn = dbm.connect(tmp_path / "bta.db")

    def add(source, source_id, updated, project=str(tmp_path)):
        return dbm.upsert_session(conn, SourceSession(
            source=source, source_id=source_id, project=project, branch=None, title=source_id,
            model=None, created_at=1, updated_at=updated,
        ))

    ids = {
        "older_claude": add("claude-code", "older", 1000),
        "claude": add("claude-code", "newest-claude", 2000),
        "opencode": add("opencode", "newest-overall", 3000),
        "elsewhere": add("claude-code", "other-dir", 4000, project="/somewhere/else"),
    }
    conn.commit()
    return ids


def test_switch_dry_run_picks_latest_session_here_from_the_other_agent(tmp_path, monkeypatch):
    ids = switch_setup(tmp_path, monkeypatch)
    result = runner.invoke(app, ["switch", "--to", "opencode", "-n"])
    assert result.exit_code == 0, result.output
    assert f"Session: {ids['claude']} " in result.stdout  # not the opencode one, not another dir
    assert result.stdout.rstrip().endswith('pick up from "Where things stand".')
    assert f"would run in {tmp_path}: opencode --prompt '<pack>' {tmp_path}" in result.stderr


def test_switch_execs_the_agent_in_the_project_directory(tmp_path, monkeypatch):
    import os
    import shutil

    ids = switch_setup(tmp_path, monkeypatch)
    calls = {}
    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(os, "execvp", lambda file, argv: calls.update(file=file, argv=argv))
    monkeypatch.chdir("/")

    result = runner.invoke(app, ["switch", "--to", "claude", "--from", ids["opencode"], "--yes"])
    assert result.exit_code == 0, result.output
    assert calls["file"] == "claude"
    assert calls["argv"][1].startswith("# Context handoff: newest-overall")
    assert os.path.samefile(os.getcwd(), tmp_path)


def test_switch_without_a_session_here_says_how_to_pick_one(tmp_path, monkeypatch):
    switch_setup(tmp_path, monkeypatch)
    (tmp_path / "empty").mkdir()
    monkeypatch.chdir(tmp_path / "empty")
    result = runner.invoke(app, ["switch", "--to", "opencode", "--yes"])
    assert result.exit_code == 1 and "--from" in result.stderr


def test_copy_uses_the_first_clipboard_tool_on_path(monkeypatch):
    import shutil
    import subprocess

    import pytest
    import typer

    from better_agent import cli

    ran = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: ran.append((argv, kw["input"])))
    monkeypatch.setattr(shutil, "which", lambda name: name if name in ("xclip", "xsel") else None)
    cli.copy_to_clipboard("pack")
    assert ran == [(["xclip", "-selection", "clipboard"], b"pack")]

    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(typer.Exit):
        cli.copy_to_clipboard("pack")


def test_switch_needs_yes_without_a_terminal(tmp_path, monkeypatch):
    switch_setup(tmp_path, monkeypatch)
    result = runner.invoke(app, ["switch", "--to", "opencode"])
    assert result.exit_code == 1 and "--yes" in result.stderr


def test_switch_requires_valid_destination_before_import(tmp_path, monkeypatch):
    monkeypatch.setenv("BTA_HOME", str(tmp_path))
    for args in (["switch"], ["switch", "opencode", "--dry-run"],
                 ["switch", "--to", "bogus", "--dry-run"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 2, (args, result.output)
    assert not (tmp_path / "bta.db").exists()


def test_switch_picker_preview_and_confirm(tmp_path, monkeypatch):
    import os
    import shutil

    from better_agent import cli

    ids = switch_setup(tmp_path, monkeypatch)
    calls = {}
    monkeypatch.setattr(cli, "stdin_is_terminal", lambda: True)
    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(os, "execvp", lambda file, argv: calls.update(argv=argv))

    # two Claude Code sessions here; pick the second (older) one, then decline
    result = runner.invoke(app, ["switch", "--to", "opencode"], input="2\nn\n")
    assert result.exit_code == 1 and not calls
    assert ids["claude"] in result.stderr and ids["older_claude"] in result.stderr
    assert "Pack" in result.stderr and "Continue in OpenCode?" in result.stderr

    result = runner.invoke(app, ["switch", "--to", "opencode"], input="2\ny\n")
    assert result.exit_code == 0, result.output
    assert f"Session: {ids['older_claude']} " in calls["argv"][2]
