"""Deterministic context-pack rendering for `bta handoff` and `bta show`.

No LLM calls: the pack is a pure function over normalized session data, built
around the "intent spine" (every user message, in order) — the user's own words
transfer intent between agents better than any summary.
"""

from __future__ import annotations

import json
import re
from collections import Counter
import sqlite3
import time

from . import db as dbm

WRITE_TOOLS = {"edit", "write", "multiedit", "notebookedit"}
PACK_HEADER = "# Context handoff: "
SESSION_LINE = re.compile(r"^Session: (bta_[0-9a-f]{8}) ", re.M)


def _parts(message: sqlite3.Row) -> list[dict]:
    return json.loads(message["parts"])


def text_of(message: sqlite3.Row) -> str:
    return "\n".join(
        p.get("text", "") for p in _parts(message) if p.get("type") == "text"
    ).strip()


def intent_spine(messages: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """User messages that carry actual intent (not tool results or sidechains)."""
    return [
        m for m in messages
        if m["role"] == "user" and not m["is_sidechain"] and text_of(m)
    ]


def files_touched(messages: list[sqlite3.Row]) -> list[str]:
    seen: list[str] = []
    for m in messages:
        for p in _parts(m):
            if p.get("type") != "tool_use":
                continue
            if (p.get("name") or "").lower() not in WRITE_TOOLS:
                continue
            inp = p.get("input") or {}
            fp = inp.get("file_path") or inp.get("filePath")
            if fp and fp not in seen:
                seen.append(fp)
    return seen


def turns(messages: list[sqlite3.Row]) -> list[tuple[sqlite3.Row, Counter, list[str]]]:
    """Each intent-spine message with what the agent did before the next one.

    Returns (user message, tool-call counts by name, shell commands run). Subagent
    (sidechain) activity is left out.
    """
    out: list[tuple[sqlite3.Row, Counter, list[str]]] = []
    for m in messages:
        if m["is_sidechain"]:
            continue
        if m["role"] == "user" and text_of(m):
            out.append((m, Counter(), []))
        elif m["role"] == "assistant" and out:
            for p in _parts(m):
                if p.get("type") != "tool_use":
                    continue
                out[-1][1][p.get("name") or "?"] += 1
                cmd = (p.get("input") or {}).get("command")
                if isinstance(cmd, str) and cmd.strip():
                    out[-1][2].append(cmd.strip())
    return out


def activity_line(tools: Counter, commands: list[str], examples: int = 2) -> str:
    """'Bash ×9 · Write ×2 · e.g. `uv run pytest`' — empty when the agent used no tools."""
    if not tools:
        return ""
    line = " · ".join(f"{name} ×{n}" for name, n in tools.most_common())
    shown = [_clip(c.splitlines()[0], 80) for c in commands[:examples]]
    if shown:
        line += " · e.g. " + ", ".join(f"`{c}`" for c in shown)
    return line


def _last_assistant_text(messages: list[sqlite3.Row]) -> str | None:
    for m in reversed(messages):
        if m["role"] == "assistant":
            text = text_of(m)
            if text:
                return text
    return None


def _clip(text: str, n: int) -> str:
    text = text.strip()
    return text if len(text) <= n else text[:n].rstrip() + " …"


def _fmt_time(ms: int | None) -> str:
    if not ms:
        return "?"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ms / 1000))


def render_transcript(messages: list[sqlite3.Row]) -> str:
    """Full transcript: text and tool calls. Thinking is omitted by design."""
    out: list[str] = []
    for m in messages:
        side = " (subagent)" if m["is_sidechain"] else ""
        out.append(f"\n### {m['role']}{side} — {_fmt_time(m['created_at'])}")
        for p in _parts(m):
            ptype = p.get("type")
            if ptype == "text" and p.get("text", "").strip():
                out.append(p["text"].strip())
            elif ptype == "tool_use":
                inp = p.get("input") or {}
                target = inp.get("file_path") or inp.get("filePath") or inp.get("command") or ""
                out.append(f"> [tool: {p.get('name')}] {str(target)[:200]}")
    return "\n".join(out)


def render_handoff(
    session: sqlite3.Row,
    messages: list[sqlite3.Row],
    linked: list[tuple[sqlite3.Row, str, str | None]],
    full: bool = False,
    max_chars: int = 8000,
    activity: bool = True,
    git: dict | None = None,
) -> str:
    spine = turns(messages)
    files = files_touched(messages)
    last_text = _last_assistant_text(messages)

    lines: list[str] = [f"{PACK_HEADER}{session['title']}", ""]
    src = f"{session['source']}"
    if session["model"]:
        src += f" ({session['model']})"
    lines.append(f"Source: {src} · Project: {session['project'] or '?'}")
    lines.append(
        f"Session: {session['id']} · {_fmt_time(session['created_at'])} → "
        f"{_fmt_time(session['updated_at'])} · {session['message_count']} messages"
    )
    lines.append(
        f"Full history: `bta show {session['id']} --full` (readable transcript) or "
        f"`bta show {session['id']} --json` (every tool call and result)"
    )
    if linked:
        rel = ", ".join(
            f"{other['id']} ({ltype}{' — ' + note if note else ''})"
            for other, ltype, note in linked
        )
        lines.append(f"Related sessions: {rel}")
    lines.append("")

    if spine:
        lines += ["## Goal", "", _clip(text_of(spine[0][0]), 600), ""]
        lines += ["## What was asked, in order", ""]
        for i, (m, tools, commands) in enumerate(spine, 1):
            lines.append(f"{i}. {_clip(' '.join(text_of(m).split()), 200)}")
            did = activity_line(tools, commands) if activity else ""
            if did:
                lines.append(f"   → {did}")
        lines.append("")

    if files:
        lines += ["## Files touched", ""]
        for fp in files[:20]:
            lines.append(f"- `{fp}`")
        if len(files) > 20:
            lines.append(f"- …and {len(files) - 20} more")
        lines.append("")

    if git:
        lines += ["## Git, at handoff", "", f"Branch: `{git['branch']}`", ""]
        for label, rows in (("Uncommitted changes", git["changes"]),
                            ("Commits since the session started", git["commits"])):
            if not rows:
                continue
            lines.append(f"{label} ({len(rows)}):")
            lines += [f"- `{r}`" for r in rows[:20]]
            if len(rows) > 20:
                lines.append(f"- …and {len(rows) - 20} more")
            lines.append("")
        if not git["changes"]:
            lines += ["The working tree is clean.", ""]

    if last_text:
        lines += ["## Where things stand", "", _clip(last_text, 1500), ""]

    if full:
        lines += ["## Full transcript", render_transcript(messages), ""]

    doc = "\n".join(lines).strip() + "\n"
    if len(doc) > max_chars and activity:  # drop activity before cutting the tail
        return render_handoff(session, messages, linked, full, max_chars, activity=False, git=git)
    if len(doc) > max_chars:
        doc = doc[:max_chars].rstrip() + f"\n\n…[truncated to {max_chars} chars — raise --max-chars or use --full]\n"
    return doc


def pack_origin(message: sqlite3.Row) -> str | None:
    """The session id of a handoff pack pasted into this message, if it has one.

    Only typed text counts. A tool result that printed a pack doesn't, so an agent
    running `bta handoff` never links its own session.
    """
    for p in _parts(message):
        text = p.get("text", "") if p.get("type") == "text" else ""
        if PACK_HEADER in text:
            m = SESSION_LINE.search(text, text.index(PACK_HEADER))
            if m:
                return m.group(1)
    return None


def link_handoffs(conn: sqlite3.Connection) -> int:
    """Link each session that starts from a pasted pack to the session the pack came from."""
    linked = 0
    for m in conn.execute(
        """SELECT m.session_id, m.parts FROM messages m
           WHERE m.role = 'user' AND m.is_sidechain = 0 AND m.text LIKE ?""",
        (f"%{PACK_HEADER.strip()}%",),
    ):
        origin = pack_origin(m)
        if not origin or origin == m["session_id"]:
            continue
        if conn.execute("SELECT 1 FROM sessions WHERE id=?", (origin,)).fetchone():
            linked += dbm.insert_link(conn, origin, m["session_id"], "handoff")
    return linked
