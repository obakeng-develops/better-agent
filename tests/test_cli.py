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
    assert run_json(["unlink", a, b]) == {"a": a, "b": b, "removed": 1}

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
