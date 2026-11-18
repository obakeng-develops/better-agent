from __future__ import annotations

import json
import re
import sqlite3
from importlib.metadata import version
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from . import db as dbm
from .handoff import intent_spine, link_handoffs, render_handoff, render_transcript
from .sources import claude, opencode

def examples(*lines: str) -> str:
    return "[bold]Examples[/bold]\n\n" + "\n\n".join(lines)


app = typer.Typer(
    epilog=examples(
        "bta import",
        'bta search "bundle install"',
        "bta handoff a1b2 --copy",
    ),
    help="better-agent — local-first, searchable, linkable agent session history.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console()
err = Console(stderr=True)


def show_version(value: bool) -> None:
    if value:
        console.print(f"bta {version('better-agent')}")
        raise typer.Exit()


@app.callback()
def main(
    _version: bool = typer.Option(False, "--version", callback=show_version, is_eager=True,
                                  help="Show the version and exit."),
):
    pass


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


def norm_source(s: str | None) -> str | None:
    if s is None:
        return None
    if s in ("claude", "claude-code"):
        return "claude-code"
    if s == "opencode":
        return "opencode"
    raise typer.BadParameter("must be 'claude' or 'opencode'")


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


def print_text(text: str) -> None:
    """Print text as-is: no markup, no highlighting, no wrapping at the terminal width."""
    console.print(text, markup=False, highlight=False, soft_wrap=True)


def print_json(obj) -> None:
    console.print_json(json.dumps(obj, default=str))


def session_to_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


def links_to_json(links) -> list[dict]:
    return [{"session": session_to_dict(o), "type": t, "note": n} for o, t, n in links]


def linked_sessions(conn, sid: str) -> list[tuple[object, str, str | None]]:
    rows = conn.execute(
        """SELECT s.*, l.type, l.note FROM links l JOIN sessions s
             ON s.id = CASE WHEN l.a = ? THEN l.b ELSE l.a END
           WHERE l.a = ? OR l.b = ? ORDER BY l.created_at""",
        (sid, sid, sid),
    ).fetchall()
    return [(r, r["type"], r["note"]) for r in rows]


# ---------- commands ----------

@app.command("import", epilog=examples("bta import", "bta import --source opencode --force"))
def import_cmd(
    source: str = typer.Option(None, "--source", "-s", callback=norm_source,
                               help="claude | opencode (default: both)"),
    force: bool = typer.Option(False, "--force", help="re-import everything, ignore cached state"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Scan known sources and import new/updated sessions."""
    conn = dbm.connect()

    stats = []
    with Progress(console=err, transient=True, disable=not err.is_terminal) as bar:
        for name, module in (("claude-code", claude), ("opencode", opencode)):
            if source not in (None, name):
                continue
            task = bar.add_task(name, total=None)
            stats.append(module.do_import(
                conn, force=force,
                progress=lambda done, total, task=task: bar.update(task, completed=done, total=total),
            ))

    handoff_links = 0
    if sum(s["messages"] for s in stats):
        handoff_links = link_handoffs(conn)
        with err.status("rebuilding search index…"):
            dbm.rebuild_fts(conn)
            conn.commit()

    if as_json:
        print_json([
            {"source": s["source"], "sessions": s["sessions"], "messages": s["messages"],
             "skipped": max(s["skipped"], 0), "links": s.get("links", 0),
             "up_to_date": s["skipped"] == -1}
            for s in stats
        ])
        return
    for s in stats:
        if s.get("skipped") == -1:
            console.print(f"[bold]{s['source']}[/bold]: up to date")
        else:
            extra = f", {s['links']} auto-links" if s.get("links") else ""
            console.print(
                f"[bold]{s['source']}[/bold]: {s['sessions']} sessions imported "
                f"({s['messages']} messages{extra}), {s['skipped']} unchanged"
            )
    if handoff_links:
        console.print(f"[bold]handoffs[/bold]: {handoff_links} new link(s)")


@app.command("list", epilog=examples(
    "bta list --since 7d",
    "bta list --project myapp --source claude --json",
))
def list_cmd(
    source: str = typer.Option(None, "--source", "-s", callback=norm_source,
                               help="claude | opencode"),
    project: str = typer.Option(None, "--project", "-p", help="substring of project path"),
    since: str = typer.Option(None, "--since", help="e.g. 24h, 7d, 2w"),
    limit: int = typer.Option(30, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
):
    """List sessions, most recently updated first."""
    conn = dbm.connect()
    where, params = [], []
    if source:
        where.append("s.source = ?"); params.append(source)
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
        print_json([session_to_dict(r) for r in rows])
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


@app.command("search", epilog=examples(
    'bta search "bundle install"',
    "bta search migration --role user --limit 20",
))
def search_cmd(
    query: str,
    role: str = typer.Option(None, "--role", "-r", help="user | assistant"),
    source: str = typer.Option(None, "--source", "-s", callback=norm_source,
                               help="claude | opencode"),
    project: str = typer.Option(None, "--project", "-p"),
    limit: int = typer.Option(10, "--limit"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Full-text search across all imported messages."""
    conn = dbm.connect()
    filters, params = [], []
    if role:
        filters.append("m.role = ?"); params.append(role)
    if source:
        filters.append("s.source = ?"); params.append(source)
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
    except sqlite3.OperationalError:
        quoted = " ".join('"' + t.replace('"', '""') + '"' for t in query.split())
        rows = run(quoted)

    if as_json:
        print_json([dict(r) for r in rows])
        return
    if not rows:
        err.print("[dim]no matches[/dim]")
        return
    for r in rows:
        console.print(
            f"[bold cyan]{r['sid']}[/bold cyan] [{r['role']}] "
            f"[dim]{r['source']} · {rel_time(r['created_at'])}[/dim] {r['title']}"
        )
        console.print(f"  {r['snip']}\n")


@app.command("show", epilog=examples("bta show a1b2", "bta show a1b2 --full"))
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
        print_json({
            "session": session_to_dict(s),
            "messages": [dict(m) for m in messages],
            "links": links_to_json(links),
        })
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
        print_text(render_transcript(messages))
        return

    spine = intent_spine(messages)
    console.print(f"\n[bold]Intent spine[/bold] ({len(spine)} messages)")
    for i, m in enumerate(spine, 1):
        text = " ".join(
            p.get("text", "") for p in json.loads(m["parts"]) if p.get("type") == "text"
        ).split()
        console.print(f"{i:>3}. [dim]{rel_time(m['created_at'])}[/dim] {' '.join(text)[:140]}")


@app.command("link", epilog=examples(
    "bta link a1b2 9f8e",
    'bta link a1b2 9f8e -t continuation --note "follow-up"',
))
def link_cmd(
    a: str,
    b: str,
    type: str = typer.Option("related", "--type", "-t",
                             help="related | continuation | handoff | fork | subagent"),
    note: str = typer.Option(None, "--note"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Link two related sessions."""
    conn = dbm.connect()
    sa, sb = resolve_or_exit(conn, a), resolve_or_exit(conn, b)
    if sa["id"] == sb["id"]:
        err.print("[red]cannot link a session to itself[/red]")
        raise typer.Exit(1)
    created = dbm.insert_link(conn, sa["id"], sb["id"], type, note)
    conn.commit()
    if as_json:
        print_json({"a": sa["id"], "b": sb["id"], "type": type, "note": note, "created": created})
        return
    if created:
        err.print(f"✓ {sa['id']} ⚭ {sb['id']}  [dim]({type}{' — ' + note if note else ''})[/dim]")
    else:
        err.print("[dim]link already exists[/dim]")


@app.command("links", epilog=examples("bta links a1b2"))
def links_cmd(
    session_id: str,
    as_json: bool = typer.Option(False, "--json"),
):
    """Show sessions linked to this one."""
    conn = dbm.connect()
    s = resolve_or_exit(conn, session_id)
    links = linked_sessions(conn, s["id"])
    if as_json:
        print_json(links_to_json(links))
        return
    if not links:
        err.print("[dim]no links[/dim]")
        return
    for other, ltype, note in links:
        console.print(
            f"[cyan]{other['id']}[/cyan] [dim]{ltype}[/dim] {other['title']}"
            + (f" — {note}" if note else "")
        )


@app.command("unlink", epilog=examples("bta unlink a1b2 9f8e", "bta unlink a1b2 9f8e --force"))
def unlink_cmd(
    a: str,
    b: str,
    force: bool = typer.Option(False, "--force", "-f", help="Remove without asking."),
    as_json: bool = typer.Option(False, "--json"),
):
    """Remove all links between two sessions. Asks first unless you pass --force."""
    conn = dbm.connect()
    sa, sb = resolve_or_exit(conn, a), resolve_or_exit(conn, b)
    pair = (sa["id"], sb["id"], sb["id"], sa["id"])
    types = [r["type"] for r in conn.execute(
        "SELECT type FROM links WHERE (a=? AND b=?) OR (a=? AND b=?)", pair
    )]
    if types and not force:
        if not sys.stdin.isatty():
            err.print("[red]unlink needs confirmation — pass --force to remove without asking[/red]")
            raise typer.Exit(1)
        typer.confirm(
            f"Remove {len(types)} link(s) between {sa['id']} and {sb['id']} ({', '.join(types)})?",
            abort=True, err=True,
        )
    cur = conn.execute("DELETE FROM links WHERE (a=? AND b=?) OR (a=? AND b=?)", pair)
    conn.commit()
    if as_json:
        print_json({"a": sa["id"], "b": sb["id"], "removed": cur.rowcount})
        return
    err.print(f"removed {cur.rowcount} link(s)")


@app.command("handoff", epilog=examples(
    "bta handoff a1b2 --copy",
    "bta handoff a1b2 --full --max-chars 20000",
))
def handoff_cmd(
    session_id: str,
    full: bool = typer.Option(False, "--full", help="include the whole transcript"),
    max_chars: int = typer.Option(8000, "--max-chars"),
    copy: bool = typer.Option(False, "--copy", help="copy to clipboard instead of printing"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Render a paste-ready context pack for continuing this session elsewhere."""
    conn = dbm.connect()
    s = resolve_or_exit(conn, session_id)
    messages = conn.execute(
        "SELECT * FROM messages WHERE session_id=? ORDER BY created_at, id", (s["id"],)
    ).fetchall()
    doc = render_handoff(s, messages, linked_sessions(conn, s["id"]), full=full, max_chars=max_chars)

    if copy:
        subprocess.run(["pbcopy"], input=doc.encode(), check=True)
    if as_json:
        print_json({"session": s["id"], "pack": doc, "copied": copy})
    elif copy:
        err.print(f"✓ copied {len(doc):,} chars — paste it into your other agent")
    else:
        print_text(doc)
