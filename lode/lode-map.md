# Lode map

- [summary.md](summary.md): what better-agent is, with a data-flow diagram
- [terminology.md](terminology.md): domain terms
- [practices.md](practices.md): invariants, adding a source, testing, CLI design (clig.dev), dependencies
- index/
  - [summary.md](index/summary.md): bta.db schema, FTS, links, search fallback
  - [ids.md](index/ids.md): session and message id derivation, prefix resolution
- sources/
  - [summary.md](sources/summary.md): the import pipeline and shared part normalization
  - [claude-code.md](sources/claude-code.md): reading the jsonl files and incremental import
  - [opencode.md](sources/opencode.md): v2 tables, dual-era fallback, auto-links
- handoff/
  - [summary.md](handoff/summary.md): intent spine, pack layout, output targets
- plans/
  - [backlog.md](plans/backlog.md): known gaps, including the clig.dev audit
- tmp/: session scraps (git-ignored)
