<!-- VERIFY ARTIFACT GUIDE — the INDEPENDENT verifier produces units/<id>/verify.json ONLY
     (JSON-only; no verify.md). It saw brief.md + debrief.json + the produced artifacts, NEVER the
     executor's reasoning/chain-of-thought. Mandate: REFUTE — a verifier that only confirms is
     malfunctioning. Schema: schemas/verify.schema.json.

     ACCURACY NOTE: do the adversarial work FREE-FORM in your reply FIRST, THEN write verify.json.
     Optionally persist that work in the `audit_notes` string; the load-bearing outputs are the
     verdict/feedback/defects/premise_check. -->

# Verify artifact — `units/<UNIT-ID>/verify.json`

Do the adversarial work in your reply, then write `verify.json`:
1. **Independently re-check each acceptance criterion** (re-run the test / re-derive / open the source).
2. **Audit every debrief evidence row** — does the locator resolve? does it reproduce?
3. **Hallucination sweep** — any fabricated citation / API / path / quote?
4. **Budget** — is the executor's reported footprint plausible and ≤ 32K?
5. **Premise-deflection backstop** — FIRST confirm the executor's `premise` names the deliverable's
   *load-bearing* claim (if it names a safe peripheral one, re-derive the true premise and treat the
   block as failing); THEN re-run COUNTER on that premise **from evidence, never from the executor's
   reasoning**, and confirm the debrief's `counter` records an outcome, not a promise.

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
- `defects[]` — `PASS ⇒ []`; `FAIL ⇒ ≥1`, each `{severity (required; blocker|major|minor), criterion
  (required; verbatim from brief.acceptance_criteria — cross-checked by the validator), minimal_repro
  (optional), fix_direction (optional)}`
- `socratic{premise, counter, pivot, confidence}` — the verifier's own 4-key block on its verdict
- `premise_check{executor_premise_quoted, is_load_bearing, counter_reran_independently, outcome}`

**Optional keys:** `inputs_reviewed[]` (e.g. `["brief.md","debrief.json","<artifact paths>"]`),
`audit_notes` (free-form: the criteria-check / evidence-audit / hallucination-sweep narrative),
`disagreement{why_unresolvable}` (**iff** `verdict==DISAGREE`).

Conditional (schema-enforced): `PASS ⇒ defects==[]`; `FAIL ⇒ ≥1 defect citing a brief criterion +
≥1 feedback.actionable_change`, else emit `DISAGREE`. No `verify.md` is written — `verify.json` is
authoritative; adjudication reads its `verdict`/`feedback`/`defects`.
