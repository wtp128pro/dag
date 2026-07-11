# Changelog — dag marketplace

All notable changes to this marketplace are documented here.
Individual plugins also maintain their own changelogs.

## [1.0.10] — 2026-07-11

### Changed
- **`dag` plugin → 1.8.0** — **Guardrail & clarification enforcement**: the run's own declared
  guardrails (DoD items, non-goals, ambiguity resolutions) become mechanically checkable via six new
  **offline** validator invariants **I20–I25** — per-unit `dod_refs`/`non_goal_refs` binding with
  graph↔brief mirror consistency (I20/I21), a `guardrail_compliance` attestation block on
  verdict-bearing verifies where a **`violated` row on a PASS verdict is a mechanical FAIL** (I22),
  P8 DoD/non-goal closure (I23), an ambiguity-register content floor (I24), and a
  resolution-required conditional for material resolved items (I25 — the release's **sole REVISES**,
  migration-argued). Groundwork: 4 schema changes (every new field OPTIONAL; nothing added to any
  required list) + 4 templates scaffolding adoption by default. Every predicate is
  **post-hoc/offline** (no live LT7 guard), so the correction-loop **termination proof is
  PRESERVED**; adoption is opt-in and pre-feature runs trip nothing (`legacy_prefeature_ok`).
  Fixtures grow **119 → 135**, swept on **both** backends; `spec_check` SC1–SC7 green. `SKILL.md` +
  `references/state-machine.md` mirror the new mechanics (incl. Limitations **L–O** and the
  version-skew postures: I20–I23 archive-silent, I24/I25 positive-evidence floors). See
  `plugins/dag/CHANGELOG.md` for the full per-WP breakdown. The in-repo `wiki/` intentionally
  remains at **1.7.0 / 1.0.9** this release (known lag; the wiki refresh is a follow-up).

## [1.0.9] — 2026-07-10

### Changed
- **`dag` plugin → 1.7.0** — **Audit round 2 (extra_check remediation)**: closes a second wave of
  reproduced holes the round-1 checkers could not see. The validator is **crash-hardened** (malformed
  amendment snapshots, a directory `GRAPH.md`, and duplicate `fsm-state.units[]` ids no longer traceback
  or become order-dependent). **Persona identity is enforced structurally** — new `I1c`
  (artifact↔graph persona reconciliation, maker ≠ checker), `I1d` (roster membership), and panel
  **independence** (distinct verifiers, none the executor). **Provenance & ledger truth**: an
  `origin.store` stamp is trusted only when corroborated by real store membership (forged self-stamps
  FAIL); a terminal ledger status with no `verify.json` fails closed; the ESCALATE fuel-origin is proven
  by structural fuel evidence, not dossier prose. `I14/AO-2` is **severity-scoped** (minor coverage-first
  observations reportable; blocker/major regressions on sealed criteria still FAIL). Report-side budget
  honesty is defined **per-unit** (`within_budget := tokens_consumed ≤ brief.budget_tokens`), runs carry
  a `validator_version` stamp under a documented version-skew policy, and the **formal harness now
  asserts** the TLC state counts + Alloy 8/8 (a gutted model FAILs instead of vacuously passing). Every
  new predicate is **post-hoc/offline** (no live LT7 guard), so the correction-loop **termination proof
  is PRESERVED**; `I14/AO-2` **REVISES** (coverage-first satisfiability). Fixtures grow to **119**, swept
  on **both** backends; `spec_check` SC1–SC7 green. See `plugins/dag/CHANGELOG.md` for the full per-WP
  breakdown.

## [1.0.8] — 2026-07-10

### Changed
- **`dag` plugin → 1.6.0** — **Validator hardening (extra_check remediation)**: closes ten reproduced
  false-PASS holes in the Bounded Graph Amendments enforcement and the core validator (baseline +
  reconciliation + records-required trigger; fuel seed anchor + `fuel_before`/`fuel_after` chain;
  per-kind amendment schema closure + split/child semantics + bookkeeping; frozen-content anchor of
  every executed unit against its `brief.json`; duplicate-unit-id detection; ledger↔verify cross-check;
  artifact-driven phase floor; forgery-proof learnings-import provenance; within-budget honesty;
  non-blank actionable-changes), documents the third ESCALATE origin (amendment-fuel exhaustion) and
  makes I9 status-aware, sweeps the drift (D1–D12) + SKILL.md operability (U1–U11), adds a negative
  fixture per previously-uncovered branch, and runs the fixture suite on **both** validator backends.
  Every new check is **post-hoc/offline** (no live LT7 guard) so the correction-loop **termination proof
  is PRESERVED**; the BGA pipeline bound and I17/I18/I19 **REVISE upward**. 106 fixtures green on both
  backends; SC1–SC7 PASS; TLC 853/408/depth 36 (2,923/1,608/depth 156 at MaxFuel=32); Alloy 8/8.

## [1.0.7] — 2026-07-10

### Changed
- **`dag` plugin → 1.5.0** — **Structured Spec Registry + Drift Checks (SSR)**: a descriptive, dev-time
  spec registry (`spec/fsm.json` + `spec/invariants.json`) recording the `state-machine.md` transition
  rows (T*/LT*) and the I* invariants as machine-readable data, plus a drift checker
  `scripts/spec_check.py` (**SC1–SC7**, wired into `scripts/run_tests.sh` as a clean-run step + a
  6-negative-fixture step) that diffs the FSM tables, dereferences schema constant-pointers, validates
  embedded worked examples, and presence-checks the TLA+ `\* spec:` pragma coverage. These are
  diff / dereference / presence (drift-detection) checks — **not** semantic proofs of correctness. Also
  ships a behaviour-neutral `validate_run.py` LABELS hoist and a `verify.md`-vs-schema dual-authority
  fix (schema authoritative). Dev-time only — `spec/` + `spec_check.py` are never on the skill's
  lazy-load path and SKILL.md gains no new runtime read; **PRESERVES** every guarantee (no FSM
  state/edge/guard, no schema constraint, no enforcement behaviour changed — proof: byte-identical
  64-fixture matrix on both backends + TLC 853/408/depth 36). See
  [plugins/dag/CHANGELOG.md](plugins/dag/CHANGELOG.md).

## [1.0.6] — 2026-07-10

### Changed
- **`dag` plugin → 1.4.0** — **Bounded Graph Amendments (BGA)**: the Phase-6 work graph may grow under
  mechanical constraints via append-only `amendments/A<NN>.json` records (`add_units`/`split_unit`/
  `add_edges` autonomous + DoD-traced; `cancel_unit` human-gated), over the not-yet-started future only,
  bounded by a monotone-decreasing fuel budget (total units ≤ N0 + fuel₀; exhaustion ⇒ ESCALATE). Five
  new **post-hoc/offline** invariants (**I3b/I3c** — also closing two pre-existing validator gaps: `waves`
  cross-check + dependency closure — and **I17/I18/I19**, none a live guard), a new `amendment.schema.json`
  (14 schemas), 10 new fixtures (**54 → 64**), and a machine-checked TLA+ liveness property **`Quiesce`**
  (TLC 853/408/depth 36; non-vacuous vs a keep-fuel mutant) plus a new Alloy `Amendment.als`. The per-unit
  correction-loop termination proof is **PRESERVED** verbatim; only the pipeline-level unit-count bound
  **REVISES** to N ≤ N0 + fuel₀ (fuel the same well-founded-counter shape as `retries`). See
  [plugins/dag/CHANGELOG.md](plugins/dag/CHANGELOG.md).

## [1.0.5] — 2026-07-06

### Changed
- **`dag` plugin → 1.3.0** — five-track audit remediation of the two skills (`dag`, `personas`):
  validator-enforcement gaps closed (PR-1), the learnings contract + Phase-0.5→G-personas deadlock
  fixed (PR-2), I12 selector semantics enforced with `phaseN` removed (PR-3), formal-model docs made
  honest (PR-4), skill instructions + debrief/verify/learnings schemas tightened (PR-5/PR-6), a
  hardened `personas` skill (PR-7), an executable HOME-isolated test harness `scripts/run_tests.sh`
  (PR-8), and a validator/shell/docs hygiene batch (PR-9). Three follow-ups add durable **per-unit
  `fsm-state.units[]` loop state** (D-02, *revises* I4's cross-check surface), **blessed per-panelist
  `verify_p*.json`** validate-if-present audit files (D-04), and a **mechanical Phase-8 sign-off gate**
  `gates.signoff_confirmed` required at `DONE` (D-06, *revises* the gate contract). All new enforcement
  is post-hoc/offline (no live guard on the sole `RETRY→EXECUTE` back-edge) → *preserves* the
  termination proof; the two *revises* carry migration arguments and TLC re-checks clean. See
  [plugins/dag/CHANGELOG.md](plugins/dag/CHANGELOG.md).

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
