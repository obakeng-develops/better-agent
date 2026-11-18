# Practices

## Invariants

- **Read-only sources.** Never write to a tool's files. OpenCode is opened with `file:...?mode=ro`.
- **No LLM calls.** Every output is a pure function of the index. Add summaries only if they stay deterministic.
- **Idempotent import.** Re-importing upserts rows. Ids derive from `source:source_id`, so they never duplicate (see [index/ids.md](index/ids.md)).
- **Times are unix milliseconds** everywhere in the index and the models.
- **Whitelist, don't blacklist** source event types. Tool formats drift, and unknown events are skipped.

## Adding a source

Add a module under `src/better_agent/sources/` that exposes `do_import(conn, force) -> dict`. It normalizes to `SourceSession` and `SourceMessage` (`models.py`), then calls `dbm.upsert_session` and `dbm.replace_messages`. Wire it into `import_cmd` in `cli.py`. Normalize parts to the shared types so the handoff and transcript code keep working unchanged.

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

- Primary output goes to stdout. Errors and status messages go to stderr (`err` console in `cli.py`).
- Exit 0 on success and non-zero on failure. Typer exits 2 on usage errors, and `resolve_or_exit` exits 1.
- Every flag has a long form. Short flags are reserved for common options and keep clig's standard meanings, for example `-n` for `--dry-run` and `-f` for `--force`.
- Use the same flag names and output formats across subcommands. Any command with output worth scripting takes `--json`, and `--json` output stays stable.
- Changes are additive. Don't rename or repurpose a flag; add a new one.
- Bail out on bad input before any side effects.
- Color is left to rich, which respects `NO_COLOR` and non-TTY output.

```python
@app.command("list")
def list_cmd(limit: int = typer.Option(30, "--limit"), as_json: bool = typer.Option(False, "--json")):
    ...
```

Known gaps are listed in [plans/backlog.md](plans/backlog.md).

## Dependencies

The only runtime dependencies are typer and rich. Use the stdlib for everything else (`sqlite3`, `hashlib`, `json`). `--copy` shells out to `pbcopy`, so it works on macOS only.
