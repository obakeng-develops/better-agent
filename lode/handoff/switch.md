# Switching agents

`bta switch --to <claude|opencode>` continues a session in the named provider. The required `--to` makes the destination explicit. The command imports, lets you pick the session, previews what will happen, asks, then replaces itself with the target provider (`os.execvp`). It starts in the session's project directory with the pack as its first message.

```mermaid
flowchart LR
  S[bta switch --to PROVIDER] --> I[run_import: incremental, ~0.7s]
  I --> P{--from?}
  P -- yes --> R[resolve_or_exit]
  P -- no --> L[sessions_in cwd and below, source != AGENT]
  L --> PK{interactive and >1?}
  PK -- yes --> PICK[pick_session]
  PK -- no --> LATEST[newest]
  R --> K[build_pack + SWITCH_FOOTER]
  PICK --> K
  LATEST --> K
  K --> D{mode}
  D -- --dry-run --> O[pack to stdout, command to stderr]
  D -- --yes --> X[chdir project, execvp agent]
  D -- default --> PV[preview_switch, confirm Y/n] --> X
```

## Modes

| Mode | Picker | Preview and confirm | Needs a TTY |
|---|---|---|---|
| default | when more than one session matches | yes, on stderr | yes. Without one it exits 1 and suggests `--yes` or `--dry-run`. |
| `-y`, `--yes` | no, takes the newest | no | no |
| `-n`, `--dry-run` | no, takes the newest | no. It prints the pack and command instead. | no |

The preview shows the session header, the last 10 requests with an `activity_line` under each (counts only, no commands), the live git summary, the pack size, the exact command, and the directory. `stdin_is_terminal()` is the single TTY check, so tests can stub it.

## Session choice

Without `--from`, the candidates are up to 9 recent sessions whose `project` is the current directory or a directory under it, and whose source isn't the target, newest first. From `~/Desktop/projects` you get sessions from every repo inside it; parents and siblings stay out. The picker shows the project path relative to the current directory when it isn't `.`. `bta switch --to opencode` never offers an OpenCode session. Paths are prefiltered in SQL with `lower()` and `LIKE dir || '/%'`, then confirmed by checking the project and each of its parents with `os.path.samefile`. That handles macOS's case-insensitive paths (`~/Desktop` and `~/desktop` are the same folder) and rejects `LIKE` wildcard matches from `_` or `%` in a path.

## Launch commands

| Target | argv | First message |
|---|---|---|
| Claude Code | `claude <pack>` | sent straight away |
| OpenCode | `opencode --prompt <pack> <project>` | fills the input box in 2.0.x; you press Enter |

OpenCode 2.0 stopped auto-submitting `--prompt` ([opencode#51135](https://github.com/anomalyco/opencode/issues/51135)). `switch` tells you to press Enter. Don't work around it with `opencode run`, which isn't interactive.

## Contracts

- Exits 1 when no session matches, when the project directory doesn't exist on this machine, or when the agent isn't on `PATH`.
- `SWITCH_FOOTER` comes after the pack. The pack still starts with `PACK_HEADER`, so the next import links the new session back as a `handoff` (see [summary.md](summary.md#handoff-auto-links)).
- There's no `--json`. A successful run hands the terminal to another program. `--dry-run` covers scripting.
- No clipboard is needed.

Related: [summary.md](summary.md), [../sources/summary.md](../sources/summary.md)
