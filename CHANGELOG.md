# Changelog — dag marketplace

All notable changes to this marketplace are documented here.
Individual plugins also maintain their own changelogs.

## [1.0.1] — 2026-07-05

### Changed
- **`dag` plugin → 1.0.1** — copyright hardening + provenance/reproducibility docs
  (see [plugins/dag/CHANGELOG.md](plugins/dag/CHANGELOG.md)). No functional change.

### Added
- Root README: a nominative-use / non-affiliation **trademark note** and an **AI-provenance note**
  (built with Claude Code; design, direction, review, and curation by wtp128pro) that links to the
  reproducible formal-check steps so the formal-verification claims stand on their own.

## [1.0.0] — 2026-07-05

### Added
- Initial marketplace (`.claude-plugin/marketplace.json`).
- **`dag` plugin v1.0.0** — gated, multi-phase task-execution skill with Socratic
  personas, atomic work-unit decomposition + dependency DAG, budget-capped subagent
  executors, independent adversarial verification, formally-enforced invariants
  (JSON Schemas + FSM spec + runnable validator; TLA+/Alloy formal-model layer),
  adaptive anti-hallucination evidence standards, and a durable
  plan/decision/progress/learnings ledger.
  See [plugins/dag/CHANGELOG.md](plugins/dag/CHANGELOG.md).
