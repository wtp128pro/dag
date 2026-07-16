# Proof Appendix — reproducing the TLA+ / Alloy checks

**Audience:** a reproducer — someone who wants to re-run the formal checks themselves and confirm the recorded results, byte for byte.

**TL;DR.** dag ships two design-time formal models — `formal/Pipeline.tla` (checked by TLC) and `formal/WorkGraph.als` (checked by Alloy) — that prove the *rules* of the pipeline can't be violated by any run in scope: gate ordering can't be bypassed, the correction loop always terminates, the work-graph is acyclic under a wave layering, and verifier independence is a structural invariant. This page gives the **exact commands** to reproduce them and the **recorded transcripts**. Historical transcripts in the later sections are **reproduced from `plugins/dag/skills/dag/references/formal-models.md` (recorded 2026-07-10, TLC 2.19, JDK 25.0.3, after the Bounded Graph Amendments added the `fuel` variable, the `FuelBound` invariant, and the `Quiesce` property)**; the **"Freshly executed" section immediately below** is a real *TLC* re-run performed while this wiki was authored (its Alloy results are cited from that same recorded run — no Alloy jar was present at authoring time). If you run the commands yourself, small search-order-dependent details (state ordering, the `<n>` and module line in the counterexample) may differ; the load-bearing signals are called out.

---

## Freshly executed this session (TLC re-run 2026-07-10, JDK 25.0.3, TLC 2.19)

The **TLC results (1)–(2) below were produced by actually running TLC** on the shipped `formal/Pipeline.tla` during authoring (2026-07-10, after the Bounded Graph Amendments `fuel`/`FuelBound`/`Quiesce` additions). Environment: `JAVA_HOME=$(/usr/libexec/java_home)` → Oracle Java SE **25.0.3**; `tla2tools.jar` v2.19 fetched to `/tmp`. **The Alloy results (3) were NOT re-run this session** — no Alloy jar was present at authoring time — so they are **cited from `references/formal-models.md`'s recorded 2026-07-10 run** (*machine-checked in scope, as recorded*), not freshly observed here.

> **One-command alternative (plugin 1.9.0):** `bash scripts/run_formal.sh` now fetches both jars (checksum-verified) and runs TLC (MaxFuel 2) **and** both Alloy files headlessly in one step — and, as of WP-F/D1, it **asserts** the literal results (the `853` / `408` / `depth 36` counts, the "2 branches of temporal properties" line, and Alloy's `SUMMARY: 8/8 commands as-expected`), so a gutted `.cfg`/`.als` now FAILs instead of vacuously passing. Add `--maxfuel32` for the parametric run. Everything below is what that script does by hand. **Plugin 1.9.0** (depth & retrieval enforcement, invariants **I26–I34**) added **no FSM state, transition, guard, or gate** — classified **PRESERVES** (zero REVISES) — so the transcripts reproduced below (853 / 408 / depth 36; Alloy 8/8) are **unchanged**.

**(1) TLC — both TLA+ properties, full state space.**
```sh
export JAVA_HOME=$(/usr/libexec/java_home)
cd plugins/dag/skills/dag/formal
"$JAVA_HOME/bin/java" -cp /tmp/tla2tools.jar tlc2.TLC -config Pipeline.cfg Pipeline.tla
```
Observed (load-bearing lines, verbatim from this run):
```
TLC2 Version 2.19 of 08 August 2024 (rev: 5a47802)
Implied-temporal checking--satisfiability problem has 2 branches.
Finished computing initial states: 1 distinct state generated at 2026-07-10 20:54:22.
Progress(36) at 2026-07-10 20:54:22: 853 states generated, 408 distinct states found, 0 states left on queue.
Checking 2 branches of temporal properties for the complete state space with 816 total distinct states ...
Model checking completed. No error has been found.
853 states generated, 408 distinct states found, 0 states left on queue.
The depth of the complete state graph search is 36.
```
Identical to the recorded figures in `references/formal-models.md` (§ "The TLC run"): **853 generated / 408 distinct / depth 36 / no error.** Every `INVARIANT` (`TypeOK`, `GateOrdering`, `LoopBound`, `VariantOK`, `BackEdgeGuarded`, `FuelBound`) held and **both** temporal properties — `Termination` and the Bounded-Graph-Amendments `Quiesce` (the "2 branches of temporal properties" line) — held on every fair behavior — Properties 1, 2, and 5, *machine-checked (in scope)*.

**Historical context — why 328, not 327 (BRK-11).** In the *pre-BGA* model (715 generated / 328 distinct / depth 28, a single `Termination` branch), 328 was exactly **one distinct state more** than an earlier 327: the BRK-11 `ToEscalate` fix widened the P6→P7 excursion guard from `verdict = "DISAGREE"` to `verdict ∈ {"DISAGREE","FAIL"}`, so a **retries-exhausted FAIL** ESCALATE (LT5) reached P7 instead of stuttering in P6 forever. That made `phase=P7 ∧ verdict=FAIL ∧ retries=2` reachable — one new state, enlarging the space 327 → 328. **That is now history:** the current model is **408 distinct** (853 / 408 / depth 36), because the Bounded Graph Amendments added a monotone `fuel` budget, the `FuelBound` invariant, and the `Quiesce` bounded-amendment-quiescence property (the second temporal branch). The FAIL-origin escalate is **subsumed** in the 408-state count and is no longer the headline delta (`references/formal-models.md:106-116`).

**(2) Non-vacuity — the liveness test has teeth.** A throwaway mutant `/tmp/Broken.tla` (the shipped spec with `retries' = retries + 1` changed to `retries' = retries`, so the variant `V = 2 − retries` no longer descends on the back-edge) was checked with the same config:
```
Error: Temporal properties were violated.
Error: The following behavior constitutes a counter-example:
Back to state <n>: <LRetryBranch … of module Broken>   (the RETRY→EXECUTE back-edge closes the lasso)
```
TLC reported a liveness **counterexample** (a lasso closing on the `RETRY→EXECUTE` back-edge) — proving `Termination` is a *genuine* check and that the counter increment is load-bearing. The shipped spec (which keeps the increment) passes; the mutant fails. The exact `<n>` and module line are search/spec-dependent — they shift as the module grows (the BGA additions grew it further); the load-bearing signal is `Temporal properties were violated`. (No repo file was modified — the mutant was built and checked entirely under `/tmp`.) The BGA `Quiesce` property is likewise checked non-vacuously against a throwaway **keep-fuel** mutant (one whose `Amend` never decrements `fuel`), which fails `Quiesce` while still passing `Termination` — see `references/formal-models.md` § 5.

**(3) Alloy — cited from the recorded run, NOT re-run this session.** No Alloy jar was present at authoring time, so the **eight** Alloy commands below — five in `WorkGraph.als`, three in `Amendment.als` (the Bounded Graph Amendments structural theorem) — are **quoted from `references/formal-models.md`'s recorded 2026-07-10 headless run** (Alloy 6.2, Kodkod / bundled SAT4J, driven via the vendored `formal/AlloyRun.java` → the Alloy Java API `CompUtil.parseEverything_fromFile` → `TranslateAlloyToKodkod.execute_command` with `-Djava.awt.headless=true`) — *machine-checked in scope, as recorded*, not freshly observed here:
```
# WorkGraph.als
check  Acyclic                  -> no counterexample (PASS)
check  LayeringImpliesAcyclic   -> no counterexample (PASS)
check  VerifierBlind            -> no counterexample (PASS)
check  DistinctMakerChecker     -> no counterexample (PASS)
run    WitnessGraph             -> instance found (PASS)
# Amendment.als (Bounded Graph Amendments)
check  AmendPreservesLayering   -> no counterexample (PASS)
check  AmendPreservesAcyclic    -> no counterexample (PASS)
run    AmendWitness             -> instance found (PASS)
SUMMARY: 8/8 commands as-expected
```
A `check` PASSes iff **UNSAT** (no counterexample within scope); a `run` PASSes iff **SAT** (a non-vacuous instance exists). As recorded, all **six** checks report no counterexample and **both** witness graphs are satisfiable — Properties 3 and 4 plus the structural half of Property 5 (`Amendment.als` layering-preservation), *machine-checked (in scope)* + (for Property 4) *asserted, shown consistent*.

> Honest caveat unchanged: a green Alloy check does **not** prove the *running* system obeys verifier independence — see **Residual A**. The models check the *rules*; runtime behavior is the validator's and the independent verifier's job.

---

## First, the honest proof-status legend

This page never says "proved for all inputs." It mirrors the three-level legend from `references/formal-models.md` (§ "Proof-status legend") exactly:

- **machine-checked (in scope)** — a model checker explored the state space *within a finite scope* and reported no error. For TLC here the scope is the full reachable state space of the model (queue empty); for Alloy it is a bounded scope (`for 7 …`), so the guarantee is "no counterexample **up to that scope**."
- **hand-proved** — a rigorous, checkable argument, not run by a tool here.
- **asserted (consistent)** — imposed structurally / by fiat and *shown consistent* (a witness instance exists), not derived as a theorem.

The five properties and their status (`references/formal-models.md` § property table):

| # | Property | Layer | Artifact | Proof-status |
|---|----------|-------|----------|--------------|
| 1 | Gate ordering | SAFETY | `Pipeline.tla` | machine-checked (TLC) + hand-proved |
| 2 | Bounded-loop termination | LIVENESS | `Pipeline.tla` | machine-checked (TLC) + hand-proved (variant) |
| 3 | DAG acyclicity | STRUCTURAL | `WorkGraph.als` | machine-checked (Alloy, no counterexample) + hand-proved |
| 4 | Verifier independence | STRUCTURAL | `WorkGraph.als` | machine-checked (Alloy, no counterexample) + asserted (structural, shown consistent) |
| 5 | Bounded-amendment quiescence | LIVENESS + STRUCTURAL | `Pipeline.tla` (`Quiesce`) + `Amendment.als` | machine-checked (TLC `Quiesce`, non-vacuous vs keep-fuel mutant; Alloy `Amendment.als`, no counterexample) + hand-proved (fuel variant) |

Property 4 stays labeled **asserted** on purpose: the Alloy `fact Independence { no reasoningSeen }` (`formal/WorkGraph.als:47`) imposes independence by fiat and the `run WitnessGraph` shows it is *consistent* — it is not derived. And note Residual A below: even a green check does **not** prove the *running* system obeys it.

---

## Tool versions (stated honestly)

From `references/formal-models.md` § Tool-status:

| Tool | Version | Status |
|------|---------|--------|
| JDK (Oracle Java SE) | **25.0.3**, via `/usr/libexec/java_home` | present, used |
| TLC (`tla2tools.jar`) | **2.19** | fetched to `/tmp`; TLA+ properties machine-checked |
| Alloy (`org.alloytools.alloy.dist.jar`) | **6.2** | fetched to `/tmp`; Alloy properties machine-checked (Kodkod / bundled SAT4J, headless) |

`tla2tools.jar` and the Alloy jar are **build tools, not skill files** — both are fetched to `/tmp`, never vendored under the skill (`references/formal-models.md` § Tool-status note; `formal/Pipeline.cfg:6-7`).

---

## Setup — fetch the tools and point at a real JDK

```sh
# One-time downloads (build tools → /tmp, never vendored)
curl -L -o /tmp/tla2tools.jar \
  https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar
curl -L -o /tmp/alloy.jar \
  https://github.com/AlloyTools/org.alloytools.alloy/releases/download/v6.2.0/org.alloytools.alloy.dist.jar

# Reach the real JDK. On a fresh macOS, /usr/bin/java may be a stub that prints
# "Unable to locate a Java Runtime"; this export routes around it. Harmless even
# when /usr/bin/java already resolves to a real JDK.
export JAVA_HOME=$(/usr/libexec/java_home)
```

These are the exact commands from `references/formal-models.md` § Tool-status note (lines 47–61).

> **Or automate all of it (plugin 1.9.0).** `bash scripts/run_formal.sh` performs every fetch-and-run
> step on this page — jars (checksum-verified), TLC (MaxFuel 2), and both Alloy files headless — and, as
> of WP-F/D1, **asserts** the literal results: the `853` / `408` / `depth 36` counts, the "2 branches of
> temporal properties" line, and Alloy's `SUMMARY: 8/8 commands as-expected`. A `.cfg` stripped of its
> invariants/properties or an `.als` stripped of its commands now **FAILs** rather than passing
> vacuously. Add `--maxfuel32` for the parametric 2,923 / 1,608 / depth 156 run
> (`references/formal-models.md` §Tool-status, lines 47–50).

---

## Property 1 & 2 — the one TLC command

TLC checks *both* TLA+ properties in a single run: the safety invariants **and** the liveness `PROPERTY`. The fairness the liveness check needs (`WF_vars(LoopNext)`) rides in via `SPECIFICATION Spec` in the `.cfg` (`formal/Pipeline.cfg:12-13`, `formal/Pipeline.tla:239`). Run **from the run directory** (the one containing `formal/`):

```sh
export JAVA_HOME=$(/usr/libexec/java_home)
"$JAVA_HOME/bin/java" -cp /tmp/tla2tools.jar tlc2.TLC \
    -config formal/Pipeline.cfg formal/Pipeline.tla
```

The `.cfg` (`formal/Pipeline.cfg`) fixes `CONSTANT MaxRetries = 2` and `CONSTANT MaxFuel = 2`, declares six `INVARIANT`s (`TypeOK`, `GateOrdering`, `LoopBound`, `VariantOK`, `BackEdgeGuarded`, `FuelBound`) and two temporal properties (`PROPERTY Termination`, `PROPERTY Quiesce`).

### TLC transcript

> **Quoted from `references/formal-models.md` (recorded 2026-07-10, TLC 2.19, JDK 25.0.3, after the Bounded Graph Amendments added the `fuel` variable, the `FuelBound` invariant, and the `Quiesce` property). The identical figures were freshly reproduced in "(1)" above.**

```
TLC2 Version 2.19 of 08 August 2024 (rev: 5a47802)
Implied-temporal checking--satisfiability problem has 2 branches.
Finished computing initial states: 1 distinct state generated ...
Progress(36): 853 states generated, 408 distinct states found, 0 states left on queue.
Checking 2 branches of temporal properties for the complete state space with 816 total distinct states
Finished checking temporal properties in 00s
Model checking completed. No error has been found.
853 states generated, 408 distinct states found, 0 states left on queue.
The depth of the complete state graph search is 36.
```

**How to read it.** `Model checking completed. No error has been found.` with `0 states left on queue` means TLC explored the **complete** reachable state space — **853 states generated, 408 distinct**, search depth 36 — and in every one of those 408 states each `INVARIANT` (now including `FuelBound`) held, and **both** temporal properties — `PROPERTY Termination` and the BGA `PROPERTY Quiesce` (the "2 branches of temporal properties" line) — held on every fair behavior (`references/formal-models.md` § "The TLC run", lines 106–116).

- **Property 1 — Gate ordering** is the `INVARIANT GateOrdering` (`formal/Pipeline.tla:247-255`): in every reachable state, being at a phase implies every strictly-earlier spine gate holds — e.g. no P3 before `gate["P2"]` (I8), no P8 before `gate["P6"]` (I10). Machine-checked across all 408 states; also hand-proved as an inductive invariant in `references/formal-models.md` § 1.
- **Property 2 — Bounded-loop termination** is the `PROPERTY Termination`: `(lstate = "EXECUTE") ~> (lstate ∈ {"DONE","ESCALATE"})`. The well-founded variant is `V = MaxRetries − retries`; the sole back-edge `LRetry` (LT7) increments `retries`, so `V` strictly descends and the back-edge is disabled at the floor (`BackEdgeGuarded`). Hand-proof: `references/formal-models.md` § 2, four claims A–D.
- **Property 5 — Bounded-amendment quiescence** is the second temporal branch `PROPERTY Quiesce`: `<>[](lstate ∈ {"DONE","ESCALATE"})` — the loop eventually *stays* terminal (graph amendments cannot re-arm it forever). Its second well-founded variant is `fuel ∈ 0..MaxFuel` (invariant `FuelBound`); only `Amend` writes `fuel`, and only `−1`, disabling itself at `fuel = 0`. Hand-proof (fuel variant): `references/formal-models.md` § 5.

> **PR1 verifier hardening — the model is UNCHANGED (classified PRESERVES).** The 1.2.0 panel-of-3 default and the bounded loop-until-dry sweep are **internal to the `VERIFY` node** (`formal/Pipeline.tla:159-163`): they add **no new TLA action** (`LVerify` still steps `VERIFY→ADJUDICATE`), no new variable, and **no second back-edge** — the fan-out (3) and round cap (`R_max=3`) are finite constants absorbed by the single `LVerify` step. So `Termination` and the well-founded measure `V = MaxRetries − retries` hold **verbatim** and `Pipeline.tla`/`.cfg` need no edit. The panel verdict is aggregated by **discrete majority** (a split maps to `DISAGREE`) *before* `ADJUDICATE` reads it, so its guard partition `{PASS} ∪ {FAIL}×{V>0,V=0} ∪ {DISAGREE}` is unchanged. This is classified **PRESERVES**, not *revises* (`references/formal-models.md:219-234`). (**Softmaxing** that aggregation WOULD break the model — it would collapse the exhaustive, mutually-exclusive guard partition — and is therefore forbidden.)

### Non-vacuity check — the `Broken.tla` counterexample (did the liveness test have teeth?)

A green liveness check is worthless if the property is *vacuously* true. To show `Termination` has teeth, the model author broke the variant in a throwaway copy `Broken.tla`: made `LRetry` write `retries' = retries` (no increment), so `V = 2 − retries` no longer decreases on the back-edge. TLC then **reported a liveness counterexample** — a lasso (the infinite `EXECUTE→VERIFY→ADJUDICATE→RETRY→EXECUTE` spin):

> **Quoted from `references/formal-models.md` (recorded 2026-07-10, TLC 2.19, JDK 25.0.3). Freshly reproduced in "(2)" above — the load-bearing `Temporal properties were violated` signal reproduced; the exact `<n>` and module line are search-order-dependent and shift as the BGA-grown module changes.**

```
Error: Temporal properties were violated.
Error: The following behavior constitutes a counter-example:
Back to state <n>: <L… of module Broken>   (the RETRY→EXECUTE back-edge closes the lasso)
```

The exact `<n>` and the action name TLC prints for the back-edge are **search-order dependent**; the load-bearing signal is `Temporal properties were violated` (`references/formal-models.md` lines 118–135). This proves two things: `Termination` is a *genuine* liveness check (not vacuously true), **and** the counter-increment on the sole back-edge is load-bearing for termination. The shipped `Pipeline.tla` (which keeps the increment) passes; the mutant fails.

> Note: `Broken.tla` is a *throwaway mutant* described in `references/formal-models.md`; it is not a vendored file in the repo. Reproduce it by copying `Pipeline.tla` and deleting the `retries' = retries + 1` increment in `LRetry`.

---

## Properties 3 & 4 — the Alloy commands

### GUI-vs-headless caveat (read before running)

Alloy's default invocation `java -jar /tmp/alloy.jar` **launches the GUI** — it does not run checks on the command line. To reproduce headlessly you have two options (`references/formal-models.md` § Tool-status note, lines 58–61; `formal/WorkGraph.als:17-21`):

1. **Open `formal/WorkGraph.als` in the Alloy Analyzer → Execute All.**
2. **Drive the Alloy Java API headlessly:** `CompUtil.parseEverything_fromFile` → `TranslateAlloyToKodkod.execute_command`, default SAT4J solver, with `-Djava.awt.headless=true`.

The commands below are the *Analyzer commands* as written in `formal/WorkGraph.als` (lines 87–100); run them via either route above.

### Property 3 — DAG acyclicity

```
check Acyclic                for 7 but 5 Int
check LayeringImpliesAcyclic for 7 but 5 Int
```

**The `for 7 but 5 Int` scope is a requirement, not a convenience.** It bounds *every* sig to 7 with Int bitwidth 5 (range −16..15, ample for ≥7 waves). A bare `7 Unit, 5 Int` does **not** work: `Unit.executor : one Persona` (`formal/WorkGraph.als:30`) makes `Persona` reachable, so a partial scope list leaves `Persona`/`Verifier` unbounded and the command will not run (`references/formal-models.md` lines 278–281; `formal/WorkGraph.als:21-22`).

**Expected:** *No counterexample found. Assertion may be valid.*

Why `check Acyclic` (`formal/WorkGraph.als:87`) passes *earns* rather than *assumes* the result: `fact WaveLayered { WaveLayering and PositiveWaves }` (`formal/WorkGraph.als:65`) imposes the Phase-4 wave discipline, and the theorem `LayeringImpliesAcyclic` (`formal/WorkGraph.als:74-76`) shows a valid layering *forces* a DAG. Remove that fact and `depends` is unconstrained → a self-loop `u in u.depends` is a counterexample and the check would *fail*. So the fact is load-bearing (`references/formal-models.md` § 3 "Why check Acyclic passes"). Hand-proof of the theorem: `references/formal-models.md` § 3.

### Property 4 — verifier independence + maker≠checker

```
check VerifierBlind        for 7 Unit, 5 Verifier, 5 Persona, 5 Int
check DistinctMakerChecker for 7 Unit, 5 Verifier, 5 Persona, 5 Int
run   WitnessGraph         for exactly 4 Unit, exactly 2 Verifier, exactly 3 Persona, 5 Int
```

**Expected:** the two `check`s → *No counterexample found*; the `run` → *Instance found* (`references/formal-models.md` line 324).

- `VerifierBlind` (`formal/WorkGraph.als:89`) mirrors `verify.schema.json` `executor_reasoning_seen : {const:false}` and validator I1 — no verifier read any executor's chain-of-thought.
- `DistinctMakerChecker` (`formal/WorkGraph.als:90`) mirrors maker≠checker (validator I1b) — a unit is never verified by its own maker.
- `run WitnessGraph` (`formal/WorkGraph.als:100`) exhibits a **non-vacuous** instance (a real dependency edge, a real verification, acyclic, independence respected). Its job is to guard against an over-constrained model that "proves" everything vacuously — the constraints are *satisfiable together* (`references/formal-models.md` § 4).

These are honestly labeled **asserted (consistent)**: given the facts, both asserts hold trivially; the model *encodes* the invariant the schema requires and shows it consistent, rather than deriving it.

---

## How this composes (one picture)

```mermaid
flowchart TB
  subgraph TLA["Pipeline.tla — checked by TLC (full state space)"]
    A["INVARIANT GateOrdering<br/>(Property 1, SAFETY)"]
    B["PROPERTY Termination<br/>(Property 2, LIVENESS)<br/>variant V = MaxRetries − retries"]
    BQ["PROPERTY Quiesce + INVARIANT FuelBound<br/>(Property 5, LIVENESS)<br/>fuel variant, MaxFuel = 2"]
  end
  subgraph ALS["WorkGraph.als — checked by Alloy (bounded scope for 7)"]
    C["assert Acyclic / LayeringImpliesAcyclic<br/>(Property 3, STRUCTURAL)"]
    D["assert VerifierBlind / DistinctMakerChecker<br/>+ run WitnessGraph<br/>(Property 4, STRUCTURAL / asserted)"]
  end
  subgraph AMEND["Amendment.als — checked by Alloy (bounded scope for 7)"]
    E["check AmendPreservesLayering / AmendPreservesAcyclic<br/>+ run AmendWitness<br/>(Property 5, STRUCTURAL)"]
  end
  A -. mirrors .-> I8I10["validator I8 / I10"]
  B -. mirrors .-> I4["validator I4 (retries ≤ 2)"]
  C -. mirrors .-> I3["validator I3 (fail-closed cycle detection)"]
  D -. mirrors .-> I1["validator I1 / I1b"]
  BQ -. mirrors .-> I18["validator I18 (fuel bound)"]
  E -. mirrors .-> I18
```

The design-time proofs (this page) and the runtime validator (`scripts/validate_run.py`) guard the *same* invariants at two levels: the models prove the **rules** can't be bypassed by any run; the validator checks a **specific run's** artifacts (`references/formal-models.md` § "Consistency with the runtime validator").

---

## What is NOT proved here (never overstate)

Two boundaries, stated honestly and inherited from `references/formal-models.md`:

- **Scope, not universality.** TLC's result is over the model's full reachable state space with `MaxRetries = 2` and `MaxFuel = 2`; the termination hand-proof is *parametric in any finite N* (`references/formal-models.md` line 216). The fuel bound is likewise parametric: pinning `MaxFuel = 2` fixes the documented 853 / 408 / depth 36 counts, while re-running the identical model at `MaxFuel = 32` (the shipped runtime ceiling) only lengthens the same terminating behaviours — **2,923 / 1,608 / depth 156, still no error** (`references/formal-models.md` §"`MaxFuel` scope (F1)", lines 418–425). Alloy's result is "no counterexample **up to scope `for 7`**" — not "for all sizes." This is bounded verification.
- **Plumbing, not content (Residual A, the load-bearing one for Property 4).** `executor_reasoning_seen = false` and the Alloy `Independence` fact are **self-attestations**; no platform hook intercepts subagent I/O. The model proves the invariant is *well-formed and consistent* — **not** that the running system obeys it (`references/formal-models.md` § Residual A). Correctness-of-content (is a `PASS` correct? is a persona genuinely different?) remains the independent verifier's semantic judgment, an external signal — never the model re-reading itself (`references/formal-models.md` § Residual B–E).

Model simplifications (the loop actions are not per-action phase-gated; `Resolve` doesn't re-arm the loop; `gate["P0"]`/`gate["P5"]` have no runtime flag) are intentional and safety-preserving — each *removes* behaviors, so it can only make `GateOrdering` easier to hold, not harder (`references/formal-models.md` § "Model simplifications"). The shipped model passes as-is: 853 states / 408 distinct / depth 36 / no error.
