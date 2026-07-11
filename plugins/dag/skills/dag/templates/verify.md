<!-- VERIFY ARTIFACT GUIDE — the INDEPENDENT verifier produces units/<id>/verify.json ONLY
     (JSON-only; no verify.md). It saw brief.md + debrief.json + the produced artifacts, NEVER the
     executor's reasoning/chain-of-thought. Mandate: REFUTE (coverage-first) — a verifier that only
     confirms is malfunctioning. Schema: schemas/verify.schema.json — the AUTHORITATIVE field list;
     this template is ILLUSTRATIVE (a field guide that tracks the schema; the schema wins on any
     drift). Distinct from the bottom note "verify.json is authoritative", which is about the produced
     ARTIFACT, not this field list — both hold.

     ACCURACY NOTE: do the adversarial work FREE-FORM in your reply FIRST, THEN write verify.json.
     Optionally persist that work in the `audit_notes` string; the load-bearing outputs are the
     verdict/feedback/defects/premise_check. -->

# Verify artifact — `units/<UNIT-ID>/verify.json`

## Coverage-first mandate (report everything; filter downstream)
**Recall first.** Report **every** defect you find, each tagged with a `severity`
(`blocker | major | minor`) — do **not** self-censor "small" findings, and do **not** apply an
"only report high-severity" filter (that lowers recall on any model). Severity **ranks** a finding;
it does **not gate whether you report it**. Triage happens *downstream* of the report, not inside
your head. A PASS **may** carry `minor` observations (the I6 PASS clause was revised for exactly
this — a PASS forbids only blocker/major defects; see references/self-learning-loops.md §5). Reserve
`FAIL` for a blocker/major defect that a retry must fix; record everything else as `minor` and let
the adjudicator/handoff decide.

Do the adversarial work in your reply, then write `verify.json`:
1. **Independently re-check each acceptance criterion** (re-run the test / re-derive / open the source).
2. **Audit every debrief evidence row** — does the locator resolve? does it reproduce?
3. **Hallucination sweep** — any fabricated citation / API / path / quote?
4. **Budget** — is the executor's reported footprint plausible and ≤ 32K?
5. **Premise-deflection backstop** — FIRST confirm the executor's `premise` names the deliverable's
   *load-bearing* claim (if it names a safe peripheral one, re-derive the true premise and treat the
   block as failing); THEN re-run COUNTER on that premise **from evidence, never from the executor's
   reasoning**, and confirm the debrief's `counter` records an outcome, not a promise.

## Loop-until-dry (bounded coverage sweep)
Run adversarial **rounds** inside this single VERIFY node, **accumulating** defects across rounds,
until a round surfaces **no new defect** ("dry") **or** you hit the cap **`R_max = 3`** rounds. The
verdict is derived from the *accumulated* defect set. This is node-internal work — it adds **no FSM
edge**, so the correction-loop termination proof is untouched (references/self-learning-loops.md §2).
Record `verify_rounds` (1–3) and `converged` (`true` iff you stopped dry, `false` iff you stopped at
the cap — say so honestly; coverage may be incomplete). A single-pass verify is `verify_rounds: 1`.

## Panel of 3 (DEFAULT on `high-stakes` units — distinct lenses, discrete majority)
A unit tagged **`high-stakes`** is verified by an **odd panel of 3** independent verifiers with
**distinct lenses**, not three clones (diversity beats redundancy):
- **correctness** — acceptance criteria met, evidence admissible and real;
- **reproduce** — re-run / re-derive the result independently (executable evidence, PR2);
- **guardrail** — no out-of-scope / gold-plated / delivered-non-goal work.

Record each panelist in `panel[]` (`{lens, verdict, verifier_persona?, summary?}`). The top-level
`verdict` MUST be the **DISCRETE majority** of the three (2-of-3) — **never a softmaxed or averaged
score**. If the three split with **no strict majority**, emit **`DISAGREE`** (a genuine split →
Phase-7 human gate, AO-5), not an invented middle verdict. `validate_run.py` **I16** enforces this
post-hoc: high-stakes ⇒ `panel[]` present (≥3, trio covered) and `verdict == discrete majority`.
(Routine units may use a single verifier and omit `panel[]`.)

## Guardrail-compliance block (`guardrail_compliance` — emit it on every verdict-bearing verify)
Attest the unit's non-goal compliance mechanically: one row per non-goal checked —
`{non_goal, status, note?}` where `non_goal` is the **VERBATIM** `clarifications.json non_goals`
string and `status ∈ respected | violated | not-applicable`. Cover at least every entry in the
unit's `non_goal_refs` (an uncovered ref is an I22 FAIL). The scaffolded default is to emit the
block on every verify that carries a verdict:
- A `violated` row on a **PASS** verdict is a validator **FAIL** (I22) — a delivered non-goal is a
  FAIL, not a bonus.
- Adoption-closure (validate_run.py **I22**, offline post-hoc): once ANY verdict-bearing verify in
  the run carries the block, EVERY verdict-bearing verify must.
- Honesty boundary: presence / verbatim membership / coverage are mechanical; whether a
  `respected` row is *true* remains your attestation (presence-not-genuineness).

**Required keys** (`schemas/verify.schema.json`):
- `unit_id`, `verifier_persona`, `verdict` (`PASS|FAIL|DISAGREE`), `iteration`
- `executor_reasoning_seen: false` (independence invariant AO-7)
- `feedback{summary (optional), actionable_changes[] (required), do_not_touch[] (optional)}` —
  `FAIL ⇒ ≥1 actionable_change`; `do_not_touch` = already-PASSED criteria a retry must not regress
  (AO-2)
  - **Auto-seed `do_not_touch` (02/P6 — completeness for the post-hoc I14 check).** Seed this
    iteration's `feedback.do_not_touch` as *(brief acceptance criteria) − (criteria in this verify's
    `defects[].criterion`)* — every criterion this verify did NOT fail is currently-passing and a
    retry must not re-open it. You MAY *add* to this set, but seeding it guarantees completeness so the
    offline **I14** disjointness check (AO-2; references/self-learning-loops.md §5) is meaningful for
    *all* passed criteria, not just the ones you remembered to list. Seed only from criteria your
    `inputs_reviewed`/audit actually covered — do not mark an untested criterion "passed".
- `defects[]` — `PASS ⇒ no blocker/major` (minor observations allowed — I6 revised, PR1); `FAIL ⇒ ≥1`, each `{severity (required; blocker|major|minor), criterion
  (required; verbatim from brief.acceptance_criteria — cross-checked by the validator), minimal_repro
  (optional), fix_direction (optional)}`
- `socratic{premise, counter, pivot, confidence}` — the verifier's own 4-key block on its verdict
- `premise_check{executor_premise_quoted, is_load_bearing, counter_reran_independently, outcome}`

**Optional keys:** `inputs_reviewed[]` (e.g. `["brief.md","debrief.json","<artifact paths>"]`),
`audit_notes` (free-form: the criteria-check / evidence-audit / hallucination-sweep narrative),
`panel[]` (`{lens ∈ correctness|reproduce|guardrail, verdict, verifier_persona?, summary?}` —
**required on `high-stakes` units**, I16), `verify_rounds` (1–3, loop-until-dry), `converged` (bool),
`guardrail_compliance[]` (`{non_goal (verbatim ∈ non_goals), status ∈
respected|violated|not-applicable, note?}` — the scaffolded default above; adoption-closure I22),
`disagreement{why_unresolvable}` (**iff** `verdict==DISAGREE`).

Conditional (schema-enforced): `PASS ⇒ no blocker/major defect` (minor observations allowed — I6
revised, PR1); `FAIL ⇒ ≥1 defect citing a brief criterion + ≥1 feedback.actionable_change`, else emit
`DISAGREE`. When a `panel[]` is present, `verdict` MUST equal its **discrete majority** (no softmax;
a split ⇒ `DISAGREE`). No `verify.md` is written — `verify.json` is authoritative; adjudication reads
its `verdict`/`feedback`/`defects`.
