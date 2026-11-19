# better-agent

`bta` keeps the history of your coding-agent sessions in one local database and moves a session from one agent to another. It supports Claude Code and OpenCode so far, and you can [add another agent](#adding-another-agent).

Each agent keeps its history in its own place and its own format. When you want to carry on a Claude Code session in OpenCode, you end up explaining the work again, and finding what you did last week means searching two places.

`bta` imports them into one SQLite database on your machine, makes every message full-text searchable and builds a summary of a session that you can hand to the other agent. It doesn't send anything anywhere and it doesn't call an LLM.

## Installing bta

```sh
uv tool install git+https://github.com/obakeng-develops/better-agent@v0.8.0
```

This puts `bta` on your PATH. Replace `v0.8.0` with any version from the [releases page](https://github.com/obakeng-develops/better-agent/releases), which also has the wheel and source for each one.

From a clone, run `uv tool install .` instead. While you work on `bta` itself, run it with `uv run bta …`.

To uninstall, run `uv tool uninstall better-agent`. To delete the index too, run `rm -r ~/.local/share/better-agent`.

## Switching agents

```sh
bta switch --to opencode                       # continue a Claude Code session in OpenCode
bta switch --to claude                         # continue an OpenCode session in Claude Code
bta switch --to opencode --yes                 # skip the picker and preview, take the latest session
bta switch --to claude --from a1b2 --dry-run   # print the pack and the command without running them
```

`switch` imports first, then lists recent sessions from the other agent in the current directory and the directories under it. When you pick one, it shows your requests with what the agent did for each, the live git state and the command it's about to run. If you confirm, it starts the other agent in the session's project directory with the pack as the first message.

Claude Code sends the pack straight away. OpenCode 2.0 puts it in the input box and you press Enter. The next `bta import` links the new session back to the old one as a `handoff`.

The pack is a summary of the session: your requests with the agent's activity under each, the files touched, the git state (branch, uncommitted changes and commits since the session started) and the agent's last reply. Its header tells the new agent to run `bta show ID --json` for the full history, which needs `bta` on your PATH.

## Resuming a session

When you exit an agent, `bta resume` takes you back into the same conversation:

```sh
bta resume                  # pick a session here and reopen it in the agent it came from
bta resume a1b2 --dry-run   # print the command without running it
```

It offers sessions from both agents and runs the agent's own resume (`claude --resume` or `opencode --session`) in the session's project directory. It doesn't send a pack or start a new session.

## Searching your history

```sh
bta import                    # import new and updated sessions
bta list --since 7d           # recent sessions
bta search "bundle install"   # full-text search across every message
bta show a1b2                 # the session header and your messages in order
bta show a1b2 --full          # the full transcript
bta handoff a1b2 --copy       # copy the pack to the clipboard
```

Session ids look like `bta_a1b2c3d4`. Any unique prefix works, with or without `bta_`.

## Linking sessions

```sh
bta link a1b2 9f8e -t continuation --note "follow-up"
bta links a1b2
bta unlink a1b2 9f8e   # asks first; --force skips the question
```

The link types are `related`, `continuation`, `handoff`, `fork` and `subagent`. Import adds some links for you: OpenCode subagent and fork sessions, and any session that starts from a pasted pack.

Run `bta -h` or `bta <command> -h` for every flag with examples, and `bta --version` for the version.

## Scripting bta

- Every command except `switch` and `resume` takes `--json`, and its output stays the same between versions. Those two hand your terminal to another program. Use `--dry-run` to script them.
- Results go to stdout. Errors, prompts and notes such as `no matches` go to stderr.
- `bta` exits 0 on success, 1 on a failure such as an unknown session id and 2 on a usage error.
- Without a terminal, `unlink` exits 1 unless you pass `--force`, and `switch` exits 1 unless you pass `--yes` or `--dry-run`.

## Understanding the index

`bta` only reads the agents' files. They stay the source of truth and you can rebuild the index from them at any time with `bta import --force`.

| Agent | What `bta` reads |
|---|---|
| Claude Code | `~/.claude/projects/*/*.jsonl`, only the `user`, `assistant` and `summary` events |
| OpenCode | `~/.local/share/opencode/opencode.db`, opened read-only |

The index is a SQLite database with FTS5 in `$XDG_DATA_HOME/better-agent`, which defaults to `~/.local/share/better-agent`. Set `BTA_HOME` to keep it somewhere else.

A session's id is a hash of the agent and the agent's own session id. Importing again updates the session instead of adding a copy. Packs come from the imported messages and the live git state, without an LLM.

Nothing in the index is redacted. Packs, transcripts and search results show messages exactly as they were written, so read a pack before you send it to anyone.

## Adding another agent

`bta` reads Claude Code and OpenCode today. To add another agent, you write an adapter for it: one module in `src/better_agent/sources/` that reads the agent's session files and hands them to `bta` in its shared format. Search, `show`, links and handoff packs then work for that agent with no other changes.

An adapter does the following: (1) finds the agent's sessions, (2) turns each one and its messages into a `SourceSession` and `SourceMessage` list, (3) saves them with `upsert_session` and `replace_messages`. It only ever reads the agent's files and never writes to them.

Then register it in `src/better_agent/cli.py`. Add it to the import loop in `run_import` and its name to `norm_source`. For `switch` and `resume` to work with it, also add the command that starts the agent to `agent_argv` and `resume_argv`, and its display name to `AGENT_NAMES`.

There's no plugin system, so adapters live in this repo and go in as a PR with a test. The full contract is in [`lode/practices.md`](lode/practices.md#adding-a-source), and `sources/claude.py` is the simpler adapter to copy from.

## Contributing

```sh
uv run pytest
```

Design notes for contributors and agents are in [`lode/`](lode/lode-map.md). Commands and flags follow [clig.dev](https://clig.dev/).
