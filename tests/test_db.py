import pytest

from better_agent import db as dbm
from better_agent.models import SourceMessage, SourceSession


def make_session(source_id="s1", source="claude-code", **kw):
    defaults = dict(
        source=source, source_id=source_id, project="/p", branch="main",
        title="T", model="m", created_at=1000, updated_at=2000,
    )
    return SourceSession(**(defaults | kw))


def test_deterministic_ids_and_upsert(tmp_path):
    conn = dbm.connect(tmp_path / "bta.db")
    sid1 = dbm.upsert_session(conn, make_session())
    sid2 = dbm.upsert_session(conn, make_session(title="renamed"))
    assert sid1 == sid2  # same source:source_id → same id
    assert sid1.startswith("bta_")
    row = conn.execute("SELECT COUNT(*) c, MAX(title) t FROM sessions").fetchone()
    assert row["c"] == 1 and row["t"] == "renamed"


def test_replace_messages_and_fts(tmp_path):
    conn = dbm.connect(tmp_path / "bta.db")
    sid = dbm.upsert_session(conn, make_session())
    msgs = [
        SourceMessage("m1", "user", None, False, None, 1000,
                      [{"type": "text", "text": "hello capacitor"}], "hello capacitor"),
        SourceMessage("m2", "assistant", "m1", False, "m", 1001,
                      [{"type": "text", "text": "fixed it"}], "fixed it"),
    ]
    dbm.replace_messages(conn, sid, "claude-code", msgs)
    dbm.rebuild_fts(conn)
    hits = conn.execute(
        "SELECT m.id FROM messages_fts JOIN messages m ON m.rowid = messages_fts.rowid "
        "WHERE messages_fts MATCH 'capacitor'"
    ).fetchall()
    assert len(hits) == 1

    # re-import replaces rather than duplicates
    dbm.replace_messages(conn, sid, "claude-code", msgs)
    assert conn.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"] == 2


def test_resolve_session_prefix_and_ambiguity(tmp_path):
    conn = dbm.connect(tmp_path / "bta.db")
    sid = dbm.upsert_session(conn, make_session())
    assert dbm.resolve_session(conn, sid)["id"] == sid
    assert dbm.resolve_session(conn, sid[:8])["id"] == sid  # prefix, no bta_ needed below
    assert dbm.resolve_session(conn, sid[4:9])["id"] == sid
    assert dbm.resolve_session(conn, "bta_00000000") is None

    conn.executemany(
        "INSERT INTO sessions (id, source, source_id) VALUES (?,?,?)",
        [("bta_aaaa0001", "x", "1"), ("bta_aaaa0002", "x", "2")],
    )
    with pytest.raises(ValueError):
        dbm.resolve_session(conn, "bta_aaaa")


def test_links_are_idempotent(tmp_path):
    conn = dbm.connect(tmp_path / "bta.db")
    a = dbm.upsert_session(conn, make_session("s1"))
    b = dbm.upsert_session(conn, make_session("s2"))
    assert dbm.insert_link(conn, a, b, "continuation", "why") is True
    assert dbm.insert_link(conn, a, b, "continuation", "why") is False  # already exists
    assert dbm.insert_link(conn, a, b, "related") is True  # different type is a new link
