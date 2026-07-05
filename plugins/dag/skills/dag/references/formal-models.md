<!-- formal-models.md — a DESIGN-TIME formal-model proof layer on
     top of the runtime validator (scripts/validate_run.py). For each of 4 core
     invariants: the formal statement, a rigorous hand-proof, the exact model-check
     command, and honest tool-status. ADD-ONLY: references existing invariants
     (state-machine.md I1-I15 + I1b/I-dod, self-learning-loops.md, graph/verify schemas); modifies
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
TLC), `formal/WorkGraph.als` (Alloy).

## Tool-status (honest — evidence-standards.md)

| Tool | Present? | Used? |
|------|----------|-------|
| JDK (Oracle Java SE **25.0.3**, via `/usr/libexec/java_home`) | **yes** | yes |
| **TLC** (`tla2tools.jar` v2.19) | fetched to `/tmp` | **yes — TLA+ properties MACHINE-CHECKED** |
| **Alloy** (`org.alloytools.alloy.dist.jar` v6.2) | fetched to `/tmp` | **yes — Alloy properties MACHINE-CHECKED** (Kodkod / bundled SAT4J, headless): all 4 `check`s → no counterexample, `run WitnessGraph` → instance found (see §3–§4) |

> On a fresh macOS `/usr/bin/java` *may* be a stub (it prints "Unable to locate a Java
> Runtime" when no JDK is installed); if so, reach the real JDK via
> `JAVA_HOME=$(/usr/libexec/java_home)`. Every command below sets it — harmless even when
> `/usr/bin/java` already resolves to a real JDK.
>
> **`tla2tools.jar` and the Alloy jar are BUILD tools, not skill files** — both are fetched to
> `/tmp`, never vendored under `staged/skill/`. Download once:
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

---

## The TLC run (evidence for Properties 1 & 2)

One command checks *both* TLA+ properties (the safety invariants and the liveness
`PROPERTY` — the `SPECIFICATION Spec` in the `.cfg` carries the `WF_vars(LoopNext)`
fairness the liveness check needs). Run from the run directory:

```sh
export JAVA_HOME=$(/usr/libexec/java_home)
"$JAVA_HOME/bin/java" -cp /tmp/tla2tools.jar tlc2.TLC \
    -config formal/Pipeline.cfg formal/Pipeline.tla
```

**Actual TLC transcript (2026-07-03, TLC 2.19, JDK 25.0.3):**

```
TLC2 Version 2.19 of 08 August 2024 (rev: 5a47802)
Implied-temporal checking--satisfiability problem has 1 branches.
Finished computing initial states: 1 distinct state generated ...
Progress(28): 712 states generated, 327 distinct states found, 0 states left on queue.
Checking temporal properties for the complete state space with 327 total distinct states
Finished checking temporal properties in 00s
Model checking completed. No error has been found.
712 states generated, 327 distinct states found, 0 states left on queue.
The depth of the complete state graph search is 28.
```

`Model checking completed. No error has been found.` ⇒ across the **327 reachable
states** (full state space, queue empty), every `INVARIANT` (`TypeOK`,
`GateOrdering`, `LoopBound`, `VariantOK`, `BackEdgeGuarded`) held in every state, and
the temporal `PROPERTY Termination` held on every fair behavior.

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
   `gate[p]=TRUE` and sets `phase'=Succ(p)`. `ToDisagree`/`Resolve` move only P6↔P7
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
   passed). TLC confirms across all 327 states.

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
**I1** (maker≠checker; gates grounded in an external signal, never the
model re-reading its own reasoning).

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

## Consistency with the runtime validator (two levels, same invariants)

| Invariant | Design-time proof (here) | Runtime enforcement (`validate_run.py`) |
|-----------|--------------------------|------------------------------------------|
| Gate ordering (I8/I10) | Prop 1 `GateOrdering` (TLC ✓) | phase-vs-gates ordering + I9/I10 presence (I9 itself is validator-only — no Prop 1 coverage; see "Covered by one layer only" below) |
| Loop bound / termination (I4) | Prop 2 `Termination`+`LoopBound` (TLC ✓) | `retries ≤ 2`, `iteration ≤ retries+1` |
| DAG acyclic (I3) | Prop 3 `Acyclic` (hand-proved + machine-checked Alloy `check`) | fail-closed cycle detection on `edges ∪ deps` |
| Verifier independence (I1) | Prop 4 structural `Independence` | `executor_reasoning_seen const:false` |
| maker≠checker (**I1b maker!=checker**) | Prop 4 Alloy `DistinctMakerChecker` (asserted + machine-checked) | `executor_persona != verifier_persona` per graph.json unit (U04) |

**Covered by one layer only (noted honestly):** the validator additionally enforces
I5–I7, I9, I11–I13, I-dod, and the premise-check attestation (the independent COUNTER re-run), which are *data-shape* checks with no
temporal/structural content worth a separate model. Conversely, the models prove the
*rules* (no run can bypass a gate; the loop can't diverge) — a guarantee the per-run
validator cannot give, since it inspects one run's artifacts, not the rule-space.

## Model simplifications (intentional, safety-preserving abstractions)

`Pipeline.tla` is a deliberately small model of the pipeline+loop; three abstractions are
called out honestly. **None weakens the proved properties — the shipped model PASSES as-is
(TLC 2.19: 712 states generated / 327 distinct / depth 28 / no error), and each abstraction is
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

Directly inherited from `state-machine.md` §5 Limitations A–E — these are *semantic*
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

These are surfaced, not papered over: the formal layer proves the *plumbing and the
rules*; correctness-of-content remains the independent verifier's semantic judgment
(an external signal, never the model re-reading itself).
