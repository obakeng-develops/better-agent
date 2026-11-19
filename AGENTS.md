# Agent instructions

This project keeps its knowledge in a Lode (https://fjzeit.github.io/lode) at `lode/`.

- At session start, read `lode/lode-map.md`, `lode/summary.md`, and `lode/terminology.md`.
- Check `lode/lode-map.md` before you search the code.
- After changing behavior or structure, update the matching lode file so it describes the current state, not a changelog.
- Put session scraps and handovers in `lode/tmp/`, which is git-ignored.
- Run tests with `uv run pytest`.

## Working conventions

- One commit per logical change. Each commit passes `uv run pytest` on its own.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): summary`, for example `feat(resume): …`, `fix(switch): …`, `docs(lode): …`.
- No AI co-author or attribution lines in commits.
- When a feature or fix lands, bump `version` in `pyproject.toml`, run `uv sync`, commit as `chore(release): X.Y.Z`, and tag it `vX.Y.Z`. Push the tag once its PR is merged. The push runs `.github/workflows/release.yml`, which tests, builds and creates the GitHub release. Breaking changes bump the minor version while we're pre-1.0.
- Design every command and flag against [clig.dev](https://clig.dev/). The rules we apply are in `lode/practices.md`.
- Shape new work as a pitch in `lode/plans/` (problem, appetite, solution, rabbit holes, no-gos) before building it. Pitches marked "not scheduled" wait for the user's go-ahead.
- No new runtime dependencies beyond typer and rich without asking.
- The remote is `origin` on GitHub (`obakeng-develops/better-agent`). Changes go up as stacked PRs against `main`, one PR per logical change, each based on the one before. Push only when asked.
