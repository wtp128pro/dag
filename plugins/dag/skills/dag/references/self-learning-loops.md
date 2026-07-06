<!-- references/self-learning-loops.md — the formal model of the Phase-6 loops (req 12).
     Formalizes the prose correction + learning loops (methodology.md §Self-learning loops)
     into a bounded state machine with a checkable termination argument,
     a JSON verdict/feedback contract, a LEARNINGS schema, and anti-oscillation invariants. -->

# Self-Learning Loops — formalized (executor ↔ verifier)

**Persona of record:** Self-Learning-Loops Engineer. **Optimizes for:** a provable
termination guarantee, no oscillation, and real learning transfer. **Skeptical of:**
unbounded retries and "learning" that is noise.

This document turns two prose loops into machine-checkable contracts:

- **Correction loop** (within a unit): an *independent* verifier's `FAIL` feeds concrete
  feedback back to a re-execution; bounded at **2 retries**; an unresolvable split → human.
- **Learning loop** (across units): a *generalizable* lesson keyed to a **verifiable
  outcome** becomes a `LEARNINGS.md` entry that later briefs are **required** to carry.

Grounding: every gate here is anchored to an **external
signal** — an independent verifier verdict, a schema check, a cited finding — never the
model re-reading its own reasoning (arXiv:2310.01798). The maker never
judges its own work (arXiv:2410.21819; NeurIPS'24 2404.13076). Reflections
are keyed to gate pass/fail outcomes, iterations are bounded, and each retry must cite new
evidence — the exact convergence conditions Reflexion relies on and whose absence causes
oscillation (arXiv:2303.11366; supported by arXiv:2303.17651).

---

## 1. The loop as a state machine

### 1.1 States

```
Q = { EXECUTE, VERIFY, ADJUDICATE, RETRY, ESCALATE, DONE }
```

| State | Kind | What happens on entry |
|-------|------|-----------------------|
| `EXECUTE` | action | Executor subagent runs the current attempt (`iteration ≤ retries+1`, I4) from its brief. On a retry (`iteration>1`) the brief **embeds the prior `feedback`** (see §3). Produces `debrief.json` + artifacts. |
| `VERIFY` | action | An **independent** verifier (sees brief + debrief + artifacts, **not** the executor's reasoning or identity) emits the **verdict/feedback JSON** (§3) validated against `verify.schema.json`. |
| `ADJUDICATE` | decision (no side effects) | Reads `verdict` and the counter `retries`; selects exactly one outgoing transition via the exhaustive guard table (§1.3). |
| `RETRY` | action | `retries := retries + 1`; build the next executor brief carrying prior `feedback`; log the iteration in `PROGRESS.md`. |
| `ESCALATE` | **terminal** (absorbing) | Write `disagreement.md`; hand to Phase 7 human gate. Control leaves the automated loop. |
| `DONE` | **terminal** (absorbing) | Mark unit `PASS`; append any generalizable `LEARNINGS` entry (§4); propagate handoff notes into downstream briefs; `TaskUpdate`. |

`EXECUTE` is the entry state for every unit.

### 1.2 Loop variables (the FSM state carried in `fsm-state.json`)

| Var | Type / domain | Init | Rule |
|-----|---------------|------|------|
| `state` | enum `Q` | `EXECUTE` | current state |
| `retries` | int, invariant `0 ≤ retries ≤ 2` (`maximum: 2`) | `0` | **monotone**: only `RETRY` writes it, and only `+1`. Never reset within a unit. |
| `iteration` | int `≥ 1` | `1` | bound (I4): `iteration ≤ retries + 1` (the current attempt number; validator checks the upper bound) |
| `verdict` | enum `{PASS, FAIL, DISAGREE, ⊥}` | `⊥` | set by `VERIFY`; read by `ADJUDICATE` |
| `feedback` | object \| null (§3) | `null` | last verifier feedback; consumed by the next `EXECUTE` |

`MAX_RETRIES = 2` is the **default**; the termination argument (§2) is *parametric in any
finite bound N* (see §6.4), so a configurable cap never weakens termination. `2` is the
hard schema ceiling `fsm-state.schema.json` encodes (`maximum: 2`).

### 1.3 Transition table (complete, guards exhaustive & mutually exclusive)

State × event/guard → action → next state. `↑retries` = increment.

| # | From | Event / guard | Action | To |
|---|------|---------------|--------|----|
| LT1 | `EXECUTE` | `execute_done` (debrief + artifacts written) | — | `VERIFY` |
| LT2 | `VERIFY` | `verify_done` (schema-valid verify.json) | set `verdict`, `feedback` | `ADJUDICATE` |
| LT3 | `ADJUDICATE` | `verdict == PASS` | — | `DONE` |
| LT4 | `ADJUDICATE` | `verdict == FAIL ∧ retries < 2` | — | `RETRY` |
| LT5 | `ADJUDICATE` | `verdict == FAIL ∧ retries == 2` | — | `ESCALATE` |
| LT6 | `ADJUDICATE` | `verdict == DISAGREE` | — | `ESCALATE` |
| LT7 | `RETRY` | `retry_prepared` (guard LT4 held ⇒ `retries<2`) | `↑retries`; embed `feedback` in next brief | `EXECUTE` |

`EXECUTE`, `VERIFY`, `RETRY` have unconditional single out-edges (LT1, LT2, LT7).
`ADJUDICATE`'s guards LT3–LT6 partition the whole reachable input space
`{PASS} ∪ {FAIL}×{retries<2, retries==2} ∪ {DISAGREE}` — so `ADJUDICATE` **always** has
exactly one enabled transition (no deadlock, no non-determinism). `verdict == ⊥` cannot
occur at `ADJUDICATE` because it is reachable only via LT2, which sets `verdict`.

> **Why no "non-actionable FAIL" branch is needed.** The verify contract (§3) makes a
> `FAIL` *schema-invalid* unless it cites a specific unmet criterion and non-empty
> `actionable_changes`. A verifier that cannot produce a concrete, retryable defect **must**
> emit `DISAGREE` (→ `ESCALATE`, LT6), not `FAIL`. So every `FAIL` reaching `ADJUDICATE` is
> already actionable, and the FAIL branch reduces to the counter guard alone.

### 1.4 Diagram

```
        ┌──────────────────────────────────────────────┐
        │                 (only back-edge, LT7: ↑retries)│
        ▼                                               │
   ┌─────────┐  LT1   ┌────────┐  LT2   ┌────────────┐    │
   │ EXECUTE │──────▶│ VERIFY │──────▶│ ADJUDICATE │    │
   └─────────┘       └────────┘       └────────────┘    │
                                       │  │  │          │
              verdict==PASS (LT3) ──────┘  │  └── verdict==FAIL ∧ retries<2 (LT4)
                        │                 │                        │
                        ▼                 │                        ▼
                   ┌────────┐             │                  ┌─────────┐
                   │  DONE  │             │                  │  RETRY  │──┘
                   └────────┘             ▼                  └─────────┘
              FAIL∧retries==2 (LT5) or DISAGREE (LT6)
                        │
                        ▼
                   ┌──────────┐
                   │ ESCALATE │ → Phase 7 human gate (leaves loop)
                   └──────────┘
```

---

## 2. Termination argument (a skeptic can verify this — not "we cap it")

We prove: **from `EXECUTE`, every run reaches a terminal state (`DONE` or `ESCALATE`)
after a bounded number of transitions.** Four checkable claims.

**Claim A — there is exactly one back-edge, and it is the counter increment.**
Enumerate every edge (LT1–LT7). Six are strictly forward or into an absorbing state
(LT1,LT2,LT3,LT5,LT6 forward/terminal; LT4 forward into `RETRY`). The *only* edge whose target
is an already-reachable earlier state is **LT7: `RETRY → EXECUTE`**. Therefore the sole
cycle in the whole graph is `EXECUTE → VERIFY → ADJUDICATE → RETRY → EXECUTE`, and every
traversal of it passes through LT7 **exactly once**. A skeptic verifies this by reading the
seven rows of §1.3 — no other row points backward.

**Claim B — a well-founded variant strictly decreases on every cycle.**
Define `V = MAX_RETRIES − retries = 2 − retries`. Since `0 ≤ retries ≤ 2`, `V ∈ {0,1,2}` —
a non-negative integer, bounded below by 0. LT7 executes `retries := retries+1`, so each
cycle traversal does `V := V − 1`: **strictly decreasing by exactly 1**. No other
transition changes `retries` (Claim A + the monotone rule in §1.2), so `V` never increases.

**Claim C — the back-edge is guarded by `V > 0`.**
LT7 is reachable only through LT4, whose guard is `retries < 2`, i.e. `V > 0`. So the cycle
can be entered only while `V > 0`. Once `V = 0` (`retries == 2`), LT4 is disabled and
`ADJUDICATE` can select only LT3 (`PASS`→`DONE`), LT5 (`FAIL`→`ESCALATE`), or LT6
(`DISAGREE`→`ESCALATE`) — all terminal. A well-founded measure that strictly descends on
the only cycle and whose back-edge is disabled at the floor **cannot be traversed
infinitely**: at most `MAX_RETRIES = 2` traversals occur.

**Claim D — no deadlock; both terminals are reachable.**
Every non-terminal state has an enabled out-edge for every reachable input: `EXECUTE`,
`VERIFY`, `RETRY` unconditionally (LT1,LT2,LT7); `ADJUDICATE` because LT3–LT6 are exhaustive
(§1.3). So the machine can never get stuck in a non-terminal state; combined with A–C it
must halt in `DONE` or `ESCALATE`. Both are reachable:
- `DONE`: `EXECUTE→VERIFY→ADJUDICATE` with `verdict=PASS` (LT3) — any attempt may pass.
- `ESCALATE`: first verdict `DISAGREE` (LT6); **or** the trace `FAIL,FAIL,FAIL` drives
  `retries 0→1→2` then LT5. So the retry budget can genuinely be exhausted, and the escape
  hatch is genuinely reachable.

**Bound.** The straight-line segments are finite, so total transitions before halt are
`(MAX_RETRIES+1)·|EXECUTE→VERIFY→ADJUDICATE| + MAX_RETRIES·|RETRY|` = `3·3 + 2·1 = 11` loop
transitions — the terminal `DONE`/`ESCALATE` edge is the last of the ≤3 `ADJUDICATE` out-edges,
not an extra step — i.e. **≤ 3 executions, ≤ 3 verifications, ≤ 2 retries, then exactly one
terminal**. (Counting the single entry edge into `EXECUTE`, the round figure **≤ 12** cited in
SKILL Phase 6 holds as a valid, non-tight bound.) Each state's internal work is itself finite (executor under a
32K budget; the `VERIFY` node is a single pass, a fixed odd panel of 3 (PR1 default on `high-stakes`
units), and/or a **loop-until-dry sweep bounded by `R_max = 3` rounds** — dry OR cap ends the node),
so wall-clock work is finite too. ∎

> **FLAG — PR1 verifier hardening, classified PRESERVES (termination + AO-1..7).** The panel-of-3
> default and the loop-until-dry sweep are **node-internal work inside `VERIFY`**: neither adds a row
> to the §1.3 transition table, neither introduces a second back-edge, and neither touches the
> variant `V = 2 − retries` (only LT7 writes `retries`). The panel is a *fixed* odd fan-out (3) and
> the sweep is *bounded* (`R_max = 3`, dry-or-cap), so `VERIFY`'s internal work stays finite — Claims
> A–D above hold **verbatim**. Migration argument: this is the same category as the pre-existing
> "fixed odd panel of 3" the proof already admitted; we only make it the default on `high-stakes`
> units and add a bounded accumulation sweep, both of which the §2 finiteness argument already
> covers. The panel verdict is aggregated by **discrete majority** (a split ⇒ `DISAGREE`, LT6) — the
> guard table stays boolean and mutually-exclusive; **softmaxing it would REVISE (break) the proof**
> by replacing the discrete split→DISAGREE routing with a thresholded/averaged score — collapsing the
> exhaustive, mutually-exclusive `ADJUDICATE` guard partition — and is therefore forbidden (§3).

> The load-bearing point the brief demands: the guarantee is **not** the cap. It is that
> the *only* cycle strictly descends a well-founded, floor-bounded measure whose back-edge
> is disabled at the floor, `ADJUDICATE`'s guards are exhaustive (no deadlock), and both
> absorbing states are reachable. The cap `2` is merely the floor value; swap any finite
> `N` and the identical proof holds (§6.4).

---

## 3. Verdict / feedback JSON contract (verify → executor)

The verifier **emits** this; on `RETRY` the next executor **consumes** `feedback`. It is
the machine seam encoded as `verify.schema.json`, which is top-level
`additionalProperties:false` with **nine required keys**: `unit_id`, `verifier_persona`,
`verdict`, `iteration`, `executor_reasoning_seen`, `feedback`, `defects`, `socratic`,
`premise_check` (the optional keys are `inputs_reviewed`, `audit_notes`, the PR1 fields
`panel`/`verify_rounds`/`converged`, and — only for a `DISAGREE` — `disagreement`). Free-form reasoning happens first; this is the *extracted* artifact
(structure the plumbing, not the reasoning). The block below is a VALID instance (a `FAIL`);
strip the `//` comments to parse it.

```jsonc
{
  "unit_id": "U07",                       // required, string matching ^U[0-9]{2,}$ (the unit under verification)
  "verifier_persona": "Adversarial Verifier (independent, correctness lens)", // required, non-empty string — FLAT, not a nested object
  "verdict": "FAIL",                      // required, enum PASS|FAIL|DISAGREE (this instance shows FAIL)
  "iteration": 1,                         // required, int ≥1  (iteration ≤ retries+1 at verify time — I4)
  "executor_reasoning_seen": false,       // required, MUST be false (independence invariant AO-7 / I1) — the field the validator checks
  "inputs_reviewed": ["brief.md", "debrief.json", "<artifact paths>"], // optional, array of strings
  "feedback": {                           // required, object (additionalProperties allowed)
    "summary": "<one-line verdict rationale>",
    "actionable_changes": ["<imperative change 1>", "..."],             // FAIL ⇒ ≥1 (conditional rule below)
    "do_not_touch": ["<already-PASSED criteria a retry must not regress/re-open>"]
  },
  "defects": [                            // required array — PASS ⇒ no blocker/major (minor allowed, PR1); FAIL ⇒ ≥1 (conditional rule below)
    {
      "severity": "major",                       // required, enum blocker|major|minor
      "criterion": "<verbatim brief acceptance-criterion this violates>", // required, non-empty; ∈ brief.acceptance_criteria
      "minimal_repro": "<inputs → observed wrong/missing output>",        // optional
      "fix_direction": "<concrete hint, NOT a full rewrite>"              // optional
    }
  ],
  "socratic": {                           // required — the VERIFIER's canonical 4-key block on its own verdict
    "premise": "<the claim my verdict stands or falls on>",
    "counter": "<the case I sought against my verdict + its OUTCOME (not a promise)>",
    "pivot": "<the fact that, if flipped, flips my verdict>",
    "confidence": "high — <residual uncertainty>"   // required, must start high|medium|low
  },
  "premise_check": {                      // required — premise-deflection backstop: verifier re-confirms the premise is load-bearing and re-runs COUNTER independently (additionalProperties:false)
    "executor_premise_quoted": "<the executor's load-bearing premise, verbatim>",
    "is_load_bearing": true,
    "counter_reran_independently": true,
    "outcome": "<holds | breaks — OUTCOME of re-running COUNTER from evidence, never from executor reasoning>"
  }
  // "disagreement": { "why_unresolvable": "..." }  // include ONLY iff verdict==DISAGREE (omitted here)
}
```

**Conditional-required rules (`verify.schema.json` encodes as `if/then`; they are the retry-validity
preconditions and the anti-vague-fail gate):**

- `verdict == PASS` ⇒ **no blocker/major defect** (REVISED for coverage-first, PR1 — was `defects == []`; a PASS MAY carry `minor` observations, but no blocker/major).
- `verdict == FAIL` ⇒ `defects.length ≥ 1` **and** every `defects[].criterion` is non-empty
  **and** appears among the brief's acceptance criteria **and** `feedback.actionable_changes.length ≥ 1`.
  (A `FAIL` that cannot meet this bar is not a valid `FAIL` — the verifier must emit
  `DISAGREE`. This is invariant **AO-3, no vague fail**, and is exactly what makes LT4's
  target actionable.)
- `verdict == DISAGREE` ⇒ `disagreement` present and complete.

**Panel + loop-until-dry contract (PR1 — optional fields; node-internal; validator-checked by I16).**
Three optional keys record the PR1 verifier hardening; all are node-internal to `VERIFY` (they add
no FSM edge — §2 FLAG):

- `panel: [{ lens ∈ {correctness, reproduce, guardrail}, verdict, verifier_persona?, summary? }]` —
  the odd panel (≥3) of independent verifiers with **distinct lenses**. **DEFAULT on `high-stakes`
  units** (I16 REQUIRES it there). The top-level `verdict` is the **DISCRETE majority** of the panel
  verdicts (2-of-3); a split with no strict majority ⇒ `verdict == DISAGREE` (→ LT6 → ESCALATE, the
  AO-5 genuine-split route). **No softmax** — the aggregate is a discrete mode, never an averaged
  score (softmaxing the discrete guard partition would REVISE the §2 proof).
- `verify_rounds: int 1..R_max` (`R_max = 3`) and `converged: bool` — the **loop-until-dry** sweep:
  run rounds accumulating defects until a round surfaces no new defect (`converged: true`) or the cap
  is hit (`converged: false`, coverage possibly incomplete). Bounded ⇒ finite (§2). I16 checks
  `1 ≤ verify_rounds ≤ R_max`.

I16 (state-machine.md §4) enforces these **post-hoc/offline** and gates **no** transition (never a
live LT7 guard — the 02/P1 deadlock lesson), exactly like I14/I15.

**Consumption contract (checkable).** On a retry (`debrief.iteration = n > 1`), the executor's
`debrief.prior_feedback` block echoes iteration `n−1`'s `verify.feedback` — `actionable_changes`
+ `do_not_touch` — plus the `changes_made` it produced in response (this field lives on
`debrief.schema.json`, not `brief.schema.json`, which is `additionalProperties:false`). The
validator does **not** diff the echo against the n−1 verify (it retains only the latest
`verify.json` per unit, so an n−1 copy is unavailable); instead it runs two **presence-gated,
post-hoc** predicates over that echo — each a no-op when the echo is absent, so neither can gate
the loop (I14 / I15 in state-machine.md §4; the inline I14/I15 checks in `validate_run.py`'s
`main()`):

```
I14 (AO-2): ∀ unit, iter=n>1 with prior_feedback.do_not_touch present :
              { verify.defects[].criterion } ∩ prior_feedback.do_not_touch == ∅
I15 (AO-6): ∀ unit, iter=n>1 with a prior_feedback echo :
              prior_feedback.changes_made is present and non-empty
```

**FSM-state seam (`fsm-state.schema.json`).** Loop substate object:
`{ unit_id, state ∈ Q, retries: int 0..2 (maximum:2), iteration: int ≥1 (≤ retries+1),
last_verdict, last_feedback_ref }`. This is the `retries`-counter + loop-substate shape the
schema encodes, with the enum `Q` and the `iteration ≤ retries+1` bound (I4; the validator
checks the upper bound, not a hard equality).

---

## 4. The two loops, formalized

### 4.1 Correction loop (within a unit) — the state machine above

`FAIL → RETRY → re-verify`, cap 2, else `ESCALATE` (Phase 7). This is §1–§3 in full. The
external signal that authorizes a retry is the **independent verifier's** `FAIL` (never the
executor's self-review — **AO-4**). Every iteration is logged in `PROGRESS.md`.

### 4.2 Learning loop (across units) — LEARNINGS entry schema

A lesson enters `LEARNINGS.md` **only if generalizable** and **keyed to a verifiable
outcome** (a verify verdict, a test result, a cited finding). One-off facts stay in the
unit debrief (this is the over-fitting guard — see §6.2).

**Entry schema.** Canonical **required** field set:
`id, trigger, lesson, how_to_apply, scope{applies_to}, evidence, since_wave` — within `scope`, only
`applies_to` is required; `excludes` and `expiry` are **optional** (matching `learnings.schema.json`
`scope.required: ["applies_to"]` and `templates/graph.md`). `promotable` is **optional** too (not
part of the required set — the §4.3 propagation predicate keys off `since_wave`, never `promotable`).

| Field | Type | Meaning / rule |
|-------|------|----------------|
| `id` | `"L<n>"` (run/project) or `"G<n>"` (global import) | stable id — matches `learnings.schema.json` `^[LG][0-9]+$` |
| `since_wave` | int ≥ 1 | the wave from which this lesson binds later briefs (used by the propagation rule §4.3) |
| `trigger` | string | **the verifiable outcome** that produced the lesson — e.g. `"U0X verify FAIL: <criterion>"`, a test result, or a cited finding id. MUST reference an external signal, **not** a self-assessment. |
| `lesson` | string (1 sentence) | the generalizable rule |
| `how_to_apply` | string | the concrete action a future brief takes |
| `scope` | object | `{ applies_to: SelectorSet, excludes: [unit-id...], expiry: "run \| project \| runs:N \| date:<iso>" }` — the **anti-over-fit guard** (§6.2); the loader-side grammar `validate_run.py` enforces (`_expiry_expired`), any other value is inert |
| `evidence` | locator | external signal: `verify.json` path / a cited finding id / command→output |
| `promotable` *(optional)* | bool | **optional**, not in the canonical required set; marks an entry eligible to be lifted to `CLAUDE.md`/a skill at Phase-8 sign-off |

**`SelectorSet` — the four selector kinds (all mechanical, no free-text NLP).** Each element
of `applies_to` is exactly one of:

| Selector | Written as | Matches unit `U` when |
|----------|-----------|-----------------------|
| unit-id | `"U0X"` | `U.id == "U0X"` |
| phase | `"phaseN"` | `U.phase == "phaseN"` |
| **pattern (tag)** | `"tag:<T>"` | `T ∈ U.tags` — set membership; `T` drawn from the **enumerated tag vocabulary `V_tag`** below |
| all | `"all"` | always (subject to `excludes`) |

**Pattern scope is a tag, not prose.** A `pattern`-scoped lesson is expressed as one or more
`"tag:<T>"` selectors. Free-text patterns are inadmissible — `T` MUST come from `V_tag`, a
**documented, enumerated registry seeded in `GRAPH.md`** (extended only by adding to the
registry, never by ad-hoc strings), e.g.:

```
V_tag = { research, schema, validator, code, template-edit, prose-edit,
          design, verification, loop, socratic, synthesis, ops, high-stakes }
```

The `high-stakes` tag additionally carries an **operational** meaning beyond learnings-scoping
(PR1 verifier hardening): a unit tagged `high-stakes` is verified by the **default odd panel of 3**
with distinct correctness/reproduce/guardrail lenses, and its `verify.json` MUST carry that
`panel[]` — enforced post-hoc by validate_run.py **I16** (§3; references/methodology.md
§Verification). It remains an ordinary `V_tag` member for tag-scoped propagation as well.

Correspondingly, **every unit declares an explicit `tags: [T ∈ V_tag]` set** in its `GRAPH.md`
row (mirrored into its brief). This is what makes pattern matching a mechanical set-membership
test a validator can enforce, instead of natural-language matching. (This requires `tags` on
`GRAPH.md` unit rows and in `brief.schema.json`, with `V_tag` seeded in `GRAPH.md`.)

**Effective tag domain `V_tag_eff` (04/G1 FLAG — a domain revision, not a pure additive check).**
The I11/I12 tag domain is widened from the run-local `V_tag` to
`V_tag_eff = global ∪ project ∪ run_local`. The global tier is the registry `~/.claude/dag/tags.json`
(schema `schemas/tags.schema.json`), UNIONed into the domain when present (label
`I11 global tag registry (G1) loaded …`); an absent/invalid file ⇒ `global_tags = ∅` ⇒
`V_tag_eff = V_tag` (today's behavior, backward-compat anchor). No project tag registry exists yet
(U03 shipped a project *learnings* store, not a tag store), so `V_tag_eff = global ∪ run_local` today;
the union is written so a project tier drops in trivially. I11 stays `T ∈ V_tag_eff` — a finite
enumerated string set, exact Python set-membership, **no NLP**: the *domain* grows, the test's *kind*
does not. Because it revises the I11/I12 **domain** (additive), an invalid registry falls back to
run-local `V_tag` — the domain is never widened silently or on bad data. Paired with it is the
**authored-vs-imported admission carve-out** (04/G1): a run-local one-off (`L#` id, not store-loaded)
still needs **≥2 current-run carriers** to admit a `tag:T` scope, but an **imported/already-generalized**
entry (store-loaded id, or a `G#` global id) is EXEMPT from that ≥2-carrier re-proof (label
`I12 admission carve-out (G1)`) while STILL governed by the I12 propagation predicate — so it is
force-injected wherever its tag actually appears. `L#` = re-proved each run; `G#`/store-loaded =
imported, exempt from re-proof only. (The exemption *trusts* the `G#`-id/store provenance as the
"already-generalized" signal — a provenance-trust boundary, see state-machine.md §5.)

**Generalizability gate (checkable admission rule).** An entry is admissible in
`LEARNINGS.md` **only if** — checked mechanically against the DAG — its `applies_to` would
match **≥ 2** units in the run:
- an `"all"` or `"phaseN"` selector trivially can (a phase holds ≥2 units in a non-trivial run);
- a **`"tag:<T>"`** selector is admissible **only if ≥ 2 units in `GRAPH.md` carry tag `T`**
  (so a one-off cannot masquerade as a pattern — a tag borne by a single unit fails the gate);
- a bare unit-id set is admissible only if it lists ≥ 2 unit-ids.

A lesson that matches a single unit is **rejected** → it belongs in that unit's `debrief.json`,
not the ledger. (Keeps the ledger generalizable: reflections keyed to outcomes,
not free-floating self-assessment.)

### 4.3 The propagation rule — "downstream briefs must include applicable learnings"

**Rule.** For every entry `E` and every unit `U` whose brief is generated in a wave **no
earlier than** `E.since_wave` (`U.wave ≥ E.since_wave`), if `E.scope` matches `U` then `U`'s
brief MUST list `E.id` in a `learnings_applied` field **and** quote `E.lesson` +
`E.how_to_apply` in its context section.

**Machine-checkable predicate (the validator runs this over the learnings ledger ×
`units/*/brief.md`; violation ⇒ non-zero exit):**

```
applies(E.scope, U) ≡
      (    "all"     ∈ E.scope.applies_to                      // all-selector
        ∨  U.id      ∈ E.scope.applies_to                      // unit-id selector
        ∨  U.phase   ∈ E.scope.applies_to                      // phase selector
        ∨  ∃ "tag:T" ∈ E.scope.applies_to :  T ∈ U.tags )      // pattern/tag selector — set membership
   ∧ ¬( U.id ∈ E.scope.excludes )

REQUIRE  ∀ E ∈ LEARNINGS, ∀ U ∈ briefs with U.wave >= E.since_wave :
             applies(E.scope, U)  ⇒  E.id ∈ U.brief.learnings_applied
```

The **pattern/tag** disjunct is the fix: a generalizable `"tag:<T>"`-scoped lesson now
matches exactly the units whose declared `U.tags` (§4.2) contain `T` — so it *is* force-
injected into every applicable later brief, and its omission *is* flagged. `U.tags` and `T`
both range over the enumerated `V_tag`, so the whole predicate stays mechanical set-membership.

Three properties make this safe, not blind:
1. **Temporal (wave-based):** a learning binds only briefs whose wave is **no earlier than** its `since_wave` (`U.wave ≥ E.since_wave`) — never retroactively.
2. **Scoped, not global:** every disjunct is set-membership on `scope`; a correctly-scoped
   one-off (or a mis-scoped lesson caught by the gate in §4.2) is **not** force-injected into
   unrelated units. The counterexample defense of §6.2.
3. **No silent drop (pattern completeness):** every selector kind admissible in §4.2 —
   `all`, `unit-id`, `phase`, **and `tag`** — has a matching disjunct here, so no admitted
   learning can pass the gate yet match zero units. (This closes the pattern-completeness gap.)

Needs `brief.schema.json` to require `learnings_applied: [string]` **and** a `tags: [T ∈ V_tag]`
field per unit (mirrored from `GRAPH.md`) so the tag disjunct is checkable.

### 4.4 Across-run + user/global persistence (rings 03/04 — post-hoc validator-checked)

The learning loop persists **beyond one run** via two stores that mirror the persona precedent,
loaded at **Phase-0.5 intake** (SKILL.md) as a prose step Dag executes, and independently
re-discovered by `validate_run.py` post-hoc so the I12 propagation predicate ranges over the merged
set. All of the below are **additive + post-hoc + offline**: none gates the FSM, so the §2 termination
proof is untouched. Only the validator predicates named are mechanically enforced (post-hoc); store
discovery/merge/promotion at *runtime* is prose the model executes.

- **Two stores, override order project > user.** Project `.dag/learnings/*.json` (03/P1) and
  user/global `~/.claude/dag/learnings/*.json` (04/G2), each file one `$defs/entry` object,
  schema-validated; a malformed entry is REPORTED and DROPPED, never a crash. On an `id` **or**
  `scope.applies_to` collision the higher-precedence (project, then user) entry wins and the shadowed
  one is dropped (label `learnings user-store override (G2)`). Absent stores ⇒ zero change; imported
  ids join `store_ids` so they are treated as imported by the 04/G1 carve-out.
- **Advisory imports until re-grounded (03/P4).** Where the I12 propagation loop consumes the finalized
  learning set, the validator PARTITIONS it into an **active** set (run-local authored entries ∪
  imported entries carrying `grounding == "re-grounded"`) and an **advisory** set (imported entries —
  `eid ∈ store_ids` or a `G#` id — WITHOUT that marker). The I12 required-propagation predicate + the
  §4.2 admission gate iterate the **active** set only (so the §4.3 `REQUIRE` quantifier ranges over
  `active`, not the full merged set); an advisory entry is still LOADED and REPORTED (label
  `advisory import (not force-injected): <id>`) but its omission from a brief NEVER `rep.fail`s, and the
  I12 propagation summary gains an `N active … M advisory import(s) not force-injected (03/P4)` suffix.
  This is the **AO-4** tie: an un-re-grounded import is **not** an external signal that binds briefs —
  only a run-local authored entry, or an import you have re-grounded to a THIS-run signal, is. A
  re-grounded import re-enters `active` and is governed by I12 (incl. the 04/G1 ≥2-carrier carve-out)
  exactly like a run-local entry. `grounding` is an **optional** top-level `$defs/entry` field
  (load-bearing value `"re-grounded"`; inert on run-local authored entries). Absent store ⇒ `store_ids`
  empty, no `G#` ids ⇒ advisory empty ⇒ `active` == today's set ⇒ zero behavior change. **Honest
  boundary:** re-grounding is keyed on this same-project `grounding` marker — a local trust signal,
  **not** cryptographic provenance; a verifiable cross-party trust model is the deferred ring-05 work,
  out of scope here.
- **Promotion → persistence → re-import cycle (03/P2).** Phase-8 writes each `promotable:true`,
  non-expired entry into `.dag/learnings/<id>.json` (upsert by `id`; `run`-scoped never persisted);
  Phase-0.5 re-reads it. This is a prose step — the validator does **not** auto-write; its 04/G3 hook
  only surfaces a non-gating `NOTE  G3 promotion (advisory)` line per `promotable` entry (eligible for
  HUMAN promotion to `~/.claude/dag/principles.md`).
- **`expiry` — loader-side grammar, not a schema enum (03/P3).** `scope.expiry` parses as
  `run|project|runs:N|date:<iso>`; an expired entry (a `runs:N` budget exhausted via `applied_count`,
  a past `date:`, or a `run`-scoped entry loaded from a store) is EXCLUDED from propagation and
  REPORTED (label `learnings expiry (03/P3): <id> EXCLUDED …`), never a hard-fail. An unparseable /
  unrecognized `expiry` fails **OPEN** (inert) — never a crash, never a silent exclusion.
- **Decay / GC (04/G5).** `max_idle_runs`/`last_applied_run`/`last_confirmed`/`applied_count` drive
  idle-decay, EXTENDING the P3 traversal (one loop, not a duplicate). Today it is DECIDABLE only for
  `max_idle_runs == 0` on a store-loaded, not-applied/confirmed-this-run entry (label
  `learnings decay/GC (04/G5): <id> EXCLUDED … ARCHIVE-not-delete`); `max_idle_runs ≥ 1` needs a
  cross-run idle counter a single-run validator cannot derive, so it is left INERT/fail-safe
  (documented limitation). ARCHIVE-not-delete: the validator only *reads*, never mutates the source file.
- **`scope.model` narrowing (04/G4).** An optional `scope.model` makes an entry bind only when the
  run's `fsm-state.model` matches (fnmatch glob OR prefix); a model-agnostic entry = all models; an
  absent run model with `scope.model` set ⇒ fail-closed (not injected). It can ONLY narrow (scope.model
  was ignored before = applies-to-all), label `I12 model narrowing (04/G4): <id> … EXCLUDED …`.
- **Contradiction / `supersedes` (03/P5).** An entry with `supersedes: "<id>"` (a single id — a
  string, not an array; to supersede several entries, emit several superseding entries or consolidate)
  EXCLUDES the
  superseded entry from propagation (label `learnings contradiction (03/P5): <id> superseded …`). Two
  live entries competing for the same `scope.applies_to` with no `supersedes` ordering are surfaced as
  a NON-failing human-escalation `NOTE  contradiction (03/P5): … NOT auto-picked` (AO-5: genuine split
  ⇒ human) — never auto-picked, never a `rep.fail`, because complementary-vs-contradictory cannot be
  decided without NLP (G2 forbids it).

---

## 5. Anti-oscillation invariants (AO-1 … AO-7)

Each is stated so it is either mechanically checkable or a hard structural rule.

- **AO-1 Monotone counter (no reset).** `retries` is append-only within a unit; only LT7
  writes it, only `+1`. ⇒ the variant `V` of §2 strictly descends; no path re-inflates the
  budget. *This is the mechanical core of both termination and anti-oscillation.*
- **AO-2 Never re-verify a PASSED claim.** A criterion once `PASS` enters
  `feedback.do_not_touch`; a retry MUST NOT re-open it and the verifier MUST NOT
  re-litigate it. Specified as `retry-verify.defects[].criterion ∩ prior.do_not_touch = ∅` and now
  **validator-checked, post-hoc**, by predicate **I14** in `validate_run.py` (label
  `I14 AO-2 do_not_touch disjointness (units/<uid>)`): for a `debrief.iteration>1` it fails **closed**
  on a non-empty intersection of `verify.defects[].criterion` with the retry's
  `debrief.prior_feedback.do_not_touch`. It is an offline read that **gates no transition** (a live
  guard on LT7 would leave `RETRY` with no out-edge → deadlock, breaking §2 Claim D — the 02/P1 FLAG),
  so AO-1 still owns halt. Kills pass→fail→pass ping-pong. (Even if the verifier flip-flops, AO-1 still
  forces halt.) **Named Limitation — I14/I15 data-availability (L1):** I14 fires *only when the retry's
  `prior_feedback` echo is present* (a retry omitting `do_not_touch` is skipped, not failed), and it
  compares the executor's **self-reported** `prior_feedback.do_not_touch` echo — NOT the authoritative
  prior verify — because the validator retains only the *latest* `verify.json` per unit (no
  per-iteration verify history to reconstruct). So I14 checks *presence/plumbing*, not full
  authoritative AO-2 enforcement; the independent verifier remains the semantic backstop. (02/P6
  auto-seeds `do_not_touch` from the passed criteria to close the completeness hole — templates/verify.md.)
- **AO-3 No vague FAIL.** Every `FAIL` defect cites a specific unmet acceptance criterion
  from the brief (§3 conditional rule). A FAIL citing no criterion is schema-invalid ⇒ the
  verifier must use `DISAGREE`. (Critics hallucinate nitpicks —
  cdn.openai.com/llm-critics-help-catch-llm-bugs — so a FAIL must be evidence-bound.)
- **AO-4 External-signal gate.** A retry is authorized **only** by an independent
  verifier's `FAIL`, never by executor self-review. The executor cannot self-trigger a
  retry. (Intrinsic self-correction of reasoning is unreliable/degrading;
  makers favor their own outputs → maker ≠ checker.)
- **AO-5 Genuine split ⇒ human, not loop.** An objective-irresolvable executor↔verifier
  split is `DISAGREE → ESCALATE` (LT6, Phase 7), never an unbounded retry. The loop never
  tries to "win" a judgment call by re-running.
- **AO-6 New-evidence requirement.** Each retry's debrief must cite ≥1 change responsive to
  the prior `feedback.actionable_changes`. A no-progress "spin in place" is thereby visible;
  and because AO-1 increments regardless, no-progress still terminates via the counter.
  (Converge only when each pass carries a fresh verifiable signal.) Now **validator-checked,
  post-hoc**, by predicate **I15** in `validate_run.py` (label `I15 AO-6 responsive change
  (units/<uid>)`): for a `debrief.iteration>1` that carries a `prior_feedback` echo it requires
  `prior_feedback.changes_made` present and non-empty, else FAIL. Like I14 it is offline and gates no
  transition. **Same Named Limitation (L1):** I15 is gated on the *presence* of the `prior_feedback`
  echo (a retry omitting the whole block is skipped, not failed), and `changes_made` is
  **executor-self-attested** — I15 checks presence/plumbing, not genuineness (the "validity ≠
  correctness" boundary, §6.5). A lazy executor could list a token change; the independent verifier is
  the semantic backstop.
- **AO-7 Verifier independence per iteration.** Every `VERIFY` (incl. retries) is a fresh
  independent verifier that does not see the executor's reasoning or identity;
  `verify.executor_reasoning_seen == false` is an invariant. When the unit runs a **panel** (PR1),
  *every* panelist is independent per this rule, and each retry re-panels afresh.

**PR1 note — the I6 PASS revision interacts cleanly with AO-2/I14.** I6's PASS clause is REVISED for
coverage-first: a PASS may now carry `minor` observations (but no blocker/major). This does **not**
weaken AO-2: the auto-seeded `do_not_touch` (02/P6) is *(brief criteria) − (this verify's
`defects[].criterion`)*, so a criterion carrying even a `minor` defect is (correctly) **not** sealed
into `do_not_touch` — a later retry is still permitted to touch it, while I14 keeps a retry's defects
disjoint from the criteria that were genuinely clean. A PASS ends the loop (LT3), so its `do_not_touch`
binds no retry anyway. The revision is a **content-rule change on the verify artifact** (I6), not an
FSM/guard change — it PRESERVES termination (verdict enum unchanged; the §1.3 partition is untouched).

---

## 6. Socratic self-interrogation (run before finalizing)

**6.1 Could this still fail to terminate or oscillate?** Constructing a non-terminating
trace requires either (a) a second cycle — none exists, §2 Claim A enumerates all edges; or
(b) traversing the one cycle infinitely — impossible, its back-edge strictly descends a
floor-bounded variant disabled at the floor (Claims B–C). The subtle oscillation risk
(verifier flip-flops pass↔fail on the same criterion) is neutralized by **AO-2** +
**AO-1**: even a flip-flopping verifier cannot prevent halt, because `retries` rises
regardless of verdict content. **No non-terminating trace exists.** The PR1 panel + loop-until-dry
sweep do not change this: both are **bounded node-internal work inside `VERIFY`** (a fixed fan-out of
3; ≤ `R_max = 3` rounds), adding no edge and **never writing `retries`** — so Claims A–D and the
oscillation argument hold unchanged (§2 FLAG).

**6.2 Where would injected "learning" HURT a downstream brief?** A lesson over-fit from a
one-off — e.g. *"a unit needed `python3.11` f-string syntax"* — blindly injected into a
research unit would waste budget and mislead. Defenses: the **generalizability gate**
(§4.2) rejects single-unit lessons (they go to the debrief); the **`scope` field** +
`applies()` predicate (§4.3) inject a lesson only into matching units; `scope.excludes`
carves out exceptions. So the propagation rule is *scoped*, not *global* — precisely
the "keep entries generalizable" principle.

**COUNTER: can a pattern-scoped learning still be silently dropped,
or a one-off wrongly force-injected?** Both no.
- *Silent drop — closed.* §4.2 now admits exactly four selector kinds (`all`,`unit-id`,
  `phase`,`tag`) and §4.3's `applies()` has a matching disjunct for **each** (property 3,
  "pattern completeness"). A `"tag:<T>"` lesson matches every later unit with `T ∈ U.tags`
  and its omission is flagged. Repro trace from the defect now *fails loudly*: the learning
  `scope.applies_to = {"tag:schema"}` matches every unit carrying `schema` in `GRAPH.md.tags`;
  any such brief lacking it in `learnings_applied` ⇒ validator non-zero exit. No admitted
  learning can match zero units.
- *Wrongful force-injection — closed.* `T` ranges only over the enumerated `V_tag` (no
  free-text), and a `tag`-scope is admissible **only if ≥2 units carry `T`** (§4.2 gate), so
  a one-off cannot be dressed as a pattern; `excludes` + the temporal guard still carve out
  the rest. **Pattern completeness holds.**

**6.3 Evidence grounding.** External-feedback necessity → **AO-4** (arXiv:2310.01798). Bound
+ require-new-evidence to converge/avoid oscillation → variant §2 + **AO-6**
(arXiv:2303.11366). Self-preference → maker≠checker independence, **AO-7** (arXiv:2410.21819;
2404.13076). Critics hallucinate → evidence-bound FAIL, **AO-3**. Self-refine helps quality
not reasoning-correctness → the loop's correctness verdict is the *independent* verifier's,
not self-refine (arXiv:2303.17651).

**6.4 Is cap = 2 right, or configurable?** A bounded retry count is what matters; the exact
value is a cost/benefit knob, not a correctness constant. `2` retries (3 attempts) matches
`SKILL.md`/`methodology.md` §Self-learning loops and MAST's "step repetition / unaware of
termination" guardrails (arXiv:2503.13657); once external feedback is exhausted, more retries
rarely help and intrinsic correction can *degrade* (arXiv:2310.01798). **Recommendation:** default
`MAX_RETRIES = 2`. The ceiling is already exposed as the shipped constant — `fsm-state.schema.json`'s
`loop.retries.maximum: 2` (the schema IS the exposed constant); no separate `max_retries` field is
added, so there is no second mirror to keep in sync. Crucially, the §2 proof is **parametric in any
finite `N`** (variant `V = N − retries`), so configurability never weakens termination — a real
property, not an assertion.

**6.5 Residual uncertainty (model-judged, not mechanically decidable).** The validator
checks the *plumbing* — contract shape, the counter, `do_not_touch` disjointness, scope
membership — but the "validity ≠ correctness" principle holds: whether a criterion is *truly*
met, whether a defect is *actually fixed*, and whether a `PASS` is *correct* remain the
independent verifier's semantic judgment. Likewise the generalizability gate checks scope
*breadth* mechanically, but "is this lesson genuinely generalizable" is finally a
verifier/human call. These are surfaced honestly, not papered over.

---

## 7. How this wires into the rest of the skill

The contracts above are realized across the shipped skill: (1) `SKILL.md` Phase-6
adjudication uses the exhaustive guard table §1.3 + AO invariants; (2) `templates/verify.md`
carries `iteration` + structured `feedback{actionable_changes,do_not_touch}` + emits the §3
JSON; (3) `templates/debrief.md` echoes `prior_feedback` on `iteration>1` + `learnings_applied`;
(4) `templates/brief.md` carries `learnings_applied` + `tags:[T ∈ V_tag]` + quotes applicable
learnings; (5) `LEARNINGS.md` + `GRAPH.md` hold the §4.2 entry schema + 4-kind `SelectorSet` +
enumerated `V_tag` registry + per-unit `tags` column + generalizability gate (`scope`,
`evidence` columns); (6) the schemas + validator encode `verify.schema.json` conditional rules
(§3, incl. the REVISED PASS clause and the optional `panel`/`verify_rounds`/`converged` fields),
`fsm-state.schema.json` loop substates `Q` + `retries` `maximum:2` + `iteration ≤ retries+1`,
`brief.schema.json` `learnings_applied` + `tags`, the §4.3 propagation predicate, and the post-hoc
**I16** panel discipline (high-stakes ⇒ panel; discrete-majority aggregation; `verify_rounds` bound).
