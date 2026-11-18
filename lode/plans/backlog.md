# Backlog

Known gaps between the code, the README, and conventions. Nothing here is decided yet.

## Against clig.dev

See [../practices.md](../practices.md#cli-design).

- **`import` shows no progress** while parsing files. Only the FTS rebuild has a spinner, so a large first import looks stuck.
- **No examples in help text,** except on `link`.
- **The data folder ignores XDG.** It's `~/.better-agent` rather than `$XDG_DATA_HOME/better-agent`. Changing it is a breaking move, so pair it with a migration note.
- **`unlink` deletes without confirming.** Links made by hand can't be rebuilt from sources.

## Other

- **The README doesn't mention** `unlink` or `--max-chars`.
- **Reversed duplicate links.** `(a, b, type)` and `(b, a, type)` can both exist. See [../index/summary.md](../index/summary.md).
- **`--copy` works on macOS only** (`pbcopy`).
