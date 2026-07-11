# dag

A gated, multi-phase **task-execution pipeline** for Claude Code. Instead of answering a
complex task in one shot, `dag` decomposes it into atomic, independently-verified
work units and drives them through named personas, budget-capped subagents, and
independent adversarial verification — pausing for you only at the decisions that matter.

> Invoked as **`/dag:dag <task>`** (plugin skills are namespaced
> `/plugin:skill`). Run it with no task and it will ask for one.

> **Formal-enforcement layer —** the pipeline's rules are **formally enforced, not
> prose**: JSON Schemas + a finite-state-machine spec + a runnable validator (`scripts/validate_run.py`)
> that mechanically rejects malformed runs (retry-cap breaches, budget breaches,
> non-independent verifiers, vague FAILs, DAG cycles, missing verifications). The Socratic move-set
> (`references/socratic-protocol.md`) is **referenced by every prompt; applied selectively (material
> surfaces only)**, the executor↔verifier
> **self-learning loop is bounded with a machine-checked (TLC) termination proof**, and a
> **TLA+/Alloy** formal-model layer proves the core invariants (TLA+ machine-checked with TLC; Alloy
> machine-checked with Kodkod/SAT4J). See the [CHANGELOG](CHANGELOG.md).

## What it does (Phases 0–8)

| Phase | What happens |
|-------|--------------|
| 0 Bootstrap | Creates a dated run dir `.wip/<date>_<time>_<label>/` and seeds the ledger |
| 1 Personas | Socratic selection of a task-fit persona roster (curated + synthesized + your project/user JSON personas), you confirm |
| 2 Clarification | Ambiguity register ranked by materiality; material gaps gated to you; mandatory Definition of Done + Non-Goals/Guardrails |
| 3 Cartography | **Contextual** map of the terrain (meaning + relationships, not a file list) |
| 4 Decomposition | Atomic work units + dependency DAG, topologically sorted into parallel waves |
| 5 Briefing | A self-contained briefing contract per unit (≤32K-token budget) |
| 6 Execute + Verify | Budget-capped subagent executors (propose/critique) + an **independent** adversarial verifier per unit |
| 7 Disagreement gate | On material disagreement: every option laid out, best marked ★, rollback to any stage |
| 8 Synthesis | Roll-up, final independent verification, sign-off, optional learnings promotion |

## Companion skill: `dag:personas`

`dag:personas` manages the reusable persona JSON files that `dag:dag`
discovers and merges into its Phase 1 candidate pool (see the table above). It's a
separate, standalone skill in this same plugin — you don't need to run it before using
`dag:dag`; the pipeline works fine off its curated library alone. Use it when
you want a persona to persist across runs (or across your whole machine) instead of
being synthesized fresh every time.

> Invoked as **`/dag:personas`**. Run it with no argument and it will ask what you
> want to do.

**What it manages** — one persona per JSON file, at one of two locations:
- **Project** (checked into the current repo): `.dag/personas/*.json`
- **User / "global"** (cross-project, personal): `~/.claude/dag/personas/*.json`

A third source, the built-in curated catalog (`skills/dag/references/personas/` — per-file
JSON plus an `index.json` selection index), ships with the plugin and is read-only — you can't
edit it directly, but you can *shadow* one of its entries with a project/user JSON file of the
same name (project > user > curated on a collision).

**Operations:**

| Operation | What it does |
|-----------|--------------|
| `list` | Aggregates all three sources (project → user → built-in) into one view, flags any name that shadows another source, then lets you pick an entry to edit or delete |
| `add` | Elicits `name` / `role` / `description` (required) plus optional `mandate` / `optimizes_for` / `skeptical_of` / `phase` / `pair_with` / `qualifications` / `tags`, then writes one schema-valid JSON file (filename = kebab-case of `name`) |
| `remove` | Lists the personas at a location, lets you pick one, confirms, then deletes the file |
| `modify` | Lists, lets you pick one, guides an edit of just the fields you want to change, re-validates, then overwrites |

Every write enforces the same schema `dag:dag` reads at Phase 1 — the one uniform
schema shared by the curated catalog and every user/project persona
(`name`/`role`/`description` required; `mandate`/`optimizes_for`/`skeptical_of`/`phase`/
`pair_with`/`qualifications`/`tags` optional; unknown fields are rejected, not silently dropped).
Once saved, a persona is
automatically picked up by the next `/dag:dag` run — no separate registration
step.

## What's inside

```
skills/dag/
├── SKILL.md                       the Dag playbook
├── DESIGN.md                      architecture + requirement traceability + grounding
├── references/
│   ├── methodology.md             deep how/why per phase + §Hard-won principles
│   ├── personas/                  curated persona catalog (per-file JSON + index.json + GUIDE.md)
│   ├── evidence-standards.md      adaptive anti-hallucination rulebook
│   ├── socratic-protocol.md       Socratic move-set — referenced by every prompt; applied selectively
│   ├── self-learning-loops.md     bounded executor↔verifier loop + termination
│   ├── data-partitioning.md       map-reduce onto the DAG for large-dataset passes
│   ├── state-machine.md           the pipeline FSM: states · transitions · invariants
│   └── formal-models.md           TLA+/Alloy models + proofs + check plan
├── schemas/                       JSON Schemas (Draft 2020-12) for every artifact
├── spec/                          descriptive SSR registry (fsm.json · invariants.json) — dev-time drift source
├── formal/                        Pipeline.tla · Pipeline.cfg · WorkGraph.als · Amendment.als (BGA) · AlloyRun.java (headless driver)
├── templates/                     brief · debrief · verify · disagreement · personas · persona ·
│                                  clarifications · cartography · graph · amendment
└── scripts/
    ├── init_run.sh                deterministic dated run-dir + ledger + fsm-state seed
    ├── validate_run.sh            enforcement entry point (python3 prober → validate_run.py)
    ├── validate_run.py            runnable validator — rejects malformed runs
    ├── run_tests.sh               the CI: HOME-isolated fixture sweep on both backends + spec_check
    ├── spec_check.py              dev-time prose↔spec↔code drift checker (SC1–SC7)
    ├── run_formal.sh              one-command TLC + Alloy reproduction (fetches jars to /tmp)
    └── tests/                     fixtures proving each enforced rule (good/bad/amend_…)
```

## Design principles

- **Machine-checked, not prose** — the pipeline's invariants (gate order, retry cap ≤ 2,
  budget, verifier independence, DAG acyclicity, mandatory verification, learning propagation)
  are enforced by JSON Schemas + an FSM spec + a validator that exits non-zero on violation,
  and proven at design time by a TLC-machine-checked TLA+ model.
- **A Socratic move-set referenced by every prompt; applied selectively** — one reusable move-set
  (FORK·COUNTER·ADMIT·PIVOT·RESIDUAL) referenced on human gates *and* subagent briefs, but applied
  selectively (material surfaces only), not as ritual; decoupled from the artifact under test.
- **Ledger is truth** — all state lives on disk (PLAN / DECISIONS / PROGRESS / LEARNINGS),
  so nothing is ever rediscovered and every run is resumable.
- **Decouple the maker from the checker** — verifiers run in fresh subagents and see only
  the brief, debrief, and artifacts, never the executor's reasoning.
- **No claim without admissible evidence** — evidence is adaptive by claim type (web/docs
  for facts, code+run for behavior); "could not verify" is surfaced, never papered over.
- **Gate on decisions that matter** — otherwise it runs autonomously and logs its rationale.

## Known limitations

- **Structure, not content.** The validator guarantees valid *structure + invariants*, not
  correct *content* (validity ≠ correctness). Semantic correctness, genuinely-engaged (non-
  decorative) Socratic reasoning, truthful token counts, and real deployed verifier-blindness
  remain model-judged / self-attested and are caught by the independent verifier, not the schema.
- **Explicit step, not a hook.** Enforcement runs as a Dag Bash step
  (`scripts/validate_run.sh <run-dir>`); there is no passive hook on subagent output.
- **TLA+ and Alloy machine-checked.** The TLA+ safety + termination properties are checked with
  TLC (a JRE re-runs them); the Alloy DAG/independence models are machine-checked with Alloy 6
  (Kodkod / bundled SAT4J, headless) — all `check`s report no counterexample and the witness run
  finds an instance.
- The ≤32K per-subagent budget is now *partly* enforceable (a token-count check on structured
  artifacts); free prose remains disciplinary. See `skills/dag/DESIGN.md §6`.

## Verify the formal claims yourself

Run the commands in this section **from a checkout of this repo** (e.g. `git clone` then
`cd dag/plugins/dag`) — the `cd skills/dag` paths are repo-relative, not paths inside an installed
plugin.

The "machine-checked" claim above isn't asked to be taken on faith — you can re-run the TLC model
check yourself in seconds. It needs a JDK; TLA+'s `tla2tools.jar` is a build tool fetched to `/tmp`,
never vendored into the skill.

```sh
curl -L -o /tmp/tla2tools.jar \
  https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar
cd skills/dag        # the directory that holds formal/
export JAVA_HOME=$(/usr/libexec/java_home)   # macOS; on Linux point JAVA_HOME at your JDK
"$JAVA_HOME/bin/java" -cp /tmp/tla2tools.jar tlc2.TLC \
    -config formal/Pipeline.cfg formal/Pipeline.tla
```

Expect `Model checking completed. No error has been found.` across **853 states generated / 408
distinct / depth 36** (shipped `MaxFuel = 2`; verified parametric at `MaxFuel = 32` → 2,923 / 1,608 /
depth 156) — that confirms the safety invariants (gate ordering, retry bound ≤ 2, well-founded loop
variant, **`FuelBound`**) and **both** temporal properties: bounded-loop **`Termination`** and
bounded-amendment **`Quiesce`**. The full annotated transcript, the invariant→property traceability,
and the Alloy structural models (`formal/WorkGraph.als` + the BGA `formal/Amendment.als`, whose `check`
commands run headless via the Alloy Java API — SAT4J, `-Djava.awt.headless=true`) are documented in
[`references/formal-models.md`](references/formal-models.md).

The validator has an executable, HOME-isolated fixture suite (the repo has no CI — this is it):

```sh
cd skills/dag
bash scripts/run_tests.sh   # every tests/ fixture on each validator backend; non-zero on any mismatch
```

It runs `validate_run.py` over every `scripts/tests/` fixture, pins each expected exit code + FAIL
line via `scripts/tests/expectations.tsv`, checks `manifest.schema.json` against its instance pair,
and stubs `$HOME` so results never depend on your real `~/.claude/dag/` (finding IMP-16). The sweep
runs on **both** validator backends — the normal one (jsonschema if importable) and, unconditionally,
a forced pass with `DAG_FORCE_MINI=1` (the stdlib fallback), so the fallback is exercised even where
jsonschema is installed. It then runs the **SSR drift checker** twice: `spec_check.py` (SC1–SC7:
registry↔labels, FSM-table↔`spec/fsm.json` row-diff, gate map, constants, examples, fixture coverage,
TLA pragmas) on the real tree, plus its negative-fixture overlays. Set `DAG_TEST_VENV=/path/to/venv`
(a venv with `jsonschema` installed) to add a second jsonschema-capable interpreter to the matrix.

## Install

See the [marketplace README](../../README.md). In short:

```
/plugin marketplace add wtp128pro/dag
/plugin install dag@dag
```

Then: `/dag:dag <your task>`

## License

[MIT](../../LICENSE) © 2026 wtp128pro. Not affiliated with or endorsed by Anthropic; "Claude" and
"Claude Code" are Anthropic trademarks used nominatively to describe compatibility.

## Versioning

Current version: **1.6.0** — **Validator hardening (extra_check remediation)**: closes ten reproduced
false-PASS holes in the Bounded Graph Amendments enforcement and the core validator, and reconciles two
guarantee narratives. BGA now has a real provenance backbone — an immutable `baseline_units` + `fuel_initial`
seed reconciled against the amendment records (smuggled/phantom/fake-retired units and a deleted
`amendments/` dir all FAIL now), a `fuel_before`/`fuel_after` tamper-evidence chain, per-kind amendment
schema closure + split/child semantics, and a frozen-content anchor pinning every executed unit's graph
entry to its immutable `brief.json`. The core validator gains duplicate-unit-id detection, ledger↔verify
cross-checks, artifact-driven phase floors, forgery-proof learnings-import provenance, honest-overrun
tying, and non-blank actionable-change enforcement. ESCALATE's third origin (amendment-fuel exhaustion) is
documented and provenance-checked; I9 is status-aware (a mid-loop debrief-with-no-verify is a NOTE, not a
FAIL). Every new check is **post-hoc/offline** (no live LT7 guard) so the correction-loop **termination
proof is PRESERVED**; the BGA pipeline bound and I17/I18/I19 surfaces **REVISE upward** (strictly stronger).
The fixture matrix grows to **106**, swept on **both** backends (jsonschema + a forced stdlib-mini pass);
TLC re-verifies 853/408/depth 36 (and 2,923/1,608/depth 156 at `MaxFuel=32`), Alloy 8/8. **1.5.0** — **Structured Spec Registry + Drift Checks (SSR)**: a descriptive, dev-time spec
registry (`spec/fsm.json` + `spec/invariants.json`) that records the `state-machine.md` transition rows
(T*/LT*) and the I* invariants as machine-readable data, plus a drift checker `scripts/spec_check.py`
(**SC1–SC7**, wired into `scripts/run_tests.sh`) that diffs the FSM tables, dereferences schema
constant-pointers `(authoritative: <schema>#/<path>)`, validates embedded worked examples, and
presence-checks the TLA+ `\* spec:` pragma coverage in `Pipeline.tla`. These are **diff / dereference /
presence (drift-detection) checks — not semantic proofs of correctness** (SC7 checks that every T*/LT* id
is *mentioned* as a pragma, not that the action faithfully models the transition). Ships a behaviour-neutral
`validate_run.py` LABELS hoist and a `verify.md`-vs-schema dual-authority fix (schema authoritative,
template illustrative). Dev-time only — `spec/` + `spec_check.py` are never on the skill's lazy-load path,
SKILL.md gains no new runtime read; **PRESERVES** every guarantee (no FSM state/edge/guard, no schema
constraint, no enforcement behaviour changed — proof: byte-identical 64-fixture matrix on both backends,
TLC 853/408/depth 36 No error). **1.4.0** — **Bounded Graph Amendments (BGA)**: the Phase-6 work graph may grow under
mechanical constraints via append-only amendment records (`add_units`/`split_unit`/`add_edges`;
`cancel_unit` human-gated), bounded by a monotone-decreasing **fuel** budget (total units ≤ N0 + fuel₀).
Five new **post-hoc/offline** invariants (**I3b** wave layering + **I3c** dependency closure — closing
two pre-existing validator gaps — and **I17** frozen executed prefix, **I18** fuel bound, **I19**
amendment scope), none a live guard; a new `amendment.schema.json` (14 schemas); 10 new fixtures
(**54 → 64**); and a machine-checked TLA+ liveness property **`Quiesce`** (non-vacuous vs a keep-fuel
mutant) plus a new Alloy `Amendment.als`. The per-unit correction-loop termination proof is **PRESERVED**
verbatim; only the pipeline-level unit-count bound is **REVISED** (fixed N → N ≤ N0 + fuel₀). **1.3.0** —
five-track audit remediation. Closes validator-enforcement evasions and
adds robustness (PR-1); fixes the learnings contract + the Phase-0.5→G-personas deadlock (PR-2) and
the I12 selector semantics — `all`/`U0X`/`tag:` enforced, `phaseN` removed (PR-3); makes the
formal-model docs honest (PR-4); tightens skill instructions + socratic schemas (PR-5) and the
debrief/verify/learnings schemas (PR-6); ships a hardened **personas** skill (PR-7), an executable
**HOME-isolated test harness** `scripts/run_tests.sh` (PR-8), and a validator/shell/docs hygiene batch
(PR-9). Three follow-ups: durable **per-unit `fsm-state.units[]` loop state** for parallel waves
(D-02, **REVISES** I4's cross-check surface); **blessed per-panelist `verify_p*.json`** as
validate-if-present audit artifacts (D-04); and a **mechanical Phase-8 sign-off gate**
`gates.signoff_confirmed` required at `DONE` (D-06, **REVISES** the gate contract). All new enforcement
is post-hoc/offline — no live guard on the sole `RETRY→EXECUTE` back-edge — so termination is
**PRESERVED** (the two REVISES carry migration arguments; TLC re-checks clean). **1.2.0** — verifier
hardening + reproducible-evidence + large-dataset
partitioning. Panel-of-3 with **distinct lenses** (correctness/reproduce/guardrail) is now the
**default on `high-stakes` units**, aggregated by **discrete majority** (a split → DISAGREE, never
softmax); a bounded **loop-until-dry** verify sweep and a **coverage-first** verifier mandate raise
recall; I6's PASS clause is revised (a PASS may carry `minor` observations). New post-hoc invariant
**I16** enforces the panel discipline offline (gates no transition). Adds
`references/data-partitioning.md` + `schemas/manifest.schema.json` (map-reduce onto the DAG) and a
reproducible/executable-evidence preference. All node-internal → **PRESERVES** the termination proof
(only I6's PASS clause is a flagged content-rule revision). **1.1.1** — corrective audit pass (no
functional/guarantee change): the Alloy
formal model is now executable and machine-checked (a partial `check` scope left `Persona`
unbounded), doc↔validator drift fixed (`scope.expiry` grammar, the retry consumption-contract
predicate), stale invariant ranges refreshed to `I1-I15`, dangling persona `pair_with` references
resolved, and loose/unbacked prose removed. **1.1.0** — adds the rings-02/03/04 self-learning-loop layer (post-hoc AO-2/AO-6
checks I14/I15, across-run project + user learnings stores with expiry/decay/supersedes, a global
tag registry with the authored-vs-imported admission carve-out, `scope.model` narrowing, an
advisory principles-promotion NOTE, and an advisory tier for imported cross-run learnings); all
additive and post-hoc, no FSM gating. 1.0.1 was a docs/hardening patch over 1.0.0 (paraphrased
third-party quotations in the persona catalog, trademark & MIT-license notes, an AI-provenance
note, and a reproducible formal-check section); no functional change. 1.0.0 was the initial release: the
gated, multi-phase task-execution pipeline with Socratic persona selection, exhaustive
clarification, contextual cartography, atomic work-unit decomposition + dependency DAG,
budget-capped subagent executors, independent adversarial verification, adaptive
anti-hallucination evidence standards, formally-enforced invariants (JSON Schemas + FSM spec +
runnable validator; TLA+/Alloy formal-model layer), and a durable
plan/decision/progress/learnings ledger. See
[CHANGELOG.md](CHANGELOG.md).
