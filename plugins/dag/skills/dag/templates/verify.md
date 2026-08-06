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

### Panel dissent — record the finding, then adjudicate it (I41)
Because the top verdict IS the discrete majority, a 2-1 panel **forces** the PASS, and I6 lets a PASS
carry only `minor`. So a dissenting lens' major finding has nowhere honest to go unless you record it:
- Put the member's own findings in **`panel[].defects[]`** at their **HONEST** severity (same shape as
  the top-level `defects`). I6 is scoped to the TOP-LEVEL list, so this is not an I6 violation.
- **If you cannot name an acceptance criterion, vote `DISAGREE`, not `FAIL`** — that is AO-3's own route
  (a `FAIL` citing no criterion is schema-invalid), and I41 does **not** ask a `DISAGREE` member for a
  criterion. It does ask you to say *something*: record a non-blank **`summary`** (or a `defects[]` entry
  with a non-blank `minimal_repro`). A bare `{lens, verdict: "DISAGREE"}` row is unauditable and FAILs
  I41-2(c). A `DISAGREE` member is still a full dissent — it still needs a `panel_adjudication` (I41-1)
  and still may not be re-polled (I41-4c).
- On a `PASS` with a dissenting member, record **`panel_adjudication`**:
  `{resolution: repoll|withdrawn|escalated-p7, rationale, dissent_refs[], dispositions[], repoll[],
  transcript_ref?}`. Every member `blocker`/`major` on a PASS needs a `dispositions[]` entry
  (`downgraded-minor` | `withdrawn` | `overruled-by-repoll`) with a real rationale.
- **You may NOT re-poll the dissenter**, nor any lens that had already tested the disputed finding
  (`tested_defect: true`) — re-running the dissenter until it flips is the AO-5 prohibition. Re-poll
  only lenses that never tested it; `panel[]` then holds the **FINAL** votes (`pre_verdict` preserves
  the original), and a re-poll counts as a second `verify_rounds` (still ≤ 3 — there is no extra
  budget; at 3, `withdrawn` or the honest FAIL majority are the only moves left).
- A `downgraded-minor` disposition MUST also appear as a top-level `minor` defect with the same
  criterion — a downgrade with no coverage-first echo is a deletion wearing a downgrade's label.
- `escalated-p7` cannot sit on a `PASS`. A withdrawal with no re-poll draws an advisory `N-I41` NOTE.

### Evidence digests in `inputs_reviewed` (I42)
An `inputs_reviewed` element may stay a bare path string **or** become
`{path, sha256?, bytes?}`. If you digest one, digest them **all** on that run (adoption closure), use
a run-dir-relative `path` that actually exists, and record a real 64-hex `sha256` — the validator
re-hashes it and FAILs when the evidence moved under the verification. Citing a SIBLING unit's artifact
is fine — the mid-loop grace period is judged on the unit that owns the **digested path**, not on yours.
Out-of-run/absolute paths are recorded as a NOTE, never failed. A digest proves the bytes did not drift; it does not prove you read
them.

## Retrieval-coverage block (`retrieval_coverage` — emit it whenever the unit's brief carries `claims_owed`/`required_sources`; adoption-closure per I30)

The verifier's RE-DERIVED comparison of debrief evidence AGAINST the brief's obligations —
never copied from executor prose (schema `verify.schema.json` is authoritative; this is a
NON-NORMATIVE mirror): `owed_check[]` `{owed_id, status: covered|covered-downgraded|uncovered,
row_refs (non-empty when counted as coverage), note}` — TOTAL over the brief's owed ids;
`retrieval_probes[]` `{row_ref, claim_echo, kind: reopen|chase, outcome}` (outcome records a
NEW falsifiable coordinate — a located span + where, or the primary reached; ≥1 reopen probe
whenever external-tier rows cover an owed entry) or `retrieval_probes_none_reason`;
`sources_check[]` `{source_id, origin, outcome}` over the brief-cited/owed/coverage-basis
S-ids; `tier_at_verification` whenever the run carries `fsm-state.depth`. PASS with an
uncovered owed id or a not-consulted required source is an I30 contradiction FAIL.

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

## Case-set audit block (`case_set_audit` — the aggregated `verify.json` ONLY; on every verdict-bearing aggregated verify for a `high-stakes` unit)
The mechanical record of the case-set mechanism — **not** a findings channel: anything that should
block a PASS goes to `defects[]` per the block above. Per-member `verify_p<N>.json` files do not
carry it; the lens holder supplies the values, the aggregator writes them. Wire shape only (the rule
is SKILL.md Phase 6's panel step; SPEC `units/U01/SPEC.md` §6.2):
- `case_set_audit` — object, `additionalProperties: false`, all six REQUIRED: `commitment_sha256`
  (string, `^[0-9a-f]{64}$`; the 64-zero string
  `0000000000000000000000000000000000000000000000000000000000000000` records that no derivation
  exists, paired with `commitment_match: false`), `commitment_iteration` (integer ≥1, the iteration
  in which the commitment was FIRST written, cited unchanged thereafter), `commitment_match`
  (boolean), `discharge_check`, `novelty_rate`, `vocabulary_containment`.
- `discharge_check` — object, `additionalProperties: false`, **four** fields, all REQUIRED (`[]`
  when empty): `missing_ids`, `extra_ids`, `duplicate_ids`, `tier_shortfall_ids`. There is no fifth
  field: the brief-side `case_set[].id` uniqueness precondition is evaluated first, with
  `extra_ids`, and is recorded as a defect, not as a field here.
- `novelty_rate` — `{"derived": <int ≥0>, "absent_from_executor_evidence": <int ≥0>}`, both
  REQUIRED. There is no `rate` key.
- `vocabulary_containment` — `{"artifact_only_identifiers": ["<identifier>", …]}`, REQUIRED.
  There is no `note_emitted` key.


## Consequential-verbatim block (`consequential_verbatim_check` — the whole-run verify field, AF-19)
On the **whole-run** `verify.json`, enumerate the consequential prompt-verbatim spot-checks:
one row per consequential ambiguity-register item, recording that item's `register_id` and the
non-blank `outcome` of re-checking that the resolution matched the prompt verbatim. This is the
AF-19-named home for the consequential prompt-verbatim enumeration (a whole-run field, distinct from
the per-unit `retrieval_coverage`/`guardrail_compliance` blocks above).
- `consequential_verbatim_check[]` — items `{register_id (integer `≥1`), outcome (string minLength 1,
  `.strip()`-non-blank)}`, `additionalProperties:false`. OPTIONAL: absent ⇒ the archive stays valid.

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

**Optional keys:** `inputs_reviewed[]` (e.g. `["brief.md","debrief.json","<artifact paths>"]`, or the
digested form `[{"path":"units/U01/debrief.json","sha256":"<64-hex>","bytes":1234}]` — I42),
`panel[].defects[]` + `panel_adjudication` (panel dissent accounting — I41),
`audit_notes` (free-form: the criteria-check / evidence-audit / hallucination-sweep narrative),
`panel[]` (`{lens ∈ correctness|reproduce|guardrail, verdict, verifier_persona?, summary?}` —
**required on `high-stakes` units**, I16), `verify_rounds` (1–3, loop-until-dry), `converged` (bool),
`guardrail_compliance[]` (`{non_goal (verbatim ∈ non_goals), status ∈
respected|violated|not-applicable, note?}` — the scaffolded default above; adoption-closure I22),
`consequential_verbatim_check[]` (`{register_id (int ≥1), outcome (string, non-blank)}` — whole-run
verify only, AF-19; see the block above),
`disagreement{why_unresolvable}` (**iff** `verdict==DISAGREE`).

Conditional (schema-enforced): `PASS ⇒ no blocker/major defect` (minor observations allowed — I6
revised, PR1); `FAIL ⇒ ≥1 defect citing a brief criterion + ≥1 feedback.actionable_change`, else emit
`DISAGREE`. When a `panel[]` is present, `verdict` MUST equal its **discrete majority** (no softmax;
a split ⇒ `DISAGREE`). No `verify.md` is written — `verify.json` is authoritative; adjudication reads
its `verdict`/`feedback`/`defects`.
