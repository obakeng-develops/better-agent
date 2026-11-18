"""OpenCode adapter: imports from ~/.local/share/opencode/opencode.db (v2, read-only).

OpenCode v2 stores everything in a drizzle-managed SQLite db. session_v2 holds
session metadata (incl. parent_id / fork_session_id, used for auto-links).
session_message is the canonical message table: the type column is the role,
user rows carry data.text, assistant rows carry data.content inline. The legacy
message/part tables stopped being written during v2's life and are only used as
a fallback for dual-era rows. The pre-v2 storage/ file layout is not imported.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .. import db as dbm
from ..models import SourceMessage, SourceSession

DB_PATH = Path("~/.local/share/opencode/opencode.db").expanduser()

TOOL_OUTPUT_MAX = 2000
TOOL_OUTPUT_FTS = 500


def _tool_target(inp: dict) -> str:
    return str(
        inp.get("filePath") or inp.get("file_path") or inp.get("command") or inp.get("pattern") or ""
    )[:200]


def _normalize_part(data: dict) -> tuple[dict | None, str]:
    ptype = data.get("type")
    if ptype == "text":
        text = data.get("text", "")
        return {"type": "text", "text": text}, text
    if ptype == "reasoning":
        return {"type": "thinking", "text": data.get("text", "")}, ""
    if ptype == "tool":
        state = data.get("state") or {}
        inp = state.get("input") or {}
        out = state.get("output") or ""
        if not isinstance(out, str):
            out = json.dumps(out)
        part = {
            "type": "tool_use",
            "name": data.get("tool"),
            "input": inp,
            "output": out[:TOOL_OUTPUT_MAX],
            "status": state.get("status"),
        }
        fts = f"[tool: {data.get('tool')}] {_tool_target(inp)}\n{out[:TOOL_OUTPUT_FTS]}"
        return part, fts
    return None, ""  # step-start / step-finish / patch / file / compaction


def _model_of(mdata: dict) -> str | None:
    m = mdata.get("model")
    if isinstance(m, dict):  # v2: {"providerID": ..., "id": ..., "variant": ...}
        return "/".join(x for x in (m.get("providerID"), m.get("id")) if x) or None
    provider, model_id = mdata.get("providerID"), mdata.get("modelID")  # legacy flat shape
    return "/".join(x for x in (provider, model_id) if x) or None


def _load_messages(src: sqlite3.Connection, session_source_id: str) -> list[SourceMessage]:
    # Legacy fallback: dual-era rows whose parts only exist in the part table.
    parts_by_msg: dict[str, list[tuple[dict, str]]] = {}
    for row in src.execute(
        "SELECT message_id, data FROM part WHERE session_id=? ORDER BY message_id, id",
        (session_source_id,),
    ):
        try:
            pdata = json.loads(row["data"])
        except json.JSONDecodeError:
            continue
        part, fts = _normalize_part(pdata)
        if part is not None:
            parts_by_msg.setdefault(row["message_id"], []).append((part, fts))

    messages: list[SourceMessage] = []
    for row in src.execute(
        """SELECT id, type, time_created, data FROM session_message
           WHERE session_id=? AND type IN ('user', 'assistant')
           ORDER BY seq, id""",
        (session_source_id,),
    ):
        try:
            mdata = json.loads(row["data"])
        except json.JSONDecodeError:
            continue
        content = mdata.get("content")
        if isinstance(content, list):  # assistant rows: parts inline
            entries = [e for e in (_normalize_part(c) for c in content) if e[0] is not None]
        elif isinstance(mdata.get("text"), str):  # user rows: plain text
            entries = [({"type": "text", "text": mdata["text"]}, mdata["text"])]
        else:  # dual-era row: parts live in the legacy part table
            entries = parts_by_msg.get(row["id"], [])
        messages.append(
            SourceMessage(
                id=row["id"],
                role=row["type"],
                parent_id=mdata.get("parentID"),
                is_sidechain=False,  # opencode subagents are separate sessions (parent_id links)
                model=_model_of(mdata),
                created_at=(mdata.get("time") or {}).get("created") or row["time_created"],
                parts=[p for p, _ in entries],
                text="\n".join(f for _, f in entries if f),
            )
        )
    return messages


def do_import(conn: sqlite3.Connection, force: bool = False) -> dict:
    if not DB_PATH.exists():
        return {"source": "opencode", "sessions": 0, "messages": 0, "skipped": 0}

    wal = Path(str(DB_PATH) + "-wal")
    mtime = max(
        int(DB_PATH.stat().st_mtime), int(wal.stat().st_mtime) if wal.exists() else 0
    )
    key = "opencode:db"
    row = conn.execute("SELECT mtime FROM imports WHERE source_path=?", (key,)).fetchone()
    if not force and row and row["mtime"] == mtime:
        return {"source": "opencode", "sessions": 0, "messages": 0, "skipped": -1}

    src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        sessions = msgs = skipped = 0
        pending_links: list[tuple[str, str, str]] = []  # (from source_id, to source_id, type)
        for r in src.execute(
            """SELECT id, project_id, directory, title, parent_id, fork_session_id,
                      model, agent, slug, time_created, time_updated,
                      tokens_input, tokens_output, cost
               FROM session_v2"""
        ):
            sid = dbm.session_id("opencode", r["id"])
            existing = conn.execute(
                "SELECT updated_at FROM sessions WHERE id=?", (sid,)
            ).fetchone()
            if not force and existing and existing["updated_at"] == r["time_updated"]:
                skipped += 1
                continue
            session = SourceSession(
                source="opencode",
                source_id=r["id"],
                project=r["directory"],
                branch=None,
                title=r["title"] or r["slug"],
                model=r["model"],
                created_at=r["time_created"],
                updated_at=r["time_updated"],
                tokens_in=r["tokens_input"],
                tokens_out=r["tokens_output"],
                raw_meta={"slug": r["slug"], "agent": r["agent"], "cost": r["cost"]},
            )
            dbm.upsert_session(conn, session)
            messages = _load_messages(src, r["id"])
            dbm.replace_messages(conn, sid, "opencode", messages)
            if r["parent_id"]:
                pending_links.append((r["id"], r["parent_id"], "subagent"))
            if r["fork_session_id"]:
                pending_links.append((r["id"], r["fork_session_id"], "fork"))
            sessions += 1
            msgs += len(messages)

        linked = 0
        for from_sid, to_sid, ltype in pending_links:
            a = dbm.session_id("opencode", from_sid)
            b = dbm.session_id("opencode", to_sid)
            exists = conn.execute(
                "SELECT COUNT(*) c FROM sessions WHERE id IN (?,?)", (a, b)
            ).fetchone()["c"]
            if exists == 2 and dbm.insert_link(conn, a, b, ltype):
                linked += 1

        conn.execute(
            "INSERT OR REPLACE INTO imports VALUES (?,?,?,?)",
            (key, mtime, 0, int(time.time() * 1000)),
        )
        conn.commit()
        return {"source": "opencode", "sessions": sessions, "messages": msgs,
                "skipped": skipped, "links": linked}
    finally:
        src.close()
