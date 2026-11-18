from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

from .models import SourceMessage, SourceSession

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id            TEXT PRIMARY KEY,
  source        TEXT NOT NULL,
  source_id     TEXT NOT NULL,
  project       TEXT,
  branch        TEXT,
  title         TEXT,
  model         TEXT,
  created_at    INTEGER,
  updated_at    INTEGER,
  message_count INTEGER DEFAULT 0,
  tokens_in     INTEGER,
  tokens_out    INTEGER,
  raw_meta      TEXT,
  UNIQUE(source, source_id)
);

CREATE TABLE IF NOT EXISTS messages (
  id           TEXT PRIMARY KEY,
  session_id   TEXT NOT NULL REFERENCES sessions(id),
  role         TEXT NOT NULL,
  parent_id    TEXT,
  is_sidechain INTEGER DEFAULT 0,
  model        TEXT,
  created_at   INTEGER,
  parts        TEXT NOT NULL,
  text         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  text, content='messages', content_rowid='rowid'
);

CREATE TABLE IF NOT EXISTS links (
  a          TEXT NOT NULL REFERENCES sessions(id),
  b          TEXT NOT NULL REFERENCES sessions(id),
  type       TEXT NOT NULL DEFAULT 'related',
  note       TEXT,
  created_at INTEGER,
  PRIMARY KEY (a, b, type)
);

CREATE TABLE IF NOT EXISTS imports (
  source_path TEXT PRIMARY KEY,
  mtime       INTEGER,
  size        INTEGER,
  imported_at INTEGER
);
"""


def default_db_path() -> Path:
    home = Path(os.environ.get("BTA_HOME", "~/.better-agent")).expanduser()
    return home / "bta.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = path or default_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def session_id(source: str, source_id: str) -> str:
    h = hashlib.sha1(f"{source}:{source_id}".encode()).hexdigest()
    return f"bta_{h[:8]}"


def message_id(source: str, source_message_id: str) -> str:
    return hashlib.sha1(f"{source}:{source_message_id}".encode()).hexdigest()


def upsert_session(conn: sqlite3.Connection, s: SourceSession) -> str:
    sid = session_id(s.source, s.source_id)
    conn.execute(
        """
        INSERT INTO sessions (id, source, source_id, project, branch, title, model,
                              created_at, updated_at, tokens_in, tokens_out, raw_meta)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source, source_id) DO UPDATE SET
          project=excluded.project, branch=excluded.branch, title=excluded.title,
          model=excluded.model, created_at=excluded.created_at, updated_at=excluded.updated_at,
          tokens_in=excluded.tokens_in, tokens_out=excluded.tokens_out, raw_meta=excluded.raw_meta
        """,
        (
            sid, s.source, s.source_id, s.project, s.branch, s.title, s.model,
            s.created_at, s.updated_at, s.tokens_in, s.tokens_out, json.dumps(s.raw_meta),
        ),
    )
    return sid


def replace_messages(
    conn: sqlite3.Connection, session_pk: str, source: str, msgs: list[SourceMessage]
) -> None:
    conn.execute("DELETE FROM messages WHERE session_id=?", (session_pk,))
    conn.executemany(
        """
        INSERT OR REPLACE INTO messages
          (id, session_id, role, parent_id, is_sidechain, model, created_at, parts, text)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                message_id(source, m.id), session_pk, m.role, m.parent_id,
                int(m.is_sidechain), m.model, m.created_at, json.dumps(m.parts), m.text,
            )
            for m in msgs
        ],
    )
    conn.execute("UPDATE sessions SET message_count=? WHERE id=?", (len(msgs), session_pk))


def rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")


def insert_link(conn: sqlite3.Connection, a: str, b: str, type: str, note: str | None = None) -> bool:
    cur = conn.execute(
        "INSERT OR IGNORE INTO links (a, b, type, note, created_at) VALUES (?,?,?,?,?)",
        (a, b, type, note, int(time.time() * 1000)),
    )
    return cur.rowcount > 0


def resolve_session(conn: sqlite3.Connection, prefix: str) -> sqlite3.Row | None:
    """Resolve a full or partial bta_ id. Returns row, None if no match.

    Raises ValueError(list of rows) on ambiguous prefix.
    """
    p = prefix.strip()
    if not p.startswith("bta_"):
        p = "bta_" + p
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (p,)).fetchone()
    if row:
        return row
    like = p.replace("%", "\\%").replace("_", "\\_") + "%"
    rows = conn.execute(
        "SELECT * FROM sessions WHERE id LIKE ? ESCAPE '\\' ORDER BY updated_at DESC", (like,)
    ).fetchall()
    if len(rows) > 1:
        raise ValueError(rows)
    return rows[0] if rows else None
