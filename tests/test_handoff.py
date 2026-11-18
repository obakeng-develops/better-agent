from pathlib import Path

from better_agent import db as dbm
from better_agent.handoff import files_touched, intent_spine, render_handoff
from better_agent.sources import claude

FIXTURE = Path(__file__).parent / "fixtures" / "claude_sample.jsonl"


def load_fixture_session(tmp_path):
    conn = dbm.connect(tmp_path / "bta.db")
    session, messages = claude.parse_file(FIXTURE)
    sid = dbm.upsert_session(conn, session)
    dbm.replace_messages(conn, sid, session.source, messages)
    srow = conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    mrows = conn.execute(
        "SELECT * FROM messages WHERE session_id=? ORDER BY created_at, id", (sid,)
    ).fetchall()
    return conn, srow, mrows


def test_intent_spine_skips_tool_results_and_sidechains(tmp_path):
    _, _, mrows = load_fixture_session(tmp_path)
    spine = intent_spine(mrows)
    assert len(spine) == 1  # only u1; u2 is a tool_result, u3 is a sidechain
    assert "flux capacitor" in spine[0]["text"]


def test_files_touched(tmp_path):
    _, _, mrows = load_fixture_session(tmp_path)
    assert files_touched(mrows) == ["/tmp/proj/flux.py"]


def test_render_handoff_sections(tmp_path):
    _, srow, mrows = load_fixture_session(tmp_path)
    doc = render_handoff(srow, mrows, [], full=False, max_chars=8000)
    assert doc.startswith("# Context handoff: Fix the flux capacitor")
    assert "## Goal" in doc
    assert "## What was asked, in order" in doc
    assert "`/tmp/proj/flux.py`" in doc
    assert "## Where things stand" in doc
    assert "The capacitor now fluxes" in doc
    assert "## Full transcript" not in doc


def test_render_handoff_full_and_truncation(tmp_path):
    _, srow, mrows = load_fixture_session(tmp_path)
    doc = render_handoff(srow, mrows, [], full=True, max_chars=400)
    assert doc.endswith("raise --max-chars or use --full]\n")
    assert len(doc) <= 500



def test_link_handoffs_links_pasted_packs_but_not_tool_output(tmp_path):
    from better_agent.handoff import link_handoffs
    from better_agent.models import SourceMessage, SourceSession

    conn, srow, mrows = load_fixture_session(tmp_path)
    pack = render_handoff(srow, mrows, [])

    def add_session(source_id, part):
        sid = dbm.upsert_session(conn, SourceSession(
            source="opencode", source_id=source_id, project="/p", branch=None, title=source_id,
            model=None, created_at=5000, updated_at=6000,
        ))
        dbm.replace_messages(conn, sid, "opencode", [SourceMessage(
            id=f"{source_id}-m1", role="user", parent_id=None, is_sidechain=False, model=None,
            created_at=5000, parts=[part], text=part["text"],
        )])
        return sid

    pasted = add_session("pasted", {"type": "text", "text": "carry on from this:\n\n" + pack})
    add_session("tool-output", {"type": "tool_result", "text": pack})

    assert link_handoffs(conn) == 1
    assert link_handoffs(conn) == 0  # idempotent
    rows = conn.execute("SELECT a, b, type FROM links").fetchall()
    assert [tuple(r) for r in rows] == [(srow["id"], pasted, "handoff")]
