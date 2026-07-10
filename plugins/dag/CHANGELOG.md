# Changelog — dag plugin

All notable changes to the `dag` plugin are documented here.
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
