# Changelog — dag marketplace

All notable changes to this marketplace are documented here.
Individual plugins also maintain their own changelogs.

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
