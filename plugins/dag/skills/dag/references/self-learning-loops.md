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
bounded by `(MAX_RETRIES+1)·|EXECUTE→VERIFY→ADJUDICATE| + MAX_RETRIES·|RETRY| + 1 exit`
= `3·3 + 2·1 + 1 = 12` transitions, i.e. **≤ 3 executions, ≤ 3 verifications, ≤ 2 retries,
then exactly one terminal**. Each state's internal work is itself finite (executor under a
32K budget; verifier is a single pass or a fixed odd panel of 3), so wall-clock work is
finite too. ∎

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
`premise_check` (`inputs_reviewed`, `audit_notes`, and — only for a `DISAGREE` — `disagreement`
are the three optional keys). Free-form reasoning happens first; this is the *extracted* artifact
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
  "defects": [                            // required array — PASS ⇒ []; FAIL ⇒ ≥1 (conditional rule below)
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

- `verdict == PASS` ⇒ `defects == []`.
- `verdict == FAIL` ⇒ `defects.length ≥ 1` **and** every `defects[].criterion` is non-empty
  **and** appears among the brief's acceptance criteria **and** `feedback.actionable_changes.length ≥ 1`.
  (A `FAIL` that cannot meet this bar is not a valid `FAIL` — the verifier must emit
  `DISAGREE`. This is invariant **AO-3, no vague fail**, and is exactly what makes LT4's
  target actionable.)
- `verdict == DISAGREE` ⇒ `disagreement` present and complete.

**Consumption contract (checkable).** For any retry brief with `iteration = n > 1`, the
brief MUST contain a `prior_feedback` block equal to iteration `n−1`'s `verify.feedback`
(`actionable_changes` + `do_not_touch`), verbatim. Predicate the validator can run:

```
∀ unit, ∀ n>1 : brief[unit, iter=n].prior_feedback == verify[unit, iter=n-1].feedback
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
`id, trigger, lesson, how_to_apply, scope{applies_to, excludes, expiry}, evidence, since_wave`.
`promotable` is **optional** (not part of the required set — the §4.3 propagation predicate keys
off `since_wave`, never `promotable`).

| Field | Type | Meaning / rule |
|-------|------|----------------|
| `id` | `"L<n>"` | stable id |
| `since_wave` | int ≥ 1 | the wave from which this lesson binds later briefs (used by the propagation rule §4.3) |
| `trigger` | string | **the verifiable outcome** that produced the lesson — e.g. `"U0X verify FAIL: <criterion>"`, a test result, or a cited finding id. MUST reference an external signal, **not** a self-assessment. |
| `lesson` | string (1 sentence) | the generalizable rule |
| `how_to_apply` | string | the concrete action a future brief takes |
| `scope` | object | `{ applies_to: SelectorSet, excludes: [unit-id...], expiry: "run \| promote \| one-off" }` — the **anti-over-fit guard** (§6.2) |
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
          design, verification, loop, socratic, synthesis, ops }
```

Correspondingly, **every unit declares an explicit `tags: [T ∈ V_tag]` set** in its `GRAPH.md`
row (mirrored into its brief). This is what makes pattern matching a mechanical set-membership
test a validator can enforce, instead of natural-language matching. (This requires `tags` on
`GRAPH.md` unit rows and in `brief.schema.json`, with `V_tag` seeded in `GRAPH.md`.)

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

---

## 5. Anti-oscillation invariants (AO-1 … AO-7)

Each is stated so it is either mechanically checkable or a hard structural rule.

- **AO-1 Monotone counter (no reset).** `retries` is append-only within a unit; only LT7
  writes it, only `+1`. ⇒ the variant `V` of §2 strictly descends; no path re-inflates the
  budget. *This is the mechanical core of both termination and anti-oscillation.*
- **AO-2 Never re-verify a PASSED claim.** A criterion once `PASS` enters
  `feedback.do_not_touch`; a retry MUST NOT re-open it and the verifier MUST NOT
  re-litigate it. Specified as `retry-verify.defects[].criterion ∩ prior.do_not_touch = ∅` —
  enforced where mechanizable (AO-2 is currently discipline-level, **not** validator-checked).
  Kills pass→fail→pass ping-pong. (Even if the verifier flip-flops, AO-1 still forces halt.)
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
  (Converge only when each pass carries a fresh verifiable signal.) Specified; enforced where
  mechanizable — AO-6 is currently discipline-level, **not** validator-checked.
- **AO-7 Verifier independence per iteration.** Every `VERIFY` (incl. retries) is a fresh
  independent verifier that does not see the executor's reasoning or identity;
  `verify.executor_reasoning_seen == false` is an invariant.

---

## 6. Socratic self-interrogation (run before finalizing)

**6.1 Could this still fail to terminate or oscillate?** Constructing a non-terminating
trace requires either (a) a second cycle — none exists, §2 Claim A enumerates all edges; or
(b) traversing the one cycle infinitely — impossible, its back-edge strictly descends a
floor-bounded variant disabled at the floor (Claims B–C). The subtle oscillation risk
(verifier flip-flops pass↔fail on the same criterion) is neutralized by **AO-2** +
**AO-1**: even a flip-flopping verifier cannot prevent halt, because `retries` rises
regardless of verdict content. **No non-terminating trace exists.**

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
`MAX_RETRIES = 2`, expose it as `max_retries` in `fsm-state.json` with **schema ceiling
`maximum: 2`**. Crucially, the §2 proof is **parametric in any finite `N`** (variant
`V = N − retries`), so configurability never weakens termination — a real property, not an
assertion.

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
(§3), `fsm-state.schema.json` loop substates `Q` + `retries` `maximum:2` + `iteration ≤ retries+1`,
`brief.schema.json` `learnings_applied` + `tags`, and the §4.3 propagation predicate.
