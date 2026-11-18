# better-agent

Local-first, searchable, linkable history for coding-agent sessions (Claude Code, OpenCode).

Agent sessions are short-lived and scattered across tools. `bta` imports them into one
local SQLite database, makes them full-text searchable, lets you link related sessions, and
renders paste-ready context packs for moving a conversation from one agent to another.

## Install

```sh
uv tool install .   # puts `bta` on your PATH
# development: uv run bta …
```

To uninstall, run `uv tool uninstall better-agent`. To delete the index too, run `rm -r ~/.better-agent`.

## Usage

```sh
bta import                     # import new and updated sessions, with a progress bar
bta list --since 7d            # recent sessions
bta search "bundle install"    # full-text search across all messages
bta show a1b2                  # header plus intent spine (your messages, in order)
bta show a1b2 --full           # full transcript
bta link a1b2 9f8e -t continuation --note "follow-up"
bta links a1b2
bta unlink a1b2 9f8e           # asks first; --force skips the question
bta handoff a1b2 --copy        # context pack to the clipboard (macOS)
bta handoff a1b2 --max-chars 20000
```

Session ids look like `bta_a1b2c3d4`. Any unique prefix works, with or without `bta_`.

Run `bta -h` or `bta <command> -h` for every flag and example, and `bta --version` for the version.

## Scripting

- Every command takes `--json`. Its output shape stays stable between versions.
- Results go to stdout. Errors, confirmations, and notes such as `no matches` go to stderr.
- `bta` exits 0 on success, 1 on a failure such as an unknown session id, and 2 on a usage error.
- Without a terminal, `unlink` exits 1 unless you pass `--force`.

## Design

- **Read-only index.** The tools' own files stay the source of truth. `bta` copies them into
  `~/.better-agent/bta.db` (SQLite with FTS5). Import is idempotent and incremental.
- **Deterministic ids.** `bta_<hash>` comes from `source:source_id`, so a re-import updates
  a session instead of duplicating it.
- **Deterministic handoffs.** There are no LLM calls. The context pack is built from the
  intent spine, the files touched, and the last thing the agent said.
- **Auto-links.** Import links OpenCode subagent (`parent_id`) and fork sessions automatically.

## Sources

| Source | What is read |
|---|---|
| Claude Code | `~/.claude/projects/*/*.jsonl` (only `user`, `assistant`, and `summary` events) |
| OpenCode v2 | `~/.local/share/opencode/opencode.db`, read-only (`session_v2`, `session_message`, `part`) |

To store the index somewhere else, set `BTA_HOME` (default `~/.better-agent`).

## Development

```sh
uv run pytest
```

Design notes for contributors and agents are in [`lode/`](lode/lode-map.md). CLI conventions follow [clig.dev](https://clig.dev/).
