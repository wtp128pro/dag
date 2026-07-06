# Changelog — dag marketplace

All notable changes to this marketplace are documented here.
Individual plugins also maintain their own changelogs.

## [1.0.4] — 2026-07-06

### Changed
- **`dag` plugin → 1.2.0** — verifier hardening + reproducible evidence + large-dataset
  partitioning: panel-of-3 with distinct correctness/reproduce/guardrail lenses is now the default on
  `high-stakes` units (discrete-majority aggregation — a split → DISAGREE, never softmax), a bounded
  loop-until-dry verify sweep and a coverage-first verifier mandate raise recall, I6's PASS clause is
  revised (a PASS may carry `minor` observations), a new post-hoc invariant **I16** enforces the panel
  discipline offline (gates no transition), and `references/data-partitioning.md` +
  `schemas/manifest.schema.json` add map-reduce-onto-the-DAG for large datasets. All node-internal →
  *preserves* the termination proof (only I6's PASS clause is a flagged content-rule revision). See
  [plugins/dag/CHANGELOG.md](plugins/dag/CHANGELOG.md).

## [1.0.3] — 2026-07-05

### Changed
- **`dag` plugin → 1.1.1** — corrective audit pass: the Alloy formal model is now executable and
  machine-checked (a partial `check` scope left `Persona` unbounded), doc↔validator drift fixed
  (`scope.expiry` grammar, the retry consumption-contract predicate), stale invariant ranges
  refreshed to `I1-I15`, dangling persona `pair_with` references resolved, and loose/unbacked prose
  removed. No functional or guarantee change (all edits *preserves*). See
  [plugins/dag/CHANGELOG.md](plugins/dag/CHANGELOG.md).

## [1.0.2] — 2026-07-05

### Changed
- **`dag` plugin → 1.1.0** — ships the bounded self-learning-loop layer (rings 02/03/04):
  post-hoc AO-2/AO-6 checks (`I14`/`I15`), across-run **project + user** learnings stores with
  expiry / decay / supersedes, a **global tag registry** (`04/G1`, flagged — guarantee-domain
  widening with the authored-vs-imported carve-out), `scope.model` narrowing (`04/G4`), an
  advisory principles-promotion NOTE (`04/G3`), and an advisory tier for imported cross-run
  learnings (`03/P4`). All additive and post-hoc; no FSM gating. Ring 05 (sharable / trust) is
  not included. See [plugins/dag/CHANGELOG.md](plugins/dag/CHANGELOG.md).

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
