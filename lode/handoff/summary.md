# Handoff and show

`handoff.py` renders sessions for people and for other agents. It's pure: it takes rows in and returns a string, with no LLM involved. The user's own words carry their intent better than any generated summary, so the pack is built around the intent spine.

## Building blocks

- `intent_spine(messages)`: user messages that aren't sidechains and have a non-empty `text` part.
- `files_touched(messages)`: unique `file_path` or `filePath` values from `tool_use` parts whose name, lowercased, is in `WRITE_TOOLS = {edit, write, multiedit, notebookedit}`.
- `render_transcript(messages)`: role headings, text, and `> [tool: name] target` lines. It leaves thinking out on purpose.

## Pack layout (`render_handoff`)

```markdown
# Context handoff: <title>
Source: <source> (<model>) · Project: <path>
Session: bta_… · start → end · N messages
Related sessions: bta_… (type — note)
## Goal                      first spine message, ≤600 chars
## What was asked, in order  each spine message, ≤200 chars
## Files touched             ≤20, then "…and N more"
## Where things stand        last assistant text, ≤1500 chars
## Full transcript           only with --full
```

The whole pack is truncated to `--max-chars` (default 8000) and ends with a marker saying so.

## Output targets

```mermaid
flowchart LR
  H[bta handoff ID] --> D{flags}
  D -- none --> O[stdout]
  D -- --copy --> C[pbcopy, macOS only]
  D -- --to-lode --> L["<project>/lode/handoffs/<date>-<slug>-<id>.md"]
```

`--to-lode` needs the session to have a project path. It adds an HTML comment marking the file as temporary ("absorb into durable lode docs, then delete"). The Lode convention puts handovers in a git-ignored `lode/tmp/` instead (see [../plans/backlog.md](../plans/backlog.md)).

`bta show` prints the header and the numbered intent spine, or the full transcript with `--full`.

Related: [../terminology.md](../terminology.md), [../index/summary.md](../index/summary.md)
