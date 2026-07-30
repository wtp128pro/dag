# Changelog — dag plugin

All notable changes to the `dag` plugin are documented here.
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.12.0] — 2026-07-29

**Verification currency — a run can no longer end with verification open or superseded.**
Five new **offline post-hoc** predicates over emitted artifacts. None is a live guard on any
transition and none guards `LT7`, so the correction-loop termination proof (Claims A–D) and
AO-1..7 are untouched.

- **`I43` verification currency** — for every unit carrying both artifacts, the aggregated
  `verify.json.iteration` must equal `debrief.json.iteration`. Four exhaustive arms
  (`SUPERSEDED`, `AHEAD`, in-flight `NOTE`, positive assertion). The in-flight carve-out mirrors
  I9's window **plus** a `signoff_confirmed is not True` conjunct — load-bearing, because the
  verbatim two-conjunct window catches **0 of 3** real defects while the third conjunct catches
  **3 of 3**. Domain is the aggregated verify **only**: `verify_p<N>.json` are a per-iteration
  audit trail that legitimately lags (precedent `2026-07-18_101631` U01, `verify_p1..p9` across
  three iterations). The durable claim about the implementation is the **code-line** one: over the
  I41/I42 region delimited by content anchors, `verify_p` occurs **0** times outside comments and
  **7** times including them — a comment-inclusive count is not zero and rises every time anyone
  documents the exclusion, this line included.
- **`I44` sign-off closure** — `gates.signoff_confirmed: true` obliges every executed unit to
  carry a present, parseable, verdict-bearing, current verify, **at any phase**, closing the
  stop-at-P6 escape. Artifact-keyed, never status-keyed. Ships as its own labelled predicate,
  **not** in `REQUIRED_GATES` (SC3 derives that from `spec/fsm.json.guards[]`, whose vocabulary
  cannot express a converse). Signing off knowingly stays **available but loud**:
  `fsm-state.accepted_incomplete` names **every** open unit with a rationale and a `DECISIONS.md`
  ref, downgrading each FAIL to a greppable NOTE — per-unit, no blanket form, fail-closed if
  malformed, over-broad NOTE if stale.
- **`N-I45` version-skew visibility** — exit-neutral NOTE counting the arms a run's own
  `validator_version` suppressed. New **`spec_check` SC8** mechanically enforces recorder
  completeness against the semver call sites, so a future site added without one goes red.
- **`I46` non-converged PASS** — `converged: false` under a `PASS` was dead data, read by nothing.
  NOTE below sign-off, FAIL at sign-off.
- **`N-I47` ledger desync at sign-off** (DoD 6) — an exit-neutral advisory NOTE, and nothing more,
  for a unit whose verification is complete and current while its `fsm-state.units[].status` is
  still non-terminal at sign-off. Four conjuncts, with the status test a **whitelist**
  (`pending`/`briefed`/`executing`/`verifying`) rather than `not in {passed, failed}`, so a closed
  outcome — `escalated`, `retired`, `blocked` — never arms an advisory. It names a **documentation**
  defect only: it neither infers the correct label nor re-checks the verdict.

**`validator_version` now re-stamps on phase advance** (`init_run.sh --restamp`, raise-only
ratchet, archive-safe on absent/malformed). This closes the self-reference by which the run that
authored I41 escaped being judged by it — measured: one digit, identical bytes,
`264/0/PASS → 264/8/FAIL`.

**Doctrine** in `SKILL.md` (new prime directive 8; Phase-6 repair-invalidates-panel with the
continue-the-numbering corollary; Phase-8 sign-off precondition), a worked member-by-member
section in `references/state-machine.md`, two REVISES filed in `references/formal-models.md`,
`CLAUDE.md`, and the wiki.

**Two flagged REVISES** with migration arguments: iteration equality becomes a normative verify
artifact contract, and `signoff_confirmed` acquires an artifact-level obligation (precedent: its
own addition to `REQUIRED_GATES` was itself a REVISES).

**Evidence, re-measured at the tip of the branch rather than at the release commit.** `run_tests.sh`
**389 passed / 0 failed on both backends**; `spec_check.py` **PASS 8 / NOTE 1 / FAIL 0**;
`normalize_artifacts.py --self-test` 0 failures; `validate_run.py` **insertion-only** (1033/0 vs
`main`) with the byte-identical-emissions test discharged by measurement — 345 pre-change fixtures
captured before/after, **0 differ, 0 exit codes changed**. Archive scan over this repository's 18
`.wip/` dirs (**17 archived + 1 in-flight**): **historically 1 archived run newly RED**, and it was
the run under repair; **currently 0**, because the maintainer-waived re-verification discharged all
8 rows — the property strengthens *a fortiori*, and the figure is a timestamped sample over a
gitignored tree, so re-measure rather than inherit it. **+47 expectation rows** (342 → 389) across
**+33 fixture directories** (343 → 376),
including the three an earlier dissent prescribed and never wrote
(`panel_downgrade_major_echo`, `digest_path_only_ok`, `panel_adj_nondict`), each pinned by
three-mutant ablation. Doctrine census corrected at **six** sites: **0/292**, **2179/2179**
(was 0/156, 964/964) — conclusion unchanged, denominators corrected. The sixth site is
`wiki/14-validator-and-invariants.md`, missed on the first pass because the coverage grep was scoped to
`plugins/` while `wiki/` sits at the repo root; the census command is now published self-contained (the
excluded run dir is named literally instead of left as a free variable `RUN`), and the "silent in both
arms" claim now carries its second ground explicitly — T1 arms on `validator_version ≥ 1.11.0` and the
maximum archived stamp is **1.10.1**, while the in-flight run is stamped **1.12.0**, so the zero is dated,
not structural.

**Erratum to the [1.11.0] entry (DIVERGENCE 8).** That entry's four-candidate enumeration read
"`DISAGREE`-without-`defects` fails I41-2", which is imprecise: `verify.schema.json` requires only
`[severity, criterion]` on a `defects` item, so I41-2(c) is satisfied by a non-blank `summary` **or** a
`defects` entry with a non-blank `minimal_repro` — a `DISAGREE` member *with* a `defects` entry that
carries neither still fails. **The predicate was always correct**; only the aside was wrong. Corrected in
substance at `references/formal-models.md:475` in 1.12.0, and corrected in place in the 1.11.0 body,
which was authored on this same unreleased branch (`main` carries no 1.11.0 entry and is still 1.10.1), so
no released header was relabelled and no shipped history was rewritten.

**Limitation AA (honest boundary).** These predicates make verification completeness *legible*,
never *true*. A loop that bumps both iterations without re-verifying satisfies I43 exactly; I44
proves a verify is current, not that verification happened; I46 is only as honest as an optional
field; `accepted_incomplete` records a human decision rather than validating it. Panel
independence and human-gate reality remain attestations.

**Residual R-I41-4** (found by *using* the shipped invariant): I41-4c and I41-4d contradict each
other for any re-poll that makes a verdict **stricter**. 4d requires `panel[]` to hold the final
vote; 4c then reads that final `FAIL` as "the dissenter was re-polled". Not fixed here —
weakening a shipped invariant is out of scope.

## [1.11.0] — 2026-07-29

**Cross-repo lessons intake** — 92 learnings from three independent `.dag/learnings` stores
(BubbleBrain 33 · music 49 · dag 10) distilled into 18 orchestrator-conduct rules, plus two new
**offline** validator invariants. **THREE guarantee changes are FLAGGED as REVISES**, each with a migration
argument in `references/formal-models.md` — the AO-5 doctrine, the I16 verify **artifact contract**, and
**AO-3's `DISAGREE` route** (AO-3 is SPLIT: its `FAIL` arm strengthens, its `DISAGREE` arm is revised).
The correction-loop **termination proof is PRESERVED**: neither new invariant guards `LT7`, both are
post-hoc reads of emitted artifacts, and `formal/` is byte-untouched (the pinned TLC/Alloy counts stand
without a re-run).

### Added
- **`references/orchestrator-conduct.md`** — a new lazy-loaded depth file carrying the reasoning behind
  18 cross-repo orchestrator rules, indexed by the decision moment each one binds. Every rule declares
  its qualified sources (`BB-`/`MU-`/`DAG-`, since the three stores number independently) and a
  **strength tier**; the file states plainly that exactly one rule is T3 and that nine of eighteen rest
  on a single entry, so a reader cites the tier rather than "the learnings say so". Rule id `R2` is left
  **vacant** (an earlier draft's rule had no corpus source and was retired). Read once at the head of
  Phase 3; `SKILL.md` carries only a one-or-two-line hook per rule at the moment it binds. Nothing here
  is a new invariant, state, edge or gate — it is orchestrator conduct at existing decision points.
- **I41 — panel dissent accounting (OFFLINE).** A `verify.json` with `verdict == PASS` and a dissenting
  `panel[]` member must carry a `panel_adjudication` recording the dissent, its disposition, and a
  rationale. A dissenting member must **substantiate** its vote: a `FAIL`-voting member names a
  criterion (I41-2a/b), while a `DISAGREE`-voting member records a non-blank `summary` **or** a
  `defects[]` entry with a non-blank `minimal_repro` and is **never obliged to name a criterion**
  (**I41-2c**) — because **AO-3** makes `DISAGREE` the mandated route for a critique that cannot name
  one, so binding it there would leave no compliant artifact. **I41-4c FORBIDS re-polling the dissenter**
  (or any lens that already tested the finding),
  so re-running to "win" a judgment call is now a hard FAIL where it was previously unconstrained. The
  presence floors arm only at `validator_version ≥ 1.11.0` (via `_i27_semver_ge` — proper semver, not a
  lexicographic string compare, which `panel_dissent_version_silent` pins); the shape clauses arm on
  adoption. Pins a previously-unspecified semantic: `panel[].verdict` holds the **FINAL** vote and
  `panel_adjudication.repoll[].pre_verdict` preserves the original.
- **I42 — evidence digest integrity (OFFLINE).** `inputs_reviewed[]` entries may now carry a sha256
  digest alongside the path; when they do, the validator re-hashes the run-dir-relative file and FAILs on
  a mismatch. I42-3 downgrades to a NOTE inside exactly the I9 transient window
  (`phase == P6_EXECUTE_VERIFY` ∧ the unit that owns the **digested path** is `executing`/`verifying`;
  a run-root path no unit owns leaves the phase conjunct to decide) and is a hard FAIL everywhere else,
  always at P8/DONE. The schema delta is a union **WIDENING** (`items` = string | object), so no archived
  verify becomes invalid — I42 carries **zero** REVISES.
- **`scripts/normalize_artifacts.py`** — an offline, idempotent, shape-only normalizer for landed
  `debrief.json` / `verify.json` pairs (key names, container types, enum casing). It gates nothing and is
  run before `validate_run.sh`, not instead of it. Sourced from `BB-L26`, `DAG-L2`, `MU-L32`: quoting the
  exact shape in a brief is necessary but not sufficient — subagents drift every wave.
  **Exit-code taxonomy — note the third code:** `0` normal (with or without changes/advisories, and for a
  readable non-artifact file, which is an advisory SKIP); `2` input error (missing path, undecodable JSON,
  non-object top level, unwritable target under `--write`, or a failing `--self-test`); **`3` CONTENT-GUARD
  VIOLATION** — normalizing would have destroyed a leaf value at its json path without recording it, so
  nothing is written. **`exit 3` fires in DRY RUN too**, so "non-zero only on unreadable input" does not
  describe this taxonomy; a `3` is a bug in the script, not in the artifact.
  The script hand-mirrors both schemas and **deletes** under `--write`, so it is coupled to
  `schemas/*.json`: every schema edit owes a `--self-test` re-run (now recorded in `CLAUDE.md`). The
  `panel_adjudication` (I41) addition in this same release proved the coupling live — it turned
  `--self-test` red (T7b/T7f) and made the script advise folding `panel_adjudication` into `audit_notes`,
  which would have destroyed an object I41-1 requires. Fixed here: the closed-key set, `required` lists and
  scalar types now mirror I41, and **T7a/T7d are bidirectional** (new `T7a2`/`T7d2`, matching `T7c`/`T7f`),
  so a schema pointer added in future is reported as unmirrored instead of going unchecked — the 8 enum and
  4 `required` pointers I41 added were previously invisible to the mirror test. `--self-test`: **73 pass,
  0 fail, exit 0**; the 371-artifact sweep is unchanged (0 changes · 0 drops · 0 guard violations,
  `diff -rq` byte-identical).
- **42 new test fixtures** (293 → 335 registry rows), including green controls that pin the OVER-fire
  direction a negative-only suite cannot see, and paired arms (`digest_mismatch` /
  `digest_mismatch_p6_note`) where neither alone pins the conjunctive I9 window.

### Changed
- **`SKILL.md` +33 net lines** (38 added / 5 removed) across eleven hunks, all one-or-two-line hooks at
  existing decision points:
  - **Continuation contract** — exactly two conditions license a stop (a human gate, a non-interactive
    halt-at-gate); a non-zero validator exit is **not** one of them (directive 7 bars *advancing* and is
    discharged by fix-and-re-run in the same turn). An unchosen boundary is *excused*, not licensed.
  - **RESUME banner** — a turn that ends unlicensed makes its last output
    `RESUME: <next action> — <resume point> — <trigger>`. The text says outright that prose cannot hold a
    turn open and does not pretend to; the durable guarantee is still the run dir.
  - **Foreground dispatch** — dispatch a wave with `run_in_background: false` whenever you need its
    results before continuing (for a dag wave, always); a background dispatch ends your turn there.
  - Hooks for R1/R3/R4/R5/R6/R7/R8/R9/R10 at their binding moments, and the Phase-3 read-once pointer.
- **Correction to the R-CONFIRM paragraph (`SKILL.md:384`).** The Phase-2 DoD/Non-Goals confirmation
  round described a bulk "confirm all" page as *the happy path* — while `validate_run.py` **hard-FAILs
  exactly that** above four items, under I36's DP-29 anti-stuffing bound. Both were shipped in the same
  commit (`91e473e`), so the always-read instruction file has been telling the orchestrator to do the one
  thing the validator rejects. The paragraph now says to plan `pages ≥ ceil(n/4)` from the start and
  names the `(stuffing)` / `(pages)` FAIL labels to grep for.

### Guarantee classification — THREE REVISES, flagged, not silent
- **AO-5 bounded intra-node re-poll — REVISES (doctrine, narrow); termination PRESERVES.** AO-5's prose
  says an objective-irresolvable split is `DISAGREE → ESCALATE`, "never an unbounded retry". I41 sanctions
  a **bounded intra-panel re-poll** before escalation, which that prose did not contemplate. Migration:
  the re-poll is capped by the **existing** `verify_rounds ≤ 3` bound (I16-(c), byte-untouched) — no new
  counter, no new fuel, no new edge; I41-4c forbids re-polling the dissenter, so the specific behavior
  AO-5 prohibits is now a hard FAIL; the escalation arm stays mandatory when no majority emerges; and
  AO-5's own subject (the *aggregate* executor↔verifier split) is untouched — I41 governs *intra-panel*
  dissent. Net effect, stated exactly: I41 narrows only the cases in which a dissent SURVIVES in
  `panel[]`'s final vote — a dissenter that rewrites its final vote to `PASS` and drops its `defects`
  arms zero clauses (Limitation Y(v)).
- **I16 verify ARTIFACT CONTRACT — REVISES (I25/GV-29 class); the I16 predicate PRESERVES
  (byte-untouched).** A `verify.json` recording `PASS` with a dissenting panel member and no
  `panel_adjudication` was **VALID** and becomes **INVALID**. Filed as a contract revision rather than
  smuggled in as a PRESERVES. Migration: version-gated to `≥ 1.11.0`; measured — the only archived
  dissent-on-PASS verifies live in a run stamped `1.9.0`, so **no archived run newly flags**; every schema
  delta is OPTIONAL, so no archived verify becomes schema-invalid; `templates/verify.md` scaffolds the
  block, so compliance is the default path; and the revision is strictly narrowing — no previously-FAILING
  artifact becomes legal. I16's majority test, lens-trio test, persona-independence test and
  `verify_rounds` bound are unchanged, and I41-4d *re-uses* `_discrete_majority` rather than replacing it.
- **AO-3's `DISAGREE` route — SPLIT: the `FAIL` arm PRESERVES (strengthens); the `DISAGREE` arm REVISES**
  (doctrine; the A2 no-compliant-path class). Extending "a `FAIL` names a criterion" to panel members is
  strictly additive — that half strengthens AO-3. But binding a **`DISAGREE`**-voting member to the same
  obligation closes the route AO-3's own text *mandates* for a critique that cannot name a criterion
  (`self-learning-loops.md:299-302`, `:601-604`), and then **no compliant artifact exists**:
  `FAIL`-without-criterion is schema-invalid, `FAIL`-with-a-fabricated-criterion is the hallucinated
  nitpick AO-3 forbids, `DISAGREE` with neither a `summary` nor a `minimal_repro`-bearing `defects` entry
  fails I41-2(c) (the schema requires only `[severity, criterion]` on a `defects` item, so *having*
  `defects` is not enough), and `DISAGREE`-with-a-criterion is the
  thing the panelist could not produce. That is the **A2 pathology verbatim**
  (`self-learning-loops.md:584-591`), which this repo filed as a REVISES rather than a tightening.
  Resolved the A2 way — **narrow the predicate, preserve its purpose**: `_I41_CRITERION_BOUND = ("FAIL",)`
  carries I41-2(a)/(b), new arm **I41-2(c)** substantiates a `DISAGREE` member, and a bare
  `{lens, verdict}` row still FAILs. Migration: the obligation bought **nothing mechanically** (I41-2 only
  ever checked the criterion string was non-blank, never that it appears among the brief's acceptance
  criteria); `_I41_DISSENT` is left **byte-untouched**, so I41-1, I41-4c and N-I41 keep treating a
  `DISAGREE` member as a full dissent — only the criterion obligation moves; and the correction's
  direction is stated rather than glossed: it is legality-**WIDENING**, over a set measured **empty** (no
  archived run is stamped ≥ 1.11.0, and **0** fixture dirs and **0** archived verifies carrying a
  `panel[]` record a `DISAGREE` member, so the withdrawn arm never fired on any artifact).

### Verification
- `run_tests.sh`: **342 passed / 0 failed on each of two schema backends** (jsonschema
  `Draft202012Validator`, and the stdlib-only minimal validator under `DAG_FORCE_MINI=1`); 6/0 negative
  fixtures. `spec_check.py`: **PASS 7 · NOTE 1 · FAIL 0**, exit 0.
- `validate_run.py` is **two pure-insertion hunks, +451 / -0** — confirmed by reconstructing the file
  minus the new hunks and getting a **byte-identical** match to `HEAD`, so every I1–I40 predicate is
  physically unmoved.
- A 67-arm predicate-ablation harness (each arm neutralizing exactly one conjunct/disjunct/branch/constant,
  asserted unique in the source, re-running the full 342-row matrix per arm): **unpinned = 0**, baseline
  clean.

## [1.10.1] — 2026-07-19

**Residual cleanup + Limitation-X hardening** — a follow-up to 1.10.0's socratic-guardrail landing.
**No shipped guarantee changes**; TLA+/Alloy are untouched (`formal/` byte-identical, the pinned
model-check counts stand) and I1–I34 are unrelaxed.

### Added
- **I39-7 — optional anchors-baseline mirror cross-check (Limitation X hardening).** When the OPTIONAL
  `fsm-state.anchors_baseline_hash` mirror is present, `validate_run.py` now requires it to equal
  `dialogues.json.anchors_baseline.content_hash`, raising the coordinated-rewrite cost from two run-dir
  files to three. The predicate is OFFLINE post-hoc, **adoption-gated on mirror presence** (absent ⇒
  silent, archive-safe), gates no FSM transition and never guards `LT7` ⇒ **PRESERVES**. Limitation X is
  **narrowed, NOT "Closed"** (git history remains the only mutation witness, unread). New fixtures
  `gov_baseline_mirror_ok` (present + matching ⇒ PASS) / `gov_baseline_mirror_mismatch` (present +
  mismatched ⇒ FAIL), registered under I39 in `spec/invariants.json`.

### Changed
- **N-I39 disarm-NOTE accuracy.** Reworded the unstamped-disarm NOTE to name only what actually disarms
  on an unstamped run — the I39-4 version-gated presence layer (item_confirmations/anchors_baseline
  requiredness) + the GV-34 baseline content-hash self-consistency — and to state that I39's
  adoption-armed content checks (confirmation/reconciliation/forbid-residue/replay) and **all I40
  mutation-gating** stay armed and still FAIL. (The prior wording over-claimed "mutation-gating … advisory".)
- **CI regression-resistance.** Tightened the 48 I35–I40 negative-fixture pins in
  `scripts/tests/expectations.tsv` from the coarse family stem to the per-sub-clause parenthetical, so a
  regression that fired the *wrong* clause is now caught (stem-sharing / prefix-colliding pins carry a
  body discriminator).
- **L9 documentation (PRESERVES).** Sanctioned the "fold `iteration` to the I4 ceiling (`retries+1`) +
  record the true pass count in prose" handling of a Phase-7-authorized post-exhaustion **in-place
  revision**, in `SKILL.md` (Phase 7) and `references/self-learning-loops.md` §1.3. **I4 is unchanged.**

### Fixed (docs)
- Corrected two stale in-`validate_run.py`-comment line-number cites (`I27`, `I8`) that pointed at the
  invariants' pre-insertion locations (comment-only; the byte-untouched guarantee is intact).
- Added an **AF-40-declined** traceability note to `references/formal-models.md` (the I8 clean-exit
  relaxation was declined — I8 kept LOUD, byte-untouched — so its absence from the classification table
  is intentional, not an omission).

## [1.10.0] — 2026-07-18

**Socratic-guardrail enforcement** — the pipeline's front-of-run discipline (Socratic
questioning, ask-before-assuming, non-goal solicitation, and anchor-stability) becomes
mechanically checkable via six new OFFLINE post-hoc validator invariants (**I35–I40**), across
four pillars: **(P-A) bounded multi-round Socratic dialogue-series** — clarification solicits a
bounded series of Socratic rounds recorded in a new machine-checkable `dialogues.json` transcript
(+ schema), so the questioning actually happened and is auditable rather than asserted; **(P-B)
consequential-gap ask-first** — a logged default is illegal for a Definition-of-Done, non-goal,
scope, or acceptance gap (materiality-blind: any such gap must be *asked*, never silently
defaulted); **(P-C) non-goal solicitation + enforcement** — an unconditional forbid round
solicits explicit non-goals, and a new `revise_anchors` amendment kind lets a run legitimately
amend its anchor set under the bounded-graph-amendment discipline; **(P-D) anti-drift** —
membership-union semantics, an immutable anchor baseline, and `add_units` autonomy narrowing keep
the executed graph from drifting off its confirmed anchors. All six predicates are OFFLINE/
post-hoc over emitted artifacts — **none is a live guard and none guards LT7** (the correction
loop's sole back-edge), so the per-unit termination proof (Claims A–D) is **PRESERVED**; AO-1..7,
I1–I34, the three-human-gates model, and the FSM edge set are unchanged. Groundwork is additive:
new `dialogues.json` artifact + schema, additive schema/template deltas (every new field
OPTIONAL, nothing added to any required list), and ~88 new self-test fixtures. TLA+ (TLC) and
Alloy models re-verified **unchanged** — the pinned formal counts are untouched.

## [1.9.0] — 2026-07-16

**Depth & retrieval enforcement** — retrieval effort and clarification depth become mechanically
checkable, closing the two behaviors that let runs go shallow: evidence standards gain a
four-tier source taxonomy (T-VENDOR/T-COMM/T-LOCAL/T-PARAM), a claim-type→tier table, a declared
fallback ladder (live-fetch → vendored-docs → cached-copy → parametric-only; silent skipping
unrepresentable), and claims-owed obligations fixed at briefing; source cartography becomes a
first-class artifact (`SOURCES.md` + `sources.json`, schema + template + init scaffold) with
tiers, per-source dispositions, venue admissions, and coverage claims feeding clarification and
briefs; Phase-2 clarification runs a nine-dimension sweep with per-dimension validator-checked
dispositions plus a cartography-informed second round (no question quotas); a human-gated run
depth tier (`light`/`standard`/`full`) rides the Phase-1 persona gate with non-negotiable
per-tier floors and an upward-only ratchet; briefs carry `required_sources`/`claims_owed`,
debrief evidence rows carry tier/rung/coverage fields, and verifiers emit a re-derived
`retrieval_coverage` block — retrieval failure is FAIL-able via the verbatim CB-1 bridge
criterion. Nine new OFFLINE validator invariants (**I26–I34**) with ~60 self-test fixtures; all
changes classified PRESERVES against the correction-loop termination proof, AO-1..7, I1–I25, the
three-human-gates model, and the FSM edge set (46/46, zero REVISES); TLC + headless-Alloy green
runs required before merge. New files: `schemas/sources.schema.json`, `templates/sources.md`.
No FSM state, transition, guard, or gate flag added; archived runs unaffected except I26's
documented version-skew posture.

## [1.8.0] — 2026-07-11

**Guardrail & clarification enforcement** — the run's own declared guardrails (Definition-of-Done
items, non-goals, ambiguity resolutions) become mechanically checkable: six new offline validator
invariants (**I20–I25**) bind work units to the DoD/non-goal registers, require verdict-bearing
verifies to attest guardrail compliance (a `violated` row on a PASS verdict is a mechanical FAIL — a
delivered non-goal is a defect, not a bonus), close the loop at P8, and put content floors under the
ambiguity register. Adoption is opt-in per run: every new schema field is OPTIONAL, nothing was added
to any required list, and a pre-feature-shape run trips nothing (proven by the `legacy_prefeature_ok`
fixture). **All six predicates are post-hoc/offline over emitted artifacts — no live guard on the
correction loop's sole back-edge LT7 — so the per-unit termination proof (Claims A–D) is PRESERVED.
I25 is the release's sole guarantee-REVISING change and carries a migration argument
(`references/state-machine.md` §4).**

### Added
- **Per-unit DoD / non-goal binding (WP-1, WP-2 / I20, I21)** — OPTIONAL `dod_refs` /
  `non_goal_refs` arrays on graph units (`graph.schema.json`) with mirrors on briefs
  (`brief.schema.json`). Once any unit adopts, I20/I21 enforce run-wide adoption closure, verbatim
  membership of every ref in `definition_of_done` / `non_goals`, and graph↔brief mirror consistency
  (fail-closed on missing, drifting, or malformed mirrors). `non_goal_refs: []` is a legal explicit
  none-applicable; an absent key under adoption is a closure FAIL.
- **Guardrail-compliance attestation (WP-3 / I22)** — new OPTIONAL `guardrail_compliance` block in
  `verify.schema.json` (rows `{non_goal, status: respected|violated|not-applicable, note?}`). Once
  any verdict-bearing verify carries it, I22 enforces closure over all verdict-bearing verifies,
  verbatim row membership in `non_goals`, coverage of the unit's `non_goal_refs`, and the bite: a
  `violated` row on a PASS verdict is a mechanical FAIL. Presence/shape only — whether a `respected`
  row is TRUE stays verifier attestation (Limitation L).
- **P8 DoD / non-goal closure (WP-4 / I23)** — at P8/DONE under adoption, every DoD item must be
  referenced by at least one PASS-verified unit and every non-goal must carry a
  respected/not-applicable attestation from a PASS unit; silent pre-P8.
- **Ambiguity-register floor (WP-5 / I24)** — an empty `ambiguity_register` after structural work
  exists is a FAIL (record real ambiguities or an explicit none-found item); a validator-only floor,
  no schema `minItems`.
- **Resolution-required conditional (WP-6 / I25)** — `clarifications.schema.json` gains an
  item-level conditional: a `material` item marked `resolved: true` must carry non-empty
  `resolution` text, with an I25 validator mirror (whitespace-only text also FAILs). **The sole
  guarantee-REVISING change of the release, migration-argued.** I24/I25 are deliberately NOT
  archive-silent (positive-evidence floors, `I-dod` precedent), while I20–I23 are archive-silent by
  construction — see the version-skew policy in `references/state-machine.md` §5.
- **Templates scaffold adoption by default** — `graph.md` (DoD-refs/Non-goal-refs table columns + a
  binding stanza), `brief.md` (the two header bullets + the sidecar-mirror note), `verify.md`
  (`guardrail_compliance` stanza incl. the violated+PASS=FAIL rule and the presence-not-genuineness
  boundary), `clarifications.md` (resolution-required stanza).
- **16 new fixtures** — the suite grows **119 → 135** on **both** schema backends, all mapped in
  `spec/invariants.json` (SC6): negatives across I20–I25 plus three green proofs
  (`guardrail_chain_ok` end-to-end adoption, `p8_adopted_preclose` pre-P8 silence,
  `legacy_prefeature_ok` no-retro-fail on a stamped pre-feature-shape run). `spec_check` stays
  PASS 7 / NOTE 1 / FAIL 0.

### Changed
- **Docs mirrored** — `SKILL.md`'s Phase 2/4/6/8 touchpoints now cite the mechanical counterparts
  (I24+I25 register discipline, I20/I21 binding, I22 attestation incl. the violated+PASS sentence,
  I23 closure + the `cancel_unit` remedy path); `references/state-machine.md` gains the six §4
  invariant rows (fixture coverage + PRESERVES/REVISES classification per row), the §5 enforce-list
  summary, Limitation letters **L–O** (row genuineness, vacuous resolution text, the all-minor
  dodge, adoption-boundary residuals), and the version-skew bullet for the new family.

## [1.7.0] — 2026-07-10

**Audit round 2 (extra_check remediation)** — a second reproduction-driven pass that closes what the
round-1 checkers could not see: validator crashes, discipline-only (declaration-only) persona identity,
provenance/ledger self-stamping, a coverage-first vs. anti-oscillation contradiction, prompt-side budget
drift, and a formal harness that asserted nothing. Every closed hole ships with a negative fixture +
`expectations.tsv` row + SC6 mapping, passing under **both** schema backends. **All new predicates are
post-hoc/offline over emitted artifacts — no live guard on the correction loop's sole back-edge LT7 — so
the per-unit termination proof (Claims A–D) is PRESERVED verbatim.**

### Added
- **Crash & order-dependence hardening (WP-A / B1, B3, B5)** — `amendment.schema.json` pins
  `retired_snapshot` item types (a `tags:7` snapshot no longer tracebacks I19; both backends), the
  `GRAPH.md` read is wrapped (a directory/dangling-symlink GRAPH.md is a fail-closed I3 defect, not a
  crash), and a new offline `I2 fsm units uniqueness` predicate rejects duplicate `fsm-state.units[]`
  ids (which made I9/I4 order-dependent). `run_tests.sh` gains a global no-traceback regression guard.
- **Structural persona identity (WP-B / C1, C2, C4)** — new offline predicates `I1c`
  (`debrief.persona == graph.executor_persona`, `verify.verifier_persona == graph.verifier_persona`, and
  the two distinct — maker ≠ checker at the artifact level), `I1d` (every working persona is a confirmed
  `personas.json` roster member), and an `I16` extension requiring panel members to be pairwise-distinct
  verifiers, none the executor. Mechanizes prime-directive #3 the same class as the round-1 `I1b`.
- **Run-version stamp + policy (WP-E / F1)** — `init_run.sh` stamps `fsm-state.json.validator_version`
  (new OPTIONAL schema field); `references/state-machine.md` §5 documents the version-skew policy
  (archived runs are judged against their contemporaneous validator; current-validator findings on
  older/unstamped runs are expected skew, not defects). The validator stays single-truth (no
  version-gated downgrades).

### Changed / Fixed
- **Provenance & ledger truth (WP-C / B2+A4, C3, C5, C6)** — an `origin.store` stamp is trusted ONLY
  when corroborated by real store membership (`store_ids` now records folded/shadowed ids); an
  uncorroborated self-stamp FAILs `I12 import provenance` (closing the B2 forgery + the A4 honest-fold
  false-positive with one mechanism). A terminal ledger status (`passed`/`failed`) with no valid
  `verify.json` fails closed (C5). The ESCALATE amendment-fuel origin is proven by **structural**
  evidence (`expansion.fuel_remaining == 0`), not a dossier substring grep (C3). A debrief with all
  `acceptance_self_check` `met:false` beside a verifier PASS is an advisory, non-gating NOTE (C6).
- **I14/AO-2 severity scoping (WP-D / A2, guarantee-REVISING)** — the `do_not_touch` intersection is
  scoped to `blocker|major` defects, so a minor coverage-first observation on a sealed criterion is
  reportable (advisory NOTE) while a blocker/major regression still FAILs — resolving the previously
  unsatisfiable coverage-first ↔ AO-2 tension. No archived run's verdict flips.
- **Per-unit budget honesty (WP-E / F2)** — `within_budget := tokens_consumed ≤ this unit's
  brief.budget_tokens` (not the global 32K) is now defined in `templates/debrief.md`,
  `debrief.schema.json`, and `SKILL.md`, matching the shipped `I5` check.
- **Spec/prose truthing (WP-D / A1, A3, A5–A12)** — fuel-seed wording, import re-grounding `since_wave`,
  the `expiry` "fails-OPEN" claim, the human-gate-flag qualification, the I10 graph-scope row, the
  high-stakes assignment criteria, the DESIGN.md schema-backed enumeration, the `init_run.sh` learnings
  header, and the P8/sign-off human-gate framing all corrected to match the shipped mechanics.
- **Formal harness integrity (WP-F / D1–D5)** — `run_formal.sh` now **asserts** the TLC state counts
  (853/408/36 and 2923/1608/156), the temporal-property line, and the literal `SUMMARY: 8/8`;
  `AlloyRun.java` takes an expected command count (killing the implicit-`Default` hole) and counts Alloy
  warnings as failures; arg parsing is robust; TLC's metadir is redirected to the cache (nothing written
  to the repo). Harness mutation probes confirm a gutted model now FAILs. The `formal-models.md`
  post-`Resolve` disclosure is corrected (disclosure-only; no model change).
- **Docs (WP-G / E4, E5)** — `plugins/dag/README.md` "Verify the formal claims" now leads with
  `bash scripts/run_formal.sh` (the one-command TLC + Alloy reproduction that shipped in **1.6.0** via
  commit `30e1c13`, previously uncredited in either changelog), keeping the manual TLC steps as the
  fallback; the root README layout gains `run_formal.sh`, `AlloyRun.java`, and the in-repo `wiki/` dir.

## [1.6.0] — 2026-07-10

**Validator hardening (extra_check remediation)** — closes ten reproduced false-PASS holes in the
Bounded Graph Amendments (BGA) enforcement and the core validator, plus two guarantee-narrative
contradictions, prose↔spec drift, test-coverage gaps, and stale docs. Every reproduced false PASS is an
anti-hallucination-layer defect (the "adversary" is the executing model drifting), so all are fixed
fail-closed. **All new predicates are post-hoc/offline over emitted artifacts — no live guard on the
correction loop's sole back-edge LT7 — so the per-unit termination proof (Claims A–D) is PRESERVED
verbatim; the BGA pipeline-level bound and the I17/I18/I19 surfaces REVISE upward (strictly stronger).**

- **BGA provenance backbone (B1/B2/B3):** immutable `graph.json.baseline_units` (schema-required once
  `revision > 1`) reconciled against the amendment records — `set(units[]) ∪ retired == baseline ∪ ⋃
  units_added`, retirement existence + disjointness + attribution; and a records-required trigger so
  amendment EVIDENCE (revision/applied/retired/fuel-spent) forces the `amendments/A<NN>.json` records to
  exist and stay in sync (deleting `amendments/` no longer launders provenance).
- **Fuel tamper-evidence (B4):** immutable `graph.json.fuel_initial` seed anchor + a per-record
  `fuel_before`/`fuel_after` chain from seed to `fuel_remaining` (widening fuel mid-run FAILs).
- **Amendment schema closure + semantics (B6/B7/G1/G2/G3/G12):** per-kind `allOf` closure (add_units /
  split_unit / add_edges / cancel_unit); split snapshot==retired, `criteria_map` targets ⊆ own children,
  ≥2 children; belt-and-braces dod_refs on any record that adds units; id uniqueness + id==filename +
  `graph_revision_after`==2+index + `expansion.amendments_applied`==|records| + `frontier_wave` teeth.
- **Frozen-prefix content anchor (B5):** every executed unit's graph entry must match its immutable
  `brief.json` (title/wave/deps/persona/tags/acceptance_criteria).
- **Core validator hardening (B8/G4/G5/G8/G9/G10/G11):** duplicate-unit-id detection; ledger status↔verify
  verdict cross-check; artifact-driven phase floor; forgery-proof learnings-import provenance
  (`origin.store`, not a `G#` id spelling); within-budget honesty vs the unit's own brief budget; fsm
  units ⊆ graph; non-blank `actionable_changes`.
- **Guarantee narratives (B9/B10):** the third ESCALATE origin (amendment-fuel exhaustion) is documented
  (prose + `spec/fsm.json` T10 `$comment` + formal-models note) and provenance-checked; I9 is status-aware
  (a mid-loop debrief-with-no-verify at P6 with fsm status executing/verifying is a NOTE, not a FAIL).
- **Drift, operability, harness, formal tidy:** D1–D12 prose/spec fixes; SKILL.md operability (U1–U11);
  one negative fixture per previously-uncovered branch; `run_tests.sh` now sweeps **both** backends
  unconditionally (`DAG_FORCE_MINI`); SC7 distinguishes modeled vs `spec-unmodeled` pragmas.

Proof: the fixture matrix grows to **106**, all green on **both** validator backends; `spec_check.py`
SC1–SC7 PASS; TLC re-verifies **853/408/depth 36 — No error** (and **2,923/1,608/depth 156** at
`MaxFuel=32`); Alloy **8/8** commands as-expected.

## [1.5.0] — 2026-07-10

**Structured Spec Registry + Drift Checks (SSR)** — a descriptive, dev-time spec registry plus a drift
checker that catch prose↔schema↔model drift at development time. Everything added is dev-time-only
test/CI infrastructure: no FSM state/edge/guard, no schema constraint, and no runtime-validation
behaviour changed, so every guarantee is **PRESERVED** verbatim (proof: a byte-identical 64-fixture
matrix on both validator backends + TLC **853/408/depth 36 No error**).

### Added
- **Structured Spec Registry + Drift Checks (SSR).** Added a descriptive, dev-time spec registry
  (`spec/fsm.json` + `spec/invariants.json`) that records the `state-machine.md` transition rows
  (T*/LT*) and the I* invariants as machine-readable data — a dev-time source-of-record, **NOT** a
  runtime artifact and **NOT** on the skill's lazy-load path.
- **Drift checker `scripts/spec_check.py` (SC1–SC7),** wired into `scripts/run_tests.sh` (a clean-run
  step + a negative-fixtures step): SC1 label↔registry, SC2 FSM-table row-diff, SC4 constant-pointer
  dereference `(authoritative: <schema>#/<path>)`, SC5 embedded worked-example validation, SC7
  `\* spec:` T*/LT* pragma presence-coverage in `Pipeline.tla`. All are diff / dereference / presence
  (drift-detection) checks — **not** semantic proofs of correctness (SC7 confirms each id is
  *mentioned* as a pragma, not that the action faithfully models the transition). Any drift folds into
  the harness fail gate (non-zero exit); six negative fixtures pin one FAIL apiece.

### Changed
- **Behaviour-neutral `validate_run.py` LABELS hoist** — check labels moved to a shared table so
  `spec_check.py` can cross-reference them; no runtime-validation behaviour changed.
- **Docs de-dup / consistency:** templates & embedded worked examples are now machine-validated against
  their schemas; the `verify.md`-vs-schema dual-authority ambiguity is resolved (schema authoritative,
  template illustrative). Descriptive notes added to `DESIGN.md` §9 (the L1 authoring-rule backstop),
  the `state-machine.md` header, and `formal-models.md` (the `\* spec:` pragma + SC7 presence-check).

### Guarantee classification
- **PRESERVES every guarantee:** no FSM state/edge/guard, no schema constraint, and no enforcement
  behaviour changed. `spec/` + `spec_check.py` are dev-time only; SKILL.md gains no new runtime read.
  Proof = byte-identical 64/64 fixture matrix on both backends, spec_check clean (SC1–SC7 PASS), and
  TLC 853/408/depth 36 / Alloy 6 checks + 2 runs all unchanged from baseline.

## [1.4.0] — 2026-07-10

**Bounded Graph Amendments (BGA)** — the Phase-6 work graph may now grow under mechanical constraints, so
discovered work no longer forces a full re-decomposition, a budget-breaching cram, or a silent DoD gap.
Amendments are append-only records (`amendments/A<NN>.json`) of four whitelisted kinds — `add_units` /
`split_unit` / `add_edges` (autonomous, DoD-traced) and `cancel_unit` (human-gated) — over the
**not-yet-started future only** (a unit whose correction loop has begun is frozen). A monotone-decreasing
**fuel** budget (`fsm-state.expansion`, schema max 32) bounds total units at N0 + fuel₀; fuel exhaustion
routes to ESCALATE. Every new invariant is **post-hoc / offline** — no FSM edge, no live guard on the sole
`RETRY→EXECUTE` back-edge (LT7) — so the per-unit correction-loop termination proof is **PRESERVED**
verbatim; only the pipeline-level unit-count bound is **REVISED** (fixed finite N → N ≤ N0 + fuel₀), with
fuel the identical well-founded-counter shape as `retries`.

### Added
- **`schemas/amendment.schema.json`** — the append-only amendment record (14 schemas total; self-check
  green on both the built-in and `jsonschema` backend). `graph.schema.json` gains optional `revision` /
  `amendments_applied` / `retired_units`; `fsm-state.schema.json` gains an optional `expansion` object and
  a `retired` unit status. All additive — the 54 legacy fixtures are byte-unchanged.
- **Five post-hoc validator invariants** in `validate_run.py`: **I3b** wave layering + **I3c** dependency
  closure (run whenever a graph is present — they also close two pre-existing gaps: `waves` was never
  cross-checked, and a dangling dep/edge endpoint was never flagged); **I17** frozen executed prefix,
  **I18** fuel bound (`fuel_remaining == fuel_initial − Σ fuel_cost ≥ 0` + revision/`amendments_applied`
  bookkeeping), **I19** amendment scope (`dod_refs` verbatim ∈ `definition_of_done` + human-gate on
  scope-change/cancel + split coverage). None gates a transition.
- **10 new fixtures** (54 → 64), swept on both backends: `amend_ok` (rev-3 graph: an `add_units` + a
  `split_unit`, correct fuel ledger, layered waves, retired parent kept brief-only) and nine negatives
  pinning `I3` / `I3b` / `I3c` / `I17` (×2) / `I18` (×2) / `I19` (×2).
- **Formal Property 5 — bounded-amendment quiescence.** `Pipeline.tla` gains a `MaxFuel` constant, a
  `fuel` variable, an `Amend` action, the `FuelBound` invariant, and the liveness property **`Quiesce`**
  `<>[](lstate ∈ {DONE,ESCALATE})`. TLC is green (**853 states / 408 distinct / depth 36**, up from
  715/328/28); a throwaway keep-fuel mutant fails `Quiesce` while still passing `Termination` — the
  external signal that `Quiesce`, not `Termination`, has teeth for BGA. New Alloy `formal/Amendment.als`
  proves amendment layering-preservation ⇒ acyclicity (headless, no counterexample); `WorkGraph.als`
  untouched.

### Changed
- Docs threaded end-to-end (authoring rule L1): SKILL.md Phase 4 fuel seeding + Phase 6 "Graph amendments
  (bounded)"; `state-machine.md` (I3b/I3c/I17/I18/I19 rows, a "no new transition" note, Limitations
  I/J/K); `self-learning-loops.md` §2 FLAG + §6.4; `formal-models.md` Property 5 + every stale TLC count
  updated; `methodology.md`, `data-partitioning.md` (BGA is **not** a dataset-sharding tool), `DESIGN.md`,
  `templates/graph.md` + new `templates/amendment.json`.

### Guarantee classification
- Per-unit correction-loop termination (Claims A–D): **PRESERVES** (verbatim — no loop edge/state/guard;
  only LT7 writes `retries`).
- Pipeline-level finiteness ("fixed finite N"): **REVISES** → N ≤ N0 + fuel₀ (fuel monotone-decreasing,
  schema-capped, validator-cross-checked; machine-checked by `Quiesce`).
- GateOrdering safety: **PRESERVES** (`Amend` guarded on `gate["P6"]=FALSE`, writes no phase/gate).
- I3 acyclicity: **PRESERVES + STRENGTHENS** (full-graph re-check per revision; I3b/I3c added).
- AO-1..7: **PRESERVES** (the frozen executed prefix forbids re-opening executed work).
- Live-guard prohibition (02/P1): **HONORED** (I3b/I3c/I17/I18/I19 are all offline predicates; violations
  route to a non-zero exit, never a transition guard).

## [1.3.0] — 2026-07-06

Five-track audit remediation of the two skills (`dag`, `personas`): thirteen work units run through
the pipeline itself, each with an independent adversarial verifier (distinct-lens panel-of-3 on the
guarantee-touching units). Every change classifies **preserves** vs **revises** the formal machinery
with a migration argument. All new enforcement is **post-hoc / offline** — no FSM edge is added and no
live guard is placed on the sole `RETRY→EXECUTE` back-edge (LT7), so the termination proof is
**PRESERVED**; the two **revises** (I4's cross-check surface, the gate contract) carry migration
arguments and TLC re-checks clean. The validator fixture suite grew from 48 to **54** explicit
fixtures (positive + negative, swept on both the built-in and the `jsonschema`-library backend).

### Added
- **Executable, HOME-isolated test harness** `scripts/run_tests.sh` (PR-8) — the repo CI: sweeps every
  `scripts/tests/` fixture via `tests/expectations.tsv` on each available validator backend, stubs
  `HOME` so fixture verdicts no longer depend on the operator's real `~/.claude/dag/` (IMP-16), and
  checks the `manifest.schema.json` instance pair.
- **Durable per-unit loop state (D-02 / IMP-11)** — `fsm-state.units[]` items may now carry optional
  `retries` + `loop_state`, so a parallel wave with >1 in-flight unit is durably representable (was an
  I2 ledger-is-truth gap); the top-level `loop` stays the back-compat most-recently-transitioned
  snapshot. **Revises** I4's cross-check surface (the per-unit `iteration ≤ retries+1` bound now
  applies to every unit that records `retries`, not just `loop.unit_id`) — offline, PRESERVES
  termination. Fixtures `units_loop_ok`, `units_loop_overrun`.
- **Blessed per-panelist verify files (D-04 / IMP-20)** — a panel MAY persist each member's full
  verify as `units/<U>/verify_p<N>.json`; the validator now validates them if present (same
  `verify.schema.json`, `executor_reasoning_seen: false`, `unit_id`-matching) as audit artifacts that
  never override the aggregated `verify.json`. Additive → **preserves**. Fixtures `panelist_files_ok`,
  `panelist_reasoning_seen`.
- **Mechanical Phase-8 sign-off gate (D-06 / BRK-13)** — new `gates.signoff_confirmed`, added to the
  validator's REQUIRED_GATES for `DONE`, so a run cannot reach `DONE` without recording the human
  sign-off (previously the validator could not tell sign-off happened). **Revises** the gate contract
  (a `DONE` run without the flag is now invalid — migration backfills every `DONE` artifact); offline
  gate-ordering predicate, no live LT7 guard, PRESERVES termination (`Pipeline.tla` already abstracts
  the P8 exit gate, so no TLA+ edit; TLC clean). Fixtures `signoff_ok`, `signoff_missing`.
- A hardened **`personas`** skill (PR-7): anchored cross-skill paths, corrected collision/corrupt-file
  flows, and index/phase-drift reconciliation.

### Changed / Fixed
- **Validator enforcement gaps closed (PR-1)** — four evasions closed plus robustness hardening
  (fail-closed predicates over emitted artifacts).
- **Learnings contract (PR-2 / D-01a)** — `G#` ids, `supersedes`, store hygiene, and the
  **Phase-0.5 → G-personas deadlock** fixed by dropping `learnings.json` from the `post_p1` trigger
  (**revises** G-personas — narrows one trigger, migration noted).
- **I12 selector semantics (PR-3 / D-03a)** — `all`, `U0X`, and `tag:` selectors are now enforced and
  an unknown selector kind hard-FAILs (BRK-08/09, previously a silent skip); the unimplementable
  `phaseN` selector is removed from the docs.
- **Formal-model truth (PR-4)** — the FAIL-origin escalation is now modeled and stale coverage claims
  are corrected.
- **Skill instruction completeness (PR-5 / D-07b)** and **schema tightenings (PR-6 / D-05a)** —
  overrun honesty (`tokens_consumed` may exceed budget only while self-identifying as over-budget),
  the retry `prior_feedback` echo is schema-required on retries (narrows Limitation F), the verify
  `disagreement` iff is fully schema-enforced, and the `scope.expiry` grammar is pinned.
- **Hygiene batch (PR-9)** — iterative cycle-DFS (no `RecursionError` on deep chains, byte-identical
  output), encoding/self-check robustness, JSON-safe/symlink-safe/single-clock shell hardening,
  gitignored TLC scratch metadir, a corrected `/plugin` update flow, and a completed DESIGN shipping list.

## [1.2.0] — 2026-07-06

Verifier hardening + reproducible evidence + large-dataset partitioning. Every change is
node-internal and classified **preserves** the termination proof and the AO-1..7 / I1..I15
invariants, with the **single exception** of I6's PASS clause, an explicitly-flagged **revises**
(content-rule) change carried with a migration argument. No FSM edge is added; no live guard is
placed on the sole `RETRY→EXECUTE` back-edge (all new enforcement is post-hoc/offline). The full
validator fixture suite's verdicts are unchanged and five new fixtures cover the new reachable states.

### Added
- **Panel-of-3 is the DEFAULT on `high-stakes` units**, with **distinct lenses** (correctness /
  reproduce / guardrail — not three clones), aggregated by **DISCRETE majority** (a no-majority split
  → `DISAGREE`, the AO-5 human route; **never** softmaxed). `high-stakes` is added to `V_tag`.
- **Loop-until-dry verify sweep**, bounded at `R_max = 3` rounds (accumulate defects until a round is
  dry or the cap). New optional `verify.json` fields `panel[]`, `verify_rounds`, `converged`.
- **Post-hoc invariant I16** in `validate_run.py` (offline; **gates no transition**): a high-stakes
  unit must carry a `panel[]` (≥3, trio covered); any panel's top verdict must equal the discrete
  majority; `verify_rounds ∈ [1,3]`.
- **`references/data-partitioning.md`** + **`schemas/manifest.schema.json`** — map-reduce onto the
  DAG for datasets larger than a unit's 32K budget: partition the *work* not the *context*, the
  mechanical-uniform-vs-judgment-heavy fork, parametric map waves + a reduce tree, verify-by-re-run+
  diff, an aggregate-ledger index (migration note), and the non-independent-shard hard case.
- Five fixtures: `panel_high_stakes_pass`, `panel_missing`, `panel_majority_mismatch`,
  `pass_with_minor`, `pass_with_major_rejected`, plus `manifest_examples/`.

### Changed
- **Verifier mandate is now coverage-first** (`templates/verify.md`, methodology §Verification, SKILL
  Phase 6): report *every* finding with its severity; no "only high-severity" filter that suppresses
  recall — triage happens downstream.
- **I6 PASS clause REVISED (flagged revises + migration note):** a `PASS` may now carry `minor`
  observations but not a blocker/major defect (was `defects==[]`). Verdict enum + the §1.3/§2
  partition are unchanged, so termination is preserved.
- **Phase 4 atomicity tightened** ("independently verifiable *within 32K*"; the budget is a
  reasoning budget, not a data budget) and **`evidence-standards.md`** now prefers
  executable/reproducible evidence (re-run test, diff output, re-derive number) over asserted
  evidence — model-independent, and the prerequisite for data-parallel verify.
- `references/state-machine.md`, `references/self-learning-loops.md`, and
  `references/formal-models.md` updated to record I16, the I6 revision (+ Limitation H), and the
  PRESERVES classification (TLA+/Alloy models need no edit).

## [1.1.1] — 2026-07-05

### Fixed
Corrective audit pass over the skill. No functional or guarantee change — every edit is classified
*preserves* (TLC and Alloy are both green before and after; the full validator fixture suite's
verdicts are unchanged).

- **Alloy model made executable and machine-checked.** `formal/WorkGraph.als`'s `check Acyclic` and
  `check LayeringImpliesAcyclic` used a partial scope (`for 7 Unit, 5 Int`) that left `Persona`
  (reachable via `Unit.executor`) unbounded, so the commands could not run. Changed to
  `for 7 but 5 Int`; all four `check`s now report no counterexample and `run WitnessGraph` finds an
  instance (Alloy 6 / Kodkod / bundled SAT4J, headless). `references/formal-models.md` tool-status
  updated from "not run / hand-proved" to machine-checked.
- **Doc↔validator drift corrected.** The `scope.expiry` grammar was documented as
  `run|promote|one-off` (where `promote`/`one-off` are silently inert) → the validator's actual
  `run|project|runs:N|date:<iso>` (`templates/graph.md`, `references/self-learning-loops.md`). The
  retry "consumption contract" was reworded from a schema-invalid `brief.prior_feedback` equality
  predicate to the actually-enforced, presence-gated I14/I15 checks over `debrief.prior_feedback`.
- **Stale invariant ranges refreshed.** `I1-I13` / `I9-I13` (pre-dating I14/I15/I1b/I-dod) →
  `I1-I15 (+ I1b, I-dod)` in `formal/Pipeline.tla`, `references/formal-models.md`, and
  `references/state-machine.md`; the non-tight termination-bound arithmetic clarified (11 loop
  transitions; ≤12 counting the entry edge).
- **Persona catalog.** Three `pair_with` fields carried prose (one naming a nonexistent
  "Critic Expert") → exact catalog persona names (`Red-Team / Devil's Advocate`, `Security
  Architect`, `Domain Expert`); dropped an unbacked "~20%" figure in `references/personas/GUIDE.md`.
- **SKILL.md.** Softened an over-broad claim about per-persona-file contents; Phase 1 step 5 now
  names the required `personas.json` sidecar.

## [1.1.0] — 2026-07-05

### Added
- **Bounded self-learning-loop layer (rings 02/03/04)** — all additive and **post-hoc**
  (offline validator predicates only; nothing gates the FSM, so termination is preserved):
  - **Post-hoc AO-2 / AO-6 checks (`I14` / `I15`)** — on a retry (`debrief.iteration > 1`),
    `I14` verifies the new verify's `defects[].criterion` are disjoint from the prior
    iteration's `do_not_touch`, and `I15` requires a responsive `changes_made`. Both are
    **presence-gated and read from the debrief's self-reported `prior_feedback` echo** (the
    validator retains only the latest `verify.json`) — a documented Named Limitation, not full
    AO-2/AO-6 enforcement.
  - **Across-run learnings stores** — a **project** store (`.dag/learnings/*.json`) and a
    **user** store (`~/.claude/dag/learnings/*.json`), merged at intake with **override order
    project > user**, plus an **expiry** grammar (`run | project | runs:N | date:<iso>`,
    loader-side), **idle decay / GC** (archive-not-delete; decidable for `max_idle_runs == 0`),
    and **supersedes / contradiction** escalation (advisory NOTE).
  - **Global tag registry (`04/G1`, flagged)** — widens the `I11`/`I12` tag domain to
    `V_tag_eff = global ∪ project ∪ run-local` via `~/.claude/dag/tags.json`, with the
    **authored-vs-imported admission carve-out** and an explicit provenance-trust boundary
    (a domain revision of `I11`/`I12`, not a purely additive check).
  - **`scope.model` narrowing (`04/G4`)** — an optional per-entry model glob/prefix that
    narrows `I12` propagation to matching runs.
  - **Advisory principles-promotion NOTE (`04/G3`)** — surfaces promotable entries for
    **human** promotion to `~/.claude/dag/principles.md`; never auto-writes, never gates.
  - **Advisory tier for imported cross-run learnings (`03/P4`)** — imported entries are
    **advisory** (loaded, reported, voluntarily citable, **not** force-injected by `I12`) until
    **re-grounded** to a local signal via the optional entry-level `grounding: "re-grounded"`
    marker; re-grounded imports and all run-local authored entries stay **active** and
    `I12`-enforced (preserves AO-4).
  - Supporting prose in `SKILL.md` (Phase 0.5 learnings intake, Phase-6 in-run capture /
    per-tag panel escalation / guarded forward re-brief, Phase-8 promote→persist write) and the
    `references/` self-learning / state-machine / methodology docs, plus new validator test
    fixtures. Ring 05 (sharable / trust) is **not** included in this release.

## [1.0.1] — 2026-07-05

### Changed
- Paraphrased the expressive third-party **blog quotations** in the persona catalog
  (Martin Fowler's *TestPyramid* and *Eradicating Non-Determinism in Tests*, the Testing Library
  guiding principle, and Unosquare / em-tools.io T-shaped-engineer commentary) into original
  wording, with their attributions preserved. The factual certification-body, standards-body,
  official-doc, and job-posting quotes are unchanged (fair-use quotation). No behavior change.

### Added
- Plugin README: an **MIT license** line and a **"Verify the formal claims yourself"** section —
  the one-command TLC re-run (expect 327 distinct states, no error) with a pointer to
  `references/formal-models.md` for the full transcript and the Alloy models.

## [1.0.0] — 2026-07-05

### Added
- Initial release of the `dag` gated, multi-phase task-execution pipeline:
  - **Socratic persona selection** (Phase 1) from a curated per-file JSON catalog plus
    user (`~/.claude/dag/personas/`) and project (`.dag/personas/`) personas, all under one
    uniform `persona.schema.json`.
  - **Exhaustive clarification** (Phase 2) with a materiality-ranked ambiguity register and a
    mandatory Definition of Done + Non-Goals/Guardrails.
  - **Contextual cartography** (Phase 3), **atomic work-unit decomposition + dependency DAG**
    (Phase 4), and **self-contained per-unit briefings** (Phase 5).
  - **Budget-capped subagent executors** (propose/critique) with **independent adversarial
    verification** of every work unit (Phase 6), a **disagreement gate** (Phase 7), and
    **synthesis + sign-off** (Phase 8).
  - **Formally-enforced invariants** — JSON Schemas + a finite-state-machine spec + a runnable
    validator (`scripts/validate_run.py`) that mechanically rejects malformed runs, plus a
    **TLA+/Alloy formal-model layer** (TLA+ machine-checked with TLC; Alloy hand-proved).
  - **Adaptive anti-hallucination evidence standards** and a durable
    plan/decision/progress/learnings ledger.
- Companion **`dag:personas`** skill to list/add/modify/remove reusable persona JSON files
  across the project, user, and built-in catalog sources.
