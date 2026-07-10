<!-- state-machine.md — the FORMAL model of record for the dag pipeline
     (formal-enforcement layer for reqs 1/4/7/9/12; not req 2 — req 2 is clarification).
     Phase-6 loop substates use the loop's Q vocabulary + 7-row table; the socratic seam is
     the canonical 4-key block; invariants I9-I16 (+ I1b, I-dod) close the missing-verification
     and fail-closed-DAG validator holes, tags/learnings propagation, socratic-counter
     genuineness, the DoD/non-goals gate, and the post-hoc anti-oscillation (AO-2/AO-6) checks.
     Bounded Graph Amendments add five more post-hoc/offline checks (I3b/I3c wave-layering +
     dependency-closure; I17/I18/I19 frozen-prefix + fuel-bound + amendment-scope) — none a live guard.
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
| `P8_SYNTHESIS`        | 8 Synthesis        | SYNTHESIS.md        | linear |
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
> **`retries`** (0..2; authoritative: `fsm-state.schema.json` `loop.retries.maximum`) and
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
| **I2 Ledger-is-truth** | Current state = disk (`fsm-state.json` + markdown), never model memory only. The ledger may not LIE about the artifacts (WP5): a `units[]` status of `passed`/`failed` matches the unit's verify verdict `PASS`/`FAIL` and `loop.last_verdict` matches its unit's verdict (G4); every `fsm-state.units[]` id is a graph unit or a retired id (G10); and artifacts imply a phase floor — an executed unit ⇒ `decomposition_approved` ∧ phase ≥ P5, `SYNTHESIS.md` ⇒ phase ∈ {P8, DONE} (G5). | validator confirms `fsm-state.json` parses & is valid, plus the post-hoc ledger↔verify / units-subset / phase-floor cross-checks. Fixtures `no_fsm_state`/`ledger_status_mismatch`/`ledger_verdict_mismatch`/`fsm_phantom_unit`/`phase_underreport`. |
| **I3 DAG acyclic (fail-closed)** | The work graph has no dependency cycle; graph.json is authoritative. Unit ids are UNIQUE (WP5/B8 — a duplicate makes last-wins enforcement order-dependent). | validator: cycle on `edges ∪ unit-deps` + a `len(units) == len(set(ids))` uniqueness check; **GRAPH.md-present or post-decomposition ⇒ VALID graph.json REQUIRED** (unparseable/absent ⇒ non-zero exit). Closes E. Fixtures `unfenced_cycle`/`amend_cycle`/`dup_unit_id`. |
| **I4 Loop bound** | `retries ≤ 2` per unit (≤3 executions); `iteration ≤ retries+1`. | schema `maximum:2` + validator cross-check — applied to the top-level `loop` slot **and** (D-02/IMP-11) to every `fsm-state.units[]` item that records its own optional per-unit `retries` (label `I4 units[] cross-check`), so parallel-wave units are each bounded, not just the most-recently-transitioned one. Both are post-hoc/offline (no LT7 guard). |
| **I5 Budget cap** | Every brief/unit ≤ 32K tokens (PLAN-side). Report-side honesty is tied to the unit's OWN budget (WP5/G9): `debrief.footprint.tokens_consumed > brief.budget_tokens ∧ within_budget==true` ⇒ FAIL. | schema `maximum:32000` on `budget_tokens`/`est_footprint_tokens` (the plan-side ceiling — briefs/graph units still cannot *plan* >32K). **Report-side (PR-6/IMP-04):** `debrief.footprint.tokens_consumed` has NO maximum, so a real overrun is *reported* truthfully; a schema `if/then` forces `tokens_consumed>32000 ⇒ within_budget:false`, and a validator check (WP5) ties the honest-overrun signal to each unit's own `brief.budget_tokens` (not just the global 32K). Fixture `within_budget_dishonest`. |
| **I6 Evidence-bound verdicts** | FAIL names ≥1 defect, each citing a brief acceptance criterion, AND ≥1 NON-BLANK `feedback.actionable_changes` (WP5/G11 — `[" "]` is not actionable); PASS ⇒ **no blocker/major defect** (REVISED for coverage-first, PR1 — was `defects==[]`; a PASS may now carry `minor` observations: "report every finding + severity, filter downstream"). | schema `if/then` (FAIL⇒defects≥1 + actionable_changes items `pattern:"\\S"`; PASS⇒every defect severity==`minor`) + validator criterion-∈-brief cross-check + a `.strip()` non-blank actionable-change check + an I6-PASS defense-in-depth check. Termination-preserving: verdict enum + the §2 partition are unchanged (content-rule revision only). Fixture `fail_blank_actionable`. |
| **I7 Single recommended option** | A disagreement dossier marks exactly ONE option recommended. | validator counts `recommended==true`. |
| **I8 No open material ambiguity past P2** | Cannot advance past clarification with an open material item. | validator (clarifications extract). |
| **I9 Every debriefed unit is verified** | A unit dir with a debrief (`.json` or `.md`) MUST have a verify.json with a verdict. | validator presence check. **Closes D.** |
| **I10 Synthesis completeness** | At P8/DONE, every debriefed unit has verdict=PASS (none advances unverified/failed). | validator phase-gated presence+verdict check. **Closes D.** |
| **I11 Tag vocabulary** | Every unit/brief `tag` is a member of `V_tag_eff` (`graph.json.v_tag` ∪ the global registry `~/.claude/dag/tags.json` — 04/G1; absent/invalid ⇒ run-local `V_tag`). | validator membership check over `V_tag_eff`. **Domain widened by 04/G1 — Limitation G.** |
| **I12 Learnings propagation** | Every unit created no earlier than a learning E and matched by E's scope selector — `all`, a unit-id (`U0X`), or `tag:T` — lists E in `learnings_applied`. Admission is selector-kind ASYMMETRIC: `all` admissible iff ≥2 graph units, `tag:T` iff ≥2 units carry T, a `U0X` selector always (single-target). An unrecognized selector kind is a hard `I12 selector` FAIL (BRK-08); `phaseN` was removed as unevaluable (BRK-09). | validator decidable predicate + admission gate (see `self-learning-loops.md` §4.3). Imported entries are EXEMPT from the ≥2-carrier re-proof via the 04/G1 carve-out but still propagation-checked. The import carve-out (WP5/G8) requires GENUINE provenance — actual store membership OR an `origin.store` stamp — not the `G#` id spelling; a bare `G#`-id with neither FAILs `I12 import provenance` (fixture `learnings_forged_import`), so a run-local `L1` renamed `G7` can no longer dodge propagation. |
| **I13 Socratic counter records an outcome** | `debrief`/`verify` `socratic.counter` states an outcome, not a blank/"n/a" (mechanical sentinel allowed). | schema (4 keys + `confidence` regex) + validator counter-outcome check. **Shape only; genuineness = the independent COUNTER re-run (Limitation B).** |
| **I14 AO-2 do_not_touch disjointness (post-hoc)** | For a retry (`debrief.iteration>1`), `verify.defects[].criterion` is disjoint from the retry's `debrief.prior_feedback.do_not_touch`; a non-empty intersection ⇒ non-zero exit. | `validate_run.py` offline predicate (label `I14 AO-2 do_not_touch disjointness (units/<uid>)`), added ring-02/P1. Gates no transition. **Presence now schema-required on retries (PR-6); content self-reported — Limitation F (narrowed).** |
| **I15 AO-6 responsive change (post-hoc)** | For a retry carrying a `prior_feedback` echo, `debrief.prior_feedback.changes_made` is present and non-empty; else non-zero exit. | `validate_run.py` offline predicate (label `I15 AO-6 responsive change (units/<uid>)`), added ring-02/P2. Gates no transition. **Presence + non-emptiness of `changes_made` now schema-required on retries (PR-6)**, so this offline check is SUBSUMED for schema-valid retries and remains a degraded-mode (no-schema) backstop; `changes_made` *content* executor-self-attested. **Limitation F (narrowed).** |
| **I16 Panel discipline (post-hoc, PR1)** | A `high-stakes` unit's `verify.json` carries a `panel[]` (≥3 members, distinct correctness/reproduce/guardrail lenses); ANY panel's top-level `verdict` equals the **DISCRETE majority** of the panel verdicts (a no-majority split ⇒ `DISAGREE` — **no softmax**); `verify_rounds` (loop-until-dry) ∈ [1,3]. | `validate_run.py` offline predicate (label `I16 panel discipline (units/<uid>)`), added PR1. Gates **no** transition (never a live LT7 guard). Node-internal ⇒ **PRESERVES** termination. **Presence/shape-checked — genuine lens-diversity + real recall stay verifier judgment (Limitation H).** |
| **I-dod DoD/non-goals present** | Any post-clarification structural artifact (cartography, graph, units, or synthesis — `learnings.json` is deliberately excluded) requires a schema-valid `clarifications.json` with non-empty `definition_of_done` AND `non_goals`, even if the file is absent (methodology.md §Clarification). | validator artifact-driven presence check, fail-closed on absence — confirmed via the `missing_dod`/`postdecomp_no_dod`/`synthesis_no_dod`/`unfenced_cycle` fixtures. |
| **I3b wave layering** (BGA) | When `graph.json.waves` is present: every unit appears in exactly one wave group (and no group names a non-unit), and every edge in `edges ∪ deps` rises strictly in wave (`wave(from) < wave(to)`). When amendments exist `waves` is REQUIRED (absent ⇒ FAIL); without amendments an absent `waves` ⇒ SKIP. Closes a pre-existing gap: `waves` was never cross-checked, so a layering-violating-yet-acyclic graph passed silently. | `validate_run.py` post-hoc/offline; runs whenever a graph is present; gates no transition ⇒ **PRESERVES** termination (+STRENGTHENS I3). Fixtures `amend_ok`/`amend_layering`. |
| **I3c dependency closure** (BGA) | Every `deps` element and every `edges[].from/to` names a CURRENT `units[].id`; a dangling reference (incl. a retired id still referenced) ⇒ FAIL. Closes a pre-existing gap: a phantom endpoint became an invisible node in cycle detection. | `validate_run.py` post-hoc/offline; runs whenever a graph is present; gates no transition ⇒ **PRESERVES** termination (+STRENGTHENS I3). Fixtures `amend_ok`/`amend_dangling_dep`. |
| **I17 frozen executed prefix + reconciliation** (BGA) | *Frozen prefix:* no amendment touches a unit with a `debrief.json`/`verify.json` (retired dirs hold at most `brief.*`); no debriefed unit id is orphaned out of the amended `graph.json`; a retired id never reappears in a later `units_added`; a retired id in `fsm-state.units[]` has status `retired`. Mirrors the load-bearing 02/P4 has-no-debrief guard. *Reconciliation (WP1, B2/B3):* against the immutable `graph.json.baseline_units` (the revision-1 unit set, schema-required once `revision > 1`), `set(units[]) ∪ retired == set(baseline_units) ∪ ⋃ units_added` (kills smuggled/phantom units); every `units_retired` id existed (baseline or an earlier add); `retired ∩ units[] == ∅`; `graph.retired_units` ids == ⋃ records' `units_retired`. *Content anchor (WP4, B5):* every EXECUTED unit's current `graph.json` entry matches its immutable `brief.json` on `title`/`wave`/`depends_on`/executor `persona`/`tags`/`acceptance_criteria` (a post-execution edit/re-wave/rewire is caught); `goal`/`est_footprint_tokens` are not brief-carried and stay attested (Limitation J). | `validate_run.py` post-hoc/offline; gates no transition ⇒ **PRESERVES** AO-1/forward-only/I10/termination, **REVISES** I17 upward (reconciliation + content anchor give the frozen prefix a mechanical floor). Fixtures `amend_frozen`/`amend_orphan`/`amend_smuggled_unit`/`amend_phantom_add`/`amend_added_unreconciled`/`amend_fake_retire`/`amend_phantom_retire_undercharge`/`amend_missing_baseline`/`amend_edit_executed`/`amend_rewave_executed`/`amend_rewire_executed`. |
| **I18 fuel bound + records-required** (BGA) | `expansion.fuel_remaining == fuel_initial − Σ fuel_cost ≥ 0`; each record's `fuel_cost == max(1, \|units_added\| − \|units_retired\|)`; `graph.json.revision == 1 + \|records\|` with `amendments_applied` listing the record ids in order; amendments present with no `expansion` ⇒ FAIL. *Records-required trigger (WP1, B1):* if `graph.json`/`fsm-state.json` bear amendment EVIDENCE (`revision > 1`, non-empty `amendments_applied`/`retired_units`, or fuel spent) the matching `amendments/A<NN>.json` records MUST be present and in sync (`\|records\| == \|amendments_applied\| == revision − 1`, ids matching) — deleting `amendments/` no longer launders the append-only provenance. *Fuel tamper-evidence (WP2, B4):* the seed is anchored to the immutable `graph.json.fuel_initial` (`expansion.fuel_initial == graph.fuel_initial`), and each record's `fuel_before`/`fuel_after` form an unbroken chain (`A01.fuel_before == fuel_initial`, `fuel_after == fuel_before − fuel_cost`, `A(k+1).fuel_before == A(k).fuel_after`, last `fuel_after == fuel_remaining`) — widening fuel mid-run is caught. *Bookkeeping (WP3, G1/G2/G3/G12):* amendment ids unique and `id == filename` stem; `graph_revision_after == 2 + record_index`; `fsm-state.expansion.amendments_applied == \|records\|`; every `units_added` lands at `wave ≥ record.frontier_wave` (internal consistency; dispatch timing stays Limitation J). The pipeline-level termination budget (schema max 32), structurally identical to `retries ≤ 2`. | `validate_run.py` post-hoc/offline; gates no transition ⇒ **PRESERVES** the per-unit proof, **REVISES** the pipeline-level bound (N ≤ N0 + fuel₀); machine-checked by the TLC `Quiesce` property. Fixtures `amend_fuel_overrun`/`amend_no_fuel_seed`/`amend_records_deleted`/`amend_fuel_widen`/`amend_fuel_chain_break`/`amend_dup_amendment_id`/`amend_id_file_mismatch`/`amend_bogus_revision_after`/`amend_dead_counter`/`amend_wave1_insert`. |
| **I19 amendment scope + kind closure** (BGA) | *Schema kind closure (WP3):* `add_units` ⇒ ≥1 `units_added`, no retirement; `split_unit` ⇒ ≥2 children, exactly 1 retired, a non-empty `retired_snapshot` (each item with `id`/`tags`/`acceptance_criteria`), `criteria_map` present; `add_edges` ⇒ no unit add/retire/snapshot; `cancel_unit` ⇒ ≥1 retired, no adds. *Validator:* `add_units`/`split_unit` (and belt-and-braces: ANY record with `units_added`) ⇒ `dod_refs` non-empty and each element verbatim ∈ `definition_of_done`; `scope_change==true ⇒ human_gate==true`; `cancel_unit ⇒ human_gate==true`; split children tags ⊇ retired-snapshot tags, `retired_snapshot` ids == `units_retired`, and every snapshot criterion maps (`criteria_map`) to ≥1 of the split's OWN children. | `validate_run.py` post-hoc/offline; gates no transition ⇒ **PRESERVES** I-dod/Non-Goals/sign-off integrity, **REVISES** I19 upward (kind closure + snapshot/child semantics). `human_gate` genuineness / `dod_refs` semantic trace stay attestation-only (Limitations I/K). Fixtures `amend_dod_untraced`/`amend_cancel_ungated`/`amend_kind_dodge`/`amend_cancel_noop`/`amend_bare_snapshot`/`amend_noncild_criteria_map`/`amend_single_child_split`. |

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
retries-exhausted FAIL, or (BGA) amendment-fuel exhaustion; §1a — exited via T11). No phase, mechanical gate, or loop is unmodeled; the sole
remaining human gate (G-resolve, T11) is modeled as a human gate, while G-signoff — formerly a human
gate — is now the mechanical `gates.signoff_confirmed` guard required at DONE (D-06).
