# Practices

## Invariants

- **Read-only sources.** Never write to a tool's files. OpenCode is opened with `file:...?mode=ro`.
- **No LLM calls.** Every output is a pure function of the index. Add summaries only if they stay deterministic.
- **Idempotent import.** Re-importing upserts rows. Ids derive from `source:source_id`, so they never duplicate (see [index/ids.md](index/ids.md)).
- **Times are unix milliseconds** everywhere in the index and the models.
- **Whitelist, don't blacklist** source event types. Tool formats drift, and unknown events are skipped.

## Adding a source

Add a module under `src/better_agent/sources/` that exposes `do_import(conn, force, progress) -> dict`. Call `progress(done, total)` before each unit of work and once more at the end, so `bta import` can draw its progress bar. It normalizes to `SourceSession` and `SourceMessage` (`models.py`), then calls `dbm.upsert_session` and `dbm.replace_messages`. Add it to the `(name, module)` loop in `import_cmd` in `cli.py`. Normalize parts to the shared types so the handoff and transcript code keep working unchanged.

```python
sid = dbm.upsert_session(conn, session)
dbm.replace_messages(conn, sid, session.source, messages)
```

The returned dict carries `source`, `sessions`, `messages`, and `skipped`, plus optional `links`. `skipped == -1` means the whole source is unchanged.

## Testing

- Run `uv run pytest`. Tests build throwaway databases under `tmp_path`.
- Claude Code tests use `tests/fixtures/claude_sample.jsonl`.
- OpenCode tests create a fake `opencode.db` with the real table shapes (`session_v2`, `session_message`, `part`). Keep that schema in step with `sources/opencode.py`.
- CLI tests use typer's `CliRunner` with `BTA_HOME` set to `tmp_path`.

## CLI design

[clig.dev](https://clig.dev/) is the working guide for every command and flag. The rules that come up most:

- Primary output goes to stdout. Errors, confirmations, and empty-result notes go to stderr (`err` console in `cli.py`), so `bta links X | wc -l` counts only real results. `import`'s summary counts are its result, so they stay on stdout.
- Exit 0 on success and non-zero on failure. Typer exits 2 on usage errors, and `resolve_or_exit` exits 1.
- Every flag has a long form. Short flags are reserved for common options and keep clig's standard meanings, for example `-n` for `--dry-run` and `-f` for `--force`.
- Use the same flag names and output formats across subcommands. Any command with output worth scripting takes `--json`, and `--json` output stays stable.
- Changes are additive. Don't rename or repurpose a flag; add a new one.
- Bail out on bad input before any side effects.
- Destructive commands confirm first. `unlink` prompts on stderr, listing the link types it will remove, only when stdin is a TTY. Without a TTY it exits 1 and says to pass `-f/--force`. Nothing is asked when there's nothing to remove.
- Color is left to rich, which respects `NO_COLOR` and non-TTY output.
- Every command's help ends with 1 or 2 runnable examples, `@app.command(..., epilog=examples(...))`. A new command needs them too; a test checks it.

```python
@app.command("list")
def list_cmd(limit: int = typer.Option(30, "--limit"), as_json: bool = typer.Option(False, "--json")):
    ...
```

`--json` output shapes, which other scripts may depend on:

| Command | Shape |
|---|---|
| `list`, `search` | array of rows |
| `show` | `{session, messages, links}` |
| `links` | array of `{session, type, note}` |
| `link` | `{a, b, type, note, created}` |
| `unlink` | `{a, b, removed}` |
| `handoff` | `{session, pack, copied}` |
| `import` | array of `{source, sessions, messages, skipped, links, up_to_date}`. The internal `skipped == -1` sentinel becomes `up_to_date: true` with `skipped: 0`. |

Known gaps are listed in [plans/backlog.md](plans/backlog.md).

## Dependencies

The only runtime dependencies are typer and rich. Use the stdlib for everything else (`sqlite3`, `hashlib`, `json`). `--copy` shells out to the first clipboard tool on `PATH` (`CLIPBOARD_TOOLS`: pbcopy, wl-copy, xclip, xsel, clip.exe) and exits 1 if there's none.
