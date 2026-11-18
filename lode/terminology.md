# Terminology

- **source**: an agent tool `bta` imports from. Stored as `claude-code` or `opencode`. The CLI also accepts `claude`.
- **source_id**: the session's id inside its source tool.
- **session id**: `bta_` plus the first 8 hex characters of `sha1("<source>:<source_id>")`. Commands accept a prefix, with or without `bta_`.
- **index**: the `bta.db` SQLite database. It's a disposable copy, never the source of truth.
- **part**: one block of a message, stored as JSON. The types are `text`, `thinking`, `tool_use`, and `tool_result`.
- **sidechain**: a Claude Code subagent message inside the parent session's file (`isSidechain`).
- **intent spine**: the user's own text messages in a session, in order, with sidechains and tool results left out. It's the core of `show` and `handoff`.
- **files touched**: file paths from write-type tool calls (`edit`, `write`, `multiedit`, `notebookedit`).
- **handoff pack**: deterministic markdown made from the header, goal, intent spine, files touched, and the last assistant text.
- **link**: an undirected relation between two sessions, with a type (`related`, `continuation`, `handoff`, `fork`, or `subagent`) and an optional note.
- **auto-link**: a link that import creates without being asked. That's a `subagent` or `fork` link from OpenCode's `parent_id` and `fork_session_id`, or a `handoff` link from a pasted pack.
- **pack origin**: the `bta_` id on a pack's `Session:` line. It tells import which session a pasted pack came from.
- **dual-era row**: an OpenCode `session_message` row whose parts exist only in the legacy `part` table.
- **BTA_HOME**: an env var that overrides the data folder (default `~/.better-agent`).
