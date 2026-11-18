"""Deterministic context-pack rendering for `bt handoff` and `bt show`.

No LLM calls: the pack is a pure function over normalized session data, built
around the "intent spine" (every user message, in order) — the user's own words
transfer intent between agents better than any summary.
"""

from __future__ import annotations

import json
import sqlite3
import time

WRITE_TOOLS = {"edit", "write", "multiedit", "notebookedit"}


def _parts(message: sqlite3.Row) -> list[dict]:
    return json.loads(message["parts"])


def _text_of(message: sqlite3.Row) -> str:
    return "\n".join(
        p.get("text", "") for p in _parts(message) if p.get("type") == "text"
    ).strip()


def intent_spine(messages: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """User messages that carry actual intent (not tool results or sidechains)."""
    return [
        m for m in messages
        if m["role"] == "user" and not m["is_sidechain"] and _text_of(m)
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


def _last_assistant_text(messages: list[sqlite3.Row]) -> str | None:
    for m in reversed(messages):
        if m["role"] == "assistant":
            text = _text_of(m)
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
) -> str:
    spine = intent_spine(messages)
    files = files_touched(messages)
    last_text = _last_assistant_text(messages)

    lines: list[str] = [f"# Context handoff: {session['title']}", ""]
    src = f"{session['source']}"
    if session["model"]:
        src += f" ({session['model']})"
    lines.append(f"Source: {src} · Project: {session['project'] or '?'}")
    lines.append(
        f"Session: {session['id']} · {_fmt_time(session['created_at'])} → "
        f"{_fmt_time(session['updated_at'])} · {session['message_count']} messages"
    )
    if linked:
        rel = ", ".join(
            f"{other['id']} ({ltype}{' — ' + note if note else ''})"
            for other, ltype, note in linked
        )
        lines.append(f"Related sessions: {rel}")
    lines.append("")

    if spine:
        lines += ["## Goal", "", _clip(_text_of(spine[0]), 600), ""]
        lines += ["## What was asked, in order", ""]
        for i, m in enumerate(spine, 1):
            lines.append(f"{i}. {_clip(' '.join(_text_of(m).split()), 200)}")
        lines.append("")

    if files:
        lines += ["## Files touched", ""]
        for fp in files[:20]:
            lines.append(f"- `{fp}`")
        if len(files) > 20:
            lines.append(f"- …and {len(files) - 20} more")
        lines.append("")

    if last_text:
        lines += ["## Where things stand", "", _clip(last_text, 1500), ""]

    if full:
        lines += ["## Full transcript", render_transcript(messages), ""]

    doc = "\n".join(lines).strip() + "\n"
    if len(doc) > max_chars:
        doc = doc[:max_chars].rstrip() + f"\n\n…[truncated to {max_chars} chars — raise --max-chars or use --full]\n"
    return doc
