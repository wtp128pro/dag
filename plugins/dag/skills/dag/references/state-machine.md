<!-- state-machine.md — the FORMAL model of record for the dag pipeline
     (formal-enforcement layer for reqs 1/4/7/9/12; not req 2 — req 2 is clarification).
     Phase-6 loop substates use the loop's Q vocabulary + 7-row table; the socratic seam is
     the canonical 4-key block; invariants I9-I16 (+ I1b, I-dod) close the missing-verification
     and fail-closed-DAG validator holes, tags/learnings propagation, socratic-counter
     genuineness, the DoD/non-goals gate, and the post-hoc anti-oscillation (AO-2/AO-6) checks.
     Bounded Graph Amendments add five more post-hoc/offline checks (I3b/I3c wave-layering +
     dependency-closure; I17/I18/I19 frozen-prefix + fuel-bound + amendment-scope) — none a live guard.
     Guardrail enforcement (1.8.0) adds six more (I20/I21 per-unit DoD/non-goal binding, I22
     guardrail-compliance blocks, I23 P8 closure, I24 register floor, I25 resolution-required) —
     likewise all post-hoc/offline, none a live guard.
     TLA+/Alloy models ship under `formal/` (Pipeline.tla/.cfg, WorkGraph.als; see
     formal-models.md) as the machine-checked complement; this transition table + guards +
     invariants is the prose FSM of record they mirror. `scripts/validate_run.py` is the
     runtime checker for the mechanically-checkable subset; the rest are semantic invariants
     a human/verifier must uphold (see Limitations).
     SSR (dev-time drift checks): the normative facts in this file — the §2/§2a transition rows and
     the §4 invariants — are ALSO recorded descriptively in `spec/fsm.json` + `spec/invariants.json`
     and diffed against these tables by `scripts/spec_check.py` (SC1 label↔registry, SC2 table
     row-diff), a DEV-TIME drift check run under `run_tests.sh` — NOT part of run validation and NOT a
     runtime read (`spec/` stays off SKILL.md's lazy-load path). -->

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
| `P0_BOOTSTRAP`        | 0 Bootstrap (incl. Phase 0.5 learnings intake — a prose sub-step, no own state) | INPUT.md | linear |
| `P1_PERSONAS`         | 1 Personas         | PERSONAS.md         | human gate |
| `P2_CLARIFICATION`    | 2 Clarification    | CLARIFICATIONS.md   | human gate |
| `P3_CARTOGRAPHY`      | 3 Cartography      | CARTOGRAPHY.md      | linear |
| `P4_DECOMPOSITION`    | 4 Decomposition    | GRAPH.md + graph.json | linear (self-critique) |
| `P5_BRIEFING`         | 5 Briefing         | units/*/brief.md    | linear |
| `P6_EXECUTE_VERIFY`   | 6 Execute+Verify   | debrief.json, verify.json | **composite (loop)** |
| `P7_DISAGREEMENT_GATE`| 7 Disagreement     | units/*/disagreement.md | human gate (as-needed) |
| `P8_SYNTHESIS`        | 8 Synthesis        | SYNTHESIS.md        | human gate (sign-off) |
| `DONE`                | —                  | —                   | terminal |

### 1a. Phase-6 loop substates (`fsm-state.loop.state`), per unit — the loop's Q vocabulary
| Substate | Meaning |
|---|---|
| `EXECUTE`     | executor subagent producing debrief.json (+ its 4-key `socratic` block + artifacts) |
| `VERIFY`      | independent verifier producing verify.json (verdict + feedback + `premise_check`) |
| `ADJUDICATE`  | branch on the verdict over the partition `{PASS} ∪ {FAIL}×{retries<2, retries==2} ∪ {DISAGREE}` |
| `RETRY`       | executor revising after a FAIL (retries<2), given verifier feedback (an external signal) |
| `ESCALATE`    | terminal within the loop: FAIL with `retries==2`, DISAGREE, or (BGA) amendment-fuel exhaustion — all hand off to the Phase-7 human gate |
| `DONE`        | verdict=PASS; unit accepted |

> **ESCALATE has THREE origins, all routed to `P7_DISAGREEMENT_GATE` (top-level T10).** (1) A
> DISAGREE-origin escalation (LT6) hands off directly. (2) A retries-exhausted FAIL escalation (LT5)
> is treated as a **material disagreement** (SKILL.md Phase 6 → 7 + self-learning-loops.md §1.1): it
> writes `disagreement.md`, marks the unit `blocked`, and hands to the same Phase-7 human gate — it
> does **not** auto-advance to synthesis (see I10). (3) **Amendment-fuel exhaustion** (BGA, WP6/B9):
> *fuel exhausted + an amendment still needed* routes to ESCALATE via the same Phase-7 gate (SKILL.md
> Phase 6 "Fuel (I18)"). This third origin is a **documentation/enumeration** addition — it is NOT a
> new modeled transition (`spec/fsm.json` T10 keeps its two spec in-edges LT5/LT6; `Pipeline.tla`
> disables `Amend` at `fuel==0`, and `Quiesce` covers the halt), which is why it is flagged here and
> in `formal/` as a **model simplification**. **Classification: REVISES** the ESCALATE-origin
> enumeration (documentation-level); **PRESERVES** termination (fuel exhaustion halts either way). A
> post-hoc validator predicate (`ESCALATE origin provenance`) checks that any unit recorded in
> loop-state `ESCALATE` carries one of the three justifications.

> **Per-unit loop state under parallel waves (`fsm-state.units[]`, D-02/IMP-11).** The single
> top-level `fsm-state.loop` object holds the substate of the **most recently transitioned** unit
> only — with parallel waves >1 unit is in flight, so that one slot cannot durably represent every
> unit's retry count (I2 ledger-is-truth). Each `units[]` item therefore MAY carry its own optional
> **`retries`** (0..2; authoritative: `fsm-state.schema.json` `units.items.properties.retries.maximum` —
> the per-unit cap, NOT the loop slot's `loop.retries.maximum`) and
> **`loop_state`** (the same `Q` vocabulary above). Both are additive and
> optional: an item that omits them is unchanged, and the top-level `loop` slot stays as the
> back-compat "current unit" snapshot. When a `units[]` item records `retries`, `validate_run.py`
> applies the **same I4 bound** to it — `verify.iteration ≤ retries+1` — extended from the single
> `loop.unit_id` unit to every unit that records its own count (label `I4 units[] cross-check`).
> This is a **post-hoc / offline** predicate over emitted artifacts — it gates no transition and
> adds no guard to the sole back-edge LT7, so it **PRESERVES** the termination proof and **REVISES**
> only I4's cross-check surface (the durable-state shape, not the loop's dynamics).

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
| T12 | P8_SYNTHESIS | synthesis_done | SYNTHESIS.md written; all units accounted for; **human accepted at the sign-off gate — recorded as `gates.signoff_confirmed` (G-signoff), now REQUIRED at DONE (D-06)** | DONE |

### 2a. Phase-6 loop transitions (per unit) — the 7-row table in `references/self-learning-loops.md` §1.3
| # | From (substate) | Event | Guard | To (substate) |
|---|---|---|---|---|
| LT1 | EXECUTE | debrief_written | debrief.json valid (incl. 4-key `socratic`) | VERIFY |
| LT2 | VERIFY | verdict_emitted | verify.json valid ∧ `executor_reasoning_seen==false` | ADJUDICATE |
| LT3 | ADJUDICATE | verdict=PASS | `verdict == PASS` (defect-content-free; a PASS may carry `minor` observations — I6 revised) | DONE |
| LT4 | ADJUDICATE | verdict=FAIL ∧ retries<2 | `retries < 2` (variant `V=2−retries > 0`) — the §1.3 branch condition | RETRY |
| LT5 | ADJUDICATE | verdict=FAIL ∧ retries==2 | `retries == 2` | ESCALATE |
| LT6 | ADJUDICATE | verdict=DISAGREE | evidence cannot settle; `disagreement` present | ESCALATE (→P7) |
| LT7 | RETRY | resubmit | `retries := retries+1`; `iteration := iteration+1` | EXECUTE  *(SOLE back-edge)* |

> **Loop-bound invariant:** the only cycle is `EXECUTE→VERIFY→ADJUDICATE→RETRY→EXECUTE`; the
> well-founded variant `V = 2 − retries` strictly decreases on LT7 and is guarded by `V>0`
> (LT4), so the cycle runs ≤2 times ⇒ ≤3 executions per unit (iterations 1,2,3). Termination
> proof (parametric in any finite N): `self-learning-loops.md` §2. Enforced by
> `fsm-state.schema.json` (`loop.retries.maximum=2`) + `validate_run.py` cross-check
> (`verify.iteration ≤ retries+1`, I4).
>
> **Row-for-row equality with `self-learning-loops.md` §1.3 (IMP-13).** These seven rows are exactly
> the §1.3 table. Two seams to note so the tables read identically: (1) **LT4's branch condition is
> just `verdict==FAIL ∧ retries<2`** — the `{FAIL}×{retries<2}` cell of the exhaustive ADJUDICATE
> partition. The I6/G-defect *content* requirements (a FAIL carries ≥1 defect each naming a brief
> criterion; `feedback.actionable_changes` non-empty) are **artifact-content rules the validator
> enforces post-hoc**, NOT part of the transition guard — a content-violating FAIL is a validator
> FAIL, not a stuck ADJUDICATE. Holding them out of the guard is what keeps the partition
> `{PASS} ∪ {FAIL}×{retries<2, retries==2} ∪ {DISAGREE}` exhaustive and mutually exclusive.
> (2) **LT7 carries `iteration := iteration+1`** alongside `retries := retries+1` — mirrored in the
> §1.3 row — because the validator cross-checks `verify.iteration ≤ retries+1` (I4), so the
> iteration counter is part of the contract, not cosmetic.

> **Graph amendments add NO transition (Bounded Graph Amendments).** The Phase-6 work graph may grow
> mid-run (`add_units`/`split_unit`/`add_edges`; `cancel_unit` human-gated) via append-only
> `amendments/A<NN>.json` records, but this adds **no row** to either transition table: T9's "every
> unit" quantifies over the **current `graph.json` revision**, and amending is **node-internal to P6
> orchestration** — the same category as the I16 panel (finite work inside a node, no FSM edge). New
> units simply enter the existing P5→P6 machinery. Termination is preserved by a monotone-decreasing
> **fuel** budget (I18, mirroring `retries ≤ 2`): total units ≤ N0 + fuel₀, and fuel exhaustion routes
> to ESCALATE (never a stuck state). Every amendment invariant (I3b/I3c/I17/I18/I19, §4) is an
> **offline validator predicate**, never a live guard on any transition (the 02/P1 deadlock lesson) —
> so the correction-loop proof holds **verbatim**. Full spec: SKILL.md Phase 6 "Graph amendments
> (bounded)"; classification: self-learning-loops.md §2.

## 3. Guards (the conditions gating each transition)
- **G-personas** (T2): user confirmed the roster. **Fail-closed & non-skippable:** the
  validator requires `gates.personas_confirmed` from P2 onward (REQUIRED_GATES) and rejects a
  `personas_confirmed:true` flag unbacked by a VALID `personas.json`. The human persona gate
  cannot be skipped — including when "right-sizing" a small task.
- **G-clarify** (T3/T4): `open_material == 0` — no unresolved *material* ambiguity.
- **G-cartography** (T5): the cartography phase is complete — a flag-bearing mechanical gate,
  `gates.cartography_done` in REQUIRED_GATES (D2: previously omitted from this list). (G-input (T1)
  and G-escalate (T10) are also transition guards but flagless — G-input keys off INPUT.md's
  existence, G-escalate off a raised escalation — so they need no gate flag.)
- **G-dag** (T6/T7): an **authoritative `graph.json` exists** and its DAG (edges ∪ unit-`deps`)
  is **acyclic**; every unit ≤ 32K est. footprint. Fail-closed: a missing/unparseable graph.json
  past decomposition is a violation, not a skip (I3).
- **G-brief** (T8): each dispatched unit's brief.json is schema-valid AND carries a
  `socratic_protocol` reference, a `tags` set (⊆ V_tag), and `learnings_applied`.
- **G-independent** (LT2): the verify.json attests `executor_reasoning_seen == false`.
- **I6/AO-3 defect-content rule** (D1: NOT a transition guard): a FAIL verdict carries ≥1 concrete
  defect whose `criterion` is drawn from the brief's acceptance criteria, and a non-empty (non-blank —
  WP5/G11) `feedback.actionable_changes`. This is a **post-hoc artifact-content check** (`validate_run.py`
  I6 + the schema `if/then`), not the LT4 guard — `spec/fsm.json` gives LT4 the guard `G-retry`, and
  content-gating LT4 would break the exhaustive ADJUDICATE partition (see the §2a deadlock note). It is
  listed here for completeness, not as a mechanical gate that maps to a T*/LT* guard.
- **G-retry** (LT4/LT5): branch on `retries < 2` vs `retries == 2` — the actual LT4 guard.
- **G-verified** (T9): every unit with a debrief has a verify.json with verdict=PASS (I9/I10).
- **G-resolve** (T11): the human picks an option at the disagreement gate (DECISIONS.md appended).
  **Human gate — NOT validator-checkable** (the validator cannot verify a human decided; mirrors the
  §5 Limitations pattern).
- **G-signoff** (T12): the human accepts the deliverable at the Phase-8 sign-off gate, recorded as
  **`gates.signoff_confirmed`**. **Fail-closed & non-skippable (D-06):** the validator's REQUIRED_GATES
  lists `signoff_confirmed` for `DONE`, so a run at phase `DONE` without the flag is INVALID (non-zero
  exit) — closing the former skip-the-human hole (the validator previously could not tell sign-off
  happened). Like `personas_confirmed`, this is a POST-HOC gate-ordering predicate over the emitted
  `fsm-state.json` (it gates no live transition, never guards LT7); the flag is a **human attestation
  whose PRESENCE — not genuineness — is checked** (validity ≠ correctness; §5 Limitation pattern).

## 4. Invariants (must hold in EVERY state)
| Inv | Statement | Enforcement |
|---|---|---|
| **I1 Verifier independence** | Verifier never sees executor reasoning; verify.json `executor_reasoning_seen==false`. | schema `const:false` + validator; **but see Limitation A (self-attestation).** |
| **I1b maker!=checker (persona distinctness)** | Every unit's `executor_persona` must differ from its `verifier_persona` (maker ≠ checker — prime-directive #3 + Alloy `DistinctMakerChecker`). | `validate_run.py` cross-checks `executor_persona != verifier_persona` over `graph.json` units and prints the label `I1b maker!=checker (persona distinctness)` (added in U04). Closes the previously-unenforced graph-level gap. *(Labeled **I1b** as the structural counterpart of **I1 Verifier independence** — both realize prime-directive #3, "decouple the maker from the checker". Genuine model-distinctness behind the persona label stays unenforceable — Limitation D.)* |
| **I1c artifact/declaration persona reconciliation** (WP-B/C1) | For a unit with BOTH a `debrief.json` and a `verify.json`: `debrief.persona == graph.executor_persona`, `verify.verifier_persona == graph.verifier_persona`, AND `debrief.persona != verify.verifier_persona`. I1b compared only the DECLARED graph personas; nothing tied the ACTUAL artifact personas to them, so one persona could execute a unit AND verify it while I1b still printed PASS. | `validate_run.py` post-hoc/offline (label `I1c artifact/declaration persona reconciliation (units/<uid>)`); gates no transition ⇒ **PRESERVES** termination. Mechanizes prime-directive #3 / I1 at the artifact layer, the same class as the round-1 I1b graph-layer check. A genuinely distinct *model* behind a distinct persona label stays unobservable (Limitation D). Fixtures `maker_eq_checker_artifacts`/`persona_identity_ok`. |
| **I1d roster membership** (WP-B/C2) | Every WORKING persona — graph `executor_persona`/`verifier_persona`, `brief`/`debrief.persona`, `verify.verifier_persona`, and every panel member's `verifier_persona` — must be a member of the confirmed `personas.json` roster. Realizes `personas.schema.json`'s stated purpose (previously any working persona could be a fabricated string absent from the roster). | `validate_run.py` post-hoc/offline (label `I1d roster membership`); runs only when a `personas.json` roster is present (its absence is G-personas' job); gates no transition ⇒ **PRESERVES** termination. Membership is a confirmed-roster check, NOT proof the named model staffed the unit (Limitation D). Fixtures `persona_roster_forgery`/`persona_identity_ok`. |
| **I2 Ledger-is-truth** | Current state = disk (`fsm-state.json` + markdown), never model memory only. The ledger may not LIE about the artifacts (WP5): a `units[]` status of `passed`/`failed` matches the unit's verify verdict `PASS`/`FAIL` and `loop.last_verdict` matches its unit's verdict (G4); every `fsm-state.units[]` id is a graph unit or a retired id (G10); and artifacts imply a phase floor — an executed unit ⇒ `decomposition_approved` ∧ phase ≥ P5, `SYNTHESIS.md` ⇒ phase ∈ {P8, DONE} (G5). | validator confirms `fsm-state.json` parses & is valid, plus the post-hoc ledger↔verify / units-subset / phase-floor cross-checks. Fixtures `no_fsm_state`/`ledger_status_mismatch`/`ledger_verdict_mismatch`/`fsm_phantom_unit`/`phase_underreport`. |
| **I3 DAG acyclic (fail-closed)** | The work graph has no dependency cycle; graph.json is authoritative. Unit ids are UNIQUE (WP5/B8 — a duplicate makes last-wins enforcement order-dependent). | validator: cycle on `edges ∪ unit-deps` + a `len(units) == len(set(ids))` uniqueness check; **GRAPH.md-present or post-decomposition ⇒ VALID graph.json REQUIRED** (unparseable/absent ⇒ non-zero exit). Closes E. Fixtures `unfenced_cycle`/`amend_cycle`/`dup_unit_id`. |
| **I4 Loop bound** | `retries ≤ 2` per unit (≤3 executions); `iteration ≤ retries+1`. | schema `maximum:2` + validator cross-check — applied to the top-level `loop` slot **and** (D-02/IMP-11) to every `fsm-state.units[]` item that records its own optional per-unit `retries` (label `I4 units[] cross-check`), so parallel-wave units are each bounded, not just the most-recently-transitioned one. Both are post-hoc/offline (no LT7 guard). |
| **I5 Budget cap** | Every brief/unit ≤ 32K tokens (PLAN-side). Report-side honesty is tied to the unit's OWN budget (WP5/G9): `debrief.footprint.tokens_consumed > brief.budget_tokens ∧ within_budget==true` ⇒ FAIL. | schema `maximum:32000` on `budget_tokens`/`est_footprint_tokens` (the plan-side ceiling — briefs/graph units still cannot *plan* >32K). **Report-side (PR-6/IMP-04):** `debrief.footprint.tokens_consumed` has NO maximum, so a real overrun is *reported* truthfully; a schema `if/then` forces `tokens_consumed>32000 ⇒ within_budget:false`, and a validator check (WP5) ties the honest-overrun signal to each unit's own `brief.budget_tokens` (not just the global 32K). Fixture `within_budget_dishonest`. |
| **I6 Evidence-bound verdicts** | FAIL names ≥1 defect, each citing a brief acceptance criterion, AND ≥1 NON-BLANK `feedback.actionable_changes` (WP5/G11 — `[" "]` is not actionable); PASS ⇒ **no blocker/major defect** (REVISED for coverage-first, PR1 — was `defects==[]`; a PASS may now carry `minor` observations: "report every finding + severity, filter downstream"). | schema `if/then` (FAIL⇒defects≥1 + actionable_changes items `pattern:"\\S"`; PASS⇒every defect severity==`minor`) + validator criterion-∈-brief cross-check + a `.strip()` non-blank actionable-change check + an I6-PASS defense-in-depth check. Termination-preserving: verdict enum + the §2 partition are unchanged (content-rule revision only). Fixture `fail_blank_actionable`. |
| **I7 Single recommended option** | A disagreement dossier marks exactly ONE option recommended. | validator counts `recommended==true`. |
| **I8 No open material ambiguity past P2** | Cannot advance past clarification with an open material item. | validator (clarifications extract). |
| **I9 Every debriefed unit is verified** | A unit dir with a debrief (`.json` or `.md`) MUST have a verify.json with a verdict. | validator presence check. **Closes D.** |
| **I10 Synthesis completeness** | At P8/DONE, every **graph** unit has verdict=PASS (none advances unverified/failed). The enforced predicate iterates the `graph.json` units (BRK-02, §5; `spec/invariants.json`), NOT just the dirs that happen to carry a debrief — so a unit cannot be hidden by deleting its `debrief.json`. | validator phase-gated presence+verdict check over graph.json units (scoped to runs that materialized the `units/` tree). **Closes D.** |
| **I11 Tag vocabulary** | Every unit/brief `tag` is a member of `V_tag_eff` (`graph.json.v_tag` ∪ the global registry `~/.claude/dag/tags.json` — 04/G1; absent/invalid ⇒ run-local `V_tag`). | validator membership check over `V_tag_eff`. **Domain widened by 04/G1 — Limitation G.** |
| **I12 Learnings propagation** | Every unit created no earlier than a learning E and matched by E's scope selector — `all`, a unit-id (`U0X`), or `tag:T` — lists E in `learnings_applied`. Admission is selector-kind ASYMMETRIC: `all` admissible iff ≥2 graph units, `tag:T` iff ≥2 units carry T, a `U0X` selector always (single-target). An unrecognized selector kind is a hard `I12 selector` FAIL (BRK-08); `phaseN` was removed as unevaluable (BRK-09). | validator decidable predicate + admission gate (see `self-learning-loops.md` §4.3). Imported entries are EXEMPT from the ≥2-carrier re-proof via the 04/G1 carve-out but still propagation-checked. The import carve-out (WP5/G8) requires GENUINE provenance — actual store membership OR an `origin.store` stamp — not the `G#` id spelling; a bare `G#`-id with neither FAILs `I12 import provenance` (fixture `learnings_forged_import`), so a run-local `L1` renamed `G7` can no longer dodge propagation. |
| **I13 Socratic counter records an outcome** | `debrief`/`verify` `socratic.counter` states an outcome, not a blank/"n/a" (mechanical sentinel allowed). | schema (4 keys + `confidence` regex) + validator counter-outcome check. **Shape only; genuineness = the independent COUNTER re-run (Limitation B).** |
| **I14 AO-2 do_not_touch disjointness (post-hoc; A2 severity-scoped)** | For a retry (`debrief.iteration>1`), the retry's **blocker/major** `verify.defects[].criterion` is disjoint from the retry's `debrief.prior_feedback.do_not_touch`; a non-empty intersection ⇒ non-zero exit. A **minor** coverage-first observation on a sealed criterion is REPORTABLE (advisory NOTE), not a FAIL. | `validate_run.py` offline predicate (label `I14 AO-2 do_not_touch disjointness (units/<uid>)`), added ring-02/P1; **A2 (WP-D) REVISES** it to scope the intersection to `blocker\|major` (coverage-first satisfiability — see self-learning-loops.md AO-2). Gates no transition. **Presence now schema-required on retries (PR-6); content self-reported — Limitation F (narrowed).** Fixtures `ao2_do_not_touch` (major→FAIL) / `i14_minor_on_sealed` (minor→PASS+NOTE). |
| **I15 AO-6 responsive change (post-hoc)** | For a retry carrying a `prior_feedback` echo, `debrief.prior_feedback.changes_made` is present and non-empty; else non-zero exit. | `validate_run.py` offline predicate (label `I15 AO-6 responsive change (units/<uid>)`), added ring-02/P2. Gates no transition. **Presence + non-emptiness of `changes_made` now schema-required on retries (PR-6)**, so this offline check is SUBSUMED for schema-valid retries and remains a degraded-mode (no-schema) backstop; `changes_made` *content* executor-self-attested. **Limitation F (narrowed).** |
| **I16 Panel discipline (post-hoc, PR1; independence WP-B/C4)** | A `high-stakes` unit's `verify.json` carries a `panel[]` (≥3 members, distinct correctness/reproduce/guardrail lenses); ANY panel's top-level `verdict` equals the **DISCRETE majority** of the panel verdicts (a no-majority split ⇒ `DISAGREE` — **no softmax**); `verify_rounds` (loop-until-dry) ∈ [1,3]. **Panel INDEPENDENCE (WP-B):** the members' declared `verifier_persona`s must be pairwise DISTINCT (no clones behind distinct lenses) and none may equal the unit's executor persona (a panelist may not be the maker). | `validate_run.py` offline predicate (label `I16 panel discipline (units/<uid>)`), added PR1 (independence WP-B). Gates **no** transition (never a live LT7 guard). Node-internal ⇒ **PRESERVES** termination. **Presence/shape-checked — genuine lens-diversity + real recall stay verifier judgment (Limitation H).** |
| **I-dod DoD/non-goals present** | Any post-clarification structural artifact (cartography, graph, units, or synthesis — `learnings.json` is deliberately excluded) requires a schema-valid `clarifications.json` with non-empty `definition_of_done` AND `non_goals`, even if the file is absent (methodology.md §Clarification). | validator artifact-driven presence check, fail-closed on absence — confirmed via the `missing_dod`/`postdecomp_no_dod`/`synthesis_no_dod`/`unfenced_cycle` fixtures. |
| **I3b wave layering** (BGA) | When `graph.json.waves` is present: every unit appears in exactly one wave group (and no group names a non-unit), and every edge in `edges ∪ deps` rises strictly in wave (`wave(from) < wave(to)`). When amendments exist `waves` is REQUIRED (absent ⇒ FAIL); without amendments an absent `waves` ⇒ SKIP. Closes a pre-existing gap: `waves` was never cross-checked, so a layering-violating-yet-acyclic graph passed silently. | `validate_run.py` post-hoc/offline; runs whenever a graph is present; gates no transition ⇒ **PRESERVES** termination (+STRENGTHENS I3). Fixtures `amend_ok`/`amend_layering`. |
| **I3c dependency closure** (BGA) | Every `deps` element and every `edges[].from/to` names a CURRENT `units[].id`; a dangling reference (incl. a retired id still referenced) ⇒ FAIL. Closes a pre-existing gap: a phantom endpoint became an invisible node in cycle detection. | `validate_run.py` post-hoc/offline; runs whenever a graph is present; gates no transition ⇒ **PRESERVES** termination (+STRENGTHENS I3). Fixtures `amend_ok`/`amend_dangling_dep`. |
| **I17 frozen executed prefix + reconciliation** (BGA) | *Frozen prefix:* no amendment touches a unit with a `debrief.json`/`verify.json` (retired dirs hold at most `brief.*`); no debriefed unit id is orphaned out of the amended `graph.json`; a retired id never reappears in a later `units_added`; a retired id in `fsm-state.units[]` has status `retired`. Mirrors the load-bearing 02/P4 has-no-debrief guard. *Reconciliation (WP1, B2/B3):* against the immutable `graph.json.baseline_units` (the revision-1 unit set, schema-required once `revision > 1`), `set(units[]) ∪ retired == set(baseline_units) ∪ ⋃ units_added` (kills smuggled/phantom units); every `units_retired` id existed (baseline or an earlier add); `retired ∩ units[] == ∅`; `graph.retired_units` ids == ⋃ records' `units_retired`. *Content anchor (WP4, B5):* every EXECUTED unit's current `graph.json` entry matches its immutable `brief.json` on `title`/`wave`/`depends_on`/executor `persona`/`tags`/`acceptance_criteria` (a post-execution edit/re-wave/rewire is caught); `goal`/`est_footprint_tokens` are not brief-carried and stay attested (Limitation J). | `validate_run.py` post-hoc/offline; gates no transition ⇒ **PRESERVES** AO-1/forward-only/I10/termination, **REVISES** I17 upward (reconciliation + content anchor give the frozen prefix a mechanical floor). Fixtures `amend_frozen`/`amend_orphan`/`amend_smuggled_unit`/`amend_phantom_add`/`amend_added_unreconciled`/`amend_fake_retire`/`amend_phantom_retire_undercharge`/`amend_missing_baseline`/`amend_edit_executed`/`amend_rewave_executed`/`amend_rewire_executed`. |
| **I18 fuel bound + records-required** (BGA) | `expansion.fuel_remaining == fuel_initial − Σ fuel_cost ≥ 0`; each record's `fuel_cost == max(1, \|units_added\| − \|units_retired\|)`; `graph.json.revision == 1 + \|records\|` with `amendments_applied` listing the record ids in order; amendments present with no `expansion` ⇒ FAIL. *Records-required trigger (WP1, B1):* if `graph.json`/`fsm-state.json` bear amendment EVIDENCE (`revision > 1`, non-empty `amendments_applied`/`retired_units`, or fuel spent) the matching `amendments/A<NN>.json` records MUST be present and in sync (`\|records\| == \|amendments_applied\| == revision − 1`, ids matching) — deleting `amendments/` no longer launders the append-only provenance. *Fuel tamper-evidence (WP2, B4):* the seed is anchored to the immutable `graph.json.fuel_initial` (`expansion.fuel_initial == graph.fuel_initial`), and each record's `fuel_before`/`fuel_after` form an unbroken chain (`A01.fuel_before == fuel_initial`, `fuel_after == fuel_before − fuel_cost`, `A(k+1).fuel_before == A(k).fuel_after`, last `fuel_after == fuel_remaining`) — widening fuel mid-run is caught. *Bookkeeping (WP3, G1/G2/G3/G12):* amendment ids unique and `id == filename` stem; `graph_revision_after == 2 + record_index`; `fsm-state.expansion.amendments_applied == \|records\|`; every `units_added` lands at `wave ≥ record.frontier_wave` (internal consistency; dispatch timing stays Limitation J). The pipeline-level termination budget (schema max 32), structurally identical to `retries ≤ 2`. | `validate_run.py` post-hoc/offline; gates no transition ⇒ **PRESERVES** the per-unit proof, **REVISES** the pipeline-level bound (N ≤ N0 + fuel₀); machine-checked by the TLC `Quiesce` property. Fixtures `amend_fuel_overrun`/`amend_no_fuel_seed`/`amend_records_deleted`/`amend_fuel_widen`/`amend_fuel_chain_break`/`amend_dup_amendment_id`/`amend_id_file_mismatch`/`amend_bogus_revision_after`/`amend_dead_counter`/`amend_wave1_insert`. |
| **I19 amendment scope + kind closure** (BGA) | *Schema kind closure (WP3):* `add_units` ⇒ ≥1 `units_added`, no retirement; `split_unit` ⇒ ≥2 children, exactly 1 retired, a non-empty `retired_snapshot` (each item with `id`/`tags`/`acceptance_criteria`), `criteria_map` present; `add_edges` ⇒ no unit add/retire/snapshot; `cancel_unit` ⇒ ≥1 retired, no adds. *Validator:* `add_units`/`split_unit` (and belt-and-braces: ANY record with `units_added`) ⇒ `dod_refs` non-empty and each element verbatim ∈ `definition_of_done`; `scope_change==true ⇒ human_gate==true`; `cancel_unit ⇒ human_gate==true`; split children tags ⊇ retired-snapshot tags, `retired_snapshot` ids == `units_retired`, and every snapshot criterion maps (`criteria_map`) to ≥1 of the split's OWN children. | `validate_run.py` post-hoc/offline; gates no transition ⇒ **PRESERVES** I-dod/Non-Goals/sign-off integrity, **REVISES** I19 upward (kind closure + snapshot/child semantics). `human_gate` genuineness / `dod_refs` semantic trace stay attestation-only (Limitations I/K). Fixtures `amend_dod_untraced`/`amend_cancel_ungated`/`amend_kind_dodge`/`amend_cancel_noop`/`amend_bare_snapshot`/`amend_noncild_criteria_map`/`amend_single_child_split`. |
| **I20 per-unit DoD binding (`dod_refs`)** (guardrails 1.8.0, WP-1) | Generalizes I19's verbatim-set-membership from amendment records to baseline `graph.json` units. *Adoption:* any unit carrying `dod_refs` arms the check; *closure:* under adoption EVERY unit must carry it (≥1 element — schema `minItems:1`, so a unit-level `[]` never reaches the validator); *membership:* each element verbatim ∈ `clarifications.json.definition_of_done`; *brief mirror:* a bound unit's `units/<id>/brief.json`, when it parses to an object, must carry an equal (sorted, string-filtered) `dod_refs` list — mirror-missing and mirror-drift both FAIL, and a malformed (non-list) brief list fails closed as drift rather than crashing. Zero-adoption runs emit NOTHING (adoption-scoped emission — the I19 zero-amendments precedent; a constraint-forced deviation from the plan pseudocode's unconditional trailing PASS line, upheld by the U06 review panel). | `validate_run.py` post-hoc/offline (stem `I20 unit dod_refs`; unit-scoped rows `(units/<id>)`); gates no transition ⇒ **PRESERVES** termination (node-internal, the I16-row argument). Requiredness is deliberately validator-side adoption-closure, never schema `required` (archived runs stay schema-valid). Adoption is GRAPH-triggered and the mirror clause needs a dict-parsed brief — honest boundary cases in Limitation O. Whether a unit *genuinely serves* its cited items stays verifier judgment (Limitation L). Fixtures `unit_dod_untraced`/`unit_dod_partial`/`unit_dod_brief_drift`/`guardrail_chain_ok`. |
| **I21 per-unit non-goal binding (`non_goal_refs`)** (guardrails 1.8.0, WP-2) | Same shape as I20 over `non_goals`, with ONE deliberate difference: `non_goal_refs: []` is legal and is the EXPLICIT "no non-goal applies to this unit" statement, while an ABSENT key under adoption is a closure FAIL — forgot-vs-none-applicable becomes mechanical. Membership (verbatim ∈ `non_goals`) and the brief mirror behave exactly as I20's (same fail-closed string-filtering, same adoption-scoped emission). | `validate_run.py` post-hoc/offline (stem `I21 unit non_goal_refs`); gates no transition ⇒ **PRESERVES** termination. Same graph-triggered-adoption / dict-parsed-mirror boundary cases as I20 (Limitation O); semantic service of the cited non-goals stays verifier judgment (Limitation L). Fixtures `unit_nongoal_untraced`/`unit_nongoal_partial`/`guardrail_chain_ok`. |
| **I22 guardrail-compliance block** (guardrails 1.8.0, WP-3) | Over every `units/<uid>/verify.json` that parses (RAW parse, deliberately not schema-gated — a schema-invalid verify still FAILs at the schema layer but stays visible here) and carries a `verdict`: *adoption/closure* — once ANY such verify carries `guardrail_compliance`, ALL must (verdict-bearing verifies only, so partial runs mid-wave stay incremental); *membership* — each row's `non_goal` verbatim ∈ the schema-valid `clarifications.json.non_goals` (an absent/schema-invalid clarifications under adoption yields an empty set — membership fails closed; a non-string `non_goal` is fail-closed non-membership); *decidable bite* — a `violated` row on a `PASS` verdict ⇒ FAIL, mechanizing SKILL.md Phase 6's "a delivered non-goal is a FAIL, not a bonus"; *coverage* (I21 synergy) — when the unit also carries `non_goal_refs`, every ref needs an attestation row. | `validate_run.py` post-hoc/offline (stem `I22 guardrail compliance`); gates no transition ⇒ **PRESERVES** termination. **Presence/shape attestation only — whether a `respected` row is TRUE stays verifier attestation, never a validator-proved fact (Limitation L).** Archive-silent: no archived verify carries the block. Fixtures `guardrail_pass_violated`/`guardrail_row_unregistered`/`guardrail_block_partial`/`guardrail_ref_uncovered`/`guardrail_chain_ok`. |
| **I23 P8 DoD/non-goal closure** (guardrails 1.8.0, WP-4) | The mechanical counterpart of SKILL.md Phase 8's task-scope DoD confirmation, double-gated: (gate 1) I10's phase condition verbatim — fires only at P8/DONE on runs that materialized `units/` (post-hoc inspection of `fsm-state`, cross-referencing I10 — phase-gated REPORTING, not a transition guard); (gate 2) adoption of the respective WP-1/WP-3 artifacts, per clause. Then: every `definition_of_done` item must appear in some PASS-verified unit's `dod_refs`, and every `non_goals` item needs a `respected`/`not-applicable` row from some PASS unit's block. Violated-row policing at closure is unnecessary (I10 forces all-PASS at DONE; I22 already forbids violated+PASS). Sanctioned remedy for a DoD item stranded by `cancel_unit`: a DoD-revising amendment through the I19-governed machinery — never fake coverage on an unrelated unit, never hand-edit `clarifications.json` post-hoc. | `validate_run.py` post-hoc/offline (stem `I23 closure`); inspects `fsm-state` exactly as I10 does ⇒ **PRESERVES** termination (no FSM edge/guard touched). Double-gating keeps unadopted archives silent. A run that NEVER advances its recorded phase to P8 is never bound — REQUIRED_GATES and I23 gate reached-phase artifacts, not progression (the plan-owned pre-P8 residual, Limitation O). Fixtures `p8_dod_unclosed`/`p8_nongoal_unattested`/`p8_adopted_preclose` (negative control: fully adopted but pre-P8 ⇒ exit 0)/`guardrail_chain_ok`. |
| **I24 ambiguity-register floor** (guardrails 1.8.0, WP-5) | Reuses the I-dod structural-trigger union verbatim (cartography/graph/units/synthesis; `learnings.json` deliberately excluded — the Phase-0.5 deadlock lesson): once structural work exists and `clarifications.json` parses, an empty (or non-list) `ambiguity_register` ⇒ FAIL. "No ambiguities found" is recorded as an ordinary register item (integer `id` ≥ 1, `resolution` explaining why the task is unambiguous), so non-emptiness IS the none-found attestation form — no new schema shape. The floor is validator-only — deliberately NO schema `minItems` (mid-dialogue pure-P2 authoring and archived empty-register docs stay schema-valid; one legible finding instead of an extraction-path cascade). I8 is untouched: it keeps judging recorded content; I24 only guarantees there is content to judge. | `validate_run.py` post-hoc/offline (stem `I24 register floor`); gates no transition ⇒ **PRESERVES** termination. **NOT archive-silent** — fires on positive artifact evidence (the I-dod trigger family): an archived stub-register run newly flags, which per §5's skew policy reads as expected skew, not a defect of that run; never backfilled. Fixtures `register_empty_structural`/`guardrail_chain_ok`. |
| **I25 resolution required on resolved material items** (guardrails 1.8.0, WP-6) | A register item with `materiality:"material"` AND `resolved:true` MUST carry non-empty `resolution` text. Two layers (the I15 schema-primary + offline-backstop precedent): an `allOf` conditional inside the `clarifications.schema.json` register-item schema (primary — no new property, item `required` gains nothing unconditionally) + an offline validator mirror over the RAW parse (required posture: the offending doc is schema-INVALID under the conditional, so a schema-valid-docs-only path could never see it) whose `.strip()` bar also rejects whitespace-only text the schema's `minLength:1` accepts (the G11 precedent). | schema conditional + `validate_run.py` mirror (stem `I25 resolution present (<register item id>)` — the parenthetical is the ITEM id, not `units/<uid>`); gates no transition. **The sole REVISES of guardrails 1.8.0** — the clarifications artifact contract is strengthened (previously-valid material+resolved-without-resolution docs become invalid), explicitly flagged with its migration argument: prose→schema promotion of what Phase 2 always required; archived offenders read as §5 skew, never edited; templates scaffold compliance. **NOT archive-silent** (fires on the positive F7 evidence). Materiality is self-declared — the all-minor dodge is Limitation N. Fixtures `resolution_missing` (expectation substring = the backend-stable field token `resolution`)/`guardrail_chain_ok`. |
| **I26 sources register** (depth 1.9.0) | Once post-clarification structural work exists (the I-dod trigger family), a schema-valid `sources.json` register must exist with ≥1 row and ≥1 CONSULTED row (fail-closed on absence); every row's disposition is complete under a raw-parse `.strip()` mirror (consulted ⇒ accessed+yielded; queued ⇒ queued_for; all ⇒ why+locator); ids unique; EVERY venue entry carries non-blank K-A/K-B/K-C rationale, admitted or refused; a `T-COMM` row with disposition consulted/queued links to an `admitted:true` venue, while a REJECTED T-COMM row needs only a resolvable `venue_ref` (the honest failed-admission record); every coverage claim's `based_on` resolves to register ids and includes ≥1 consulted row (rejects an all-unopened basis — membership, not relevance). Advisory NOTEs: dangling `queued_for` unit ids; coverage monoculture (≥2 claims all resting on ONE consulted row); external tiers present but none consulted. | `validate_run.py` post-hoc/offline (stem `I26 sources register`); gates no transition ⇒ **PRESERVES** termination and every AO/I guarantee. **NOT archive-silent** — like I-dod/I24 it fires on positive structural evidence (the observed failure is SILENT cartography-skipping; adoption-gating was considered and rejected — a deleted or hand-rolled scaffold goes silent, the exact lens-B failure class); archived runs newly flagging read as §5 expected skew, never edited, never backfilled. Consultation GENUINENESS, tier honesty, coverage RELEVANCE, and sweep adequacy stay verifier/human judgment — Limitation P (validity ≠ correctness). Fixtures `sources_missing_structural`/`sources_no_consulted`/`sources_dup_id`/`sources_row_incomplete`/`sources_tcomm_unadmitted`/`sources_tcomm_rejected_ok`/`sources_tcomm_rejected_admitted_ok`/`sources_venue_blank_k`/`sources_coverage_dangling`/`sources_coverage_unread_basis`/`sources_ok` (the canonical floor register). |
| **I27 clarification sweep** (depth 1.9.0) | Two-level version-honest trigger: T1 (presence) fires when post-clarification structural work exists (the I-dod/I24 trigger family) AND the run is version-stamped ≥ the shipping release (`fsm-state.json.validator_version`, semver comparison — archive-SILENT, the deliberate asymmetry with I26); T2 (shape) fires whenever `dimension_sweep` is present (adoption = submission, the I20/I21 pattern). Checks I27-1..I27-11 (NOTEs at -6/-7/-11): sweep present; nine-dimension exact-once coverage at EVERY tier; per-entry completeness (found ⇒ `register_ids` resolve; clean ⇒ `.strip()`-non-blank `search_statement`); `cartography_round` record + set checks against the SOURCES register; `resolution_source` on resolved rows; material+logged-default NOTE; normalized duplicate-statement NOTE; prompt-verbatim ⇒ `prompt_span` receipt; clean→found flip rule; P8 `sweep_spot_check[]` presence; all-found-all-minor NOTE. | `validate_run.py` post-hoc/offline (stem `I27 clarification sweep`); gates no transition, never guards LT7 ⇒ **PRESERVES**. Disposition GENUINENESS stays attestation — Limitation Q (validity ≠ correctness). Fixtures: the twelve I27 cases listed at PLAN §5.2 (U03 §6 CS-E6a/b validation list, incl. the fully-green sweep). |
| **I28 depth-tier floors** (depth tiers) | Adoption-gated on `fsm-state.depth` (absent ⇒ silent — Limitation O(i) pattern). P0 shape/contentfulness (`.strip()` bar on stakes/reversibility/external_surface.detail); P1 gate provenance; P1b unconditional Phase-2 touch (`phase2_touch` required once clarification resolves on a personas-confirmed tier; `raised` ⇒ an override entry with `at_gate == "P2_CLARIFICATION"` — `at_gate` enum-constrained to phase literals); P2 canonical `skipped_floors` prefix-set == {DT-K2,K4,K5,K6}@confirmed_tier (empty iff full) — a completeness (no-omission) check, contentfulness stays human-judged; P3 ratchet (overrides append-only, upward-only in light<standard<full, chain-consistent, pending_units snapshot, `tier` == final; downward moves schema-unrepresentable); P3b override time-scoping (per-unit `tier_at_verification` ∈ chain values; pending units PASS at ≥ the override's `to`; pre-override PASS units keep their floors — frozen-prefix consistent); P4 floor conformance — probe/chase coverage per unit vs its `tier_at_verification` (exact row_ref index match; checker lists unprobed fallback rows even on PASS), full-tier nine-dimension `sweep_spot_check[]` coverage (the I27-10 record — the cartography round itself is tier-independent I27-4 machinery, untouched) + SOURCES-register disposition rows vs effective tier (U03/U02 interfaces), full-tier panel on design/schema/validator-tagged units (existing I16 shapes); P5 external-surface consistency (`project-local` contradicted by T-VENDOR/T-COMM rows in PASS units ⇒ FAIL). `stakes`/`reversibility` genuineness is human-judged at the gate — I28 checks recording + floor conformance only. | `validate_run.py` post-hoc/offline (stem `I28 depth floor`); gates no transition, never guards LT7 ⇒ **PRESERVES** termination. Adds no gate flag — REQUIRED_GATES untouched (three-human-gates model immutable). Fixtures `depth_ok_light`/`depth_ok_full` (clean-map negative control)/`depth_blank_justification`/`depth_no_phase2_touch`/`depth_phase2_raised`/`depth_skipped_floors_mismatch`/`depth_divergent_confirmation`/`depth_tier_lowered`/`depth_override_midrun`/`depth_probe_gap_standard`/`depth_full_spot_check_gap`/`depth_surface_contradiction`/`guardrail_chain_ok`. |
| **I29 execution-effort briefs** (depth 1.9.0) | Adoption-closure (I20/I21 pattern): once any brief carries `claims_owed`/`required_sources`, every graph unit's brief carries `claims_owed` (entries or `[]` + `claims_owed_none_reason`). Clause 1 queued-consumer closure is adoption-INDEPENDENT (rides I26's structurally-triggered register): a `queued_for` row naming a current unit must appear in that unit's brief. Clause 2 owed-entry shape/no-straw (`trigger_ref` verbatim ∈ criteria ∪ dod_refs; `min_tier` iff source-native type); clause 3 register linkage (S-ids resolve; rejected rows unrequirable); clause 4 CB-1 bridge presence (whitespace-normalized comparison — what preserves I6 FAIL-ability); clause 5 explicit-none (CO-2 folded in, trigger = key adoption). NOTEs: owed-heavy split advisory; tier-shape mismatch advisory. | `validate_run.py` post-hoc/offline (stem `I29 execution-effort briefs`); gates no transition, never guards LT7 ⇒ **PRESERVES**. Derivation adequacy/subject-match stay judgment — Limitation S. Fixtures: the eleven `effort_brief_*` cases at PLAN §5.4. |
| **I30 retrieval coverage verify** (depth 1.9.0) | Adoption-closure (I22 pattern) + forced linkage (an owing brief forces the block onto its verdict-bearing verify). Clause 0 tier stamp when `fsm-state.depth` exists; clause 1 owed_check totality (set EQUALITY with the brief's owed ids; indexes valid); clause 2 coverage arithmetic re-computed (non-empty `row_refs`; `covers_owed`+type joins; existential min_tier lattice; forced `covered-downgraded` on parametric/vendor-silent coverage); clause 3 PASS-with-uncovered contradiction FAIL (the headline; `covered-downgraded` on PASS legal); clause 4 probe floor + shape (≥1 reopen probe on external coverage — tier-independent FLOOR; DT-K2 scales on top); clause 5 target-list superset (required_sources ∪ source_refs ∪ note-carried S-ids ∪ context-pointer S-ids); clause 6 consulted-evidenced ⇒ debrief `source_refs` witness join; clause 7 unreachable-declared ⇒ canonical `unreachable: S<n>` residual_risks declaration. NOTEs: covers_owed fan-out; covers_owed dangling. | `validate_run.py` post-hoc/offline (stem `I30 retrieval coverage`); gates no transition, never guards LT7 ⇒ **PRESERVES** (verdict enum + LT3–LT6 partition untouched). Probe/consultation genuineness stays attestation — Limitation S. Fixtures: the twelve cases at PLAN §5.5 (incl. `retrieval_coverage_vacuous`, the RT-1 pin). |
| **I35 dialogue transcript presence, shape & coverage** (socratic-guardrail 1.10.0) | Reads run-root `dialogues.json` RAW (`load_json` + isinstance guards, the I26/I27 posture). Two-level version-honest trigger (the I27-T1 pattern, `_SHIP="1.10.0"`): T1 (presence) — once post-clarification structural work exists on a run stamped ≥1.10.0, `dialogues.json` MUST be present and RAW-parse to the DP-22 surface-record shape (a deleted transcript FAILs); T2 (shape) — fires whenever `dialogues.json` is present, any version. Clauses I35-1..6 (= MC-1..6): surface coverage (a DS-2 `p2` record before `clarification_resolved`; DS-1/4/5/6 records when their gates/flags exist); `rounds_used ≤ 3` (schema `maximum:3` mirror) ∧ `len(rounds[]) == rounds_used`; per-INSTANCE mandatory-kind coverage (`p2` runs R-FORBID+R-CONFIRM; `p2-r<k>` runs R-CONFIRM iff the recorded list-delta ≠ ∅; DS-1/4/5/6 run R-GATE); round/Q/A shape (non-blank LITERAL `a` on EVERY answer — `answer_ref` supplements, never substitutes — and non-blank `recommended` on EVERY question, `.strip()` bars); every answer slot filled OR `termination.reason=="halt-pending"` with non-empty `pending_questions[]` (the I25 `allOf` conditional). | `validate_run.py` post-hoc/offline (stem `I35 dialogue`); T1 archive-SILENT (`_semver1`→False on unstamped/pre-1.10.0 runs; no archive carries `dialogues.json`), T2 adoption-fires any version; gates no transition, never guards LT7 ⇒ **PRESERVES** termination (`dialogues.json` is a NEW optional artifact — the sources.json/I26 zero-fsm-delta precedent). Dialogue GENUINENESS (a human spoke; verbatim `q`/`a` fidelity; move truth) stays attestation — Limitation U/V. Fixtures `dialogue_missing_stamped`/`dialogue_shape_bad`/`dialogue_version_gated_silent`/`dialogue_missing_ds2`/`dialogue_ds4_missing`/`dialogue_rounds_over`/`dialogue_rounds_desync`/`dialogue_missing_forbid`/`dialogue_missing_confirm`/`dialogue_reentry_noforbid_ok`/`dialogue_blank_answer`/`dialogue_missing_recommended`/`dialogue_empty_answer_no_halt`/`dialogue_halt_pending_ok`/`dialogue_ok`. |
| **I36 dialogue disposition & presentation-bind** (socratic-guardrail 1.10.0) | R-CONFIRM disposition bijection ↔ final `definition_of_done`/`non_goals` verbatim via the THREE-ARM union (presented-verbatim in `items_presented[]` \| `edited_to`-of-a-presented-pre-round item \| `origin:human-elicited` passing the DP-31 bind); `items_presented[]` `maxItems:4` (**stuffing FAIL**); per-disposition `q_ref` join; `pages ≥ ceil(\|distinct items presented\|/4)`; bijection scoped to the LATEST disposition per item (superseded iff a later row carries `reopened_by`). **Presentation-bind dissent:** a disposition over an item in NO R-CONFIRM `items_presented[]` (and neither an edit-chain nor DP-31-bound row) ⇒ FAIL — orchestrator-authored records cannot self-cover. **I36-1b recommended-echo counter-join:** an item appearing VERBATIM in its eliciting question's `recommended`/`offered` text is orchestrator-offered BY CONSTRUCTION and MUST NOT claim `origin:human-elicited` via the verbatim-`a` bind (DP-31 disjunct 1) — closes the round-3 happy-path laundering. I36-2 forbid-round residue joins (`non_goals_added[]`⊆`non_goals` verbatim; `clean_sweep`⇒non-blank; `battery_topic` all four covered; origin bind BOTH DP-31 disjuncts, disjunct-2 hardened else its genuineness is AR). I36-3 never-re-ask; I36-4 register-row coverage (two exemption arms). Clauses = MC-7,8,11,14. | `validate_run.py` post-hoc/offline (stem `I36 dialogue`; NOTE stem `N-I36 (rubber-stamp signature)` via `print`); rides I35's presence (dispositions live in `dialogues.json`), T2-adoption otherwise; gates no transition ⇒ **PRESERVES** termination. Presentation fidelity + the **DP-31 disjunct-2 `draft_edits` echo genuineness** (one-click accept: `amendment` a verbatim substring of `a`) stay attestation — Limitation U. Fixtures `dialogue_confirm_unpresented`/`dialogue_confirm_stuffing`/`dialogue_confirm_bijection`/`dialogue_confirm_ok`/`dialogue_recommended_echo_launder`/`dialogue_forbid_dangling`/`dialogue_forbid_topics_missing`/`dialogue_draftedit_unbacked`/`dialogue_reask`/`dialogue_regrow_uncovered`/`dialogue_regrow_impasse_ok`/`dialogue_rubberstamp_note`. |
| **I37 dialogue termination & probe accounting** (socratic-guardrail 1.10.0) | I37-1 termination enum + conditional payloads (`capped_open[]`+`impasse_dossier` iff `capped-unconverged`; `pending_questions[]` iff `halt-pending`; non-blank `gate_answer` at DS-2 on `converged`/`human-early`) + `probes_lapsed[]` totality + **rung-choice LEGALITY** (cause `cap-exhausted` legal IFF the trigger fired in the instance's final recorded round with rungs 1–2 unavailable and `termination.reason != human-early`; cause `human-early` legal IFF `termination.reason == human-early`). I37-2 probe-obligation accounting both directions (a fired computable trigger with NONE of {R-PROBE round, `probe_discharge`, `probes_lapsed[]`, `human-early`, `halt-pending`} ⇒ flag; the deviation recompute's *consequential* qualifier is CONDITIONAL on I38's CC predicate; `halt-pending` SUSPENDS obligations). I37-3 instance closure (`instance` ids ∈ DP-49 per-surface vocabulary; per-key uniqueness; exactly-one/at-most-one cardinalities; DS-4/DS-6 ↔ escalation-event/amendment joins; `p2-r<k>` ↔ `rollback_ref` license join with **INJECTIVITY** — distinct re-entries reference DISTINCT license records, `k` dense/ordered). Clauses = MC-9,10,13. | `validate_run.py` post-hoc/offline (stem `I37 dialogue`); T2 adoption; gates no transition, never guards LT7 ⇒ **PRESERVES** (the DP-15 well-founded variant is model discipline, unaffected). Substrate honesty of the recomputed bits + an UNRECORDED trigger invisible to every rung check stay attestation — Limitation V. Fixtures `dialogue_capped_no_dossier`/`dialogue_gate_answer_missing`/`dialogue_lapse_wrong_rung`/`dialogue_probe_unserved`/`dialogue_lapse_at_cap_ok`/`dialogue_probe_humanearly_ok`/`dialogue_instance_freeform`/`dialogue_reentry_unlicensed`/`dialogue_reentry_noninjective`. |
| **I38 ask-first consequential-default legality** (socratic-guardrail 1.10.0; = provisional I35, renumbered) | `CC(r) = AF-1 ∨ AF-33` (K1 dimension keying ∨ K2 content-linkage incl. the `out_of_scope_provenance` extension); **materiality-BLIND by construction** (AF-2), so the self-declared-materiality loophole cannot re-open. FAIL clauses: AF-14 illegal logged-default on a consequential gap (`_t1∨_t1h`), AF-15 dimension required, AF-16 unlinked/dangling human-gate, AF-17 provenance well-formedness (three blocks), AF-18 open-consequential-past-P2 with structural evidence, AF-19 verbatim spot-check, AF-35 halt-dangling shape, AF-36 halt-materiality coherence (declaring a consequential row `minor` to buy a clean exit ⇒ FAIL), AF-42 halt-freshness/anti-forgery, AF-45 provenance attribution + round-resolution. NOTE clauses: AF-20 verbatim-heavy, AF-35 `N-I38 (halted pending human; <n> structural artifact(s))`, AF-38 unsolicited-authorship. **I27 is byte-UNTOUCHED** (I27-6 keeps `N-I27 (material self-default)` at all versions) and **I8 is kept LOUD** (the `pending_halt` clean-exit relaxation DECLINED); a ≥1.10.0 material consequential logged-default draws BOTH the N-I27 NOTE and the I38 AF-14 FAIL — intended. | `validate_run.py` post-hoc/offline (stem `I38 ask-first`, NOTE stem `N-I38`; carries every AF-* clause verbatim, provisional-I35 renumbered); split trigger `_t1∨_t1h / _t1 / _t1h / _t1v / _t2`, all `_semver1` arms archive-SILENT (T2 keys absent from archives); gates no transition ⇒ **PRESERVES** termination (AF-22 — no edge/flag/guard; all schema deltas OPTIONAL). Ask-first semantic remainders R1–R8 (incl. **R8 completion-evidence-withholding forged-halt window**) stay attestation — Limitation W. Fixtures `askfirst_illegal_default_dim`/`askfirst_illegal_default_prov`/`askfirst_missing_dimension`/`askfirst_unlinked_humangate`/`askfirst_dangling_round_ref`/`askfirst_prov_dangling`/`askfirst_open_conseq_past_p2`/`askfirst_verbatim_unchecked`/`askfirst_verbatim_heavy_note`/`askfirst_version_gated_silent`/`askfirst_ok`/`askfirst_halt_p2`/`askfirst_halt_note`/`askfirst_halt_minor_dodge`/`askfirst_halt_dangling`/`askfirst_authorship_note`/`askfirst_halt_default`/`askfirst_halt_after_work`/`askfirst_illegal_default_prov_oos`/`askfirst_oos_prov_dangling`/`askfirst_prov_attribution`/`askfirst_prov_round_dangling`. |
| **I39 anchor confirmation, provenance & baseline integrity** (socratic-guardrail 1.10.0) | Reads `clarifications.json.item_confirmations[]`/`anchors_retired[]` and the transcript `anchors_baseline` block. I39-1 forbid-round residue lands (GV-3). I39-2 `human_confirmed(x,L)` via the CURRENT (highest-index non-superseded) record with non-blank `transcript_ref`; duplicate-currency ⇒ FAIL; a re-opened round supersedes (GV-7/GV-35). I39-3 list↔record↔baseline reconciliation (a–d); clause (d) replays the POST-baseline record sequence forward from the IMMUTABLE `anchors_baseline` to reproduce the current lists — **dissent obligation 2:** anchored to the immutable baseline (the I17 `baseline_units` pattern) so a same-file coordinated rewrite cannot move the baseline it is judged against (GV-8). I39-4 fail-closed presence + **dissent 1:** on a ≥1.10.0 structural run an ABSENT `item_confirmations` ⇒ FAIL (GV-9); on a `_semver1` run with `clarification_resolved:true` an ABSENT `anchors_baseline` or self-inconsistent content hash ⇒ FAIL; UNSTAMPED runs disarm → advisory `NOTE N-I39 (governance disarmed; unstamped)`. I39-5 no unconfirmed anchor past the gate (GV-11). I39-6 baseline-anchored totality — any anchor delta not explained by an R1–R6 receipt ⇒ FAIL (GV-23). I39-7 (1.10.1) the OPTIONAL `fsm-state.anchors_baseline_hash` mirror, when present, MUST equal the transcript `anchors_baseline.content_hash` — adoption-gated on mirror presence (fires at any version, ABSENT ⇒ silent); Limitation X hardening (narrows, NOT Closes). | `validate_run.py` post-hoc/offline (stem `I39 anchor`, NOTE stem `N-I39`); `item_confirmations` REQUIRED once `_t1` (version-gated, archive-silent below-ship), T2 adoption otherwise; gates no transition ⇒ **PRESERVES** termination (GV-28 — optional property, write-once snapshot inside the already-write-once transcript). **GV-29** (required-once-stamped presence) is a flagged **REVISES** of the clarifications artifact contract for NEW runs only (I25/I27-T1 class). Confirmation genuineness stays attestation (Limitation L); the coordinated multi-file baseline rewrite is Limitation X. Fixtures `gov_forbid_residue_lost`/`gov_dup_currency`/`gov_reclarify_supersede_ok`/`gov_recon_dangling`/`gov_coordinated_rewrite`/`gov_replay_ok`/`gov_no_item_confirmations`/`gov_missing_baseline`/`gov_bad_baseline_hash`/`gov_unstamped_disarm_note`/`gov_unconfirmed_past_gate`/`gov_unexplained_delta`/`gov_baseline_mirror_ok`/`gov_baseline_mirror_mismatch`. |
| **I40 anchor mutation gating** (socratic-guardrail 1.10.0) | Adoption-armed on `revise_anchors`/`item_confirmations` presence (the AF-25 pattern; archive-safe — no archive carries the kind). I40-1 every `revise_anchors` record carries `human_gate:true`+`transcript_ref` (no autonomous branch, any list/op — GV-13). I40-2 fuel cost `== max(1,0−0) == 1`; at `fuel_remaining==0` NO amendment record is writable (`fuel_after==−1` violates I18 ≥0) — **I18 carried VERBATIM** (GV-14/GV-36). I40-3 in-transaction ref-reconciliation (add refs on `propagation_targets`; edit REWRITES matching refs verbatim; remove drops refs except a unit whose sole `dod_refs` element is removed must be re-pointed or `cancel_unit`-paired; touched unexecuted briefs mirror-updated — GV-15). I40-4 **membership-union** — I20/I21/I22 accept `current ∪ anchors_retired[].prior_text`; a unit ADDED after a retirement (later record id) citing retired text ⇒ FAIL (GV-16). I40-5 added-item closure (GV-17). I40-6 any op on a `violated`-row-bearing NG routes to P7/ESCALATE, never a P6 gate; a `violated`-on-PASS stays a FAIL regardless (GV-18). I40-7 `scope_change` add residue (GV-21). I40-8 `add_units` autonomy narrowed — an `add_units` with `human_gate` absent/false whose every `dod_refs` element fails `human_confirmed(x, definition_of_done)` ⇒ FAIL (downgrade-laundering guard, GV-25). | `validate_run.py` post-hoc/offline (stem `I40 anchor`); adoption-armed any version; gates no transition ⇒ **PRESERVES per-unit** (GV-30 — Claims A–D untouched, no back-edge, adds no units, fuel cost ≥1 keeps events ≤ fuel₀); **I18 carried VERBATIM — no fuel REVISES**. Flagged enumeration-level **REVISES** (→ formal-classification): the `revise_anchors` kind-whitelist add (GV-30); the **GV-16 membership-union widening of I20/I21/I22 (`current ∪ retired`)**; the GV-25 narrowing of I19 `add_units` autonomy. `human_gate` genuineness stays attestation (Limitation I). Fixtures `gov_revise_ungated`/`gov_revise_fuel_cost`/`amend_fuel0_revise_unwritable`/`gov_revise_ok`/`gov_ref_recon_soleref`/`gov_ref_recon_briefdrift`/`gov_retired_membership_ok`/`gov_later_unit_cites_retired`/`gov_added_item_stranded`/`gov_revise_violated_target`/`gov_scope_change_no_confirm`/`gov_autonomous_unconfirmed_ref`/`gov_autonomous_confirmed_ok`. |
| **I41 panel dissent accounting & adjudication** (cross-repo-lessons 1.11.0) | Closes the hole where **I16** (`top_verdict == discrete majority`) and **I6** (a PASS may carry only `minor`) TOGETHER force a 2-1 panel's dissenting lens to downgrade, drop or bury a major finding — invisible to every prior predicate. Reads `units/<uid>/verify.json` RAW. **I41-1** verdict=PASS with ≥1 `panel[]` member voting `FAIL`/`DISAGREE` REQUIRES a `panel_adjudication` record (T1, version-gated ≥1.11.0 via `_i27_semver_ge`). **I41-2** a dissenting vote must be substantiated. **(a)** version floor and **(b)** adoption closure (once ANY member records findings — the I20/I22 pattern) bind `FAIL`-voting members to ≥1 member `defects[]` entry with a non-blank `criterion`; **(c)** a `DISAGREE`-voting member must instead carry a non-blank `summary` **or** a `defects[]` entry with a non-blank `minimal_repro`, and is **never** obliged to name a criterion — AO-3 makes `DISAGREE` the MANDATED route for a critique that cannot name one (`self-learning-loops.md:299-302`, `:601-604`), so binding it there would leave NO compliant artifact. The narrower `_I41_CRITERION_BOUND = ("FAIL",)` carries (a)/(b) alone; `_I41_DISSENT` still holds both verdicts, because I41-1, I41-4c and N-I41 read it and a `DISAGREE` member is a full dissent for all three. **I41-3** on a PASS, every member `blocker`/`major` MUST be named by a `dispositions[]` entry (`downgraded-minor`|`withdrawn`|`overruled-by-repoll`) with a non-blank rationale — `upheld` on a PASS ⇒ FAIL; deliberately **NOT** a flat ban, because banning member majors reproduces the laundering. **I41-4a** `resolution` enum + rationale; **4b** `dissent_refs`/`dispositions` resolve to a real `(lens, defect_index)`; **4c** THE DISSENTER MAY NOT BE RE-POLLED (nor any lens with `tested_defect:true`) — re-running the dissenter until it flips is the AO-5 prohibition, and the pathology lives in `pre_verdict`, so `panel[]`'s FINAL vote alone would never see it; **4d** `panel[lens].verdict == post_verdict` (panel[] holds the FINAL vote) and the majority recomputed with **I16's own rule** must equal the top verdict; **4e** a re-poll rides the EXISTING `verify_rounds` ≥2, still bounded by I16-(c) at ≤3 — **I41 adds no bound and no counter**. **I41-5** a `downgraded-minor` disposition MUST echo as a top-level `minor` with the same criterion (coverage-first; a downgrade with no echo is a deletion wearing a downgrade's label). **I41-6** `escalated-p7` is incompatible with a PASS (it deliberately demands NO `disagreement` block — the schema's `disagreement` ⟺ `DISAGREE` iff would make that a schema-INVALID artifact). NOTE `N-I41 (dissent withdrawn without re-poll)` is the rubber-stamp signature (N-I36 precedent), exit-neutral. | `validate_run.py` post-hoc/offline (stem `I41 panel dissent`, NOTE stem `N-I41`); T1 version-gated + T2 adoption-armed (measured 0/292 archived verifies carry `panel_adjudication` or member `defects`, so the **T2 adoption arm** is unarmed on every archive — re-measured 2026-07-29 and re-derived IDENTICALLY 2026-07-30 by the census command below; the previously published 0/156 denominator was stale, the zero-adopter conclusion is not. **T1 stays silent on a SECOND, separately measured ground**, since an adoption count says nothing about a version floor: T1 arms at `validator_version >= 1.11.0` and the MAXIMUM stamp across the 17 archived `fsm-state.json` files is **1.10.1** (9 unstamped, then 1.7.0 / 1.8.0 ×2 / 1.9.0 ×3 / 1.10.0 / 1.10.1), so no archive reaches the floor. Both arms are silent, but on TWO facts, not one — and the zero is **DATED, NOT STRUCTURAL**: the excluded in-flight run is itself stamped **1.12.0** and already carries `panel_adjudication` records, so **T1 will arm on it the moment it archives**); gates no transition, **never guards LT7** ⇒ **PRESERVES** Claims A–D, AO-1/2/4/6/7 and I1–I40 predicates; `formal/` byte-untouched. **AO-3 is SPLIT: its `FAIL` arm PRESERVES (strengthens) — I41-2(a)/(b) extends "a FAIL names a criterion" to panel members, which previously escaped AO-3 entirely — while its `DISAGREE` arm is a flagged REVISES.** **THREE flagged REVISES** (→ formal-models.md, each with a migration argument): the **AO-5 doctrine** (a BOUNDED intra-node re-poll becomes a sanctioned pre-escalation path), the **I16 verify ARTIFACT CONTRACT** (a PASS + dissent + no adjudication was VALID and becomes INVALID), and **AO-3's `DISAGREE` route** (the pre-release predicate bound `DISAGREE` members to cite a criterion — the route AO-3 itself mandates for a criterion-less critique — leaving no compliant artifact, the A2 no-compliant-path shape; resolved by NARROWING the obligation to `FAIL` members and substantiating a `DISAGREE` member via I41-2(c). That correction is legality-WIDENING, disclosed as such, over a set measured EMPTY: 0 of the fixture dirs and 0 of the archived verifies carrying a `panel[]` record a `DISAGREE` member, so the withdrawn arm never fired on any artifact in either tree). I16's own predicate is byte-untouched; I41-4d RE-USES its `_discrete_majority`. Every schema delta is OPTIONAL. An UNRECORDED dissent, an overwritten earlier iteration, a dissenter that rewrites its FINAL vote to `PASS` and drops its `defects` (arming ZERO clauses), and `tested_defect`/rationale genuineness stay attestation — Limitation Y. Fixtures `panel_dissent_unadjudicated`/`panel_dissent_version_silent`/`panel_dissent_bare`/`panel_dissent_closure`/`panel_major_unexplained`/`panel_adj_badresolution`/`panel_adj_no_rationale`/`panel_adj_dangling_ref`/`panel_repoll_dissenter`/`panel_repoll_tested`/`panel_repoll_majority_desync`/`panel_repoll_majority_raw`/`panel_repoll_rounds`/`panel_downgrade_unechoed`/`panel_escalate_on_pass`/`panel_withdrawn_note`/`panel_dissent_ok`, plus the iteration-2 sub-clause pins `panel_upheld_on_pass`/`panel_disposition_blank_rationale`/`panel_disposition_wrong_lens`/`panel_disposition_wrong_index`/`panel_blocker_unexplained`/`panel_dissent_blank_criterion`/`panel_dissent_refs_dangling`/`panel_repoll_final_dissent`/`panel_repoll_rounds_one` and the green controls `panel_dissent_nonpass_ok`/`panel_major_on_nonpass_ok`/`panel_unanimous_ok`/`panel_withdrawn_flipped`/`panel_withdrawn_after_repoll`, plus the iteration-3 arm pins for I41-2(c) `panel_dissent_disagree_bare` (the bare `DISAGREE` row) / `panel_dissent_disagree_ok` (the compliant criterion-less path — the regression test for the narrowing) / `panel_dissent_disagree_repro_ok` (the `minimal_repro` disjunct). |
| **I42 evidence digest integrity** (cross-repo-lessons 1.11.0) | **THE RULE, EXTRACTABLE IN ONE LINE — first thing in the row on purpose, so a left-to-right reader meets it before the arms:** offline/post-hoc, T2-armed by the first object element, archive-silent because no archived verify has adopted (a **dated** zero), closure gated at `_I42_SHIP`, and it **never guards `LT7`** ⇒ PRESERVES everything. What follows is the arms `I42-1a`…`I42-5`, then measurement and provenance — with four exceptions that are *also* rule and must not be skipped: Limitation Z (I42 detects DRIFT, not READING), the union-**WIDENING** guarantee classification, the path-owner PRESERVES ruling, and the fixture-suite contract. Read on for an arm's exact predicate, for those four, or to re-derive a figure. · R18/BB-L46: a verifier's `inputs_reviewed` may carry content DIGESTS, not just paths, so evidence that MOVED under the verification is detectable. **I42-1a** every evidence object carries a non-blank `path`; **1b** adoption closure — once any element is an object, EVERY element of EVERY verdict-bearing **aggregated** `units/<uid>/verify.json` must be — **"aggregated" is the domain, not a flourish:** panelist `verify_p<N>.json` files are **out of domain**, by the same decision I43 records, and the mechanism is that the collection loop opens the **literal filename** `verify.json` and nothing else — **no CODE line in the whole I41/I42 region names `verify_p`.** That narrower claim is the one the mechanism needs and the one that is true; a **comment-inclusive** count is *not* zero and **rises every time anyone documents the exclusion** (this cell included), so none is published here. An earlier revision published "occurs **zero** times" unqualified and it was already false when measured, the region's own 292-document composition comment being one of the hits — the same self-defeating-citation shape §5 warns about. Re-derive both over a region delimited by **content anchors, never offsets** — `A='/^ *# ---- I41 panel dissent accounting/'; B='/^ *# I9 MISSING VERIFICATION/'` (each matches exactly once: `grep -c` on either → 1), then `awk "$A,$B" validate_run.py | grep verify_p | grep -vc '^[[:space:]]*#'` → **0** (the durable CODE claim) versus `awk "$A,$B" validate_run.py | grep -c verify_p` → **> 0 and rising**. It is *not* the D-04/IMP-20 `unit_docs` carve-out, since I41/I42 read RAW and never consult `unit_docs`. Witness, measured on this repository's own in-flight run: **3** panelist files carry the mixed string/object shape and emit **zero** I42 rows of any severity (mixed shape ⇒ FAIL at ≥1.11.0, exit-neutral NOTE below it, so a pre-ship experiment is not punished). **I42-2** a present `sha256` must match `^[0-9a-f]{64}$` — fail-CLOSED, never read as "no digest". **I42-3** for a run-dir-relative path that EXISTS and carries a well-formed digest, the recomputed hash MUST match — **except** the I9 status-aware transient, a CONJUNCTION (`phase == P6_EXECUTE_VERIFY` ∧ the owning unit `executing`/`verifying` ⇒ NOTE), copied verbatim from I9 for the same reason (a retry legitimately rewrites `debrief.json` under a not-yet-rewritten verify); a hard FAIL at every other phase/status and **ALWAYS at P8/DONE**. **"The owning unit" is the unit owning the DIGESTED PATH** (`units/<uid>/…`), never the unit owning the verify: the fact that excuses the drift is "unit B is still rewriting that file", a property of B, and a cross-unit citation of a sibling artifact is exactly what R18/BB-L46 invites. A run-root path (`graph.json`, `fsm-state.json`) that no unit owns leaves the PHASE conjunct to decide — an absent status is NOT read as "not in flight". **I42-4** a run-relative path that does not exist ⇒ FAIL (the verifier cites evidence the run never emitted; a retired unit dir under I17 lands here correctly). **I42-5** an absolute path or one escaping the run dir is **NOT decidable from emitted artifacts**, so it is an exit-neutral NOTE `N-I42 (undigestable evidence)` — never a FAIL. | `validate_run.py` post-hoc/offline (stem `I42 evidence digest`, NOTE stem `N-I42`); T2 adoption-armed at any version (measured 2179/2179 archived `inputs_reviewed` elements across 292 archived verify documents are strings ⇒ archive-silent with no version gate needed — and **that zero is DATED, NOT STRUCTURAL:** nothing prevents an object element from being archived, this repository's own in-flight run already carries them, so the arm arms the moment such a run archives; re-measure rather than inheriting the zero. **Census command** (derives the I41 *and* I42 figures; re-measured 2026-07-29 and re-derived IDENTICALLY 2026-07-30, printing `docs elements string-elements verifies-with-panel_adjudication verifies-with-member-defects` = `292 2179 2179 0 0`). It is **SELF-CONTAINED** — the excluded run dir is named **literally**, so the published integers are re-derivable from the published mechanism with no external knowledge (left as a free variable `RUN` it raises `NameError`): `python3 -c "import json,glob;RUN='2026-07-29_183514';V=[p for p in sorted(glob.glob('.wip/*/units/*/verify*.json')) if RUN not in p];D=[json.load(open(p)) for p in V];E=[e for d in D for e in (d.get('inputs_reviewed') or [])];print(len(V),len(E),sum(isinstance(e,str) for e in E),sum('panel_adjudication' in d for d in D),sum(any(m.get('defects') for m in d.get('panel') or []) for d in D))"` → `292 2179 2179 0 0` at **2026-07-30T03:10:51Z on tree `23c9962`**, and **IDENTICALLY** at 2026-07-30T03:15:41Z on tree `1bf2626` (the axis held across a tree change mid-repair — the point of excluding the in-flight run; this very one-liner was extracted verbatim from this cell and executed: exit 0) (`RUN` = `2026-07-29_183514`, the then-in-flight run, excluded because it is not yet archived). **Adjacent axes**, so a reader who measures a different number can tell WHICH axis they are on: **295** docs / 2179 elements under the looser recursive glob `.wip/**/verify*.json` (same archived population, +3 run-root `verify.json` files carrying ZERO `inputs_reviewed` elements — so the ELEMENT count is axis-insensitive here and only I41's denominator moves); both of those EXCLUDE the in-flight run and are therefore **stable**, whereas any in-flight-**inclusive** count is **not durable and must not be quoted forward** (346 total under `.wip` / 343 under `units/` at the same instant, up from 321/318 forty minutes earlier — it moved *during* the repair). **Composition** of the 292: **159** unit-final `verify.json` + **133** panelist `verify_p*.json` across **159** archived unit dirs, so this is "no DOCUMENT adopted", which entails but is stronger than "no UNIT adopted". The previously published 964/964-across-156 denominators were stale: **both numbers moved, the safety conclusion did not** — zero object elements and zero adopters then and now, so no version gate is needed in either arm); `_I42_SHIP` gates the CLOSURE arm alone; gates no transition, **never guards LT7** ⇒ **PRESERVES** Claims A–D, AO-1..AO-7 and I1..I41 — all of them; `formal/` byte-untouched. The schema delta is a union **WIDENING** (`inputs_reviewed.items` = string | object), so no previously-valid artifact becomes invalid — this is **NOT** the I25/GV-29 contract-revision class; the closest neighbour is I22's adoption-closure, whose pattern I42-1b copies. A digest proves the bytes match NOW, never that the verifier READ them — I42 detects DRIFT, not READING (Limitation Z). The path-owner keying of the transient window is PRESERVES: it narrows one NOTE window and widens another, both inside I42's own adoption arm, and no archive is armed. Fixtures `digest_ok`/`digest_shape_mixed`/`digest_blank_path`/`digest_malformed`/`digest_mismatch`/`digest_mismatch_p6_note`/`digest_dangling`/`digest_outofrun_note`, plus the iteration-2 sub-clause pins `digest_shape_mixed_below` (the below-ship NOTE arm) / `digest_mismatch_offphase` and `digest_mismatch_p6_terminal` (the transient window is CONJUNCTIVE: phase AND status), and the iteration-3 path-owner pins `digest_mismatch_crossunit_note` / `digest_mismatch_crossunit_fail` (the discriminator: the path owner is terminal while the verify's own unit is still in flight) / `digest_mismatch_root_note` (the run-root fall-back) / `digest_outofrun_abs_note` (the absolute-path arm, isolated so its sibling element cannot mask it). |
| **I43 verification currency** (verify-repair 1.12.0) | An executed unit's **aggregated** `verify.json` must adjudicate the iteration its debrief claims: `verify.iteration == debrief.iteration`. Four exhaustive, mutually-exclusive arms behind two guards (an indeterminate debrief, and an absent/unusable verify, are DECLINED to I9's domain — no double-charging): **P1-a** verify *behind* debrief off-window ⇒ hard FAIL (SUPERSEDED, the measured defect class); **P1-b** verify *ahead* off-window ⇒ hard FAIL (AHEAD — `LT7` increments `iteration` BEFORE the next `EXECUTE` writes its debrief, so it is a rollback under a live verification or an AUTHORED number); **P1-d** *any* mismatch INSIDE the in-flight window ⇒ exit-neutral `N-I43` NOTE — **direction-blind, so it covers AHEAD too**, and `--quiet`-gated, so an AHEAD-in-flight case is silent at exit 0 (**not** a hard FAIL; unpinned residual, §5); **P1-ok** equality ⇒ positive assertion. IN_FLIGHT := I9's `phase == P6_EXECUTE_VERIFY ∧ status ∈ {executing, verifying}` **plus** `signoff_confirmed is not True`; both twin window sites are CITED and byte-untouched, never hoisted. Never reads `retries` (I4's ceiling is neither widened nor narrowed — this is an equality between two ARTIFACTS) and never reads `verdict` (complete means CURRENT, not PASS). | `validate_run.py` post-hoc/offline (stem `I43 verification currency`, NOTE stem `N-I43`); **UNGATED** by `validator_version` — measured **1 of the 17 archived runs in THIS REPOSITORY** is newly RED (the 18th `.wip/` dir is this repair run, still in flight, which the in-flight window carves out by construction) (the branch's own repair target, 8 rows), **zero false positives**; never `0` (§5 carries the population, timestamp and reproducing command). **REVISES** the verify **artifact contract** (iteration parity was previously unstated by every schema, predicate and doc) with a migration argument — see `references/formal-models.md`. Gates no transition, **never guards `LT7`** ⇒ **PRESERVES** Claims A–D, AO-1..AO-7 and I1..I42. Limitation AA: detects STALENESS, never GENUINENESS. |
| **I44 sign-off closure** (verify-repair 1.12.0) | Antecedent `gates.signoff_confirmed is True` **by identity**, with **no phase condition at all** (the motivating run rolled `P8 → P6` back with the flag still set, so any phase-gated formulation is inert on it). Five arms, **artifact-keyed, never status-keyed**, evaluated in order: **a** absent `verify.json`; **b** unusable (not JSON / not schema-valid / `unit_id` mismatch); **c** verdict-less; **d** superseded; **e** an unresolved `DISAGREE` ⇒ exit-neutral NOTE, never a FAIL (a `DISAGREE` is a COMPLETE verification act closed by `LT6 → ESCALATE →` the Phase-7 human gate; failing it would attack AO-5 from the incentive side) — **but arm (e)'s print is `--quiet`-gated, so the "recorded NOTE" is invisible in the mandated invocation** (§5). A **current** `FAIL` at `retries == 2` is deliberately NOT an arm. Domain is `unit_dirs_with_debrief` (executed units); a never-executed materialized unit stays I10's. | `validate_run.py` post-hoc/offline (stem `I44 sign-off closure`, NOTE stem `N-I44`). Recorded human override `fsm-state.json.accepted_incomplete {units[], rationale, decision_ref}` **downgrades, never suppresses**, per unit, with **no blanket form**, **fail-CLOSED** when malformed (one extra FAIL naming the first unmet condition) and an over-broad NOTE for stale entries; the downgrade row is **un-gated by `--quiet`** (§9-R12: un-gate a NOTE exactly when stdout is its only channel). Deliberately **NOT** in `REQUIRED_GATES` — SC3 derives that table from `spec/fsm.json.guards[]`, whose `required_from_phase` vocabulary cannot express "given gate G, artifacts A must exist"; ships as its own labelled predicate on the `gpersonas_failclosed` converse archetype. **REVISES** the gate contract (`signoff_confirmed` acquires an artifact-level obligation) with a migration argument. Never guards `LT7` ⇒ **PRESERVES** everything; I10 and gate ordering byte-untouched. |
| **N-I45 version-skew visibility** (verify-repair 1.12.0) | An exit-neutral **NOTE**, not an invariant with a FAIL arm: a shadow count of the version-gated arms this run's own `validator_version` stamp suppressed **while the arm's non-version precondition HELD**. The count is of **evaluation gates** and is an **UPPER BOUND** on suppressed FAILs (an armed clause may well have passed) — the upper-bound sentence is normative text, and the measured `stamp 1.10.1 → 0 problems / 1.11.0 → 8 problems` figure may **NOT** be restated as this NOTE's output (the wrong-mechanism defect). Fires loudly on unstamped archives, where every comparison against an absent stamp is `False` — intended: it is the version-skew policy's *"what would need to change to re-validate this run today"* made legible. | `validate_run.py` — a bare `print` before `_finish`, touching neither `rep.problems` nor `rep.checked` ⇒ **exit-neutral by construction**; zero suppressed arms emits nothing. **NOT** `--quiet`-gated (a filed, labelled deviation from its quiet-gated I39-4 sibling: SKILL.md mandates `--quiet`, so a quiet-gated skew NOTE would be inert in the only invocation that matters). It READS `validator_version` because the stamp is its subject matter, but its own emission is not stamp-gated — calling it version-gated is a category error. Completeness is enforced mechanically by **SC8** (`count('_skew_record(') == count('_i27_semver_ge(') - 1`), so a future version-gated arm added without a recorder breaks the dev-time build instead of silently under-counting. **PRESERVES** everything. |
| **I46 non-converged PASS** (verify-repair 1.12.0) | An aggregated `verdict: PASS` whose `converged` is **identically `False`** — absent, `0`, `""` and `null` never arm, which is what keeps it archive-silent. The field was **dead data**, read by nothing, so a verifier honestly reporting "I hit the `R_max = 3` round cap, coverage may be incomplete" under a PASS said so to no one. Severity is tiered exactly like I43/I44: exit-neutral **NOTE below sign-off** (a round-capped verifier is being honest, and punishing an optional honesty field would teach runs to omit it), **hard FAIL under `signoff_confirmed`** (a unit whose own verification declares its coverage incomplete, at claimed completion, is verification left unfinished). `verify_rounds` is printed when present but is never a condition. | `validate_run.py` post-hoc/offline (stem `I46 non-converged PASS`, NOTE stem `N-I46`); downgradable by the same per-unit `accepted_incomplete` override as I44. The FAIL arm is a **recorded fork** (DECISIONS#29): the intake wording says "flags", which is severity-neutral. Its field is `verdict == PASS ∧ converged is False`, so the **iteration-parity census is silent on it** — I46's own 2 archived FAILs (U03/U07 of the repair target) are an arming consequence of a different field and are published as such, never implied by the parity number (§5). Never guards `LT7` ⇒ **PRESERVES** everything. |
| **N-I47 ledger desync at sign-off** (verify-repair 1.12.0, DoD 6) | An **advisory NOTE and nothing else** — the predicate I44 deliberately does not carry, closed here so the doctrine no longer promises a fifth member the code lacks. Four conjuncts: (1) `signoff_confirmed is True` by identity; (2) the unit is EXECUTED (`unit_dirs_with_debrief`, exactly I44's domain); (3) its verification is **COMPLETE AND CURRENT** — present, usable, verdict-bearing and iteration-matched, the exact **negation** of I44 arms a–d and I43-a/-b, so the row never double-charges a fact another predicate already FAILs; (4) `fsm-state.units[].status` is **NON-TERMINAL**, defined as the whitelist `{pending, briefed, executing, verifying}` rather than `not in {passed, failed}` — `escalated` (Phase-7-closed), `retired` (cancelled) and `blocked` (I10's domain) are CLOSED outcomes at sign-off, and an unknown/future enum member must never arm an advisory. | `validate_run.py` — a bare `print` touching neither problem sink ⇒ **exit-neutral by construction**, so it can move no exit code and newly RED no archived run (the witness `2026-07-05_143454` U09 keeps its verdict). **NOT** gated on `validator_version` (stdout is its only channel; `init_run.sh` stamps once at scaffold, so a gate would not arm on the run authoring it) and **NOT** `--quiet`-gated (§9-R12). Whitelist is doctrine, not tuning: over all 18 of this repository's `.wip/` run dirs (17 archived + this in-flight run) it selects the **same two units** as the broader form, so it buys no silence. Fixtures `i47_ledger_desync_note` / `i47_ledger_desync_control`. Limitation: it names a **documentation** defect only — it neither infers the correct label nor re-checks the verdict, and the opposite lie (a terminal label with no verdict behind it) is I2's G4, untouched. **PRESERVES** Claims A–D, AO-1..AO-7 and I1..I46. |

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
(persona-distinctness: `executor_persona != verifier_persona` per graph.json unit); **I1c
artifact/declaration persona reconciliation** (a unit with both artifacts: `debrief.persona ==
graph.executor_persona`, `verify.verifier_persona == graph.verifier_persona`, and the two artifact
personas DISTINCT — WP-B/C1); **I1d roster membership** (every working executor/verifier/panel persona
∈ the confirmed `personas.json` roster — WP-B/C2);
**I9/I10 missing-verification + synthesis-completeness rejection** (I10 iterates the graph.json
units at P8/DONE so a unit cannot be hidden by deleting its debrief — BRK-02, scoped to runs that
materialized the `units/` tree; I9 also rejects a verify-without-debrief — IMP-17); **G-brief offline
presence** (a unit dir carrying a debrief/verify but no `brief.json` fails at any phase, and — for a
run that materialized the `units/` tree — every graph unit needs a `brief.json` at P8/DONE — BRK-03;
these are the offline counterpart of T8/G-brief); **I2
ledger-is-truth** (an absent `fsm-state.json` alongside other run artifacts fails — IMP-17); I4 (loop bound + cross-check); I5 (budget); I6 (FAIL⇒defect∈brief-criteria,
PASS⇒no blocker/major defect — the coverage-first REVISION, PR1); I7 (single recommended); I8 (open-material); **I-dod** (DoD/non-goals
presence, artifact-triggered — fail-closed even when `clarifications.json` is absent);
**I11 tag-vocabulary
membership** (over `V_tag_eff` = run-local ∪ global registry — 04/G1); **I12 learnings-propagation
predicate + admission gate** over the three selector kinds `all` | unit-id | `tag:T` (an unknown kind
hard-FAILs — BRK-08; with the 04/G1 authored-vs-imported carve-out); **I13 socratic-counter
outcome shape**; **I14/I15 post-hoc anti-oscillation** (AO-2 `do_not_touch` disjointness / AO-6
responsive-change, offline over the retry `debrief` echo — 02/P1, 02/P2); **I16 panel discipline**
(high-stakes⇒panel present with the distinct correctness/reproduce/guardrail lenses; discrete-majority
aggregation — a split⇒DISAGREE, no softmax; `verify_rounds`∈[1,3] — post-hoc/offline, PR1); the `premise_check`
attestation; **the verify `disagreement` iff** (present ⟺ verdict==DISAGREE — both directions now
schema-enforced, the ⇒ direction via a `not` clause added PR-6/N-06); gate-ordering of
`fsm-state.phase` vs `gates` (REQUIRED_GATES — including **`signoff_confirmed` required at `DONE`**,
the G-signoff sign-off gate, D-06); and the `const:false` shape of I1; and — for **Bounded Graph
Amendments** — **I3b** wave layering + **I3c** dependency closure (run whenever a graph is present),
**I17** frozen executed prefix, **I18** fuel bound (`fuel_remaining == fuel_initial − Σ fuel_cost ≥ 0`
plus the revision/`amendments_applied` bookkeeping), and **I19** amendment scope (`dod_refs` verbatim ∈
`definition_of_done`, human-gate on scope_change/cancel, split coverage) — all post-hoc/offline, **none
a live transition guard** (the 02/P1 deadlock lesson).

For **guardrail enforcement (1.8.0)** it also enforces — same posture: post-hoc/offline, none a live
guard: **I20/I21** per-unit `dod_refs`/`non_goal_refs` binding (adoption-closure + verbatim membership
+ the graph↔brief mirror; `[]` legal for I21 only, as the explicit none-applicable statement),
**I22** the verify-time `guardrail_compliance` block (closure over verdict-bearing verifies, verbatim
membership, `non_goal_refs` coverage, and the decidable violated-row-on-PASS rejection), **I23**
P8/DONE closure (every DoD item covered by a PASS-verified unit's `dod_refs`, every non-goal attested
`respected`/`not-applicable` by a PASS unit — under the I10 phase gate + adoption), **I24** the
ambiguity-register floor (I-dod trigger family: structural work + empty register ⇒ FAIL), and
**I25** resolution-required on `material`+`resolved:true` register items (schema conditional +
raw-parse validator mirror with a `.strip()` bar).

For **depth & retrieval enforcement (1.9.0)** it also enforces — same posture: post-hoc/offline,
none a live guard: **I26** the sources register (structural trigger, fail-closed presence,
disposition completeness, venue admissions, coverage-basis membership), **I27** the
clarification sweep (nine-dimension exact-once coverage, disposition presence, cartography-round
record, resolution_source visibility, spot-check presence), **I28** depth-tier recording + floor
conformance (adoption-gated on fsm-state.depth; unconditional Phase-2 touch; ratchet
monotonicity with per-unit time-scoping; canonical skipped-floors completeness;
probe/sweep/register/panel floors; external-surface consistency), **I29** execution-effort
briefs (owed-entry shape, register linkage, CB-1 bridge presence, explicit-none, queued-consumer
closure), **I30** retrieval-coverage verifies (owed_check totality + recomputed coverage
arithmetic, PASS-with-uncovered contradiction, probe floor, target-list superset,
consulted/unreachable joins), and **I31–I34** = RL-1 rung presence / RL-2 parametric-downgrade
consistency / RL-3 premise extraction / CO-1 per-entry owed coverage (evidence-standards.md
§Source tiers is the doctrine home).

For **socratic-guardrail enforcement (1.10.0)** it also enforces — same posture: post-hoc/offline,
none a live guard, none a guard on LT7: **I35** dialogue transcript presence/shape/coverage
(version-gated T1 presence @1.10.0 + T2 adoption shape over the NEW `dialogues.json`; `rounds_used ≤ 3`,
per-instance mandatory kinds, literal-`a` answers), **I36** dialogue disposition & presentation-bind
(the three-arm union, `maxItems:4` anti-stuffing, the I36-1b recommended-echo counter-join, forbid-residue
+ register-row coverage; `N-I36` rubber-stamp NOTE), **I37** dialogue termination & probe accounting
(enum + conditional payloads, rung-choice legality with the human-early carve-out, instance closure with
license injectivity), **I38** ask-first consequential-default legality (`CC` = dimension ∨ content-linkage,
materiality-blind; loud declared halt; split `_t1`/`_t1h`/`_t1v`/`_t2` trigger; I8 and I27 carried
byte-untouched), **I39** anchor confirmation/provenance/baseline integrity (fail-closed `item_confirmations`
+ immutable-`anchors_baseline` replay vs a coordinated rewrite, the I17 baseline pattern; GV-29 REVISES the
clarifications artifact contract for new runs only), and **I40** anchor mutation gating (`revise_anchors`
always human-gated, fuel cost 1 / fuel-0 unwritable with **I18 carried VERBATIM**, ref-reconciliation, the
GV-16 membership-union `current ∪ retired` REVISES of I20/I21/I22, and the GV-25 narrowing of I19
`add_units` autonomy); **I41** panel dissent accounting & adjudication (a mechanical 2-1 majority may not
absorb a member's own blocker/major; the dissenter may not be re-polled) and **I42** evidence digest
integrity (a recorded `sha256` over a run-relative input must still match). Every I35–I42 predicate is an
OFFLINE post-hoc check over emitted artifacts — none
writes `retries`/`fuel`, gates a transition, or guards LT7 — so Claims A–D, AO-1..7, I1–I34, and the TLC
`Termination`/`Quiesce` + Alloy properties are **PRESERVED**; the REVISES set (DP-39 anti-theater, GV-29
artifact contract, GV-30 `revise_anchors` kind, GV-16 membership-union, GV-25 `add_units` narrowing, GV-31
P4 touchpoint, AF-41 §5 doc-repair, **the AO-5 bounded-re-poll doctrine (I41)** and **the I16 verify
artifact contract (I41)**) is confined to artifact-contracts, invariant enumerations, and prose
doctrines, each with a migration argument (formal-classification.md).

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
- **F.** Whether I14/I15 **authoritatively** enforce AO-2/AO-6. **Presence is now schema-required on
  retries (PR-6/IMP-05):** `debrief.schema.json` mandates the `prior_feedback` echo — with non-empty
  `changes_made` and a present `do_not_touch` — on `iteration>=2`, so a retry can no longer EVADE the
  checks by omitting the block (the former presence-gate hole; see the `retry_no_echo` fixture, and
  `ao6_no_changes` for the omitted-`changes_made` case). What remains self-reported: I14 compares the
  executor's **self-reported** `do_not_touch` echo — NOT the authoritative prior verify, since the
  validator retains only the *latest* `verify.json` per unit (no per-iteration verify history to
  reconstruct); and the *content* of `changes_made` is executor-attested. So the schema+checks now
  enforce *presence/plumbing* authoritatively, but not the *genuineness* of the echoed content
  (validity ≠ correctness); the independent verifier stays the semantic backstop. (Learning L1.)
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
- **I.** (BGA) Whether a `human_gate` on a scope-change/cancel was a **genuine** human decision.
  `amendment.human_gate == true` (I19) is a **presence-checked attestation** — like
  `signoff_confirmed` / `personas_confirmed` — not proof a human approved (validity ≠ correctness, the
  A/D boundary).
- **J.** (BGA) Whether an amendment's `frontier_wave` reflects the **real dispatch frontier**. WP3 gives
  it internal-consistency teeth (every `units_added` lands at `wave ≥ frontier_wave`, I18), and I17's
  content anchor (WP4) pins every executed unit's `wave`/`deps`/etc. against its immutable `brief.json`;
  but the validator still cannot reconstruct dispatch *timing* from artifacts, so `frontier_wave` as a
  claim ABOUT that timing remains attested. (The two former faith surfaces this limitation used to also
  cover — expansion-fuel integrity, B4, and ops↔graph reconciliation, B2/B3 — are now mechanical: WP2's
  fuel seed anchor + chain, and WP1's baseline reconciliation.)
- **K.** (BGA) Whether a new/split unit **genuinely serves** its cited `dod_refs`. I19 checks verbatim
  **string membership** in `definition_of_done` (decidable), not semantic traceability — that the added
  work actually advances that DoD item stays the verifier/critique-pass backstop (the same shape as E
  for tags).
- **L.** (guardrails 1.8.0) Whether a `guardrail_compliance` row is **true**. I22 checks the block's
  presence, shape, verbatim membership, `non_goal_refs` coverage, and the one decidable semantic
  clause (a `violated` row on a `PASS` verdict ⇒ FAIL); whether a `respected`/`not-applicable` row
  genuinely reflects what the unit shipped stays **verifier attestation — presence, not genuineness**
  (enforcement of the row's truth would be theater, D2). The same boundary covers the whole family:
  whether a unit *genuinely serves* its `dod_refs`/`non_goal_refs` (I20/I21 check verbatim string
  membership — the K shape), and whether `resolution` text *genuinely resolves* its ambiguity (I25
  checks non-empty presence). The independent verifier stays the semantic backstop.
- **M.** (guardrails 1.8.0) **Vacuous-text residual (R1/F5):** a run may still write a one-item DoD
  like `["done"]` and bind every unit to it — I20/I23 then pass mechanically. Text quality is
  undetectable without NLP, which the validator deliberately excludes (the G2 boundary; D3); the
  linkage at least makes vacuous items **load-bearing, visible strings** that PASS units must
  verbatim-carry and P8 closure must account for.
- **N.** (guardrails 1.8.0) **All-minor-materiality dodge (R2):** materiality is self-declared, so a
  run may mark every register item `materiality:"minor"` and I25's material-only conditional never
  binds — an F7-style fake resolution on a de-facto-material item escapes mechanically (the same G2
  boundary as M). Deliberately NOT closed by requiring `resolution` on minor items (that would punish
  legitimately-open minors and violate the strengthen-only-where-motivated discipline); the honest
  posture is this documented residual.
- **O.** (guardrails 1.8.0) **Adoption-boundary residuals (plan-owned):** (i) *fully-lazy run (D1):*
  a new run that adopts none of `dod_refs`/`non_goal_refs`/`guardrail_compliance` stays green —
  unconditional requiredness would either retro-fail every archived run or need a
  `validator_version` branch (both forbidden); adoption-closure + scaffolded templates are the
  maximum ratchet available under those constraints. (ii) *Graph-only adoption asymmetry:* adoption
  triggers on `graph.json` units — a `brief.json` carrying `dod_refs`/`non_goal_refs` while no graph
  unit does fires nothing (spec-faithful: inherited from the plan's pseudocode). (iii)
  *Non-dict-brief mirror-skip:* a `units/<id>/brief.json` that parses to a NON-object skips the
  I20/I21 mirror clause — no green path exists (the schema separately FAILs non-object briefs), but
  the mirror clause itself will not name it. (iv) *Perpetually-pre-P8 dodge:* a run that never
  advances its recorded phase to P8/DONE is never bound by I23 — REQUIRED_GATES and I23 gate
  reached-phase artifacts, not progression; nothing mechanically forces a run to ever reach P8.
- **P.** (depth 1.9.0) **Register truthfulness:** I26 proves a sources register has SHAPE —
  rows, dispositions, dates, venue rationale, coverage linkage — never that a `consulted` row was
  genuinely read (the validator opens no locator — the B boundary), that a tier tag is honest,
  that a coverage claim's basis is RELEVANT to its area (check 6 tests membership, not relevance
  — the M shape, flagged by the monoculture NOTE), that the sweep was ADEQUATE (a
  thin-but-well-formed register passes), or that dispositions predate the clarification round
  (single-snapshot posture: append-only and no-restamping are discipline; git history is the
  only mutation witness and nothing mechanically reads it). Backstops: the verifier's target
  list — brief-cited rows, owed rows, coverage-lineage rows, orphan sampling (≥1 consulted row
  per coverage area at P8), and the queued-heavy sampling rule; coverage `gaps` are load-bearing
  visible strings read at the cartography-informed clarification round; criterion-intersecting
  `queued` rows convert to owed work via claims_owed derivation.
- **Q.** (depth 1.9.0) **Sweep genuineness:** I27 proves the nine-dimension sweep has COVERAGE
  and disposition PRESENCE — never that a recorded search happened, that `resolution_source:
  "human-gate"` is truthful (it must trace to a DECISIONS.md gate entry — verifier judgment,
  Limitation-B class), that a row's `dimension` tag is apt, or that nine bespoke-but-fake
  statements weren't authored (same honesty class as I13). Sub-items Q(i)–Q(vii) = U03 R-1..R-7
  (plan §5.8). Backstops: the SYMMETRIC recorded `sweep_spot_check[]` (presence checked by
  I27-10), the prescribed Phase-2 gate render (CS-E4), and the I27-6/-7/-11 NOTEs.
- **R.** (depth 1.9.0) **Depth-tier residuals** — romanette sub-items R(i)–R(vii) = U04
  DR-a..DR-g (plan §5.8 carries full text): (i) `stakes`/`reversibility` are attested prose,
  human-judged at the gate; (ii) owed-set derivation-breadth conformance is judgment; (iii) a
  probe record proves a probe was CLAIMED with an outcome, not performed; (iv) a human can be
  talked into `light` at the initial gate — the unconditional Phase-2 touch (I28-P1b) is the
  mitigation, not a proof; (v) executor-authored inputs to the probe floor; (vi) backfill
  (records written late, G-personas attestation class); (vii) no-downward rigidity — a
  genuinely over-tiered run burns tokens, never correctness.
- **S.** (depth 1.9.0) **Effort-enforcement residuals** — S(i)–S(viii) = U05 R-1..R-8 (plan
  §5.8): (i) attestation boundary — the sample proves spot-checkability, not totality; (ii) the
  dispatched tool set is not an emitted artifact; (iii) owed-entry subject-match is judgment;
  (iv) derivation adequacy of O1–O4 sweeps is judgment; (v) falsifier-scope narrowing (items
  c–e recorded, not validator-forced); (vi) locator↔register matching is judgment; (vii)
  zero-adoption silence (no brief adopts ⇒ I29/I30 silent); (viii) bridge verbatimness rests on
  the normalized comparison + quote-source rule.
- **T.** (depth 1.9.0) **Retrieval-standard residuals** — T(i)–T(vii) = U01 R-a..R-g (plan
  §5.8): (i) a declared `live-fetch` genuinely read the page is attestation (the B boundary);
  (ii) RL-1 proves a rung was DECLARED, not that higher rungs were genuinely attempted; (iii)
  K-A/B/C venue answers are attested; (iv) O1–O4 application is judgment — a thin owed set
  passes; (v) `accessed`/original-fetch dates are self-reported (Limitation C class); (vi)
  premise-extraction adequacy; (vii) the confidence downgrade is mostly informational.
- **U.** (socratic-guardrail 1.10.0) **Dialogue genuineness:** I35/I36/I37 prove the transcript has
  SHAPE, coverage, disposition bijection, and termination bookkeeping — never that a human actually
  spoke, that `q`/`a` are verbatim-faithful, that `move`/`moves_used` are truthful, that the R-FORBID
  battery was task-tailored rather than boilerplate, that a bulk-confirm was genuinely considered, or
  that a **DP-31 disjunct-2 `draft_edits` pairing** (`amendment` a verbatim substring of `a`) reflects a
  GENUINE edit rather than a one-click echo (I36-1b mechanizes disjunct-1's recommended-echo laundering;
  the disjunct-2 echo case stays here); MC-4's R-FORBID "new-scope" re-pose owedness and the DP-49 P7-arm
  license are likewise attested. Backstop: the independent verifier + the human at the gate who LIVES the
  dialogue + the `N-I36 (rubber-stamp signature)` NOTE (validity ≠ correctness, the I13 class).
- **V.** (socratic-guardrail 1.10.0) **Recompute substrate honesty:** the deviation recompute, the
  rung-legality arithmetic, and the DP-31 origin bind are only as honest as the literal `a`/`recommended`
  fields and the recorded round indices they read — an UNRECORDED trigger is invisible to every
  rung/probe check (I37), so rung legality proves a probe was *accounted-for on the record*, not that
  every owed probe was recorded. Backstop: the verifier; the recompute over-fires toward MORE probing
  (the safe direction), so the residual is under- not over-enforcement (validity ≠ correctness).
- **W.** (socratic-guardrail 1.10.0) **Ask-first semantic remainders (R1–R8):** I38 proves
  consequential-default LEGALITY mechanically, but the semantic remainders stay judgment — R1 dimension
  self-assignment; R2 human-presence behind a `round_ref` (round-recycling); R3 verbatim aptness; R4/R6
  provenance completeness, silent non-registration, and mis-attribution; R5 materiality self-declaration
  (the material-non-consequential NOTE tier); R7 an unmarked silent stop; and **R8 completion-evidence
  withholding — the unclosable forged-halt window** (a run can withhold the evidence that would prove
  work remained). Backstop: the verifier; the SS-7 gate render; the AF-43 NOTE structural-artifact count
  is only a PARTIAL R8 handle (validity ≠ correctness).
- **X.** (socratic-guardrail 1.10.0) **Anchor transcript-file integrity (the GV-34 honest scope):**
  I39-3(d) anchors the list↔record reconciliation to the IMMUTABLE `anchors_baseline`, so an
  uncoordinated hand-edit and even a same-file coordinated list+record rewrite are caught (the I17
  `baseline_units` pattern). What is NOT caught is a COORDINATED rewrite that ALSO rewrites the baseline
  itself — `item_confirmations` (in `clarifications.json`) + `anchors_baseline` (in the transcript) + its
  hash + the join's per-item texts — spanning two/three run-dir files under the single-snapshot posture
  (Limitation P: git history is the only mutation witness, and nothing mechanically reads it). This
  channel is therefore **narrowed — closed up to transcript-file integrity — NOT "Closed"**: coordination
  cost rises from one file to two, and to **three when the optional `fsm-state.anchors_baseline_hash`
  mirror is present** — as of 1.10.1 that mirror is **CROSS-CHECKED by I39-7**
  (`gov_baseline_mirror_ok`/`gov_baseline_mirror_mismatch`): a present mirror MUST equal
  `dialogues.json.anchors_baseline.content_hash`, so a coordinated rewrite must now ALSO rewrite
  `fsm-state.json`. This still does **NOT "Close" X** — git history remains the ONLY mutation witness and
  nothing mechanically reads it — it only tightens the scope. A cheaper cross-linked dodge: an
  unstamped/below-ship run disarms the I35/I38-T1/I39-4 presence arms (version-gate NOTE-only) at zero
  coordination cost — backstopped by the execution-run scaffolded-stamping obligation (I39-7 itself is
  adoption-gated on mirror PRESENCE, so it fires even on an unstamped run once the mirror is written).
  Backstop: the verifier; the multi-file coordination cost; the I39-7-enforced hash mirror
  (validity ≠ correctness).

- **Y.** (cross-repo-lessons 1.11.0) **Panel dissent is observed only where it is WRITTEN (I41).** (i) A
  dissent that is **never recorded** — a lens that objects in conversation and whose `panel[]` row is
  written `PASS` — is invisible to every I41 clause. I41 raises the cost of laundering from "say nothing"
  to "write a false panel row"; it does not observe the panel. (ii) A dissent adjudicated in iteration *k*
  and overwritten by iteration *k+1*'s fresh panel is unrecoverable — the validator retains only the
  LATEST verify per unit (the Limitation F/L1 data-availability boundary), and AO-7 re-panels afresh, so
  I41 judges the latest verify only. (iii) `tested_defect`, the `rationale`'s genuineness, and whether a
  re-poll was actually independent stay **attestation** — validity ≠ correctness. (iv) Disclosed narrowing
  of *panel-internal* blindness: `executor_reasoning_seen` stays `false` (a re-polled panelist sees another
  PANELIST's finding, never the executor's reasoning), but I41 makes explicit that panelists are not
  required to be mutually blind — already implied by node-internal `verify_rounds` ∈ [1,3]. **(v) NEW
  (1.11.0 iteration 3) — withdrawal by FINAL-VOTE REWRITE.** Because `panel[].verdict` holds the FINAL vote
  (I41-4d-i) and a self-withdrawal is only *expressible* as `resolution: "withdrawn"`, never required, a
  dissenter that rewrites its final vote to `PASS` and drops its `defects` — omitting `panel_adjudication`
  — arms **ZERO** I41 clauses and is byte-indistinguishable from a genuinely unanimous panel. Traced
  clause-by-clause: I41-1, I41-2(a)/(b)/(c) and I41-4c need a dissenting `panel[]` row; I41-3 needs a member
  `defects` entry; I41-4/5/6 and N-I41 need `panel_adjudication` or member `defects`. This is a DISTINCT
  channel from (i): (i) is a dissent *never recorded* and costs a false panel row, whereas (v) is a dissent
  *recorded then erased* and costs **nothing**, because the row it leaves behind is TRUE — so (i)'s
  "raises the cost of laundering to writing a false panel row" holds only within (i)'s own scope. No
  predicate closes (v) without a mandatory retention field, which the OPTIONAL-only schema rule forbids;
  the honest withdrawal is what I41 makes expressible and green (`panel_withdrawn_flipped`). Backstop: the
  verifier; the panel's own written record.
- **Z.** (cross-repo-lessons 1.11.0) **A digest detects DRIFT, not READING (I42).** A matching `sha256`
  proves the bytes are the same NOW; it does not prove the verifier ever read them, and a verifier that
  fabricates a digest from the current file passes trivially. Paths outside the run dir are not decidable
  from emitted artifacts at all and are recorded as an exit-neutral NOTE (I42-5) rather than guessed at.
  Backstop: the verifier; the panel; validity ≠ correctness.
- **AA.** (verify-repair) **Verification completeness is made LEGIBLE, never TRUE (I43/I44/I46).** I43
  is an equality between two *artifacts* (`verify.iteration == debrief.iteration`), so a repair loop
  that bumps **both** iterations without actually re-verifying satisfies it exactly: I43 detects
  **staleness**, never **genuineness**, and no emission text may imply otherwise. I44 proves a verify
  is *present, parseable, verdict-bearing and current* at sign-off — never that the verification was
  *performed*, that the panel was independent, or that the human at the gate read anything. I46 reads
  the verifier's own `converged` declaration and is therefore only as honest as that field; a verifier
  can simply omit it (identity to `False`, so absence never arms). The `accepted_incomplete` override
  is a *recorded human decision*, not a validator-proved fact: nothing checks that the rationale is
  true or that the maintainer was actually asked. Backstop: the independent verifier; the panel; the
  human at the gate; validity ≠ correctness.

### Verification currency — the escape-hatch class, worked member by member (verify-repair)

**The doctrine, in one line.** A unit is *verified* only while its aggregated `verify.json`
adjudicates the debrief on disk **now**; *mid-loop staleness is legal, staleness once the run claims
to be finished is not*, and `gates.signoff_confirmed: true` IS that claim (SKILL.md prime directive
8). An executor repair **invalidates** its prior panel: iteration *N*'s verdict adjudicates bytes
that no longer exist. Three shipped predicates and one NOTE make that legible, all post-hoc and
offline over emitted artifacts, none a live guard on any transition and none on `LT7`:
**I43 verification currency**, **I44 sign-off closure**, **N-I45 version-skew visibility**,
**I46 non-converged PASS**, plus the advisory **N-I47 ledger desync at sign-off** (DoD 6, shipped
1.12.0 — see the stale-label bullet under I44).

**Measured arming safety — the figure, its population, and the command that reproduces it.**
The predicates are **ungated** by `validator_version`, and the evidence for that is a measurement,
not an absolute. Measured **2026-07-30T03:11Z at tree `23c9962`** and re-derived **identically at
03:22Z on tree `1bf2626`** (the tree moved mid-repair; the figure did not), over **this repository's
own `.wip/` archive (18 run dirs, all 18 carrying `fsm-state.json`) and nothing else**. **The
population, stated exactly:** of those 18 dirs, **17 are archived and 1 is this repair run itself**
(`2026-07-29_183514_verify-repair-units`, phase `P6_EXECUTE_VERIFY`, `signoff_confirmed: false`), so
"18 archived runs" is an over-count of the archive by exactly one — and the one it over-counts is
**the live run, which is the single member this class deliberately carves out** (I43's `not
SIGNED_OFF` conjunct, the in-flight window). Counting it inside a false-positive tally counts a member
that structurally *cannot* supply that evidence, which is why the archive figure below is scoped to
the **17**:

> **DATED FIGURE — superseded by this branch's own repair; read the current measurement below it.** As
> measured before the maintainer-waived re-verification, **1 of the 17 archived runs in this repository was
> newly RED** — `2026-07-29_090706_cross-repo-lessons-intake`,
> the branch's own **repair target** — carrying **8 hard FAILs**: `I43` on U05/U07/U08 (debrief 2/3/2
> vs verify 1/2/1), `I44` arm d (SUPERSEDED) on the same three, and `I46` on U03/U07.
>
> **CURRENT, measured 2026-07-30 over the same population: ZERO archived runs are newly RED, and no run
> in the population emits a class FAIL row of any severity.** That repair target now closes at
> `checks passed: 282 · problems: 0 · RESULT: PASS` with all nine of its units iteration-current, because
> this branch re-verified its U05 i2 / U07 i3 / U08 i2 under an explicit maintainer waiver (run ledger
> `DECISIONS#44`, extended `#46`). **The safety property therefore STRENGTHENS *a fortiori*** — zero is
> stronger than one — and what was lost is only the *illustrative instance*, which was consumed by being
> repaired. This is **not** a return to the retracted absolute: an earlier revision asserted "newly REDs
> ZERO archived runs" **before measuring**, and that retraction stands. This zero is reached *by*
> measurement, *after* discharging the exception. Both figures are kept, in order, because they are not
> the same claim. The figure is a property of a mutable gitignored directory and will move again;
> `tar cf - <dir> | shasum -a 256` is the cheap anchor that would make any such figure permanently
> checkable, which mtime-plus-file-count is not (`DECISIONS#50`). **Zero false
> positives:** no other run in the population emits an I43/I44/I46 **FAIL** row at all, so the other
> **16 archived runs are unaffected** (as is the 18th dir, this live run, which the in-flight window
> carves out by construction). *Newly RED* means every FAIL row on that run is an I43/I44/I46 row — it
> was green before these predicates. **The universal is about FAIL rows only, and deliberately so:**
> the class is far from silent elsewhere — `Report.ok` positive assertions fire on every
> iteration-matched pair, so **15 of the 18 dirs emit 6–18 class PASS rows** in the default
> (non-`--quiet`) invocation. Read "no other run emits a row" as "no other run emits a **FAIL** row";
> the materialization bullet below measures the same distinction from the other side (the 3 empty-tree
> runs emit **nothing at all**, not even a PASS row). Both figures re-measured **2026-07-30 at tree
> `35f44a0`** with the loop below, which prints one line per run dir:
> `for d in .wip/*/; do o=$(python3 plugins/dag/skills/dag/scripts/validate_run.py "$d"); echo "$d PASS=$(printf '%s' "$o" | grep -cE '^ +PASS +(I43|I44|I46) ') FAIL=$(printf '%s' "$o" | grep -cE '^ +FAIL +(I43|I44|I46) ')"; done`

```sh
# from the repo root; prints one line per newly-RED run
for d in .wip/*/; do o=$(python3 plugins/dag/skills/dag/scripts/validate_run.py "$d"); \
  n=$(printf '%s' "$o" | grep -cE '^ +FAIL +(I43|I44|I46) '); \
  t=$(printf '%s' "$o" | grep -cE '^ +FAIL +'); \
  [ "$n" -gt 0 ] && [ "$n" -eq "$t" ] && echo "NEWLY RED $d ($n rows)"; done
```

**Never state this as "zero", and never as a bare count.** The honest claim is that *zero
**legitimately-closed** archived runs are newly RED, and the one run that is, is the run this
pipeline exists to repair, on exactly the commissioned defect class* — a strong property, but a
weaker and different one than `0`. Publishing `0` was a **defect in those words**: it rested an
ungated arming decision on a number a checking reader would find false. **Scope, stated rather than
implied:** the population is this repository's `.wip/` archive; another installation's archive is a
different population and may yield a different figure — re-run the command against it rather than
assuming this number transfers. A version gate at the shipping release was **rejected** because
`init_run.sh` stamps `validator_version` once at scaffold time and never refreshes it, so the gate
would not arm on the run that authors the predicate. The arming decision is unchanged; only the
number is.

**The stamp census, PUBLISHED rather than merely deleted.** An earlier revision of this section
published "**8** distinct `validator_version` stamps" in this archive. That figure is **unreproducible
under every reading we could construct**, so it was deleted — but a deleted number leaves the next
reader with nothing to reason from (L16), so here are the measured ones, each with its population
**named**, all measured **2026-07-30 with the validator at tree `35f44a0`** over **this repository's
`.wip/` and nothing else** (`.wip/` is gitignored, so these counts are a property of the archive on
disk, not of the tree — the pin records which validator did the reading):

| population | dirs | distinct stamps |
|---|---|---|
| all `.wip/` dirs carrying `fsm-state.json` | 18 | **7** (`None`×9, 1.7.0, 1.8.0×2, 1.9.0×3, 1.10.0, 1.10.1, 1.12.0) |
| …the **archived** subset (excludes this live run) | 17 | **6** (drop 1.12.0, this run's own stamp) |
| dirs holding ≥1 co-present `debrief`/`verify` pair | 15 | **6** |
| …the **archived** subset of those | 14 | **5** (`None`×7, 1.7.0, 1.8.0×2, 1.9.0×3, 1.10.1) |

```sh
# from the repo root; prints the four denominators and their distinct-stamp counts
python3 - <<'PY'
import json, os, glob
LIVE = "2026-07-29_183514_verify-repair-units"          # this run; drop it for the archived rows
D = [d for d in sorted(glob.glob(".wip/*")) if os.path.exists(d + "/fsm-state.json")]
st = lambda p: {json.load(open(d + "/fsm-state.json")).get("validator_version") for d in p}
pair = lambda d: any(os.path.exists(u + "/debrief.json") and os.path.exists(u + "/verify.json")
                     for u in glob.glob(d + "/units/*"))
A = [d for d in D if LIVE not in d]
for name, p in (("all dirs", D), ("archived", A),
                ("pair-carrying", [d for d in D if pair(d)]),
                ("pair-carrying archived", [d for d in A if pair(d)])):
    print(f"{name:24} dirs={len(p):3}  distinct stamps={len(st(p))}")
PY
```

Prints `18/7`, `17/6`, `15/6`, `14/5`. **8 appears under none of the four**, which is why it is
retracted rather than re-scoped: it was not a mis-labelled axis, it was wrong.

**The iteration-parity census, kept narrow — and quoted as the ARCHIVED sub-figure only.** Separately
measured at the same tree over the **17 archived runs**: **159** co-present
`debrief.json`/`verify.json` pairs. **Historically** (before this branch's waived re-verification) **156
were iteration-matched** and the **3** mismatches were exactly the rows armed above — the repair target's
U05/U07/U08. **Currently, measured 2026-07-30: 159 of 159 are iteration-matched, 0 mismatched**, because
those three were re-verified with panels of three under the maintainer waiver. The earlier claim that
"those figures are stable because every run in them is closed" was FALSE: a run that repairs a defect
class invalidates its own published measurements of that class, so the honest artifact publishes the
decay law and a digest anchor rather than a sample (`DECISIONS#51`). An earlier revision published **168 co-present pairs across those 18 runs** — an
**archive-wide, in-flight-inclusive** total, and therefore the very thing the `verify_p*` paragraph
below forbids: it measures **173** today, having moved as this live run's own panels landed. That
census measures
**iteration equality only**, so it is *silent on I46*, whose field is `verdict == PASS ∧ converged is
False` — I46's own 2 FAILs (U03/U07) are an arming consequence of a **different** field and are
recorded here as such, not surveyed by the parity number.

**Domain, stated once.** The predicates read the **aggregated** `units/<u>/verify.json` only. They
never open `verify_p<N>.json`, because per-member files are a **per-iteration audit trail by design**
and legitimately lag their unit's debrief — **15** member files in `2026-07-18_101631` sit strictly
behind their own unit's debrief (U01 6, U02 6, U03 3; measured 2026-07-30T03:22Z on tree `1bf2626`),
and that run's U01 holds `verify_p1..p9`: three rounds of three lenses across iterations 1–3,
numbering **continued** rather than overwritten, with the aggregated verify current. A freshness check
over those files would RED-flag the best audit trail in the archive. **Quote the archived sub-figure,
never the archive-wide total:** the total moves while any run is live (measured 39 behind of 175 at
03:11Z, 45 of 175 eleven minutes later, as this run's own panels landed), whereas the
`2026-07-18_101631` figure is stable because that run is closed. An earlier revision published
"27 of 133 … 18 of them in `2026-07-18_101631`"; **both** numbers were wrong — the sub-figure was
never 18, and the total was a moving target quoted as a constant.

**Closed by currency (I43).**
- *Superseded verification* — U05 of the motivating run: `debrief.iteration: 2`, aggregated
  `verify.iteration: 1`, `verdict: PASS`. Every presence and verdict test passes; only the equality
  catches it. Outside the in-flight window this is a hard FAIL whose detail names both iterations,
  the direction, the fsm unit status, the phase and `signoff_confirmed`.
- *Fabricated bump (`AHEAD`)* — `debrief.iteration: 1` under `verify.iteration: 2`. A hard FAIL
  **outside the in-flight window, and only there**: `LT7` increments the counter *before* the next
  `EXECUTE` writes its debrief, so at every legal point the debrief is at or ahead of the verify,
  never behind it. This arm is what closes the "author the number instead of observing it" direction.
  **The in-flight carve-out applies to AHEAD too — measured, not inferred.** Arm P1-b carries
  `and not _i43_inf`, and the NOTE arm P1-d tests a bare `!=`, so it is **direction-blind**: an AHEAD
  pair *inside* `P6 ∧ executing|verifying ∧ ¬signoff_confirmed` emits an exit-neutral
  `N-I43 (in-flight)` NOTE with `RESULT: PASS` and exit 0 — and under the `--quiet` SKILL.md mandates,
  **nothing at all**, because P1-d's print is quiet-gated. Repro (2026-07-30, tree `1bf2626`): copy
  `tests/i43_inflight_before_signoff`, set `debrief.iteration: 1` / `verify.iteration: 2`, leave
  phase `P6_EXECUTE_VERIFY`, unit status `verifying`, sign-off unset ⇒ `NOTE N-I43 … (in-flight)` +
  `RESULT: PASS`; add `--quiet` ⇒ zero I43 rows. So **repairing under a live verifier is a doctrine
  violation the validator does not catch**, not a hard FAIL — filed as the unpinned residual it is
  (no fixture covers AHEAD-inside-the-window; `i43_ahead_of_debrief` sits at phase `DONE` with
  sign-off true, i.e. off-window). A second-order defect rides along: P1-d's own text says the unit
  "legitimately carries a verify one iteration behind" while in this arm the verify is *ahead*.
  Closing either would mean editing a shipped predicate, which this pass does not do.
- *Retries under-count, transitively* — a run whose `retries` counter under-reports the repairs it
  actually performed leaves the artifact pair mismatched, so I43 fires even though I4's ceiling
  (`iteration ≤ retries+1`) is untouched. I43 never reads `retries`: it is an equality between two
  artifacts, orthogonal to a bound between an artifact and a counter.
- *The legal transient it must NOT touch* — at every compliant `RETRY`, `debrief == N` while the
  newest verify still attests to `N−1`. I43 downgrades to an exit-neutral `N-I43 (in-flight)` NOTE
  inside `phase == P6_EXECUTE_VERIFY ∧ status ∈ {executing, verifying} ∧ ¬signoff_confirmed` — I9's
  window **plus** the third conjunct. Without the window the predicate
  would halt a compliant orchestrator at every retry (the `LT7` hazard class); without the third
  conjunct it would be **inert on the very run that motivated it**, whose three stale units are all
  `verifying` at P6 and whose NOTEs `--quiet` suppresses.
  **Citing the twins — by conjunct, because line numbers drift.** The two pre-existing window sites
  are I9's missing-verification arm (`phase == "P6_EXECUTE_VERIFY" and _st in ("executing",
  "verifying")`) and its I42-3 digest twin, which is keyed on the **path owner's** status
  (`_st42`) rather than the verify's own unit. Locate them by predicate, not by offset:
  `grep -n 'phase == "P6_EXECUTE_VERIFY"' validate_run.py`. Measured 2026-07-30T03:22Z on tree
  `1bf2626`: I42-3's twin at **`:5633`**, I9's window at **`:5673`**. Both are **byte-untouched** by
  the currency landing (the third conjunct lives in I43's own block; nothing was hoisted). Treat the
  offsets as a dated observation, never as an identifier: an earlier revision published `:5594`/`:5554`
  — neither of which ever matched, `:5554` not even the validator's own contemporaneous comment — and
  the correct pair moved **twice in eleven minutes** during this very repair (`:5610`/`:5650` at tree
  `23c9962` → `:5633`/`:5673` at `1bf2626`) as a sibling inserted lines above them. The conjunct text
  is the durable anchor; the residual hoist-to-a-shared-constant is still open (DECISIONS#20).

**Closed by closure (I44, antecedent `signoff_confirmed is True`, phase-independent).** Each arm is a
hard FAIL, downgradable only by the recorded override below.
- *Absent verification at sign-off* — a unit dir with `debrief.json` and no `verify.json` while the
  flag is true. Fires at P6 as readily as at DONE: the motivating run rolled P8 → P6 back **with the
  flag still set**, so any phase-gated formulation is inert on it.
- *Sign-off ahead of closure* — the superseded case again, now under the flag: I44's own
  `not CURRENT` arm, so the defect is reported against the sign-off claim rather than only against
  the pair.
- *Unusable / verdict-less verification* — a `verify.json` that is not JSON, not schema-valid, whose
  `unit_id` does not match its directory, or that carries no `verdict` key at all. Absence and
  unusability are the same attack; neither is read as "nothing to check".
- *`DISAGREE` parked at sign-off* — an exit-neutral `N-I44` NOTE, deliberately **not** a FAIL: a
  `DISAGREE` is a *complete* verification act declaring irresolvability, whose sanctioned exit is
  `LT6 → ESCALATE →` Phase 7, a human gate, not more verification. Failing it would also pressure a
  verifier away from `DISAGREE`, attacking AO-5 from the incentive side. Promotion needs a census
  first (below). **Measured quiet posture — do not read "recorded NOTE" as "visible":** arm (e)'s
  print is `--quiet`-gated, so under the invocation SKILL.md mandates the row does **not** appear.
  Measured 2026-07-30 on tree `1bf2626` (fixture `i43_current_positive` with `signoff_confirmed: true`
  and U01's verify rewritten to `verdict: DISAGREE` + the schema-required
  `disagreement.why_unresolvable`): default invocation ⇒ 1 `N-I44` row; `--quiet` ⇒ **0**.
  Exit-neutrality is confirmed either way (arm (e) adds nothing to the problem sink and `continue`s),
  so the gap is **visibility, not severity**. It is a live inconsistency with the un-gating already
  applied to `_vc_override_note`, N-I45 and N-I47 for the §9-R12 reason ("un-gate a NOTE exactly when
  stdout is its only channel") — and a `DISAGREE` at sign-off has the *stronger* claim, being the one
  state that routes to a human Phase-7 gate. Filed as an open residual: closing it is one guard plus a
  fixture mirroring `i44_override_quiet_visible`, and until it lands this bullet is the boundary.
- *A **current** `FAIL` at `retries == 2`* — **not** an arm, and pinned by a GREEN control. Complete
  means *current*, not PASS; demanding PASS would be unsatisfiable for every escalated unit and would
  pressure a run to manufacture one.
- *Ledger desync at sign-off* — a `fsm-state.units[]` status of `executing` at `DONE` over a complete,
  iteration-matched pair (`2026-07-05_143454`'s U09). I44 is keyed on **artifacts, never on status
  labels**, precisely because status-keyed formulations newly RED 3 archived runs for cosmetic desync
  while catching nothing extra. A stale label is a documentation defect, so it is carried by a
  **separate** predicate rather than folded into I44 — and that predicate **now ships** as the advisory
  **`N-I47` ledger desync at sign-off** (DoD 6, plugin 1.12.0). Sequence matters here: until 1.12.0 this
  sentence described a predicate that did **not exist**, which made it the one place the doctrine
  promised a fifth member the code lacked. `N-I47` fires when all four conjuncts hold —
  `signoff_confirmed` true **by identity**, the unit executed (I44's own
  `unit_dirs_with_debrief` domain), the verification **complete and current** (the exact negation of
  I44 arms a–d and I43-a/-b, so it never double-charges), and the status in the whitelist
  `{pending, briefed, executing, verifying}` (`escalated`/`retired`/`blocked` are closed outcomes, and
  an unknown future enum must never arm an advisory). It is a bare `print` touching neither problem
  sink ⇒ **exit-neutral by construction**, and it is **not** `--quiet`-gated, for the same §9-R12
  reason as `_vc_override_note` and N-I45. Verified on tree `1bf2626`: the witness
  `2026-07-05_143454`'s U09 (`executing` at `DONE` over a current PASS) emits the row under `--quiet`
  and that run's verdict is unchanged; fixtures `i47_ledger_desync_note` / `i47_ledger_desync_control`
  pin both arms. It names a **documentation** defect only — it neither infers the correct label nor
  re-checks the verdict, and the opposite lie (a terminal label with no verdict behind it) stays I2's.
- *Never-executed materialized unit at sign-off* — **out of I44's domain** (which is
  `unit_dirs_with_debrief`, i.e. *executed* units). Distinguishing a legitimately cancelled unit from
  an abandoned one requires reading `cancel_unit`/amendment records — judgment the measurement on
  file does not cover. I10 still covers it at P8/DONE.

**The recorded override — a FAIL becomes loud, not impossible.** On 2026-07-29 the maintainer was
offered further verification, declined it, and signed off knowingly. That decision must stay
**available** while ceasing to be **invisible**. A top-level `fsm-state.json.accepted_incomplete`
object carrying `units` (a list of ids), a non-blank `rationale`, and a `decision_ref` naming
`DECISIONS.md` (which must exist in the run dir) downgrades the FAIL of each **named** unit to an
exit-neutral `N-I44 sign-off closure (accepted-incomplete override)` row. Four properties are
load-bearing: it **downgrades, never suppresses** (the row is always printed and always greppable);
coverage is evaluated **per unit** with **no blanket form**, so an override that omits an open unit
leaves that unit a hard FAIL; a **present-but-malformed** override downgrades nothing and adds one
hard FAIL naming the first unmet condition (fail-closed); and a well-formed override naming units
that are no longer open emits an exit-neutral over-broad NOTE, so a stale override becomes visible
instead of accreting silently. `accepted_at`/`accepted_by` are optional and never read — no
attestation is invented. The same override applies, per unit and in one shape, to I46's FAIL arm.

**Newly authorized.**
- *Version-stamp suppression* — `N-I45 version-skew visibility`, an exit-neutral NOTE (a bare
  `print`, touching neither problem sink, so exit-neutral *by construction*). It counts the
  version-gated arms whose **non-version preconditions HELD** while this run's own stamp suppressed
  them, and says so: suppressed **arms** are an **upper bound** on suppressed FAILs — an armed clause
  may well have passed. It must never be reworded as, or reconciled against, the measured
  `stamp 1.10.1 → 0 problems / stamp 1.11.0 → 8 problems` figure: those 8 are *failures*, the count
  is of *evaluation gates*, and publishing one as the other is the wrong-mechanism defect. The NOTE
  fires loudly on unstamped archives (every comparison against an absent stamp is `False`), which is
  the version-skew policy's *"what would need to change to re-validate this run today"* made legible,
  and it can never change an exit code. Deliberate, labelled deviation: it is **not** `--quiet`-gated
  (SKILL.md mandates `--quiet`, so a quiet-gated skew NOTE would be inert in the only invocation that
  matters), whereas its closest sibling — the I39-4 governance NOTE — **is**.
- *Non-converged PASS* — `I46`: an aggregated `verdict: PASS` whose `converged` is **identically
  `False`** (absent, `0`, `""`, `null` never arm — that is what keeps it archive-silent). Worked:
  U03/U07 of the predecessor run stopped at the `R_max = 3` round cap and honestly wrote
  `converged: false` under a PASS, where the field was **dead data** — read by nothing. Severity is
  tiered exactly like I43/I44: an exit-neutral NOTE below sign-off (a verifier at its round cap is
  reporting honestly, and punishing an optional honesty field would create an incentive to omit it),
  a hard FAIL under `signoff_confirmed` (a unit whose own verification declares its coverage
  incomplete, at claimed completion, is verification left unfinished). The FAIL arm is a recorded
  fork: the intake wording says "flags", which is severity-neutral.

**RESIDUAL — worked, and each one a declared boundary rather than an oversight.**
- *Stop-at-P6 (Limitation O)* — worked example: a run leaves `phase: P6_EXECUTE_VERIFY`, three units
  `verifying`, never sets `signoff_confirmed`, and is simply abandoned. I43 emits only in-flight
  NOTEs (its window is exactly what is satisfied), I44's antecedent never fires, I46 stays at NOTE.
  **Not closable by any single-run predicate:** from the run dir alone, abandonment is
  indistinguishable from being mid-flight, and the carve-out that makes it undecidable is the same
  one that keeps a compliant orchestrator from deadlocking. That is the deliberate price. Closing it
  needs a cross-run or process convention (a staleness clock), which no per-run contract can hold.
- *Untagged solo verification* — worked example: a unit carrying **no** `high-stakes` tag is verified
  by a single verifier; `verify.json` has no `panel[]` at all. Legal by design (`panel` is optional
  and I16 requires it only on `high-stakes` units), and the currency predicates never count
  verifiers, so a run can systematically avoid panels by never applying the tag. Nothing in this
  class observes it; the backstop is decomposition-time tagging and the human at the gate.
- *Retire-and-delete* — worked example: a unit's `verify.json` says FAIL, so the orchestrator deletes
  `debrief.json` **and** `verify.json`, then retires the id through an amendment. Every predicate in
  this class keys on debrief PRESENCE (`unit_dirs_with_debrief`), so the unit exits every domain
  silently; I17's frozen-prefix check likewise keys on the artifacts being on disk, so a
  delete-then-retire looks like the legal retirement of an unexecuted unit. What survives is
  id-level: I17's reconciliation against the immutable `graph.json.baseline_units` still records the
  retirement, and `cancel_unit` is **always human-gated** — the backstop is a human seeing scope
  drop, not a predicate seeing the deletion.
- *Evidence freshness* — worked example: a verifier's `inputs_reviewed` lists a bare path string
  (`"units/U05/debrief.json"`); the executor then repairs that file. I42 re-hashes only elements that
  carry a `sha256`, and a bare string carries none, so nothing detects that the reviewed bytes are
  gone. `inputs_reviewed` is optional and its object form is a union **widening**, so a run can stay
  string-only forever and remain valid — and even a matching digest proves the bytes match *now*,
  never that anyone read them (Limitation Z). I43 catches the *iteration* consequence when the
  repair bumps the debrief; it says nothing about the evidence.
- *Unclosed `minor` defects at PASS* — worked example: `verdict: PASS` with two `severity: minor`
  defects and no record that either was fixed, waived or carried forward. This is legal and
  intentional (I6's coverage-first revision lets a PASS carry `minor` observations so recall is never
  suppressed), and no field expresses a minor defect's *disposition*, so there is nothing for a
  predicate to read. Closing it would need a mandatory disposition field on `defects[]` — a new
  required key on an archived artifact, which the optional-only schema rule forbids.
- *`DISAGREE` promotion* — deliberately parked as a NOTE (above). Promote only after a census returns
  zero: count archived runs with `gates.signoff_confirmed: true` holding an aggregated
  `verdict: "DISAGREE"` with **no** `units/<u>/disagreement.*` record —
  `grep -l '"verdict": *"DISAGREE"' .wip/*/units/*/verify.json`, cross-referenced against
  `signoff_confirmed` and `disagreement.json` presence.
- *Materialization* — **the trigger is an EMPTY `units/` tree, not an absent one.** Measured
  2026-07-30T03:22Z on tree `1bf2626` over all 18 of this repository's `.wip/` run dirs (17 archived + this in-flight run): **0 lack a `units/`
  tree** and exactly **3 carry an empty one** — `2026-07-05_170505`, `2026-07-06_110152`,
  `2026-07-19_082325`. Every predicate in this class iterates `unit_dirs_with_debrief` (I44's surplus
  arm additionally needs `unit_subdirs`, I46's `_i46_declared`), so an empty tree makes each loop body
  execute **zero times** and the whole class no-ops. An earlier revision published "4 of 18 archived
  runs have no `units/` tree"; the count *and* the mechanism were wrong, and the mechanism is what a
  reader reasons from (L16).
  **The mitigation this bullet used to claim does not hold — stated plainly.** It read "a
  silently-skipped domain cannot masquerade as a pass." It can. The positive assertions are emitted via
  `Report.ok`, which is `--quiet`-gated, and on the empty-units path they are **never reached at all**
  because each one sits *inside* the per-unit loop. Measured on all three empty-tree runs in the
  **default** (non-quiet) invocation: **zero** I43/I44/I46 rows of any kind — not a FAIL, not a NOTE,
  not a positive assertion. So this domain is exactly the silently-skipped one the old sentence said
  could not exist, and it stays filed here as the **residual** it is: distinguishing "the class ran and
  found nothing" from "the class never ran" needs a domain-level assertion outside the loops, which
  this pass does not add.
- *Genuineness, permanently* — **Limitation AA** above. Currency proves a verify is CURRENT; it can
  never prove it was PERFORMED.
- *Same-iteration edits, permanently under this predicate* — **Limitation AB, a hole in a predicate
  this release ships, stated rather than softened.** I43 compares `verify.iteration` to
  `debrief.iteration`. It therefore sees **rollbacks and fabricated bumps, and nothing else**: an edit to
  an already-verified debrief that leaves `iteration` **unchanged** is **invisible to it by
  construction**. The staleness I43 detects is a staleness *of numbers*, not of bytes.
  **This run produced the instance, in its own artifacts.** U15 repaired
  `units/U05/debrief.json` at **2026-07-29T21:42:07**, **47 minutes after** U05's aggregated
  `verify.json` closed `PASS` at **20:55:06**. Both sides still read `iteration: 1`, so the currency
  test passes — the validator emits the positive assertion
  `PASS  I43 verification currency (units/U05: iteration 1 verified)` — while U05's `PASS` vouches for
  bytes **no verifier ever read**. Reproduce with
  `stat -f '%Sm %N' -t '%Y-%m-%dT%H:%M:%S' units/U05/{debrief,verify}.json` inside that run dir, against
  the `iteration` field on each side. Note the shape: this is not a defect in I43's arms, all four of
  which are correct on their own field; it is the **field's own reach**. A same-iteration repair is also
  exactly what the Phase-6 rule "an executor repair invalidates its prior panel" exists to govern — so
  the doctrine covers this case while **the predicate does not**, and that gap is discipline, not
  enforcement.
  **A remedy exists and is NOT shipped.** Recording a `sha256` of each artifact before and after an edit
  (the digest machinery I42 already has) would make a same-iteration rewrite decidable from emitted
  artifacts. It is stated here as a **possibility, not as a shipped guarantee**: no predicate computes it,
  no schema requires it, and nothing in this release detects the U05 case above. Do not read this
  paragraph as a mitigation.
  **Same register as Limitation AA, deliberately:** these predicates make verification completeness
  *legible*, never *true*. AA names the loop that bumps both iterations without re-verifying; AB names
  the edit that bumps **neither**. Both satisfy I43 exactly.

### Version-skew policy — archived runs vs. the current validator (F1/WP-E)

The validator is **single-truth**: it always applies the CURRENT invariant set. It never
*downgrades or disables an earned check* by a run's recorded version, and never penalizes an
unstamped/archived run for a key it could not have carried (archive-silent). What the recorded version
DOES do is *arm* a small set of version-gated **new-run presence requirements** (I27-T1, I28, I39-4,
and the socratic-guardrail I35–I40 presence arms): each fires only on a run stamped ≥ its shipping
release and stays silent below it — the stamp gates no transition, it arms these new-run floors
(**AF-41 documentation repair, classified PRESERVES:** naming a posture the depth-1.9.0 I27-T1 arm
already shipped changes no guarantee — formal-classification §D). To keep that honest without
deadlocking old runs, `init_run.sh` stamps `fsm-state.json.validator_version` (F1(a); the OPTIONAL
schema field) with the plugin version that scaffolded the run, and this policy holds:

- **An archived run is judged against its CONTEMPORANEOUS validator.** When the current validator is
  run over a run stamped with an OLDER `validator_version` (or an *unstamped* pre-1.7.0 run), any new
  findings are **expected schema/invariant skew, NOT defects of that run** — the run was correct under
  the validator it shipped with. Read such findings as "what would need to change to re-validate this
  run today," not "this run was wrong."
- **The stamp gates no transition, but arms version-gated new-run presence requirements.** The stamp
  never gates an FSM transition and never penalizes an unstamped/archived run: an absent
  `validator_version` is judged exactly as before — `None`⇒False on every semver comparison, so legacy
  runs are never penalized for lacking it (archive-silent). What it DOES arm is version-gated **new-run
  presence requirements** (I27-T1, I28, I39-4, I35–I40): a run stamped ≥ its shipping release must carry
  the required artifact/key, while below-ship and unstamped runs stay silent. So the stamp both *labels*
  provenance (making future skew legible) AND *arms* those new-run floors — it does not merely label.
  **(AF-41 documentation repair, classified PRESERVES:** this corrects prose that predated I27-T1; the
  depth-1.9.0 I27-T1 presence arm already shipped this behavior, so naming it changes no guarantee — see
  formal-classification.md §D. Limitation X is NOT relabelled "Closed".)
- **Positive-evidence checks may newly flag archives — that is expected skew, not a defect.** The
  adoption-triggered guardrails-1.8.0 checks (I20/I21/I22/I23) are archive-silent by construction (no
  archived artifact carries the new keys), but **I24/I25 are NOT archive-silent**: like I-dod before
  them, they fire on what a run's artifacts positively show (structural work beside an empty
  register; a `material`+`resolved:true` item with no resolution text) — no `validator_version` read
  either way. An archived offender newly flagging under the current validator reads under this policy
  as expected skew — never edit the archived run, never backfill evidence it did not produce.
- **The stamp is REFRESHED on every phase advance, not only at scaffold time (U08).** `init_run.sh`
  writes the stamp when it seeds `fsm-state.json`, and `init_run.sh --restamp <RUN_DIR>` rewrites it to
  the current plugin version as part of the orchestrator's phase-advance bookkeeping (SKILL.md prime
  directive 1). Before this, the stamp was written **once** and never refreshed, which produced a
  self-reference defect: a run that AUTHORS an invariant kept its pre-release stamp for its whole life
  and was version-gated **out of being judged by the invariant it shipped**. Measured on the run that
  authored I41: flipping one digit of its stamp on otherwise byte-identical bytes turned
  `264 checks / 0 problems / PASS` into `264 checks / 8 problems / FAIL` — eight findings the authoring
  run's own new invariant would have raised against it. Re-stamping closes that: **a run that ships an
  invariant is judged by it.** Classified **PRESERVES** — this changes only *when* the stamp is
  **written**, never how it is **read**: no predicate and no arming logic is touched (`_i27_semver_ge`
  and every version gate reading it are byte-untouched), and the stamp still gates no FSM transition.
  **Archive safety, explicitly:** (i) the re-stamp path only ever touches the ONE run dir it is pointed
  at — nothing under an archive is rewritten; (ii) it refuses to write a blank/malformed value (an
  unresolvable plugin version leaves the file untouched), so an absent or malformed `validator_version`
  keeps the `None ⇒ False` reading on **every** semver comparison (`_i27_semver_ge` returns False unless
  BOTH sides parse) and no unstamped archived run is newly penalized; (iii) the stamp is a **ratchet** —
  only raised, never lowered — so validating a run under an older installed plugin cannot silently
  disarm a floor the run already armed. Fixture `panel_dissent_version_silent` continues to pin the
  archive-silent reading of a below-ship stamp.
- **Dogfood/self-runs in THIS repo are the exception** (see F3 / CLAUDE.md): they must be validated
  with the repo's own `scripts/validate_run.sh`, contemporaneously, so they are held to the current
  bar rather than an installed plugin's stale copy.
- Where a mechanical class of skew is cheaply fixable, a **clearly-labeled migration** may backfill
  archived runs (the 1.3.0 signoff-backfill precedent; WP-E F1(c) backfills `.wip/`) — never fabricate
  evidence a run did not actually produce (a missing artifact gets a dated annotation, not an invention).

## 6. Phase→state coverage (no orphan phases)
Every SKILL.md phase 0–8 maps to exactly one state (§1), with **one deliberately-unmodeled
sub-step: Phase 0.5 (learnings intake).** Phase 0.5 is a prose sub-step *within* `P0_BOOTSTRAP` —
it writes no gated artifact (its `learnings.json` is ledger bookkeeping, not a work-graph output),
adds no transition, and is validated only post-hoc (I12); T1's guard (INPUT.md exists) is unchanged.
It is intentionally not its own FSM state / schema enum value (full modeling would add a state with
zero enforcement value — see D-01).

Every **mechanical** gate maps to a §3 guard. **G-signoff** (Phase-8 sign-off) is now recorded as
`gates.signoff_confirmed` and **mechanically REQUIRED at DONE** (D-06) — like `personas_confirmed`,
its *presence* is validator-checked (its *genuineness* stays a human attestation, the §5 Limitation
pattern). That leaves **G-resolve** (T11 user-decides) as the **sole human gate outside the
mechanical guard set** — the validator cannot confirm a human picked a disagreement option. T12's
guard text names G-signoff and its `signoff_confirmed` flag explicitly. The Phase-6 executor↔verifier loop maps to the loop substate
machine (§1a/§2a, `EXECUTE·VERIFY·ADJUDICATE·RETRY·ESCALATE·DONE`). The as-needed Phase 7 maps to
`P7_DISAGREEMENT_GATE` (entered via T10 from an ESCALATE — a DISAGREE-origin escalation, a
retries-exhausted FAIL, or (BGA) amendment-fuel exhaustion; §1a — exited via T11). No phase, mechanical gate, or loop is unmodeled. **Sign-off (P8) remains a human gate** — the human
must accept the deliverable — but its flag `gates.signoff_confirmed` is now **mechanically required at
DONE** (D-06), so the validator checks the flag's PRESENCE (not its genuineness — the §5 attestation
boundary), exactly as it does `personas_confirmed`. G-resolve (T11, disagreement) stays the one human
gate with **no** mechanical flag the validator can check at all.
