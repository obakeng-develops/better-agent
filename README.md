# better-traces

Local-first, searchable, linkable history for coding-agent sessions (Claude Code, OpenCode).

Agent sessions are ephemeral and fragmented across tools. `bt` imports them into a single
local SQLite db, makes them full-text searchable, lets you link related sessions, and
renders paste-ready context packs for moving a conversation from one agent to another.

## Install

```sh
uv tool install .   # gives you `bt` on PATH
# dev loop: uv run bt …
```

## Usage

```sh
bt import                     # scan sources, import new/updated sessions (incremental)
bt list                       # recent sessions
bt search "bundle install"    # full-text search across all messages
bt show bt_a1b2c3d4           # header + intent spine (your messages, in order)
bt show a1b2 --full           # full transcript
bt link a1b2 9f8e -t continuation -n "follow-up"
bt links a1b2
bt handoff a1b2 --copy        # context pack → clipboard, paste into another agent
```

Every command takes `--json` for scripting.

## Design

- **Read-only index.** The tools' own files remain the source of truth; `bt` normalizes
  copies into `~/.better-traces/bt.db` (SQLite + FTS5). Import is idempotent and incremental.
- **Deterministic ids.** `bt_<hash>` is derived from `source:source_id`, so re-imports
  upsert instead of duplicating.
- **Deterministic handoffs.** No LLM calls — the context pack is built from the "intent
  spine" (your own messages), files touched, and where the session left off.
- **Auto-links.** OpenCode subagent (`parent_id`) and fork relationships are linked at import.

## Sources

| Source | What is read |
|---|---|
| Claude Code | `~/.claude/projects/*/*.jsonl` (whitelists `user`/`assistant`/`summary` events) |
| OpenCode v2 | `~/.local/share/opencode/opencode.db`, read-only (`session_v2`, `session_message`, `part`) |

Override the db location with `BT_HOME` (default `~/.better-traces`).
