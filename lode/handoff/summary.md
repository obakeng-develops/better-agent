# Handoff and show

`handoff.py` renders sessions for people and for other agents. It's pure: it takes rows in and returns a string, with no LLM involved. The user's own words carry their intent better than any generated summary, so the pack is built around the intent spine.

## Building blocks

- `intent_spine(messages)`: user messages that aren't sidechains and have a non-empty `text` part.
- `files_touched(messages)`: unique `file_path` or `filePath` values from `tool_use` parts whose name, lowercased, is in `WRITE_TOOLS = {edit, write, multiedit, notebookedit}`.
- `render_transcript(messages)`: role headings, text, and `> [tool: name] target` lines. It leaves thinking out on purpose.

- `turns(messages)`: each spine message with the tool calls (counted by name) and shell commands the agent ran before the next one. Sidechains are left out. `activity_line` turns that into `Bash ×9 · Write ×2 · e.g. \`cmd\``.
- `git_state(project, since_ms)` (`gitstate.py`): branch, `git status --porcelain`, and `git log --since` the session started. It's read live, so it catches edits made through Bash that `files_touched` can't see. It returns None outside a repo. It's the only part of building a pack that runs a command, which keeps `handoff.py` pure.

## Pack layout (`render_handoff`)

The pack stays small, about 2–4k characters. The receiving agent pulls detail on demand through the `Full history:` line. `--full` shows tool names and targets, and `--json` has every part, including tool results.

```markdown
# Context handoff: <title>
Source: <source> (<model>) · Project: <path>
Session: bta_… · start → end · N messages
Full history: `bta show ID --full` … or `--json` …   in the header, so truncation never cuts it
Related sessions: bta_… (type — note)
## Goal                      first spine message, ≤600 chars
## What was asked, in order  each spine message, ≤200 chars
   → activity line           tool counts + first 2 commands
## Files touched             ≤20, then "…and N more"
## Git, at handoff           branch, uncommitted (≤20), commits since start (≤20)
## Where things stand        last assistant text, ≤1500 chars
## Full transcript           only with --full
```

When the pack is over `--max-chars` (default 8000), it first re-renders without the activity lines. Only then is it truncated, with a marker saying so.

## Output targets

```mermaid
flowchart LR
  H[bta handoff ID] --> D{--copy?}
  D -- no --> O[stdout]
  D -- yes --> C[first clipboard tool on PATH]
```

There's deliberately no option to write the pack to a file. A person pastes it with `--copy`, and an agent runs `bta handoff ID` and reads the output. Lode handovers are written by the agent, into `lode/tmp/`, from its own context, so `bta` doesn't write into a project's lode.

## Handoff auto-links

After any import that wrote messages, `link_handoffs` scans user messages (not sidechains) for `PACK_HEADER`. It reads the pack origin from the `Session:` line and links origin → new session with type `handoff`.

- Only `text` parts count. A `tool_result` that printed a pack (an agent ran `bta handoff`) never creates a link.
- Text before the pack is fine, such as "carry on from this:".
- It links only when the origin session is in the index. It's idempotent through `insert_link`.
- The pack format is the contract. Changing `PACK_HEADER` or the `Session: bta_… ·` line breaks detection for packs that are already pasted, so treat both as stable.

```python
SESSION_LINE = re.compile(r"^Session: (bta_[0-9a-f]{8}) ", re.M)
```

`bta show` prints the header and the numbered intent spine, or the full transcript with `--full`.

Related: [../terminology.md](../terminology.md), [../index/summary.md](../index/summary.md)
