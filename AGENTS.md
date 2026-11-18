# Agent instructions

This project keeps its knowledge in a Lode (https://fjzeit.github.io/lode) at `lode/`.

- At session start, read `lode/lode-map.md`, `lode/summary.md`, and `lode/terminology.md`.
- Check `lode/lode-map.md` before you search the code.
- After changing behavior or structure, update the matching lode file so it describes the current state, not a changelog.
- Put session scraps and handovers in `lode/tmp/`, which is git-ignored.
- Run tests with `uv run pytest`.
