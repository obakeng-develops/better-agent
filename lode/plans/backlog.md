# Backlog

Known gaps between the code, the README, and conventions. Nothing here is decided yet.

## Against clig.dev

See [../practices.md](../practices.md#cli-design).

- **The data folder ignores XDG.** It's `~/.better-agent` rather than `$XDG_DATA_HOME/better-agent`. Changing it is a breaking move, so pair it with a migration note.

## Other

- **Reversed duplicate links.** `(a, b, type)` and `(b, a, type)` can both exist. See [../index/summary.md](../index/summary.md).
- **`--copy` works on macOS only** (`pbcopy`).
