"""Claude Code adapter: imports ~/.claude/projects/*/*.jsonl session files.

Each file holds one event per line. Event types drift between Claude Code
versions, so we whitelist 'user' / 'assistant' / 'summary' and ignore the rest
(api-request, attachment, permission-mode, ...).
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .. import db as dbm
from ..models import SourceMessage, SourceSession

CLAUDE_DIR = Path("~/.claude/projects").expanduser()

TOOL_RESULT_MAX = 2000  # chars kept in parts
TOOL_RESULT_FTS = 500  # chars indexed for search


def discover() -> list[Path]:
    if not CLAUDE_DIR.exists():
        return []
    return sorted(CLAUDE_DIR.glob("*/*.jsonl"))


def _ts_ms(ts: str | None) -> int | None:
    if not ts:
        return None
    try:
        return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _tool_target(inp: dict) -> str:
    return str(
        inp.get("file_path") or inp.get("command") or inp.get("pattern") or inp.get("path") or ""
    )[:200]


def _tool_result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _normalize_content(content) -> tuple[list[dict], str]:
    """Returns (parts, fts_text). Thinking is kept in parts but not indexed."""
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    parts: list[dict] = []
    fts: list[str] = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = block.get("text", "")
            parts.append({"type": "text", "text": text})
            fts.append(text)
        elif btype == "thinking":
            parts.append({"type": "thinking", "text": block.get("thinking", "")})
        elif btype == "tool_use":
            inp = block.get("input") or {}
            parts.append({"type": "tool_use", "name": block.get("name"), "input": inp})
            fts.append(f"[tool: {block.get('name')}] {_tool_target(inp)}")
        elif btype == "tool_result":
            text = _tool_result_text(block.get("content"))
            parts.append({"type": "tool_result", "text": text[:TOOL_RESULT_MAX]})
            fts.append(text[:TOOL_RESULT_FTS])
    return parts, "\n".join(t for t in fts if t)


def parse_file(path: Path) -> tuple[SourceSession, list[SourceMessage]]:
    session_id_from_lines: str | None = None
    project = branch = model = summary = None
    version = None
    timestamps: list[int] = []
    messages: list[SourceMessage] = []
    first_user_text: str | None = None

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate a truncated last line in live sessions
            etype = ev.get("type")
            if etype == "summary":
                summary = summary or ev.get("summary")
                continue
            if etype not in ("user", "assistant"):
                continue

            session_id_from_lines = session_id_from_lines or ev.get("sessionId")
            project = ev.get("cwd") or project
            branch = ev.get("gitBranch") or branch
            version = ev.get("version") or version
            ts = _ts_ms(ev.get("timestamp"))
            if ts:
                timestamps.append(ts)

            msg = ev.get("message") or {}
            parts, fts_text = _normalize_content(msg.get("content"))
            if etype == "assistant":
                model = msg.get("model") or model
            if first_user_text is None and etype == "user" and not ev.get("isSidechain"):
                text = " ".join(p.get("text", "") for p in parts if p["type"] == "text").strip()
                if text:
                    first_user_text = " ".join(text.split())[:80]

            messages.append(
                SourceMessage(
                    id=ev.get("uuid") or f"line-{len(messages)}",
                    role=etype,
                    parent_id=ev.get("parentUuid"),
                    is_sidechain=bool(ev.get("isSidechain")),
                    model=msg.get("model"),
                    created_at=ts,
                    parts=parts,
                    text=fts_text,
                )
            )

    title = summary or first_user_text or path.stem
    session = SourceSession(
        source="claude-code",
        source_id=session_id_from_lines or path.stem,
        project=project,
        branch=branch,
        title=title,
        model=model,
        created_at=min(timestamps) if timestamps else None,
        updated_at=max(timestamps) if timestamps else None,
        raw_meta={"version": version, "project_slug": path.parent.name},
    )
    return session, messages


def do_import(
    conn: sqlite3.Connection,
    force: bool = False,
    progress: Callable[[int, int], None] = lambda done, total: None,
) -> dict:
    sessions = msgs = skipped = 0
    paths = discover()
    for i, path in enumerate(paths):
        progress(i, len(paths))
        st = path.stat()
        key = f"claude:{path}"
        row = conn.execute(
            "SELECT mtime, size FROM imports WHERE source_path=?", (key,)
        ).fetchone()
        if not force and row and row["mtime"] == int(st.st_mtime) and row["size"] == st.st_size:
            skipped += 1
            continue
        session, messages = parse_file(path)
        sid = dbm.upsert_session(conn, session)
        dbm.replace_messages(conn, sid, session.source, messages)
        conn.execute(
            "INSERT OR REPLACE INTO imports VALUES (?,?,?,?)",
            (key, int(st.st_mtime), st.st_size, int(time.time() * 1000)),
        )
        sessions += 1
        msgs += len(messages)
    progress(len(paths), len(paths))
    conn.commit()
    return {"source": "claude-code", "sessions": sessions, "messages": msgs, "skipped": skipped}
