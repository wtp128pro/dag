<!-- formal-models.md — a DESIGN-TIME formal-model proof layer on
     top of the runtime validator (scripts/validate_run.py). For each of 4 core
     invariants: the formal statement, a rigorous hand-proof, the exact model-check
     command, and honest tool-status. ADD-ONLY: references existing invariants
     (state-machine.md I1-I16 + I1b/I-dod, self-learning-loops.md, graph/verify schemas); modifies
     no validator/schema/prose. -->

# Formal Models — TLA+ / Alloy proof layer

Two levels of assurance guard the same invariants:

- **Runtime enforcement** — `scripts/validate_run.py` checks a *specific run's*
  artifacts (schema validity, fail-closed DAG, missing-verification rejection, loop
  bound, …). See `state-machine.md` §5.
- **Design-time proof (this document)** — TLA+/Alloy prove the *rules themselves*
  can't be violated by any run: gate ordering can never be bypassed, the loop always
  terminates, the graph is always acyclic under a wave layering, and verifier
  independence is a structural (not incidental) invariant.

Artifacts: `formal/Pipeline.tla` + `formal/Pipeline.cfg` (TLA+, machine-checked by
TLC), `formal/WorkGraph.als` + `formal/Amendment.als` (Alloy). `Amendment.als` is the Bounded Graph
Amendments structural theorem (adding wave-layered units above their deps preserves acyclicity — §5).

> **SSR spec-pragma coverage (dev-time, `spec_check.py` SC7).** Each FSM-bearing definition in
> `formal/Pipeline.tla` carries a TLA+ comment pragma `\* spec: <id>` naming the transition/loop id it
> realizes (e.g. `\* spec: T6`, `\* spec: LT7`). `scripts/spec_check.py` **SC7** then
> **presence-checks** that every `T*`/`LT*` id enumerated in the `state-machine.md` tables has a
> matching `\* spec:` pragma in `Pipeline.tla`. This is a **coverage / presence check that each id is
> *mentioned* — NOT a semantic verification** that the TLA+ action faithfully models that transition;
> that faithfulness stays the hand-proof + TLC/Alloy machine-check in §§1–5 and, ultimately, reviewer
> judgment (validity ≠ correctness, §5 Residual). Like the rest of SSR it is **dev-time only** (runs
> under `run_tests.sh`), never a runtime read; it modifies no validator, schema, or proof here.

## Tool-status (honest — evidence-standards.md)

| Tool | Present? | Used? |
|------|----------|-------|
| JDK (Oracle Java SE **25.0.3**, via `/usr/libexec/java_home`) | **yes** | yes |
| **TLC** (`tla2tools.jar` v2.19) | fetched to `/tmp` | **yes — TLA+ properties MACHINE-CHECKED** |
| **Alloy** (`org.alloytools.alloy.dist.jar` v6.2) | fetched to `/tmp` | **yes — Alloy properties MACHINE-CHECKED** (Kodkod / bundled SAT4J, headless): all 4 `WorkGraph.als` `check`s + both `Amendment.als` `check`s → no counterexample; `run WitnessGraph` / `run AmendWitness` → instance found (see §3–§5) |

> On a fresh macOS `/usr/bin/java` *may* be a stub (it prints "Unable to locate a Java
> Runtime" when no JDK is installed); if so, reach the real JDK via
> `JAVA_HOME=$(/usr/libexec/java_home)`. Every command below sets it — harmless even when
> `/usr/bin/java` already resolves to a real JDK.
>
> **`tla2tools.jar` and the Alloy jar are BUILD tools, not skill files** — both are fetched to
> `/tmp`, never vendored into the repo. Download once:
> `curl -L -o /tmp/tla2tools.jar https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar`
> `curl -L -o /tmp/alloy.jar https://github.com/AlloyTools/org.alloytools.alloy/releases/download/v6.2.0/org.alloytools.alloy.dist.jar`
> Alloy's default `java -jar alloy.jar` launches the GUI; drive it headlessly through the Alloy
> Java API (`CompUtil.parseEverything_fromFile` → `TranslateAlloyToKodkod.execute_command`, default
> SAT4J solver, `-Djava.awt.headless=true`), or open the file in the Analyzer and Execute All.

**Proof-status legend:** *machine-checked* (a model checker explored the state space
and reported no error) · *hand-proved* (a rigorous checkable argument; not run by a
tool here) · *asserted* (imposed structurally / by fiat and shown consistent, not
derived).

| # | Property | Layer | Artifact | **Proof-status** |
|---|----------|-------|----------|------------------|
| 1 | Gate ordering | SAFETY | `Pipeline.tla` | **machine-checked** (TLC) + hand-proved |
| 2 | Bounded-loop termination | LIVENESS | `Pipeline.tla` | **machine-checked** (TLC) + hand-proved (variant) |
| 3 | DAG acyclicity | STRUCTURAL | `WorkGraph.als` | **machine-checked** (Alloy — no counterexample) + hand-proved |
| 4 | Verifier independence | STRUCTURAL | `WorkGraph.als` | **machine-checked** (Alloy — no counterexample) + asserted (structural invariant, shown consistent) |
| 5 | Bounded-amendment quiescence | LIVENESS + STRUCTURAL | `Pipeline.tla` (`Quiesce`) + `Amendment.als` | **machine-checked** (TLC `Quiesce`, non-vacuous vs keep-fuel mutant; Alloy `Amendment.als` layering-preservation — no counterexample) + hand-proved (fuel variant) |

---

## The TLC run (evidence for Properties 1 & 2)

One command checks *both* TLA+ properties (the safety invariants and the liveness
`PROPERTY` — the `SPECIFICATION Spec` in the `.cfg` carries the `WF_vars(LoopNext)`
fairness the liveness check needs). Run from `plugins/dag/skills/dag/` (the skill dir, where
`formal/` lives — the `formal/…` config paths below resolve there, not in a run dir):

```sh
export JAVA_HOME=$(/usr/libexec/java_home)
"$JAVA_HOME/bin/java" -cp /tmp/tla2tools.jar tlc2.TLC \
    -config formal/Pipeline.cfg formal/Pipeline.tla
```

**Actual TLC transcript (2026-07-10, TLC 2.19, JDK 25.0.3 — after adding the Bounded Graph Amendments
`Amend` action, the `fuel` variable, the `FuelBound` invariant, and the `Quiesce` property):**

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

`Model checking completed. No error has been found.` ⇒ across the **408 reachable
states** (full state space, queue empty), every `INVARIANT` (`TypeOK`,
`GateOrdering`, `LoopBound`, `VariantOK`, `BackEdgeGuarded`, **`FuelBound`**) held in every state, and
**both** temporal properties — `Termination` and the new **`Quiesce`** (the "2 branches of temporal
properties" line) — held on every fair behavior. **Baseline → BGA:** the pre-BGA model checked at
**715 states generated / 328 distinct / depth 28** with a single `Termination` branch; adding the
bounded `fuel` variable (`MaxFuel = 2`) and the `Amend` re-arm action grows the reachable space to
**853 / 408 / depth 36** with a second temporal branch (`Quiesce`) — the graph-amendment budget made
visible to the model checker. (The earlier BRK-11 `ToEscalate` fix — which added the
`phase=P7 ∧ verdict=FAIL ∧ retries=2` state and made the probe `P7OnlyViaDisagree` reportably violated,
P7 now reachable from a FAIL-origin escalate — is subsumed in this 408-state count.)

**Non-vacuity check (adversarial — did the liveness test have teeth?).** I broke the
variant in a throwaway copy `Broken.tla`: made `LRetry` write `retries' = retries`
(no increment), so `V = 2 − retries` no longer decreases on the back-edge. TLC then
**reported a liveness counterexample** — a lasso:

```
Error: Temporal properties were violated.
Error: The following behavior constitutes a counter-example:
Back to state <n>: <L… of module Broken>   (the RETRY→EXECUTE back-edge closes the lasso)
```

(The exact `<n>` and the action name TLC prints for the back-edge are search-order
dependent; the load-bearing signal is `Temporal properties were violated`.) I.e. the
infinite `EXECUTE→VERIFY→ADJUDICATE→RETRY→EXECUTE` spin. This proves
`Termination` is a *genuine* liveness check (not vacuously true) **and** that the
counter-increment on the sole back-edge is load-bearing for termination. The shipped
`Pipeline.tla` (which keeps the increment) passes; the mutant fails. This is the
external signal that the model captures the real invariant.

---

## 1. Gate ordering — SAFETY (TLA+) · machine-checked

**Mirrors:** `state-machine.md` guards G-personas … G-verified + invariants **I8**
(no P3 before clarifications) and **I10** (no P8/synthesis while any unit lacks PASS).

**Formal statement** (`GateOrdering`, an `INVARIANT`): in every reachable state, the
current `phase` implies every strictly-earlier spine phase's exit gate holds — e.g.

```
(phase ∈ {P3,…,DONE}) ⇒ gate["P2"]        (no Cartography before clarifications, I8)
(phase ∈ {P8,DONE})   ⇒ gate["P6"]        (no Synthesis before every unit PASS, I10)
```

**What bad behavior it must exclude** (COUNTER): reaching P3's work before P2's gate;
or reaching P8 (synthesis) while the loop has not delivered a `DONE` (a unit un-PASSed).

**Hand-proof (inductive invariant).** Let *Ord* be the spine order P0<P1<…<P6<P8<DONE.
Two facts:
1. **Gates are monotone.** The only writers of `gate` are `Complete(p)` and `LinkP6`,
   each flipping one entry `FALSE→TRUE`; none sets `TRUE→FALSE`. So once a gate holds
   it holds forever.
2. **`phase` only advances through the guarded `Advance`.** `Advance(p)` requires
   `gate[p]=TRUE` and sets `phase'=Succ(p)`. `ToEscalate`/`Resolve` move only P6↔P7
   (never forward past a gate).
   *Base:* `Init` has `phase=P0`; the antecedents of every `GateOrdering` clause are
   false ⇒ holds.
   *Step:* the only way to make a clause's antecedent newly true is `Advance(p)`
   moving into `Succ(p)`; its guard establishes `gate[p]`, and by monotonicity every
   earlier gate (true by the induction hypothesis when we were at `p`) still holds.
   The P6↔P7 excursion changes no gate and never advances, so it preserves the
   invariant. ∎  The bad behaviors above are therefore unreachable: to be at P3,
   `Advance(P2)` fired ⇒ `gate["P2"]`; to be at P8, `Advance(P6)` fired ⇒ `gate["P6"]`,
   and `gate["P6"]` is set *only* by `LinkP6`, which requires `lstate="DONE"` (the unit
   passed). TLC confirms across all 408 states.

**Check command:** the run above; `GateOrdering` is listed as `INVARIANT`.
**Tool-status:** **machine-checked** by TLC 2.19 (no JRE→TLC excuse: a real JDK 25 was
found and used). Also hand-proved above.

---

## 2. Bounded-loop termination — LIVENESS (TLA+) · machine-checked

**Mirrors:** `self-learning-loops.md` §2 termination argument; states Q + table 1.3;
variant `V = MaxRetries − retries`. Runtime backstop: `fsm-state.schema.json`
`retries.maximum=2` + validator I4.

**Formal statement** (`Termination`, a `PROPERTY` under `WF_vars(LoopNext)`):

```
(lstate = "EXECUTE") ~> (lstate ∈ {"DONE","ESCALATE"})
```

("~>" = leads-to; from `Init`'s `lstate=EXECUTE` this is `<>Terminated`.)

**What bad behavior it must exclude** (COUNTER): a fair run that cycles the correction
loop forever, never reaching a terminal (unbounded retries).

**Hand-proof (well-founded variant — `self-learning-loops.md` §2, four claims).**
- **A. One back-edge.** Enumerate LT1–LT7 (the `L*` actions): six are forward or into
  an absorbing terminal; the only edge to an earlier state is `LRetry` (RETRY→EXECUTE).
  So the sole cycle is `EXECUTE→VERIFY→ADJUDICATE→RETRY→EXECUTE`, traversing `LRetry`
  exactly once per lap.
- **B. Strict descent.** `V = MaxRetries − retries ∈ {0,1,2}` (a non-negative integer,
  invariant `VariantOK`). `LRetry` does `retries' = retries+1` ⇒ `V' = V−1`; no other
  action changes `retries`. So `V` strictly decreases on every lap and never rises.
- **C. Floor-guarded back-edge.** `LRetry` is reachable only via `LRetryBranch`, whose
  guard is `retries < MaxRetries`, i.e. `V > 0` (invariant `BackEdgeGuarded`). At
  `V=0` (`retries=2`) `LRetryBranch` is disabled; `ADJUDICATE` can then fire only
  `LPass`→DONE, `LEscFail`→ESCALATE, or `LEscDisagree`→ESCALATE — all terminal.
- **D. No deadlock; fairness.** Every non-terminal loop state has an enabled action for
  every reachable input (`ADJUDICATE`'s guards partition `{PASS}∪{FAIL}×{V>0,V=0}∪
  {DISAGREE}`; `verdict≠NONE` there because `LVerify` set it). `WF_vars(LoopNext)`
  forces the loop to keep moving. A well-founded measure that strictly descends on the
  only cycle, whose back-edge is disabled at the floor, cannot be traversed infinitely:
  ≤ `MaxRetries=2` laps ⇒ ≤3 executions, then a terminal. ∎

The proof is *parametric in any finite N* (`V = N − retries`), so a configurable cap
never weakens termination (`self-learning-loops.md` §6.4).

> **PR1 verifier hardening — the model is UNCHANGED (classified PRESERVES).** The panel-of-3
> default and the bounded loop-until-dry sweep are **internal to the `VERIFY` node**: they add **no
> new TLA action** (`LVerify` still steps `EXECUTE→…→VERIFY→ADJUDICATE`), no new variable, and no
> second back-edge — the fan-out (3) and round count (`R_max=3`) are finite constants absorbed by the
> single `LVerify` step. So `Termination` and the well-founded measure `V = 2−retries`
> hold **verbatim**; `Pipeline.tla`/`.cfg` need no edit. (Deadlock-freedom is not a *named* property —
> it is TLC's built-in default check, kept satisfied by the `TermStutter` step on the absorbing
> terminals `{DONE, ESCALATE}`, so the composed behavior is always infinite and TLC needs no
> `-deadlock` flag.) The panel verdict is aggregated by **discrete
> majority** before `ADJUDICATE` reads it, so `ADJUDICATE`'s guard partition
> `{PASS}∪{FAIL}×{V>0,V=0}∪{DISAGREE}` is unchanged — a split maps to `DISAGREE`. **Softmaxing** that
> aggregation WOULD break the model (it would replace the discrete split→DISAGREE routing with a
> thresholded/averaged score, collapsing the exhaustive, mutually-exclusive guard partition) and is
> therefore forbidden. Likewise the I6 PASS-clause revision (a PASS may carry `minor` defects) is a *content
> rule on the verify artifact*, not a state/guard change — `verdict ∈ {PASS,FAIL,DISAGREE}` is
> untouched, so the model is unaffected.

**Check command:** the run above; `Termination` is a `PROPERTY`, fairness supplied by
`SPECIFICATION Spec`. Non-vacuity demonstrated by the `Broken.tla` counterexample.
**Tool-status:** **machine-checked** by TLC 2.19 (liveness, complete state space) +
hand-proved.

---

## 3. DAG acyclicity — STRUCTURAL (Alloy) · machine-checked (no counterexample) + hand-proved

**Mirrors:** `graph.schema.json` (`units`,`edges`,`waves`,`v_tag`) + validator **I3**
(fail-closed cycle detection on `edges ∪ unit.deps`).

**Formal statement** (`WorkGraph.als`):

```alloy
assert Acyclic { no (^depends & iden) }                       // no unit reaches itself
assert LayeringImpliesAcyclic {
  (WaveLayering and PositiveWaves) => no (^depends & iden) }   // waves ⇒ DAG (I3)
```
where `WaveLayering ≡ all u | all d : u.depends | d.wave < u.wave`.

**Hand-proof (`LayeringImpliesAcyclic`).** Suppose a cycle `u₀→u₁→…→uₖ=u₀` in
`depends` (each `uᵢ₊₁ ∈ … ` s.t. `uᵢ ∈ uᵢ₊₁.depends`). `WaveLayering` gives
`u₀.wave < u₁.wave < … < uₖ.wave = u₀.wave`, so `u₀.wave < u₀.wave` — contradiction in
the strict order on ℤ. Hence no cycle: `no (^depends & iden)`. ∎  This is precisely why
the validator's wave-layering check is *sufficient* for a DAG: any run that presents a
valid topological layering is acyclic.

> **Why `check Acyclic` passes (not by fiat).** In `WorkGraph.als` the wave discipline is
> imposed as the structural fact `WaveLayered { WaveLayering and PositiveWaves }` (the
> Phase-4 layering the decomposition produces; the validator's fail-closed I3 relies on it).
> The standalone `assert Acyclic { no (^depends & iden) }` then reports *no counterexample*
> **because** a valid layering forces a DAG (this very theorem) — **not** because acyclicity
> was assumed. Without that fact `depends` is unconstrained and a self-loop (`u in u.depends`)
> is a counterexample, so the check would *fail*: the fact is load-bearing for the check.

**Check command** (open `WorkGraph.als` in the Alloy Analyzer → Execute All, or drive the Alloy
Java API headlessly — see the Tool-status note above):
```
check Acyclic                for 7 but 5 Int
check LayeringImpliesAcyclic for 7 but 5 Int
```
Scope `7 but 5 Int` bounds every sig to 7 (Int bitwidth 5 ⇒ −16..15, ample for ≥7 waves). The
**global** bound is required, not a bare `7 Unit, 5 Int`: `Unit.executor` makes `Persona`
reachable, so a partial scope list leaves `Persona`/`Verifier` unbounded and the command will not
run. Expected: *No counterexample found. Assertion may be valid.*

**Tool-status:** **machine-checked** — both `check`s run headless (Alloy 6, bundled SAT4J) and
report *no counterexample*; the hand-proof above is the checkable argument for *why* a valid
layering forces a DAG.

---

## 4. Verifier independence — STRUCTURAL (Alloy) · asserted + machine-checked (no counterexample)

**Mirrors:** `verify.schema.json` `executor_reasoning_seen : {const:false}` + validator
**I1** (verifier independence — gates grounded in an external signal, never the model re-reading
its own reasoning) and **I1b** (maker≠checker) — the split this document's own table (§Consistency)
already uses.

**Formal statement** (`WorkGraph.als`):

```alloy
fact Independence   { no reasoningSeen }                              // I1: relation empty
fact MakerNotChecker{ all v:Verifier, u:v.checked | v.persona != u.executor }  // maker != checker
assert VerifierBlind        { no reasoningSeen }
assert DistinctMakerChecker { all v:Verifier, u:v.checked | v.persona != u.executor }
```

**What bad behavior it must exclude** (COUNTER): a verifier reading the executor's
chain-of-thought for a unit it judges, or a unit being verified by its own maker.

**Argument + ADMIT.** `reasoningSeen ⊆ checked` (fact `SeenSubsetChecked`) makes the
relation *meaningful*; `Independence` then forces it **empty** — independence is modeled
as a **structural invariant**, not an incidental runtime flag. Given the fact, both
asserts hold trivially. So this is honestly labeled **asserted** (imposed by fiat and
shown *consistent*), **not a derived theorem** — the model *encodes* the invariant that
the schema's `const:false` and the maker≠checker rule require, and the `run WitnessGraph` command exhibits a
non-vacuous instance (a real dependency edge, a real verification, acyclic, independence
respected) to prove the constraints are *satisfiable together* — the guard against an
over-constrained model that "proves" everything vacuously.

**Check command:**
```
check VerifierBlind        for 7 Unit, 5 Verifier, 5 Persona, 5 Int
check DistinctMakerChecker for 7 Unit, 5 Verifier, 5 Persona, 5 Int
run   WitnessGraph         for exactly 4 Unit, exactly 2 Verifier, exactly 3 Persona, 5 Int
```
Expected: checks → *No counterexample found*; run → *Instance found*.

**Tool-status:** **machine-checked** — both `check`s report *no counterexample* and `run
WitnessGraph` finds an instance (Alloy 6, bundled SAT4J, headless). This is still a *structural
asserted* invariant (the model encodes it by fiat and shows it consistent); and — importantly —
even a green Alloy check would **not** prove the *real system* enforces it: see Residual A.

---

## 5. Bounded-amendment quiescence — LIVENESS (TLA+) + STRUCTURAL (Alloy) · machine-checked

**Mirrors:** the Bounded Graph Amendments invariants **I18** (fuel bound) + I3b/I3c/I17/I19
(state-machine.md §4); self-learning-loops.md §2 FLAG (PRESERVES per-unit / REVISES pipeline-bound).
Runtime backstop: `fsm-state.schema.json` `expansion.fuel_*` (max 32) + validator **I18**.

**Formal statement** (`Quiesce`, a `PROPERTY` under `WF_vars(LoopNext)`):

```
<>[](lstate \in {"DONE","ESCALATE"})
```

("<>[]" = eventually-always; the loop eventually STAYS in a terminal — amendments cannot re-arm it
forever.)

**What bad behavior it must exclude** (COUNTER): an unbounded-amendment run whose graph grows without
limit — the loop re-armed (`DONE → EXECUTE`) infinitely, so the *pipeline* never quiesces even though
every individual unit still terminates.

**Hand-proof (well-founded variant — the §3.4 / self-learning-loops §2 argument).** The amendment is
the `Amend` action: guarded on `phase="P6" ∧ gate["P6"]=FALSE ∧ lstate="DONE" ∧ fuel>0`, it spends one
unit of fuel (`fuel' = fuel − 1`) and re-arms the representative loop (`lstate'="EXECUTE",
retries'=0, verdict'="NONE"`; `UNCHANGED <<phase, gate>>`). Two facts:
1. **Per-unit termination is untouched** (Property 2, Claims A–D verbatim): each re-armed lap runs the
   same `EXECUTE→VERIFY→ADJUDICATE` loop with variant `V = 2 − retries`; `WF_vars(LoopNext)` drives it
   to a terminal. Only LT7 writes `retries`; `Amend` resets it for a *fresh* unit and adds no back-edge.
2. **`fuel` is a second well-founded variant.** `fuel ∈ 0..MaxFuel` (invariant `FuelBound`), only
   `Amend` writes it and only `−1`, and `Amend`'s own guard `fuel>0` disables it at the floor. So after
   ≤ MaxFuel re-arms `Amend` is permanently disabled; the loop then reaches a terminal and — with no
   enabled `Amend` — `{DONE,ESCALATE}` absorb (`TermStutter`). Hence `lstate` is eventually always
   terminal. ∎  Total transitions ≤ 12·(N0 + fuel₀) + fuel₀ — finite.

Classification (self-learning-loops.md §2 FLAG): the **per-unit correction-loop proof PRESERVES**
(verbatim); the **pipeline-level bound REVISES** ("fixed finite N" → "N ≤ N0 + fuel₀", fuel the same
well-founded-counter shape as `retries`). `GateOrdering` **PRESERVES** — `Amend` is guarded on
`gate["P6"]=FALSE` and writes neither `phase` nor any `gate` entry, so no gate can be bypassed.

**Non-vacuity (adversarial — does `Quiesce` have teeth?).** The load-bearing point: `Termination`
(`EXECUTE ~> {DONE,ESCALATE}`) alone would **NOT** catch unbounded amendment — each re-armed lap still
terminates, so `Termination` stays true; only the *run* fails to quiesce. Demonstrated on a throwaway
keep-fuel mutant (`Amend` with `fuel' = fuel`, so fuel never decreases):

```
mutant + PROPERTY Termination only  =>  Model checking completed. No error has been found.
mutant + PROPERTY Quiesce only      =>  Error: Temporal properties were violated.
                                        Back to state <n>: <LRetryBranch/Amend>   (infinite DONE->EXECUTE re-arm lasso)
```

The shipped `Pipeline.tla` (fuel strictly decreases) passes `Quiesce`; the mutant fails it while still
passing `Termination`. This is the external signal that `Quiesce` — not `Termination` — captures the
BGA termination guarantee. (Mutant deleted after recording; never vendored, like `Broken.tla`.)

**Structural half (Alloy — `formal/Amendment.als`).** The TLA+ liveness proof assumes the amended graph
stays acyclic; `Amendment.als` proves that *structurally*. `Old` abstracts the frozen executed prefix
(I17); `Unit − Old` are amendment-added units placed strictly above their dependencies. Given
`OldLayered` + `FrozenOld` (old edges never point at new units — I17) + `NewAboveDeps`, both
`check AmendPreservesLayering` and `check AmendPreservesAcyclic` report **no counterexample**
(scope `7 but 5 Int`), and `run AmendWitness` finds a non-vacuous instance (real new units, one
consuming an old unit, acyclic). Hand-proof: case-split on `u ∈ Old` (then `depends ⊆ Old` by FrozenOld,
and OldLayered gives `d.wave < u.wave`) vs `u ∉ Old` (NewAboveDeps gives it directly) ⇒ the combined
graph is wave-layered, and the existing `LayeringImpliesAcyclic` theorem (Property 3) yields acyclicity.
∎  Honest scope: `add_edges` into an unexecuted *old* unit is not modeled in Alloy — it is caught at
runtime by the full-graph I3 + I3b re-check per revision (noted, not hidden). `WorkGraph.als` is left
untouched and its four checks still report no counterexample.

**Check command** (from `plugins/dag/skills/dag/`): the TLC run above, now with `Quiesce` in the
`PROPERTY` list + `FuelBound` in the `INVARIANT` list (`Pipeline.cfg` carries `MaxFuel = 2`); for Alloy,
drive `Amendment.als` headless via the Alloy Java API (default SAT4J, `-Djava.awt.headless=true`) —
never `java -jar` (GUI). **Tool-status:** **machine-checked** — TLC 2.19 (`Quiesce` liveness, complete
408-state space, non-vacuous vs the keep-fuel mutant) + Alloy 6 (`Amendment.als`, no counterexample) +
hand-proved.

---

## Consistency with the runtime validator (two levels, same invariants)

| Invariant | Design-time proof (here) | Runtime enforcement (`validate_run.py`) |
|-----------|--------------------------|------------------------------------------|
| Gate ordering (I8/I10) | Prop 1 `GateOrdering` (TLC ✓) | phase-vs-gates ordering + I9/I10 presence (I9 itself is validator-only — no Prop 1 coverage; see "Covered by one layer only" below) |
| Loop bound / termination (I4) | Prop 2 `Termination`+`LoopBound` (TLC ✓) | `retries ≤ 2`, `iteration ≤ retries+1` |
| DAG acyclic (I3) | Prop 3 `Acyclic` (hand-proved + machine-checked Alloy `check`) | fail-closed cycle detection on `edges ∪ deps` |
| Verifier independence (I1) | Prop 4 structural `Independence` | `executor_reasoning_seen const:false` |
| maker≠checker (**I1b maker!=checker**) | Prop 4 Alloy `DistinctMakerChecker` (asserted + machine-checked) | `executor_persona != verifier_persona` per graph.json unit (U04) |
| Bounded-amendment quiescence (I18) | Prop 5 `Quiesce` (TLC ✓, non-vacuous vs keep-fuel mutant) + `Amendment.als` layering (Alloy ✓) | I18 fuel bound (`fuel_remaining == fuel_initial − Σ fuel_cost ≥ 0` + revision/`amendments_applied` bookkeeping) |

**Covered by one layer only (noted honestly):** the validator additionally enforces
I5–I7, I9, I11–I16, I-dod, the BGA frozen-prefix + scope + graph-closure checks (I17/I19/I3b/I3c), and the premise-check attestation (the independent COUNTER re-run), which are *data-shape* checks with no
temporal/structural content worth a separate model. Conversely, the models prove the
*rules* (no run can bypass a gate; the loop can't diverge) — a guarantee the per-run
validator cannot give, since it inspects one run's artifacts, not the rule-space.

## Model simplifications (intentional, safety-preserving abstractions)

`Pipeline.tla` is a deliberately small model of the pipeline+loop; three abstractions are
called out honestly. **None weakens the proved properties — the shipped model PASSES as-is
(TLC 2.19: 853 states generated / 408 distinct / depth 36 / no error, incl. `FuelBound` + `Quiesce`), and each abstraction is
safety-preserving (it removes behaviors, so it can only make `GateOrdering` easier to hold, not
harder).**

- **(a) The loop actions are not per-action phase-gated.** The `L*` actions (`LExecute`,
  `LVerify`, …) guard only on `lstate`, not on `phase = "P6"`. Loop-locality to Phase 6 is
  therefore enforced by the single link action `LinkP6` (which requires `phase="P6"` to flip
  `gate["P6"]`), **not** by a `phase="P6"` conjunct on every loop action. The composed model
  is still faithful because the loop's only *observable* coupling to the phase machine is
  through `LinkP6`; letting `L*` step regardless of `phase` adds interleavings but no gate
  bypass (the loop never writes `phase` or any `gate` except via `LinkP6`).
- **(b) `Resolve` (T11) returns to P6 without resetting the loop terminal.** `Resolve` sets
  `phase'="P6"` and leaves `lstate` at its terminal value, so **post-escalation recovery** (a
  fresh loop after a human decision) and the **P2/P3/P4 rollback targets** T11 lists in
  state-machine.md are **out of model scope**. This is safety-preserving: `Resolve` never
  advances forward past a gate and changes no `gate` entry, so `GateOrdering` still holds; the
  omitted recovery/rollback edges would only add more (still gate-respecting) behavior. In-model,
  the post-`Resolve` P6 state is a stutter-absorbing terminal rather than a re-armed loop.
  **BGA note:** an ESCALATE-origin amendment (a P7 resolution that amends the graph — an
  `amendment.origin.trigger` of `p7_resolution`) folds into this same out-of-scope `Resolve`
  simplification. The model's `Amend` re-arms only from `lstate="DONE"` (an autonomous, mid-P6
  amendment), not from a post-`Resolve` ESCALATE; the human-approved-split path is the same
  out-of-model recovery edge (b) already omits. The runtime validator's I17/I18/I19 govern the
  amendment regardless of origin, so nothing is unenforced — only the P7-recovery *edge* is
  unmodeled, exactly as it was pre-BGA.
- **(c) `gate["P0"]` / `gate["P5"]` have no runtime gate flag.** The model carries an exit gate
  for every spine phase (`gate ∈ [SpinePhases -> BOOLEAN]`), but the *runtime* `gates` object
  has only the **four gate flags** (`personas_confirmed`, `clarification_resolved`,
  `cartography_done`, `decomposition_approved`). `gate["P0"]`/`gate["P5"]` (bootstrap, briefing) are modeled
  as ordinary `Complete(p)` steps with no user-facing flag — they are linear, non-gated phases
  whose "gate" abstracts *"this phase's work is done"*, not a human confirmation. The precedence
  they encode in `GateOrdering` is real (P0 before P1, P5 before P6); only their *runtime
  representation* is folded into phase progression rather than a `gates` boolean.

These are model-scoping choices, surfaced rather than hidden; the properties proved
(`GateOrdering`, `Termination`, and the auxiliary invariants) hold over the model as shipped.

## Residual — invariants that are NOT formalizable (semantic / model-judged)

Directly inherited from `state-machine.md` §5 Limitations A–H — these are *semantic*
and **cannot** be captured in TLA+/Alloy:

- **A. (the load-bearing one for Prop 4).** Whether the verifier was *truly* blind to
  executor reasoning. `executor_reasoning_seen=false` / the Alloy `Independence` fact are
  **self-attestations**; no platform hook intercepts subagent I/O. The model proves the
  invariant is *well-formed and consistent*, **not** that the running system obeys it.
- **B.** Whether a `PASS` is *correct*, evidence locators actually resolve, or the
  `socratic`/`defects` text is *genuine* vs. theater (the independent COUNTER re-run is the real backstop).
- **C.** Truthfulness of reported `budget_tokens`/`tokens_consumed`.
- **D.** Whether executor and verifier are genuinely a *different model/persona*. The
  **persona-label** distinctness (`executor_persona != verifier_persona` per unit) is now
  graph-checked at runtime by `validate_run.py` (**I1b maker!=checker**, state-machine.md §4),
  and Alloy models maker≠*persona* structurally — but neither the label check nor the model can
  observe whether the real deployment ran a genuinely different model behind the label.
- **E.** Whether a `tag` denotes a *genuinely reusable* pattern (I12 checks ≥2 carriers
  mechanically; "truly generalizable" stays a human/verifier call).
- **F, G, H, I, J, K (validator-layer limitations — the models do not touch them).** These are
  properties of the *runtime validator*, not the design-time model, so they are neither proved nor
  weakened here: **F** — I14/I15 are post-hoc, presence-gated, self-reported anti-oscillation checks
  (the model proves loop *termination*, not that a retry genuinely responded to feedback);
  **G** — the `V_tag_eff = global ∪ project ∪ run_local` domain widening + the authored-vs-imported
  admission carve-out are a validator data-domain revision with a provenance-trust boundary
  (`Pipeline.tla`/`WorkGraph.als` model neither tags nor the learnings domain); **H** — I16 panel
  discipline checks panel presence/shape/discrete-majority, not that the lenses were genuinely applied
  (the model has no panel construct). The three **Bounded Graph Amendments** semantic limits are
  likewise validator-layer, not modeled: **I** — `amendment.human_gate` is a presence-checked
  attestation (I19), not proof a human approved a scope-change/cancel; **J** — `frontier_wave` is
  attested, not derived (the validator cannot reconstruct dispatch timing); **K** — I19's `dod_refs`
  verbatim match is string membership in `definition_of_done`, not semantic traceability that the
  added unit genuinely serves that DoD item. The TLA+ `Amend`/`Quiesce` proof covers only the
  *termination* + *acyclicity* half of BGA (Property 5); these three semantic guarantees stay the
  verifier/human backstop. Listing them keeps this inheritance range honest — state-machine.md defines
  Limitations A through K.

These are surfaced, not papered over: the formal layer proves the *plumbing and the
rules*; correctness-of-content remains the independent verifier's semantic judgment
(an external signal, never the model re-reading itself).
