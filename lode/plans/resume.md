# Pitch: `bta resume` reopens a session in its own agent

Status: implemented in 0.7.2. Reader: `bta switch` users.

## Problem

After `bta switch` starts an agent and you exit it, there's no bta way back into that conversation. `bta switch --to claude` leaves out Claude Code sessions by design, and switching again would start a fresh handoff session instead of continuing the one you left. The agents' own flags work (`claude --resume`, `opencode --session`), but you have to know each tool's flag and be in the right directory.

## Appetite

Small: one command reusing the switch picker and launch, tests, docs.

## Solution

```sh
bta resume            # pick a recent session here or below, from either agent, and reopen it
bta resume a1b2       # reopen that session
bta resume -n         # print the command instead of running it
```

`resume` imports, picks a session the same way `switch` does but from both agents, then runs the agent's own resume in the session's project directory:

| Source | argv |
|---|---|
| Claude Code | `claude --resume <source_id>` |
| OpenCode | `opencode --session <source_id> <project>` |

The picker is the confirmation. With one candidate, or no terminal, it takes the newest. There's no preview and no pack, because nothing new is created.

## Rabbit holes

- Claude Code finds sessions by the current directory, so the command must `chdir` to the project first, as `switch` does.
- Session choice must stay one function shared with `switch`: `sessions_in` with no excluded source.

## No-gos

- No `--to`. Resuming in a different agent is `switch`.
- No `--json`. It hands the terminal to another program, like `switch`.
