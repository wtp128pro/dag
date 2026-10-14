# Changelog — dag marketplace

All notable changes to this marketplace are documented here.
Individual plugins also maintain their own changelogs.

## [1.0.19] — 2026-10-14

- **`dag` 1.14.0 → 1.15.0 — blast radius.** Five offline post-hoc predicates — `I60` write scope,
  `I61` wave write disjointness, `I62` impact settled, `I63` end re-run, `I64` integration — and an
  exit-neutral summary NOTE (`N-I65`), armed only on runs stamped 1.15.0 or later: a unit's captured
  file footprint must stay inside its declared write scope, same-wave units must not write the same
  path, every out-of-scope consumer a scan finds must be settled by the verifier, and at sign-off the
  declared checks are replayed and declared census counts compared at base and tip. Four
  standard-library scripts (`frame_match.py`, `footprint.py`, `impact_scan.py`, `integrate.py`), four
  schemas, a persona, a template, 53 fixture runs, an `init_run.sh` blast stamp with a restamp refusal,
  a test-harness fix that keeps a user-site `jsonschema` visible, and a `state-machine.md` §5
  enumeration of the 1.14.0 predicates, whose §4 rows already existed.
- **Guarantee classifications.** I54 REVISES upward (`deliverable` required on runs stamped ≥ 1.15.0);
  I17 widened to anchor `frame` (PRESERVES below 1.15.0); Limitation AC boundary (iv) / Non-Goal 10
  REVISES — narrowed, not closed; Limitation AB narrowed for repository files; N-I45's `BLAST-T1` arm a
  narrow REVISES. The formal model and FSM spec are byte-unchanged (TLC 853 / 408 / depth 36, Alloy
  8/8). The migration notes are in the plugin changelog.
- **This repository's `.dag/blast.json`** declares three regression commands, three coupling rules, one
  census and one test surface for its own runs.
- **Limit:** the checks cover declared, visible surfaces only; cross-unit and integration blindness
  beyond them is not closed.

## [1.0.18] — 2026-08-09

- **`dag` 1.13.0 → 1.14.0 — drift and autonomy.** Ten offline post-hoc predicates (`I49`–`I54`,
  `I56`–`I59`) that let a run see what it is spending itself on: a `horizon` record so a dialogue's
  rejected alternative survives in the artifact, measurable plain-language prose bounds, a bounded
  per-unit projection contract for the orchestrator's context, an append-only directive ledger so an
  explicit maintainer request stops being indistinguishable from self-generated investigation, a
  **recomputed** deliverable clock, a cap on consecutive non-shipping units per requirement, an
  exit-neutral run-composition NOTE, and re-sequencing eligibility carrying the pre-amendment wave map
  that makes it decidable at all.
- **One declared REVISES.** A disjoint machine-decision channel lets a fully-automatic run reach
  `DONE` **without forging a human attestation** — previously honesty and completion were mutually
  exclusive. Every archived `signoff_confirmed: true` becomes permanently ambiguous, and that cannot
  be repaired; the migration argument is in the plugin changelog.
- **Two mechanisms deferred with stated adoption triggers** rather than quietly dropped, and two new
  orchestrator conduct rules — including one that is explicitly a **named gap**, not a mechanism:
  nothing bounds the orchestrator's own ad-hoc dispatches.

## [1.0.17] — 2026-08-06

- **`dag` 1.12.1 → 1.13.0 — the frozen case-set contract.** A brief may freeze a `case_set[]` of
  named checks, each carrying the observations it must be able to make and the observations it
  forbids, and a debrief must discharge every one back with an `outcome`, its `evidence` and a
  `non_vacuity` statement. Enforced by the new **`I48`**, an offline post-hoc predicate in eight
  clauses over emitted artifacts.
- **Guarantee classification.** The termination proof, **AO-1..7** and **I1..I47** are **PRESERVED**
  — `I48` adds no live guard to any transition, and none to the correction loop's sole back-edge.
  The invariant set is **REVISED** by the addition. **Migration:** `I48` is version-gated on
  `validator_version >= 1.13.0`, above the 1.12.1 release stamp, so it arms on zero archived runs;
  the suppressed arm is counted by the exit-neutral `N-I45` skew NOTE. This is why the plugin bump is
  a **minor** and not a patch: below 1.13.0 the predicate is inert.
- **Schema additions are optional** (`brief.case_set[]`, `debrief.case_set_discharge[]`, the
  `verify.defects[]` adequacy route), so artifacts written against 1.12.x remain schema-valid.
- **Ships with its harness**: `i48_clause_matrix.py`, `i48_crash_class.py`, three counterfactual
  run-dir fixtures wired into `expectations.tsv`, and `U29`'s four standalone fixtures under
  `scripts/tests/`, deliberately left out of `expectations.tsv` so no pipeline behaviour changes.
- **No detection benefit is claimed and none was measured** — the archive shows no measured gain of
  that kind. The claim is consistency and legibility. Completeness or adequacy of a case set, and
  cross-unit blindness, stay open (`Limitation AC` boundary (iv)).
- **The iterate-over-`.get()` crash class is NOT closed by this release.** The same change **ADDED four** sites of that class and **CLOSED two**; **two survive**, at `validate_run.py:6698` and `:6705`, inside the very block this release arms — and the first is a **live abort**: a `1.13.0`-stamped run whose `brief.acceptance_criteria` is not an array now exits 1 with **no** `RESULT:` line, where 1.12.1 reported `RESULT: FAIL`. That sentence stands unweakened and now ships with the command that reproduces it, both arms, on a throwaway fixture run: `cd plugins/dag/skills/dag/scripts/tests && python3 -c "import sys,json,shutil,subprocess;sys.path.insert(0,'.');import u29_fixture_base as mk;R=lambda s,d:(shutil.rmtree(d,ignore_errors=True),mk.build(d,stamp=s),json.dump(dict(json.load(open(d+'/units/U01/brief.json')),acceptance_criteria=7),open(d+'/units/U01/brief.json','w')),subprocess.run(['bash','../validate_run.sh',d,'--quiet'],capture_output=True,text=True))[-1];[print(s,'rc=%d'%r.returncode,'RESULT: line ->',any(l.startswith('RESULT:') for l in (r.stdout+r.stderr).splitlines())) for s,r in ((s,R(s,'/tmp/abort_'+s)) for s in ('1.13.0','1.12.1'))]"` -> `1.13.0 rc=1 RESULT: line -> False` / `1.12.1 rc=1 RESULT: line -> True`, with `TypeError: 'int' object is not iterable` on stderr of the first (measured 2026-08-06). Census over the class, measured against this run's BASE commit and not against HEAD (`scripts/tests/i48_crash_class.py --census --file <copy>`): `f547aef` **190** -> `4fb475d` **194** -> `c9e5571` **192** -> `8bdf4d6` **192**. All four points are now **sha-pinned** — the fourth previously read a bare `HEAD`, which cannot date a working tree; re-measured 2026-08-06 and unchanged at 192. Published as the **gross**, not the net `+2`. Open, recorded as `.dag/learnings/L27` and `L29`; the repair is a separate change.
- Nine cross-run learnings persisted to the project store (`.dag/learnings/L22`–`L30`). **Eight**
  (`L22`–`L28`, `L30`) were carried over verbatim from the authoring run's ledger, each validated
  against `learnings.schema.json` before write into a slot verified free against `git show HEAD:`;
  the ninth, `L29`, was authored earlier in the same run directly into the store and was verified
  present by sha256 rather than written or pre-validated here.

## [1.0.16] — 2026-07-31

- **`dag` 1.12.0 → 1.12.1 — doctrine retractions.** Five surfaces that still asserted
  `init_run.sh` stamps `validator_version` once at scaffold time and never refreshes it now carry an
  inserted retraction: `references/state-machine.md` (the shipped payload, which contradicted the
  `validator_version` description shipped in `schemas/fsm-state.schema.json` by the same release),
  both loci in `wiki/14-validator-and-invariants.md` (previously containing no retraction at all),
  `wiki/15-artifacts-and-schemas.md`, and `CLAUDE.md`. Each states that `init_run.sh --restamp` shipped
  in 1.12.0 as a **flag plus the orchestrator protocol that calls it**, and that an **automatic**
  re-stamp on phase advance is **unbuilt**, not impossible.
- **Retract by insertion.** Every false sentence is left standing verbatim with the retraction
  appended, quoting the retracted clause **verbatim** rather than indicating it with a demonstrative —
  zero lines removed at any of the five loci.
- **`CLAUDE.md`'s merge procedure corrected in place**: `delete_branch_on_merge` is **disabled** on
  this repository, so a merge requires an explicit `--delete-branch` and may need
  `git remote prune origin` for a stale remote-tracking ref.
- Documentation only — no predicate logic, arming, severity, scope or schema changes, so every
  formal guarantee is **PRESERVED**.

## [1.0.15] — 2026-07-29

- **`dag` 1.11.0 → 1.12.0 — verification currency.** Five offline post-hoc predicates so a run can
  no longer end with verification open or superseded: **`I43`** (aggregated `verify.iteration` must
  equal `debrief.iteration`, with a carve-out that expires at sign-off), **`I44`** (sign-off obliges
  every executed unit to carry a current verify, at any phase, with a loud per-unit
  `accepted_incomplete` override), **`N-I45`** (exit-neutral version-skew visibility, completeness
  enforced by new `spec_check` SC8), **`I46`** (`converged: false` under a `PASS` is no longer
  dead data), and **`N-I47`** (an exit-neutral advisory NOTE when a unit's verification is complete
  and current but its ledger status is still non-terminal at sign-off). `validator_version`
  can be re-stamped on phase advance via the new `init_run.sh --restamp` flag, closing the
  self-reference by which a run escaped the invariant it shipped — the mechanism plus the
  orchestrator protocol that calls it, **not** an automatic re-stamp, which is unbuilt. Suite **389/0 on both backends**, `spec_check` **PASS 8 / NOTE 1 / FAIL 0**,
  `validate_run.py` insertion-only with the byte-identical-emissions test discharged by measurement
  (0 of 345 fixtures differ). Archive scan over this repository's 18 `.wip/` dirs (17 archived + 1
  in-flight): historically 1 archived run newly RED — the run under repair — and **currently 0**,
  the waived re-verification having discharged all 8 rows. Honest boundary filed as
  **Limitation AA** — these predicates make completeness legible, never true.

## [1.0.14] — 2026-07-29

### Changed
- **`dag` plugin → 1.11.0** — **cross-repo lessons intake**. 92 learnings from three independent
  `.dag/learnings` stores (BubbleBrain 33 · music 49 · dag 10) are distilled into **18
  orchestrator-conduct rules**, landing as a new lazy-loaded `references/orchestrator-conduct.md`
  (indexed by binding decision moment, every rule carrying qualified sources and an honest strength
  tier — exactly one rule is T3 and nine of eighteen rest on a single entry) plus **+33 net lines** of
  `SKILL.md` hooks: a **continuation contract** (only a human gate or a non-interactive halt-at-gate
  licenses a stop — a red validator does not), a **RESUME banner** for any unlicensed turn end, and
  **foreground-dispatch** guidance for wave dispatch. Two new **offline** validator invariants ship with
  it — **I41** (panel dissent accounting: a `PASS` over a dissenting panel member must carry a
  `panel_adjudication`, and re-polling the dissenter is forbidden) and **I42** (evidence digest
  integrity: `inputs_reviewed[]` sha256 digests re-hashed against disk) — both version-gated to
  `validator_version ≥ 1.11.0`, alongside an offline `scripts/normalize_artifacts.py` shape normalizer
  and 49 new fixtures (293 → **342**). **THREE REVISES are flagged, not silent**: the **AO-5** doctrine (a
  bounded intra-panel re-poll becomes a sanctioned pre-escalation path, capped by the existing
  `verify_rounds ≤ 3`), the **I16 verify artifact contract** (a `PASS` + dissent + no adjudication was
  valid, becomes invalid), and **AO-3's `DISAGREE` route** — SPLIT, since I41-2 *strengthens* AO-3 on
  `FAIL`-voting members but, as first written, also bound `DISAGREE`-voting members to cite a criterion,
  which is the route AO-3 itself mandates for a critique that cannot name one, leaving no compliant
  artifact; narrowed to `FAIL` members with **I41-2(c)** taking over, and the legality-*widening*
  direction of that correction disclosed. The I16 *predicate* is byte-untouched, and all three carry
  migration arguments in `references/formal-models.md`. Neither invariant guards `LT7`, so the correction-loop **termination
  proof is PRESERVED** and `formal/` is byte-untouched (the pinned TLC/Alloy counts stand without a
  re-run). See the plugin changelog for the full entry.

### Fixed
- **`SKILL.md` R-CONFIRM correction.** The Phase-2 DoD/Non-Goals confirmation paragraph called a bulk
  "confirm all" `AskUserQuestion` page *the happy path*, while `validate_run.py` **hard-FAILs exactly
  that** above four items under I36's DP-29 anti-stuffing bound — both shipped in the same commit
  (`91e473e`). The paragraph now prescribes `pages ≥ ceil(n/4)` and names the `(stuffing)` / `(pages)`
  FAIL labels.

## [1.0.13] — 2026-07-19

### Changed
- **`dag` plugin → 1.10.1** — residual cleanup + **Limitation-X hardening** atop the 1.10.0
  socratic-guardrail landing. A new OFFLINE **I39-7** optional-mirror cross-check requires
  `fsm-state.anchors_baseline_hash`, when present, to equal
  `dialogues.json.anchors_baseline.content_hash` (adoption-gated on presence; gates no transition,
  never guards `LT7` ⇒ **PRESERVES**) — it **narrows** Limitation X (coordinated-rewrite cost two files
  → three) but does **not** Close it (git remains the only mutation witness). Plus: the `N-I39`
  unstamped-disarm NOTE reworded for accuracy; the I35–I40 negative-fixture pins tightened to
  per-sub-clause parentheticals (CI regression-resistance); the L9 P7-revision fold-to-ceiling handling
  documented (**PRESERVES**, I4 unchanged); two stale in-comment line cites fixed; an AF-40-declined
  traceability note. TLA+/Alloy untouched (`formal/` byte-identical; the pinned model-check counts
  stand). See the plugin changelog for the full entry.

### Docs
- **Project wiki refreshed `1.9.0` → `1.10.1`** (catalog `1.0.11` → `1.0.13`): the socratic-guardrail
  invariants **I35–I40** + **I39-7**, the new `dialogues.json` artifact + schema, the ask-first /
  non-goal / anti-drift behavior, **Limitations U–X**, the updated fixture total (**293**), and
  re-resolved `validate_run.py` / `state-machine.md` line cites across the validator-and-invariants,
  artifacts, verification, accuracy, and formal-methods pages.

## [1.0.12] — 2026-07-18

### Changed
- **`dag` plugin → 1.10.0** — **Socratic-guardrail enforcement**: the run's front-of-run
  discipline becomes mechanically checkable via six new **offline** validator invariants
  **I35–I40**, across four pillars — **(P-A)** bounded multi-round Socratic dialogue-series
  solicitation recorded in a new machine-checkable `dialogues.json` transcript (+ schema);
  **(P-B)** consequential-gap **ask-first** (a logged default is illegal for a DoD, non-goal,
  scope, or acceptance gap — materiality-blind); **(P-C)** non-goal **solicitation + enforcement**
  (an unconditional forbid round plus a new `revise_anchors` amendment kind); and **(P-D)**
  anti-drift (membership-union semantics, an immutable anchor baseline, and `add_units` autonomy
  narrowing). Every predicate is **post-hoc/offline** — **none is a live LT7 guard** — so the
  correction-loop **termination proof is PRESERVED** and I1–I34 are unrelaxed. Groundwork is
  additive: new `dialogues.json` artifact + schema, additive schema/template deltas (every new
  field OPTIONAL), and ~88 new self-test fixtures; TLA+/Alloy models re-verified **unchanged**
  (pinned formal counts untouched). See `plugins/dag/CHANGELOG.md` for the full breakdown.
- Marketplace catalog version → 1.0.12.

## [1.0.11] — 2026-07-16

### Changed
- **`dag` plugin → 1.9.0** — **Depth & retrieval enforcement**: mandatory claim-type→source-tier
  retrieval standard with a declared fallback ladder; first-class SOURCES register (source
  cartography) feeding clarification and briefs; nine-dimension validator-checked clarification
  sweep + cartography-informed round (no quotas); human-gated depth tiers with non-negotiable
  floors and upward-only ratchet; per-unit retrieval obligations in briefs with verifier-side
  re-derived coverage checks (CB-1 bridge). Nine new offline invariants (I26–I34), ~60 validator
  self-test fixtures, zero formal-guarantee revisions (TLC/Alloy re-verified green).
- Marketplace catalog version → 1.0.11.

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
