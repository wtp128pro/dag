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
| **I39 anchor confirmation, provenance & baseline integrity** (socratic-guardrail 1.10.0) | Reads `clarifications.json.item_confirmations[]`/`anchors_retired[]` and the transcript `anchors_baseline` block. I39-1 forbid-round residue lands (GV-3). I39-2 `human_confirmed(x,L)` via the CURRENT (highest-index non-superseded) record with non-blank `transcript_ref`; duplicate-currency ⇒ FAIL; a re-opened round supersedes (GV-7/GV-35). I39-3 list↔record↔baseline reconciliation (a–d); clause (d) replays the POST-baseline record sequence forward from the IMMUTABLE `anchors_baseline` to reproduce the current lists — **dissent obligation 2:** anchored to the immutable baseline (the I17 `baseline_units` pattern) so a same-file coordinated rewrite cannot move the baseline it is judged against (GV-8). I39-4 fail-closed presence + **dissent 1:** on a ≥1.10.0 structural run an ABSENT `item_confirmations` ⇒ FAIL (GV-9); on a `_semver1` run with `clarification_resolved:true` an ABSENT `anchors_baseline` or self-inconsistent content hash ⇒ FAIL; UNSTAMPED runs disarm → advisory `NOTE N-I39 (governance disarmed; unstamped)`. I39-5 no unconfirmed anchor past the gate (GV-11). I39-6 baseline-anchored totality — any anchor delta not explained by an R1–R6 receipt ⇒ FAIL (GV-23). | `validate_run.py` post-hoc/offline (stem `I39 anchor`, NOTE stem `N-I39`); `item_confirmations` REQUIRED once `_t1` (version-gated, archive-silent below-ship), T2 adoption otherwise; gates no transition ⇒ **PRESERVES** termination (GV-28 — optional property, write-once snapshot inside the already-write-once transcript). **GV-29** (required-once-stamped presence) is a flagged **REVISES** of the clarifications artifact contract for NEW runs only (I25/I27-T1 class). Confirmation genuineness stays attestation (Limitation L); the coordinated multi-file baseline rewrite is Limitation X. Fixtures `gov_forbid_residue_lost`/`gov_dup_currency`/`gov_reclarify_supersede_ok`/`gov_recon_dangling`/`gov_coordinated_rewrite`/`gov_replay_ok`/`gov_no_item_confirmations`/`gov_missing_baseline`/`gov_bad_baseline_hash`/`gov_unstamped_disarm_note`/`gov_unconfirmed_past_gate`/`gov_unexplained_delta`. |
| **I40 anchor mutation gating** (socratic-guardrail 1.10.0) | Adoption-armed on `revise_anchors`/`item_confirmations` presence (the AF-25 pattern; archive-safe — no archive carries the kind). I40-1 every `revise_anchors` record carries `human_gate:true`+`transcript_ref` (no autonomous branch, any list/op — GV-13). I40-2 fuel cost `== max(1,0−0) == 1`; at `fuel_remaining==0` NO amendment record is writable (`fuel_after==−1` violates I18 ≥0) — **I18 carried VERBATIM** (GV-14/GV-36). I40-3 in-transaction ref-reconciliation (add refs on `propagation_targets`; edit REWRITES matching refs verbatim; remove drops refs except a unit whose sole `dod_refs` element is removed must be re-pointed or `cancel_unit`-paired; touched unexecuted briefs mirror-updated — GV-15). I40-4 **membership-union** — I20/I21/I22 accept `current ∪ anchors_retired[].prior_text`; a unit ADDED after a retirement (later record id) citing retired text ⇒ FAIL (GV-16). I40-5 added-item closure (GV-17). I40-6 any op on a `violated`-row-bearing NG routes to P7/ESCALATE, never a P6 gate; a `violated`-on-PASS stays a FAIL regardless (GV-18). I40-7 `scope_change` add residue (GV-21). I40-8 `add_units` autonomy narrowed — an `add_units` with `human_gate` absent/false whose every `dod_refs` element fails `human_confirmed(x, definition_of_done)` ⇒ FAIL (downgrade-laundering guard, GV-25). | `validate_run.py` post-hoc/offline (stem `I40 anchor`); adoption-armed any version; gates no transition ⇒ **PRESERVES per-unit** (GV-30 — Claims A–D untouched, no back-edge, adds no units, fuel cost ≥1 keeps events ≤ fuel₀); **I18 carried VERBATIM — no fuel REVISES**. Flagged enumeration-level **REVISES** (→ formal-classification): the `revise_anchors` kind-whitelist add (GV-30); the **GV-16 membership-union widening of I20/I21/I22 (`current ∪ retired`)**; the GV-25 narrowing of I19 `add_units` autonomy. `human_gate` genuineness stays attestation (Limitation I). Fixtures `gov_revise_ungated`/`gov_revise_fuel_cost`/`amend_fuel0_revise_unwritable`/`gov_revise_ok`/`gov_ref_recon_soleref`/`gov_ref_recon_briefdrift`/`gov_retired_membership_ok`/`gov_later_unit_cites_retired`/`gov_added_item_stranded`/`gov_revise_violated_target`/`gov_scope_change_no_confirm`/`gov_autonomous_unconfirmed_ref`/`gov_autonomous_confirmed_ok`. |

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
`add_units` autonomy). Every I35–I40 predicate is an OFFLINE post-hoc check over emitted artifacts — none
writes `retries`/`fuel`, gates a transition, or guards LT7 — so Claims A–D, AO-1..7, I1–I34, and the TLC
`Termination`/`Quiesce` + Alloy properties are **PRESERVED**; the REVISES set (DP-39 anti-theater, GV-29
artifact contract, GV-30 `revise_anchors` kind, GV-16 membership-union, GV-25 `add_units` narrowing, GV-31
P4 touchpoint, AF-41 §5 doc-repair) is confined to artifact-contracts, invariant enumerations, and prose
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
  cost rises from one file to two (three with the optional `fsm-state.anchors_baseline_hash` mirror). A
  cheaper cross-linked dodge: an unstamped/below-ship run disarms the I35/I38-T1/I39-4 presence arms
  (version-gate NOTE-only) at zero coordination cost — backstopped by the execution-run
  scaffolded-stamping obligation. Backstop: the verifier; the multi-file coordination cost; the optional
  hash mirror (validity ≠ correctness).

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
