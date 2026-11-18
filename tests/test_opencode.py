import json
import sqlite3

from better_traces import db as dbm
from better_traces.sources import opencode


def make_fake_opencode_db(path):
    c = sqlite3.connect(path)
    c.executescript(
        """
        CREATE TABLE session_v2 (
          id text PRIMARY KEY, project_id text, parent_id text, fork_session_id text,
          slug text, directory text, title text, model text, agent text,
          time_created integer, time_updated integer,
          tokens_input integer, tokens_output integer, cost real
        );
        CREATE TABLE session_message (
          id text PRIMARY KEY, session_id text, type text, seq integer,
          time_created integer, time_updated integer, data text
        );
        CREATE TABLE part (
          id text PRIMARY KEY, message_id text, session_id text,
          time_created integer, time_updated integer, data text
        );
        """
    )
    sessions = [
        ("ses_parent", None, None, "parent-slug", "Parent session", 1000, 2000),
        ("ses_child", "ses_parent", None, "child-slug", "Child session", 3000, 4000),
    ]
    for sid, parent, fork, slug, title, created, updated in sessions:
        c.execute(
            """INSERT INTO session_v2
               (id, project_id, parent_id, fork_session_id, slug, directory, title, model, agent,
                time_created, time_updated, tokens_input, tokens_output, cost)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, "proj1", parent, fork, slug, "/tmp/oc-proj", title,
             "openai/gpt-5.2-codex", "build", created, updated, 10, 20, 0.01),
        )
    c.execute(
        "INSERT INTO session_message VALUES ('m1','ses_parent','user',1,1001,1001,?)",
        (json.dumps({"role": "user", "time": {"created": 1001}, "parentID": None}),),
    )
    c.execute(
        "INSERT INTO part VALUES ('pt1','m1','ses_parent',1001,1001,?)",
        (json.dumps({"type": "text", "text": "hello from parent"}),),
    )
    c.execute(
        "INSERT INTO session_message VALUES ('m2','ses_child','assistant',1,3001,3001,?)",
        (json.dumps({"role": "assistant", "time": {"created": 3001}, "parentID": None,
                     "providerID": "openai", "modelID": "gpt-5.2-codex"}),),
    )
    c.execute(
        "INSERT INTO part VALUES ('pt2','m2','ses_child',3001,3001,?)",
        (json.dumps({"type": "tool", "tool": "edit",
                     "state": {"status": "completed",
                               "input": {"filePath": "/tmp/oc-proj/app.py"},
                               "output": "edited ok"}}),),
    )
    c.execute(
        "INSERT INTO part VALUES ('pt3','m2','ses_child',3002,3002,?)",
        (json.dumps({"type": "step-start"}),),  # must be ignored
    )
    c.commit()
    c.close()


def test_import_sessions_messages_and_autolinks(tmp_path, monkeypatch):
    fake = tmp_path / "opencode.db"
    make_fake_opencode_db(fake)
    monkeypatch.setattr(opencode, "DB_PATH", fake)

    conn = dbm.connect(tmp_path / "bt.db")
    stats = opencode.do_import(conn)

    assert stats["sessions"] == 2
    assert stats["messages"] == 2
    assert stats["links"] == 1  # child → parent subagent link

    child = conn.execute(
        "SELECT * FROM sessions WHERE source='opencode' AND source_id='ses_child'"
    ).fetchone()
    assert child["title"] == "Child session"
    assert child["project"] == "/tmp/oc-proj"
    assert child["tokens_in"] == 10 and child["tokens_out"] == 20

    parts = json.loads(
        conn.execute("SELECT parts FROM messages WHERE session_id=?", (child["id"],)).fetchone()[0]
    )
    assert [p["type"] for p in parts] == ["tool_use"]  # step-start dropped
    assert parts[0]["name"] == "edit"
    assert parts[0]["output"] == "edited ok"

    link = conn.execute("SELECT * FROM links").fetchone()
    assert link["type"] == "subagent"
    assert {link["a"], link["b"]} == {
        dbm.session_id("opencode", "ses_child"),
        dbm.session_id("opencode", "ses_parent"),
    }


def test_import_is_incremental(tmp_path, monkeypatch):
    fake = tmp_path / "opencode.db"
    make_fake_opencode_db(fake)
    monkeypatch.setattr(opencode, "DB_PATH", fake)

    conn = dbm.connect(tmp_path / "bt.db")
    first = opencode.do_import(conn)
    second = opencode.do_import(conn)  # db mtime unchanged → early exit
    assert first["sessions"] == 2
    assert second["skipped"] == -1 and second["sessions"] == 0
