from pathlib import Path

from better_agent.sources import claude

FIXTURE = Path(__file__).parent / "fixtures" / "claude_sample.jsonl"


def test_parse_file_session_fields():
    session, messages = claude.parse_file(FIXTURE)
    assert session.source == "claude-code"
    assert session.source_id == "sess-1"
    assert session.project == "/tmp/proj"
    assert session.branch == "main"
    assert session.title == "Fix the flux capacitor"  # from the summary event
    assert session.model == "claude-opus-5-5"
    assert session.created_at < session.updated_at
    # 5 user/assistant events; the api-request event is whitelisted out
    assert len(messages) == 5


def test_parse_file_message_normalization():
    _, messages = claude.parse_file(FIXTURE)
    by_id = {m.id: m for m in messages}

    u1 = by_id["u1"]
    assert u1.role == "user" and u1.parts == [{"type": "text", "text": "Please fix the flux capacitor"}]
    assert "flux capacitor" in u1.text

    a1 = by_id["a1"]
    types = [p["type"] for p in a1.parts]
    assert types == ["thinking", "text", "tool_use"]
    assert "[tool: Edit] /tmp/proj/flux.py" in a1.text  # tool calls are searchable
    assert "hmm" not in a1.text  # thinking is not indexed

    u3 = by_id["u3"]
    assert u3.is_sidechain is True


def test_title_falls_back_to_first_user_text(tmp_path):
    f = tmp_path / "nosummary.jsonl"
    f.write_text(
        '{"type":"user","uuid":"u1","timestamp":"2026-11-10T10:00:00Z","cwd":"/p",'
        '"sessionId":"s2","isSidechain":false,'
        '"message":{"role":"user","content":"what is the airspeed velocity of an unladen swallow"}}\n'
    )
    session, messages = claude.parse_file(f)
    assert session.title.startswith("what is the airspeed")
    assert len(messages) == 1


def test_import_reports_progress_to_completion(tmp_path, monkeypatch):
    import shutil

    from better_agent import db as dbm

    proj = tmp_path / "projects" / "-p"
    proj.mkdir(parents=True)
    for name in ("a.jsonl", "b.jsonl"):
        shutil.copy(FIXTURE, proj / name)
    monkeypatch.setattr(claude, "CLAUDE_DIR", tmp_path / "projects")

    calls = []
    claude.do_import(dbm.connect(tmp_path / "bta.db"), progress=lambda d, t: calls.append((d, t)))
    assert calls == [(0, 2), (1, 2), (2, 2)]
