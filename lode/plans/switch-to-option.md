# Pitch: make the switch destination explicit

Status: implemented in 0.7.0. Reader: `bta switch` users.

## Problem

`bta switch opencode` can sound like switching away from OpenCode, even though the provider argument is the destination.

## Appetite

Small: one CLI argument change, tests, and documentation.

## Solution

Require an explicit destination option:

```sh
bta switch --to opencode
bta switch --to claude --from a1b2 --dry-run
```

Keep the session picker, preview, confirmation, and launch behavior unchanged. Do not keep the positional form as an alias.

## Rabbit holes

- Supporting both positional and option forms creates two ways to express the same destination.
- Renaming the `switch` command is unnecessary; `--to` resolves the direction ambiguity.

## No-gos

- Changing session selection or handoff behavior.
- Adding a `--from` provider option.

## Done means

The destination is required and validated before import or other side effects; help, examples, tests, README, and Lode describe the new syntax. `uv run pytest` passes.
