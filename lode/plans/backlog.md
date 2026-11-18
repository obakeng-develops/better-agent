# Backlog

Known gaps between the code, the README, and conventions. Nothing here is decided yet.

- **`--to-lode` target folder.** It writes to `lode/handoffs/`, which is committed, but the Lode convention keeps handovers in `lode/tmp/`, which is git-ignored. Decide which one to follow. See [../handoff/summary.md](../handoff/summary.md).
- **README overstates `--json`.** It says every command takes `--json`, but only `list`, `search`, and `show` do.
- **The README doesn't mention** `unlink`, `handoff --to-lode`, or `--max-chars`.
- **Reversed duplicate links.** `(a, b, type)` and `(b, a, type)` can both exist. See [../index/summary.md](../index/summary.md).
- **`--copy` works on macOS only** (`pbcopy`).
