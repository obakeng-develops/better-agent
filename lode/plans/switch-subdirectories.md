# Pitch: offer sessions from subdirectories in `bta switch`

Status: implemented in 0.7.1. Reader: `bta switch` users.

## Problem

From `~/Desktop/projects`, `bta switch --to claude` only offered sessions whose project is exactly `~/Desktop/projects`. A minute-old session in `~/Desktop/projects/better-agent` was missing, so the picker preselected an older, unrelated one. `bta list` showed the newer session, so the two commands disagreed.

## Appetite

Small: one matching rule, the picker label, tests, docs.

## Solution

Candidates are sessions whose project is the current directory or anything under it, newest first, still capped at 9. The picker shows the project path relative to the current directory when it isn't `.`, so you can see where the agent will start.

## Rabbit holes

- Case: macOS paths are case-insensitive. Prefilter in SQL with lowercase `LIKE`, confirm by walking the project's parents with `os.path.samefile`.
- `_` and `%` in paths are `LIKE` wildcards. The samefile check rejects false matches, so no escaping is needed.

## No-gos

- No cross-project picker (like `bta list`). Parent directories and siblings stay out.
- No new flag.
