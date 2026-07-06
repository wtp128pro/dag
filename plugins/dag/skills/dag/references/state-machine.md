<!-- state-machine.md — the FORMAL model of record for the dag pipeline
     (formal-enforcement layer for reqs 1/4/7/9/12; not req 2 — req 2 is clarification).
     Phase-6 loop substates use the loop's Q vocabulary + 7-row table; the socratic seam is
     the canonical 4-key block; invariants I9-I15 (+ I1b, I-dod) close the missing-verification
     and fail-closed-DAG validator holes, tags/learnings propagation, socratic-counter
     genuineness, the DoD/non-goals gate, and the post-hoc anti-oscillation (AO-2/AO-6) checks.
     TLA+/Alloy models ship under `formal/` (Pipeline.tla/.cfg, WorkGraph.als; see
     formal-models.md) as the machine-checked complement; this transition table + guards +
     invariants is the prose FSM of record they mirror. `scripts/validate_run.py` is the
     runtime checker for the mechanically-checkable subset; the rest are semantic invariants
     a human/verifier must uphold (see Limitations). -->

# Dag Pipeline — Finite-State Machine (formal spec)

## 0. Scope & source of truth

The pipeline is modeled as a finite-state machine whose **states are the 9 phases** (0–8)
plus the **executor↔verifier loop substates** inside Phase 6. `fsm-state.json`
(schema: `schemas/fsm-state.schema.json`) is the durable current-state file; the append-only
`PROGRESS.md` is its event log. The Phase-6 loop is formalized in full — with a termination
proof — in `references/self-learning-loops.md`; this section is the pipeline-level view.

> **Ledger-is-truth invariant:** the FSM state lives on disk (`fsm-state.json` + the
> markdown ledger), never only in the model's context. Any transition first writes disk.

## 1. States

| State id (fsm-state.phase) | Phase | Artifact produced | Kind |
|---|---|---|---|
| `P0_BOOTSTRAP`        | 0 Bootstrap        | INPUT.md            | linear |
| `P1_PERSONAS`         | 1 Personas         | PERSONAS.md         | human gate |
| `P2_CLARIFICATION`    | 2 Clarification    | CLARIFICATIONS.md   | human gate |
| `P3_CARTOGRAPHY`      | 3 Cartography      | CARTOGRAPHY.md      | linear |
| `P4_DECOMPOSITION`    | 4 Decomposition    | GRAPH.md + graph.json | linear (self-critique) |
| `P5_BRIEFING`         | 5 Briefing         | units/*/brief.md    | linear |
| `P6_EXECUTE_VERIFY`   | 6 Execute+Verify   | debrief.json, verify.json | **composite (loop)** |
| `P7_DISAGREEMENT_GATE`| 7 Disagreement     | units/*/disagreement.md | human gate (as-needed) |
| `P8_SYNTHESIS`        | 8 Synthesis        | SYNTHESIS.md        | linear |
| `DONE`                | —                  | —                   | terminal |

### 1a. Phase-6 loop substates (`fsm-state.loop.state`), per unit — the loop's Q vocabulary
| Substate | Meaning |
|---|---|
| `EXECUTE`     | executor subagent producing debrief.json (+ its 4-key `socratic` block + artifacts) |
| `VERIFY`      | independent verifier producing verify.json (verdict + feedback + `premise_check`) |
| `ADJUDICATE`  | branch on the verdict over the partition `{PASS} ∪ {FAIL}×{retries<2, retries==2} ∪ {DISAGREE}` |
| `RETRY`       | executor revising after a FAIL (retries<2), given verifier feedback (an external signal) |
| `ESCALATE`    | terminal within the loop: FAIL with `retries==2` **or** DISAGREE — both hand off to the Phase-7 human gate |
| `DONE`        | verdict=PASS; unit accepted |

> **ESCALATE has two origins, both routed to `P7_DISAGREEMENT_GATE` (top-level T10).** A
> DISAGREE-origin escalation hands off directly. A retries-exhausted FAIL escalation is treated
> as a **material disagreement** (SKILL.md Phase 6 → 7 + self-learning-loops.md §1.1): it writes
> `disagreement.md`, marks the unit `blocked`, and hands to the same Phase-7 human gate — it does
> **not** auto-advance to synthesis (see I10).

## 2. Transition table  (state × event → next state [guard])

| # | From | Event | Guard (must hold) | To |
|---|---|---|---|---|
| T1 | P0_BOOTSTRAP | input_captured | INPUT.md exists | P1_PERSONAS |
| T2 | P1_PERSONAS | user_confirms_roster | `gates.personas_confirmed` | P2_CLARIFICATION |
| T3 | P2_CLARIFICATION | ambiguities_resolved | **no OPEN material ambiguity** (`open_material==0`) | P3_CARTOGRAPHY |
| T4 | P2_CLARIFICATION | material_open | ≥1 material ambiguity unresolved | P2_CLARIFICATION (block; ask user) |
| T5 | P3_CARTOGRAPHY | map_done | CARTOGRAPHY.md valid | P4_DECOMPOSITION |
| T6 | P4_DECOMPOSITION | graph_approved | **authoritative `graph.json` present ∧ DAG acyclic** ∧ every unit `est_footprint_tokens ≤ 32000` ∧ `gates.decomposition_approved` | P5_BRIEFING |
| T7 | P4_DECOMPOSITION | cycle_or_oversize | DAG has a cycle ∨ a unit >32K ∨ no parseable graph.json | P4_DECOMPOSITION (re-split) |
| T8 | P5_BRIEFING | briefs_written | every ready unit has a schema-valid brief.json (incl. `socratic_protocol` ref, `tags`, `learnings_applied`) | P6_EXECUTE_VERIFY |
| T9 | P6_EXECUTE_VERIFY | all_units_passed | every unit loop = `DONE` (**every unit with a debrief has a verify.json verdict=PASS — I9/I10**) | P8_SYNTHESIS |
| T10 | P6_EXECUTE_VERIFY | escalation_raised | a unit loop = `ESCALATE` (via DISAGREE **or** a retries-exhausted FAIL) | P7_DISAGREEMENT_GATE |
| T11 | P7_DISAGREEMENT_GATE | user_decides | user picks an option (DECISIONS.md appended) | P6_EXECUTE_VERIFY (or P2/P3/P4 on rollback) |
| T12 | P8_SYNTHESIS | synthesis_done | SYNTHESIS.md written; all units accounted for | DONE |

### 2a. Phase-6 loop transitions (per unit) — the 7-row table in `references/self-learning-loops.md` §1.3
| # | From (substate) | Event | Guard | To (substate) |
|---|---|---|---|---|
| LT1 | EXECUTE | debrief_written | debrief.json valid (incl. 4-key `socratic`) | VERIFY |
| LT2 | VERIFY | verdict_emitted | verify.json valid ∧ `executor_reasoning_seen==false` | ADJUDICATE |
| LT3 | ADJUDICATE | verdict=PASS | `verdict == PASS` (defect-content-free; a PASS may carry `minor` observations — I6 revised) | DONE |
| LT4 | ADJUDICATE | verdict=FAIL ∧ retries<2 | `retries < 2` (variant `V=2−retries > 0`) ∧ FAIL carries ≥1 defect (each naming a brief criterion) ∧ `feedback.actionable_changes` non-empty | RETRY |
| LT5 | ADJUDICATE | verdict=FAIL ∧ retries≥2 | `retries == 2` | ESCALATE |
| LT6 | ADJUDICATE | verdict=DISAGREE | evidence cannot settle; `disagreement` present | ESCALATE (→P7) |
| LT7 | RETRY | resubmit | `retries := retries+1`; `iteration := iteration+1` | EXECUTE  *(SOLE back-edge)* |

> **Loop-bound invariant:** the only cycle is `EXECUTE→VERIFY→ADJUDICATE→RETRY→EXECUTE`; the
> well-founded variant `V = 2 − retries` strictly decreases on LT7 and is guarded by `V>0`
> (LT4), so the cycle runs ≤2 times ⇒ ≤3 executions per unit (iterations 1,2,3). Termination
> proof (parametric in any finite N): `self-learning-loops.md` §2. Enforced by
> `fsm-state.schema.json` (`loop.retries.maximum=2`) + `validate_run.py` cross-check
> (`verify.iteration ≤ retries+1`, I4).

## 3. Guards (the conditions gating each transition)
- **G-personas** (T2): user confirmed the roster. **Fail-closed & non-skippable:** the
  validator requires `gates.personas_confirmed` from P2 onward (REQUIRED_GATES) and rejects a
  `personas_confirmed:true` flag unbacked by a VALID `personas.json`. The human persona gate
  cannot be skipped — including when "right-sizing" a small task.
- **G-clarify** (T3/T4): `open_material == 0` — no unresolved *material* ambiguity.
- **G-dag** (T6/T7): an **authoritative `graph.json` exists** and its DAG (edges ∪ unit-`deps`)
  is **acyclic**; every unit ≤ 32K est. footprint. Fail-closed: a missing/unparseable graph.json
  past decomposition is a violation, not a skip (I3).
- **G-brief** (T8): each dispatched unit's brief.json is schema-valid AND carries a
  `socratic_protocol` reference, a `tags` set (⊆ V_tag), and `learnings_applied`.
- **G-independent** (LT2): the verify.json attests `executor_reasoning_seen == false`.
- **G-defect** (LT4): a FAIL verdict carries ≥1 concrete defect whose `criterion` is drawn from
  the brief's acceptance criteria, and non-empty `feedback.actionable_changes` (no empty rejections).
- **G-retry** (LT4/LT5): branch on `retries < 2` vs `retries == 2`.
- **G-verified** (T9): every unit with a debrief has a verify.json with verdict=PASS (I9/I10).

## 4. Invariants (must hold in EVERY state)
| Inv | Statement | Enforcement |
|---|---|---|
| **I1 Verifier independence** | Verifier never sees executor reasoning; verify.json `executor_reasoning_seen==false`. | schema `const:false` + validator; **but see Limitation A (self-attestation).** |
| **I1b maker!=checker (persona distinctness)** | Every unit's `executor_persona` must differ from its `verifier_persona` (maker ≠ checker — prime-directive #3 + Alloy `DistinctMakerChecker`). | `validate_run.py` cross-checks `executor_persona != verifier_persona` over `graph.json` units and prints the label `I1b maker!=checker (persona distinctness)` (added in U04). Closes the previously-unenforced graph-level gap. *(Labeled **I1b** as the structural counterpart of **I1 Verifier independence** — both realize prime-directive #3, "decouple the maker from the checker". Genuine model-distinctness behind the persona label stays unenforceable — Limitation D.)* |
| **I2 Ledger-is-truth** | Current state = disk (`fsm-state.json` + markdown), never model memory only. | convention; validator confirms `fsm-state.json` parses & is valid. |
| **I3 DAG acyclic (fail-closed)** | The work graph has no dependency cycle; graph.json is authoritative. | validator: cycle on `edges ∪ unit-deps`; **GRAPH.md-present or post-decomposition ⇒ VALID graph.json REQUIRED** (unparseable/absent ⇒ non-zero exit). Closes E. |
| **I4 Loop bound** | `retries ≤ 2` per unit (≤3 executions); `iteration ≤ retries+1`. | schema `maximum:2` + validator cross-check. |
| **I5 Budget cap** | Every brief/unit ≤ 32K tokens. | schema `maximum:32000` on `budget_tokens`/`est_footprint_tokens`. |
| **I6 Evidence-bound verdicts** | FAIL names ≥1 defect, each citing a brief acceptance criterion; PASS ⇒ **no blocker/major defect** (REVISED for coverage-first, PR1 — was `defects==[]`; a PASS may now carry `minor` observations: "report every finding + severity, filter downstream"). | schema `if/then` (FAIL⇒defects≥1 + actionable_changes; PASS⇒every defect severity==`minor`) + validator criterion-∈-brief cross-check + an I6-PASS defense-in-depth check. Termination-preserving: verdict enum + the §2 partition are unchanged (content-rule revision only). |
| **I7 Single recommended option** | A disagreement dossier marks exactly ONE option recommended. | validator counts `recommended==true`. |
| **I8 No open material ambiguity past P2** | Cannot advance past clarification with an open material item. | validator (clarifications extract). |
| **I9 Every debriefed unit is verified** | A unit dir with a debrief (`.json` or `.md`) MUST have a verify.json with a verdict. | validator presence check. **Closes D.** |
| **I10 Synthesis completeness** | At P8/DONE, every debriefed unit has verdict=PASS (none advances unverified/failed). | validator phase-gated presence+verdict check. **Closes D.** |
| **I11 Tag vocabulary** | Every unit/brief `tag` is a member of `V_tag_eff` (`graph.json.v_tag` ∪ the global registry `~/.claude/dag/tags.json` — 04/G1; absent/invalid ⇒ run-local `V_tag`). | validator membership check over `V_tag_eff`. **Domain widened by 04/G1 — Limitation G.** |
| **I12 Learnings propagation** | Every unit created no earlier than a `tag:T`-scoped learning E, carrying tag T, lists E in `learnings_applied`; a `tag:T` scope is admissible only if ≥2 units carry T. | validator decidable predicate + admission gate (see `self-learning-loops.md` §4.3). Imported entries (`G#`/store-loaded) are EXEMPT from the ≥2-carrier re-proof via the 04/G1 carve-out but still propagation-checked. |
| **I13 Socratic counter records an outcome** | `debrief`/`verify` `socratic.counter` states an outcome, not a blank/"n/a" (mechanical sentinel allowed). | schema (4 keys + `confidence` regex) + validator counter-outcome check. **Shape only; genuineness = the independent COUNTER re-run (Limitation B).** |
| **I14 AO-2 do_not_touch disjointness (post-hoc)** | For a retry (`debrief.iteration>1`), `verify.defects[].criterion` is disjoint from the retry's `debrief.prior_feedback.do_not_touch`; a non-empty intersection ⇒ non-zero exit. | `validate_run.py` offline predicate (label `I14 AO-2 do_not_touch disjointness (units/<uid>)`), added ring-02/P1. Gates no transition. **Presence-gated + self-reported — Limitation F.** |
| **I15 AO-6 responsive change (post-hoc)** | For a retry carrying a `prior_feedback` echo, `debrief.prior_feedback.changes_made` is present and non-empty; else non-zero exit. | `validate_run.py` offline predicate (label `I15 AO-6 responsive change (units/<uid>)`), added ring-02/P2. Gates no transition; `changes_made` executor-self-attested. **Limitation F.** |
| **I16 Panel discipline (post-hoc, PR1)** | A `high-stakes` unit's `verify.json` carries a `panel[]` (≥3 members, distinct correctness/reproduce/guardrail lenses); ANY panel's top-level `verdict` equals the **DISCRETE majority** of the panel verdicts (a no-majority split ⇒ `DISAGREE` — **no softmax**); `verify_rounds` (loop-until-dry) ∈ [1,3]. | `validate_run.py` offline predicate (label `I16 panel discipline (units/<uid>)`), added PR1. Gates **no** transition (never a live LT7 guard). Node-internal ⇒ **PRESERVES** termination. **Presence/shape-checked — genuine lens-diversity + real recall stay verifier judgment (Limitation H).** |
| **I-dod DoD/non-goals present** | Any post-clarification structural artifact (cartography, graph, units, or synthesis — `learnings.json` is deliberately excluded) requires a schema-valid `clarifications.json` with non-empty `definition_of_done` AND `non_goals`, even if the file is absent (methodology.md §Clarification). | validator artifact-driven presence check, fail-closed on absence — confirmed via the `missing_dod`/`postdecomp_no_dod`/`synthesis_no_dod`/`unfenced_cycle` fixtures. |

**Socratic seam (canonical 4-key).** The `brief` carries only a **reference** to
`references/socratic-protocol.md`; the answered block `socratic = {premise, counter, pivot,
confidence}` is required in **debrief + verify**. `confidence` starts `high|medium|low`. The
**verifier additionally emits `premise_check`** attesting it confirmed the executor's `premise`
is the deliverable's load-bearing claim and re-ran COUNTER independently — the
validator requires `counter_reran_independently==true` and rejects a PASS whose
`premise_check.is_load_bearing==false` (premise-deflection guard).

## 5. Mechanically-checked vs. semantic (honest boundary — validity ≠ correctness)
`validate_run.py` mechanically enforces: schema-validity of every artifact; **I3 fail-closed
DAG** (authoritative graph.json required past decomposition); **I1b maker!=checker**
(persona-distinctness: `executor_persona != verifier_persona` per graph.json unit);
**I9/I10 missing-verification rejection**; I4 (loop bound + cross-check); I5 (budget); I6 (FAIL⇒defect∈brief-criteria,
PASS⇒no blocker/major defect — the coverage-first REVISION, PR1); I7 (single recommended); I8 (open-material); **I-dod** (DoD/non-goals
presence, artifact-triggered — fail-closed even when `clarifications.json` is absent);
**I11 tag-vocabulary
membership** (over `V_tag_eff` = run-local ∪ global registry — 04/G1); **I12 learnings-propagation
predicate + admission gate** (with the 04/G1 authored-vs-imported carve-out); **I13 socratic-counter
outcome shape**; **I14/I15 post-hoc anti-oscillation** (AO-2 `do_not_touch` disjointness / AO-6
responsive-change, offline over the retry `debrief` echo — 02/P1, 02/P2); **I16 panel discipline**
(high-stakes⇒panel present with the distinct correctness/reproduce/guardrail lenses; discrete-majority
aggregation — a split⇒DISAGREE, no softmax; `verify_rounds`∈[1,3] — post-hoc/offline, PR1); the `premise_check`
attestation; gate-ordering of `fsm-state.phase` vs `gates`; and the `const:false` shape of I1.

**It CANNOT enforce** (these remain human/verifier judgment):
- **A.** Whether the verifier *truly* was blind to executor reasoning — `const:false` /
  `premise_check` are self-attestations, not platform guarantees (no passive hook intercepts
  subagent I/O).
- **B.** Whether a PASS is *correct*, whether evidence locators actually resolve/reproduce, or
  whether the `socratic`/`defects`/`premise_check` text is *genuine* rather than theater. I13
  checks the counter's *shape*; the independent COUNTER re-run is the real backstop.
- **C.** Whether the reported `budget_tokens`/`tokens_consumed` are truthful.
- **D.** Whether executor and verifier are genuinely a *different model/agent* at runtime. The
  **persona-label** distinctness (`executor_persona != verifier_persona` per unit) IS now
  graph-checked — **I1b maker!=checker** — but a genuinely distinct *model* behind the label
  stays unobservable to the validator.
- **E.** Whether a `tag` genuinely denotes a reusable pattern (I12 enforces ≥2 carriers +
  presence; whether the lesson is *truly* generalizable stays a verifier/human judgment).
- **F.** Whether I14/I15 **authoritatively** enforce AO-2/AO-6. They are **post-hoc + presence-gated
  + self-reported**: both fire only when the retry's `debrief.prior_feedback` echo is present (a retry
  omitting it is skipped, not failed); I14 compares the executor's **self-reported** `do_not_touch`
  echo — NOT the authoritative prior verify, since the validator retains only the *latest*
  `verify.json` per unit (no per-iteration verify history to reconstruct); and I15's `changes_made` is
  executor-self-attested. So they check *presence/plumbing*, not genuineness (validity ≠ correctness);
  the independent verifier stays the semantic backstop. (Learning L1.)
- **G.** The I11/I12 tag domain is **widened** by 04/G1 to `V_tag_eff = global ∪ project ∪ run_local`
  (global tier `~/.claude/dag/tags.json`, schema-validated) — a **domain revision** of I11/I12, not a
  pure additive check; an absent/invalid registry falls back to run-local `V_tag`, so the domain is
  never widened silently or on bad data. Its **authored-vs-imported admission carve-out** EXEMPTS
  imported/already-generalized entries (`G#` id or store-loaded) from the ≥2-carrier admission re-proof
  while STILL enforcing I12 propagation; the carve-out **trusts** the `G#`-id / store provenance as the
  "already-generalized" signal (a hand-authored `G#` id in a run-local file would receive the
  exemption) — a deliberate provenance-trust boundary, not a cryptographic proof. It never weakens I12
  propagation.
- **H.** **I16 panel discipline** checks *presence + shape*, not *substance*. It enforces that a
  high-stakes unit carries a ≥3-member `panel[]` whose lenses cover the canonical trio and whose
  DISCRETE majority equals the top-level verdict (no softmax), and that `verify_rounds` is bounded —
  all mechanically decidable. It **cannot** enforce that the three lenses were *genuinely* applied by
  *genuinely* independent verifiers, that a `converged` (dry) sweep truly exhausted the defects, or
  that a panelist's verdict is *correct* — those stay verifier/human judgment (validity ≠ correctness,
  the same boundary as I13/I14/I15). It is POST-HOC and gates no transition, so it can never deadlock
  the loop (the 02/P1 live-LT7-guard lesson); the independent panel itself is the semantic backstop.
  Note too that `verify_rounds` is OPTIONAL: I16 bounds it to [1,3] only when present, so an *omitted*
  `verify_rounds` leaves the internal loop-until-dry round count unaudited (that node's finiteness then
  rests on model discipline, as it did before the field existed — VERIFY is a single LT2 transition
  regardless, so termination is unaffected).

## 6. Phase→state coverage (no orphan phases)
Every SKILL.md phase 0–8 maps to exactly one state (§1); every gate maps to a guard (§3);
the Phase-6 executor↔verifier loop maps to the loop substate machine (§1a/§2a, `EXECUTE·VERIFY·
ADJUDICATE·RETRY·ESCALATE·DONE`). The as-needed Phase 7 maps to `P7_DISAGREEMENT_GATE` (entered
via T10 from an ESCALATE — a DISAGREE-origin escalation or a retries-exhausted FAIL — exited via
T11). No phase, gate, or loop is unmodeled.
