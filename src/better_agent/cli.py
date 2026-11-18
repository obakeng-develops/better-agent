from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import db as dbm
from .handoff import intent_spine, render_handoff, render_transcript
from .sources import claude, opencode

app = typer.Typer(
    help="better-agent — local-first, searchable, linkable agent session history.",
    no_args_is_help=True,
)
console = Console()
err = Console(stderr=True)


# ---------- helpers ----------

def rel_time(ms: int | None) -> str:
    if not ms:
        return "-"
    secs = max(0, (time.time() * 1000 - ms) / 1000)
    for unit, div in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= div:
            return f"{int(secs // div)}{unit} ago"
    return "just now"


def parse_since(s: str) -> int:
    m = re.fullmatch(r"(\d+)([hdw])", s.strip())
    if not m:
        raise typer.BadParameter("--since looks like 24h, 7d, 2w")
    mult = {"h": 3600, "d": 86400, "w": 604800}[m.group(2)]
    return int((time.time() - int(m.group(1)) * mult) * 1000)


def norm_source(s: str) -> str:
    if s in ("claude", "claude-code"):
        return "claude-code"
    if s == "opencode":
        return "opencode"
    raise typer.BadParameter("source must be 'claude' or 'opencode'")


def slugify(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n].strip("-") or "session"


def resolve_or_exit(conn, prefix: str):
    try:
        row = dbm.resolve_session(conn, prefix)
    except ValueError as e:
        err.print(f"[red]ambiguous id {prefix!r} — matches:[/red]")
        for r in e.args[0][:10]:
            err.print(f"  {r['id']}  {r['title']}")
        raise typer.Exit(1)
    if row is None:
        err.print(f"[red]no session matches {prefix!r}[/red]")
        raise typer.Exit(1)
    return row


def session_to_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


def linked_sessions(conn, sid: str) -> list[tuple[object, str, str | None]]:
    rows = conn.execute(
        """SELECT s.*, l.type, l.note FROM links l JOIN sessions s
             ON s.id = CASE WHEN l.a = ? THEN l.b ELSE l.a END
           WHERE l.a = ? OR l.b = ? ORDER BY l.created_at""",
        (sid, sid, sid),
    ).fetchall()
    return [(r, r["type"], r["note"]) for r in rows]


# ---------- commands ----------

@app.command("import")
def import_cmd(
    source: str = typer.Option(None, "--source", "-s", help="claude | opencode (default: both)"),
    force: bool = typer.Option(False, "--force", help="re-import everything, ignore cached state"),
):
    """Scan known sources and import new/updated sessions."""
    conn = dbm.connect()
    if source not in (None, "claude", "opencode"):
        raise typer.BadParameter("--source must be 'claude' or 'opencode'")

    stats = []
    if source in (None, "claude"):
        stats.append(claude.do_import(conn, force=force))
    if source in (None, "opencode"):
        stats.append(opencode.do_import(conn, force=force))

    if sum(s["messages"] for s in stats):
        with console.status("rebuilding search index…"):
            dbm.rebuild_fts(conn)
            conn.commit()

    for s in stats:
        if s.get("skipped") == -1:
            console.print(f"[bold]{s['source']}[/bold]: up to date")
        else:
            extra = f", {s['links']} auto-links" if s.get("links") else ""
            console.print(
                f"[bold]{s['source']}[/bold]: {s['sessions']} sessions imported "
                f"({s['messages']} messages{extra}), {s['skipped']} unchanged"
            )


@app.command("list")
def list_cmd(
    source: str = typer.Option(None, "--source", "-s"),
    project: str = typer.Option(None, "--project", "-p", help="substring of project path"),
    since: str = typer.Option(None, "--since", help="e.g. 24h, 7d, 2w"),
    limit: int = typer.Option(30, "--limit", "-n"),
    as_json: bool = typer.Option(False, "--json"),
):
    """List sessions, most recently updated first."""
    conn = dbm.connect()
    where, params = [], []
    if source:
        where.append("s.source = ?"); params.append(norm_source(source))
    if project:
        where.append("s.project LIKE ?"); params.append(f"%{project}%")
    if since:
        where.append("s.updated_at >= ?"); params.append(parse_since(since))
    sql = f"""
        SELECT s.*, (SELECT COUNT(*) FROM links l WHERE l.a = s.id OR l.b = s.id) AS nlinks
        FROM sessions s
        {('WHERE ' + ' AND '.join(where)) if where else ''}
        ORDER BY s.updated_at DESC LIMIT ?
    """
    rows = conn.execute(sql, (*params, limit)).fetchall()

    if as_json:
        console.print_json(json.dumps([session_to_dict(r) for r in rows], default=str))
        return

    table = Table(show_lines=False)
    for col in ("id", "source", "project", "updated", "msgs", "title", "links"):
        table.add_column(col, overflow="fold")
    for r in rows:
        table.add_row(
            r["id"], r["source"], Path(r["project"] or "?").name, rel_time(r["updated_at"]),
            str(r["message_count"]), (r["title"] or "")[:60],
            f"⚭ {r['nlinks']}" if r["nlinks"] else "",
        )
    console.print(table)


@app.command("search")
def search_cmd(
    query: str,
    role: str = typer.Option(None, "--role", "-r", help="user | assistant"),
    source: str = typer.Option(None, "--source", "-s"),
    project: str = typer.Option(None, "--project", "-p"),
    limit: int = typer.Option(10, "--limit", "-n"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Full-text search across all imported messages."""
    conn = dbm.connect()
    filters, params = [], []
    if role:
        filters.append("m.role = ?"); params.append(role)
    if source:
        filters.append("s.source = ?"); params.append(norm_source(source))
    if project:
        filters.append("s.project LIKE ?"); params.append(f"%{project}%")

    def run(q: str):
        return conn.execute(
            f"""SELECT m.id AS mid, m.role, m.created_at, s.id AS sid, s.title, s.source,
                       snippet(messages_fts, 0, '[', ']', ' … ', 28) AS snip
                FROM messages_fts
                JOIN messages m ON m.rowid = messages_fts.rowid
                JOIN sessions s ON s.id = m.session_id
                WHERE messages_fts MATCH ? {'AND ' + ' AND '.join(filters) if filters else ''}
                ORDER BY rank LIMIT ?""",
            (q, *params, limit),
        ).fetchall()

    try:
        rows = run(query)
    except Exception:
        quoted = " ".join('"' + t.replace('"', '""') + '"' for t in query.split())
        rows = run(quoted)

    if as_json:
        console.print_json(json.dumps([dict(r) for r in rows], default=str))
        return
    if not rows:
        console.print("[dim]no matches[/dim]")
        return
    for r in rows:
        console.print(
            f"[bold cyan]{r['sid']}[/bold cyan] [{r['role']}] "
            f"[dim]{r['source']} · {rel_time(r['created_at'])}[/dim] {r['title']}"
        )
        console.print(f"  {r['snip']}\n")


@app.command("show")
def show_cmd(
    session_id: str,
    full: bool = typer.Option(False, "--full", help="print the whole transcript"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Show a session: header plus the intent spine (your messages, in order)."""
    conn = dbm.connect()
    s = resolve_or_exit(conn, session_id)
    messages = conn.execute(
        "SELECT * FROM messages WHERE session_id=? ORDER BY created_at, id", (s["id"],)
    ).fetchall()
    links = linked_sessions(conn, s["id"])

    if as_json:
        console.print_json(json.dumps({
            "session": session_to_dict(s),
            "messages": [dict(m) for m in messages],
            "links": [{"session": session_to_dict(o), "type": t, "note": n} for o, t, n in links],
        }, default=str))
        return

    console.print(f"[bold]{s['title']}[/bold]")
    console.print(
        f"[dim]{s['id']} · {s['source']}"
        + (f" ({s['model']})" if s["model"] else "")
        + f" · {s['project'] or '?'}"
        + (f" · ⎇ {s['branch']}" if s["branch"] else "")
        + "[/dim]"
    )
    console.print(
        f"[dim]{rel_time(s['created_at'])} → {rel_time(s['updated_at'])} · "
        f"{s['message_count']} messages[/dim]"
        + (f"[dim] · {s['tokens_in'] + s['tokens_out']:,} tokens[/dim]"
           if s["tokens_in"] is not None and s["tokens_out"] is not None else "")
    )
    if links:
        for other, ltype, note in links:
            console.print(f"[dim]⚭ {ltype}: [cyan]{other['id']}[/cyan] {other['title']}"
                          + (f" — {note}" if note else "") + "[/dim]")

    if full:
        console.print(render_transcript(messages))
        return

    spine = intent_spine(messages)
    console.print(f"\n[bold]Intent spine[/bold] ({len(spine)} messages)")
    for i, m in enumerate(spine, 1):
        text = " ".join(
            p.get("text", "") for p in json.loads(m["parts"]) if p.get("type") == "text"
        ).split()
        console.print(f"{i:>3}. [dim]{rel_time(m['created_at'])}[/dim] {' '.join(text)[:140]}")


@app.command("link")
def link_cmd(
    a: str,
    b: str,
    type: str = typer.Option("related", "--type", "-t",
                             help="related | continuation | handoff | fork | subagent"),
    note: str = typer.Option(None, "--note", "-n"),
):
    """Link two sessions (e.g. bta link a1b2 9f8e -t continuation)."""
    conn = dbm.connect()
    sa, sb = resolve_or_exit(conn, a), resolve_or_exit(conn, b)
    if sa["id"] == sb["id"]:
        err.print("[red]cannot link a session to itself[/red]")
        raise typer.Exit(1)
    created = dbm.insert_link(conn, sa["id"], sb["id"], type, note)
    conn.commit()
    if created:
        console.print(f"✓ {sa['id']} ⚭ {sb['id']}  [dim]({type}{' — ' + note if note else ''})[/dim]")
    else:
        console.print("[dim]link already exists[/dim]")


@app.command("links")
def links_cmd(session_id: str):
    """Show sessions linked to this one."""
    conn = dbm.connect()
    s = resolve_or_exit(conn, session_id)
    links = linked_sessions(conn, s["id"])
    if not links:
        console.print("[dim]no links[/dim]")
        return
    for other, ltype, note in links:
        console.print(
            f"[cyan]{other['id']}[/cyan] [dim]{ltype}[/dim] {other['title']}"
            + (f" — {note}" if note else "")
        )


@app.command("unlink")
def unlink_cmd(a: str, b: str):
    """Remove all links between two sessions."""
    conn = dbm.connect()
    sa, sb = resolve_or_exit(conn, a), resolve_or_exit(conn, b)
    cur = conn.execute(
        "DELETE FROM links WHERE (a=? AND b=?) OR (a=? AND b=?)",
        (sa["id"], sb["id"], sb["id"], sa["id"]),
    )
    conn.commit()
    console.print(f"removed {cur.rowcount} link(s)")


@app.command("handoff")
def handoff_cmd(
    session_id: str,
    full: bool = typer.Option(False, "--full", help="include the whole transcript"),
    max_chars: int = typer.Option(8000, "--max-chars"),
    copy: bool = typer.Option(False, "--copy", help="copy to clipboard instead of printing"),
    to_lode: bool = typer.Option(False, "--to-lode",
                                 help="write the pack into the project's lode/handoffs/ directory"),
):
    """Render a paste-ready context pack for continuing this session elsewhere."""
    conn = dbm.connect()
    s = resolve_or_exit(conn, session_id)
    messages = conn.execute(
        "SELECT * FROM messages WHERE session_id=? ORDER BY created_at, id", (s["id"],)
    ).fetchall()
    doc = render_handoff(s, messages, linked_sessions(conn, s["id"]), full=full, max_chars=max_chars)

    if to_lode:
        if not s["project"]:
            err.print("[red]session has no project path — cannot locate its lode[/red]")
            raise typer.Exit(1)
        lode_dir = Path(s["project"]).expanduser() / "lode" / "handoffs"
        lode_dir.mkdir(parents=True, exist_ok=True)
        date = time.strftime("%Y-%m-%d", time.localtime((s["created_at"] or 0) / 1000 or time.time()))
        path = lode_dir / f"{date}-{slugify(s['title'] or '')}-{s['id']}.md"
        note = ("<!-- Temporary handover generated by bta from "
                f"{s['source']} session {s['id']}. Absorb into durable lode docs, then delete. -->\n\n")
        path.write_text(note + doc, encoding="utf-8")
        console.print(f"✓ wrote {path}")
    if copy:
        subprocess.run(["pbcopy"], input=doc.encode(), check=True)
        console.print(f"✓ copied {len(doc):,} chars — paste it into your other agent")
    if not to_lode and not copy:
        console.print(doc, markup=False, highlight=False)
