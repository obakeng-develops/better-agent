# Pitch: GitHub releases from tags

Status: implemented in `.github/workflows/release.yml`. Reader: maintainers and people installing `bta`.

## Problem

Every release has a `vX.Y.Z` tag, but there's no GitHub release behind it. Nobody can see what changed between versions or download a built package without cloning the repo.

## Appetite

Small: one workflow file and the docs that point at it.

## Solution

Pushing a `v*` tag runs `.github/workflows/release.yml`, which does the following: (1) checks the tag matches `version` in `pyproject.toml`, (2) runs `uv run pytest`, (3) runs `uv build`, (4) creates the GitHub release with the wheel and sdist attached and notes generated from the merged PRs.

Running it by hand with a `tag` input releases a tag that already exists. That's how tags from before the workflow get a release.

## Rabbit holes

- A tag pushed before its PR merges releases code that isn't on `main`. Push the tag after the merge.
- A push only runs the workflow file that's in the tagged commit, so older tags need the manual run.

## No-gos

- No PyPI publishing yet. It needs a trusted publisher set up on PyPI first. Add a publish step when that exists.
- No changelog file. The release notes are generated from PR titles, which follow Conventional Commits.
