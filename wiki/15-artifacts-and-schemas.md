# 15 — Artifacts, schemas & the run ledger

**Audience:** technical readers who want to see the *files on disk* — what `dag` actually writes, why almost every artifact comes as a prose file plus a machine-checkable JSON shadow, and exactly what each of the 14 schemas guarantees. If page 08 is "how the machine composes" and page 14 is "what the validator enforces," this page is "what the machine writes down, and the shape of every write."

**TL;DR.** A `dag` run is not held in the model's head — it is a directory of files. The run directory `.wip/<date>_<time>_<label>/` is the *single source of truth* (DESIGN.md:33-35), and Dag itself keeps almost no state. Most artifacts are written twice: a human-readable `<name>.md` and a machine-checkable `<name>.json` sidecar (init_run.sh:19-24). Two per-unit artifacts break that pattern and are **JSON-only** — `debrief.json` and `verify.json` — because nothing downstream reads a second markdown copy (DESIGN.md:64-66). The JSON sidecars are validated against 14 schemas under `schemas/*.schema.json` (Draft 2020-12); the schema pins the *shape* of every handoff, and the validator refuses to advance a phase on a bad shape. **Validity is not correctness** — the schema checks that a file has the right fields; whether those fields are *true* is the verifier's and the human's job (DESIGN.md:62).

> **Proof-status legend (used verbatim below, never softened).** A claim is one of:
> *machine-checked (in scope)* — a validator/model-checker mechanically enforces it over emitted artifacts; *hand-proved* — argued on paper (e.g. loop termination); *asserted (consistent)* — a discipline the system relies on but cannot mechanically enforce today. Never "proved for all inputs."

---

## First principle: the ledger *is* the program

Start from the mental model page 08 opens with: **the run directory is the program, and Dag is just an interpreter with a tiny working set.** Everything durable lives on disk — the ledger files, the FSM state, and one folder per work unit (DESIGN.md:33-55). Dag's own context is deliberately lean; the design's phrase is that Dag "holds almost no state in its own context; it reads/writes ledger files. This is what makes the run resumable and keeps Dag's own context lean" (DESIGN.md:33-35).

Why does this matter enough to be *first principle*? Three payoffs fall out of it:

1. **Resumability.** If a run is interrupted, the resume point is recovered purely from disk: re-read `PLAN.md`'s phase table + `PROGRESS.md`'s last line; completed units are exactly those whose `verify.json` verdict is `PASS` (SKILL.md:564-568). No in-memory state is lost because there is none to lose.
2. **Isolated subagents can't leak.** The *only* channel into an isolated subagent is its Agent prompt, so each executor is told to read its `brief.md` and write its `debrief.json`, and downstream briefs quote upstream debriefs' handoff notes (DESIGN.md:72-75). The files *are* the inter-agent bus.
3. **The validator has something to check.** A mechanical validator can only enforce invariants over artifacts that exist on disk. "Ledger-is-truth" is what makes the whole Phase-14 invariant catalog possible — and it is itself an invariant: **I2** fails a run where `fsm-state.json` is absent but other artifacts exist (validate_run.py:1682-1694). A run with work but no state file is incoherent by construction.

*Machine-checked (in scope):* I2 (ledger-is-truth) and every schema/invariant on this page are enforced by `scripts/validate_run.py` over the emitted run directory — see page 14 for the full catalog.

---

## The sidecar convention: prose + a machine-checkable shadow

The convention every artifact follows is written into the bootstrap script itself:

> most artifacts are written as `<name>.md` PLUS a machine-checkable `<name>.json` (e.g. `GRAPH.md` + `graph.json`). The per-unit debrief and verify are JSON-only … reason free-form in your reply, then write the JSON. (init_run.sh:19-24)

So there are **three** classes of artifact, and knowing which is which is the whole trick:

| Class | Files | Why |
|---|---|---|
| **Prose + JSON sidecar** | `PERSONAS.md`+`personas.json`, `CLARIFICATIONS.md`+`clarifications.json`, `CARTOGRAPHY.md`+`cartography.json`, `GRAPH.md`+`graph.json`, `LEARNINGS.md`+`learnings.json`, `units/<id>/brief.md`+`brief.json` | Humans read the `.md`; the validator reads the `.json`. The prose carries the reasoning; the sidecar carries the load-bearing residue (DESIGN.md:62-66). |
| **JSON-only** | `units/<id>/debrief.json`, `units/<id>/verify.json`, `fsm-state.json` | Nothing downstream reads a second markdown copy — the verifier and adjudicator consume the JSON directly, so a prose twin would be dead weight (DESIGN.md:64-66; debrief.schema.json:5; verify.schema.json:5). |
| **Prose-only** | `INPUT.md`, `PLAN.md`, `DECISIONS.md`, `PROGRESS.md`, `SYNTHESIS.md` | No schema, no mechanical shape to check — these are narrative ledger and the final deliverable (DESIGN.md:62-64). |

The design states the rule crisply: **only the artifacts backed by a schema carry a machine-checkable `.json`** — `personas`, `clarifications`, `cartography`, `graph`, `fsm-state`, and `learnings` — while `INPUT`/`PLAN`/`DECISIONS`/`PROGRESS`/`SYNTHESIS` are prose-only, and the per-unit debrief and verify are JSON-only (DESIGN.md:62-66). One more practical detail: the validator resolves schemas *relative to itself* (`validate_run.py` reads `../schemas`), so the run directory needs no copy of any schema (init_run.sh:22-24; DESIGN.md:65-66).

*Asserted (consistent):* the split of which artifacts get a `.json` is a documented convention seeded by `init_run.sh`; what the validator then *enforces* over each `.json` is machine-checked.

---

## The run-directory tree

This is the exact layout `init_run.sh` seeds plus what later phases add (DESIGN.md:37-55):

```
.wip/<date>_<time>_<label>/
├── INPUT.md         raw prompt + params                         (Phase 0, prose-only)
├── PLAN.md          living master plan (phase table + objective) (prose-only)
├── DECISIONS.md     append-only decision log                     (prose-only)
├── PROGRESS.md      append-only progress log                     (prose-only)
├── LEARNINGS.md     durable generalizable lessons  (+ learnings.json sidecar — see timing below)
├── fsm-state.json   pipeline FSM state (phase + gates + loop)    — seeded at bootstrap, JSON-only
├── PERSONAS.md      confirmed roster (Phase 1)     (+ personas.json)
├── CLARIFICATIONS.md ambiguity register (Phase 2)  (+ clarifications.json)
├── CARTOGRAPHY.md   contextual terrain map (Phase 3) (+ cartography.json)
├── GRAPH.md         atomic units + DAG + waves (Phase 4) (+ graph.json — fail-closed parse)
├── amendments/A<NN>.json  append-only graph-amendment records (BGA, Phase 6) — JSON-only, +amendment.schema.json
├── units/<id>/
│   ├── brief.md         self-contained contract IN   (+ brief.json sidecar)
│   ├── debrief.json     structured result OUT          (JSON-only)
│   ├── verify.json      independent adversarial report (JSON-only)
│   └── disagreement.md  (only if escalated)            (+ disagreement.json)
└── SYNTHESIS.md     final rolled-up deliverable (Phase 8, prose-only)
```

**What bootstrap actually seeds.** `init_run.sh` creates only the five ledger files (`INPUT`, `PLAN`, `DECISIONS`, `PROGRESS`, `LEARNINGS.md`), an initial `fsm-state.json` at phase `P0_BOOTSTRAP` with all gates `false`, and an empty `units/` directory (init_run.sh:69-153). Everything else — `PERSONAS.md`, the sidecars, `units/<id>/…`, and crucially `learnings.json` — is written by later phases, not at bootstrap. The seeded `fsm-state.json` carries all five gates set to `false`, which is *valid* at P0/P1 because no gate is required yet; gate-ordering fires from P2 onward (init_run.sh:142-151).

**Templates.** The skill also ships `templates/{brief,clarifications,cartography,graph,debrief,verify,disagreement,personas}.md` + `persona.json` — the prose scaffolds a subagent fills in. Templates carry the human-readable structure; the schema carries the machine-checkable one. (Directory: `plugins/dag/skills/dag/templates/`.)

---

## The four ledger files (req 13)

The ledger is the "no rediscovery" mechanism — any subagent can be pointed at these files, which is *why* nothing gets re-derived (SKILL.md:535). Their discipline (SKILL.md:527-535):

- **PLAN.md** — the *living* plan: keep the phase table + objective + open questions current. (The only mutable ledger file; the others are append-only.)
- **DECISIONS.md** — append-only, timestamped: every material choice + rationale + alternatives rejected + who decided.
- **PROGRESS.md** — append-only: one line per phase/unit state change.
- **LEARNINGS.md** — durable, generalizable lessons injected into later briefs (the self-learning loop, req 12).

### `learnings.json` sidecar timing (a load-bearing subtlety)

`LEARNINGS.md` is seeded at bootstrap as an empty-table markdown file (init_run.sh:132-140). Its JSON sidecar `learnings.json` is **not** — and getting this wrong is a real trap. The rule (SKILL.md:551-554; learnings.schema.json:5):

> `learnings.json` … is **emitted in Phase 6 when a generalizable lesson is admitted, or seeded by the Phase-0.5 intake when cross-run imports survive** (it is *not* seeded by `init_run.sh` at bootstrap); the I12 propagation check is enforced **when that `learnings.json` sidecar is present.**

So there are exactly two ways `learnings.json` comes into existence — a Phase-6 admission or a surviving Phase-0.5 cross-run import — and `init_run.sh` is never one of them (verifiable: the script writes `LEARNINGS.md` at lines 132-140 and nothing named `learnings.json`). This matters for the validator: the I12 propagation invariant is *conditional on the sidecar's presence*, so a run that never admitted a generalizable lesson simply has no `learnings.json` and I12 is a no-op — not a failure. (This also means `learnings.json` is *not* a signal that trips the G-personas gate — BRK-06; see page 05.)

*Asserted (consistent):* the emission *timing* (Phase 6 / Phase 0.5) is a documented prose step Dag executes; that `init_run.sh` does not create the sidecar is *located* (init_run.sh:132-153, by inspection); the schema's own description restates the timing (learnings.schema.json:5).

---

## The 14 schemas — a tour

All live under `plugins/dag/skills/dag/schemas/*.schema.json`, JSON Schema **Draft 2020-12** (`$schema` on line 1 of each). The validator self-checks every schema (valid JSON + `$schema` + `type`) before it validates anything against them (page 14, §2). Global ceilings recur: any *planned* budget (`brief.budget_tokens`, `graph.est_footprint_tokens`) is capped at **32000**; `loop.retries` at **2**; `verify.verify_rounds` at **1..3**; the BGA `expansion` fuel budget at **0..32**.

| # | Schema | Validates | Required keys | Notable constraint (1.3.0 / 1.7.0) |
|---|---|---|---|---|
| 1 | `brief.schema.json` | `units/<UID>/brief.json` | `unit_id, title, wave, depends_on, persona, budget_tokens, acceptance_criteria, context_pointers, outputs, socratic_protocol, tags, learnings_applied` (brief.schema.json:8-12) | `budget_tokens` max 32000 (:23); `tags` non-empty ⊆ V_tag; `learnings_applied` items `^[LG][0-9]+$`, **may be empty** (:48-53); `socratic_protocol` is a *reference only* (:36-40) |
| 2 | `debrief.schema.json` | `units/<UID>/debrief.json` (**JSON-only**) | `unit_id, persona, iteration, result, evidence_table, socratic, confidence, footprint` (debrief.schema.json:8) | `evidence_table` minItems 1 (:14); `socratic` is the canonical 4-key block; `footprint.tokens_consumed` has **no max** + if/then honesty clause (:63-79); retry echo required on `iteration≥2` (:92-110) — deep-dive below |
| 3 | `verify.schema.json` | `units/<UID>/verify.json` (**JSON-only**) | `unit_id, verifier_persona, verdict, iteration, executor_reasoning_seen, feedback, defects, socratic, premise_check` (9 keys; verify.schema.json:8) | `executor_reasoning_seen` **const false** (:14-18); optional `panel[]`/`verify_rounds`/`converged` (:24-53) — deep-dive below |
| 4 | `graph.schema.json` | `graph.json` | `units, edges, v_tag` (graph.schema.json:8) | `v_tag` minItems 1 = the run's tag enum (:11-16); each unit requires `id, title, goal, executor_persona, verifier_persona, deps, est_footprint_tokens, acceptance_criteria, tags` (:24); `est_footprint_tokens` max 32000 (:33); optional `waves`, `socratic` (:57-80) |
| 5 | `fsm-state.schema.json` | `fsm-state.json` | `run_dir, phase, updated_at` (fsm-state.schema.json:8) | `phase` enum = 10 states (:11-18); optional `validator_version` stamp (**1.7.0**/F1, :24-27); `gates` includes `signoff_confirmed` (:36-39); `loop{retries max 2, iteration min 1}` (:42-58); `units[]` items MAY carry optional `retries 0..2` + `loop_state` (:59-79); optional BGA `expansion{fuel_initial, fuel_remaining, amendments_applied}` 0..32 (:80-89) — deep-dive below |
| 6 | `learnings.schema.json` | `learnings.json` + store files | *entry*: `id, trigger, lesson, how_to_apply, scope, evidence, since_wave`; `scope` requires `applies_to` (learnings.schema.json:19, :44-51) | `id ^[LG][0-9]+$` (:23); `since_wave` min 1 (:69-73); `scope.expiry` pattern pinned to `run\|project\|runs:N\|date:YYYY-MM-DD` (:53-56); optional `model`, `promotable`, `supersedes` (**a string**, :96-98), `grounding` (:100-103) |
| 7 | `clarifications.schema.json` | `clarifications.json` | `ambiguity_register, definition_of_done, non_goals` (clarifications.schema.json:8) | DoD + non_goals **both required, minItems 1, non-empty** (:35-44); register items `id, ambiguity, materiality(material\|minor), resolved` (:16-24) |
| 8 | `cartography.schema.json` | `cartography.json` | `terrain_shape, elements, invariants` (cartography.schema.json:8) | `elements` minItems 1, each `element, role, relevance, authority` (:12-26); `invariants` minItems 1 (:27); optional `risks`, `unknowns`, `socratic` (:28-41) |
| 9 | `personas.schema.json` | `personas.json` (backs `personas_confirmed`) | `roster` (each item `persona, mandate`) (personas.schema.json:8, :18-21) | optional `confirmed_by_user` is **not** the gate — the validator keys off the *fsm* gate, not this flag (:11); optional `pairings[{producer, critic}]` (:29-40) |
| 10 | `persona.schema.json` | a *single* persona (curated/user/project input) | `name, role, description` (persona.schema.json:8) | `additionalProperties:false`; optional `mandate, optimizes_for, skeptical_of, phase, pair_with, qualifications[], tags[]`; **meta-validated by `--self-check` only** — never required by a run (:5) |
| 11 | `disagreement.schema.json` | `units/<UID>/disagreement.json` | `subject, question, options` (disagreement.schema.json:8) | `options` minItems 2, each `name, recommended, what_it_is` (:14-24); the validator adds I7 = **exactly one** `recommended:true` (:5) |
| 12 | `manifest.schema.json` | `manifest.json` (large-dataset) | `grain, shards` (manifest.schema.json:8) | shard = `shard_id` + `locator{kind, ref}` (by-reference, never raw data) (:27-39); optional `results_index[]`, `sampling_log{strategy}`; **NOT auto-run by `validate_run.py`** (:5) — see below |
| 13 | `tags.schema.json` | global `~/.claude/dag/tags.json` | `tags` (tags.schema.json:8) | `tags` minItems 1, unique (:10-15); absent ⇒ `V_tag_eff` falls back to the run-local `v_tag` (`validate_run.py:1385,1410`); invalid ⇒ an `I11` FAIL (`validate_run.py:1399`) |
| 14 | `amendment.schema.json` **(BGA, 1.7.0)** | `amendments/A<NN>.json` (append-only) | `id, kind, origin, rationale, scope_change, human_gate, fuel_cost, fuel_before, fuel_after, graph_revision_after` (amendment.schema.json:8) | `kind ∈ {add_units, split_unit, add_edges, cancel_unit}` (:11); `fuel_before`/`fuel_after` 0..32, the I18 tamper-evidence chain (:27-30); `allOf` kind-closure — `dod_refs` on add/split, `split_unit` needs ≥2 children + `retired_snapshot` + `criteria_map` (:57-91); the `human_gate` policy is left to the validator's I19, **not** this schema's `allOf` (:5); feeds I17/I18/I19 |

*Machine-checked (in scope):* schemas 1–9, 11, 13, and 14 are applied by `validate_run.py` over emitted artifacts (top-level: personas/clarifications/cartography/graph/fsm-state; per-unit: brief/debrief/verify/disagreement; and — when amendments exist — `amendments/A<NN>.json` under the I17/I18/I19 offline checks, page 14 §4.2). Schema 10 (`persona`) is meta-validated only under `--self-check`. Schema 12 (`manifest`) is validated by the decomposer, not auto-run — see the last section.

### Deep dive — `fsm-state.schema.json`: the sign-off gate, per-unit loop state, and the 1.7.0 stamps

Four schema additions live here — two from 1.3.0, two from the 1.7.0 BGA / audit-round-2 work — and all are worth pinning.

**`gates.signoff_confirmed` (D-06/BRK-13, 1.3.0).** The gate object grew a fifth flag. It is a human attestation the validator checks the *presence* of — REQUIRED `true` to reach phase `DONE`, because `validate_run.py`'s `REQUIRED_GATES` lists it for `DONE`, so **a run at `DONE` without the flag is INVALID** (fsm-state.schema.json:36-39; SKILL.md:499-503). The sign-off is set only after the human accepts at the Phase-8 gate — Dag sets `gates.signoff_confirmed = true` *before* advancing `phase` to `DONE` (SKILL.md:498-503). Like `personas_confirmed`, the validator checks that the flag is present, not whether the human genuinely accepted — a *machine-checked* presence gate over an *asserted* attestation.

**The `loop` slot vs `units[]` per-unit `retries`/`loop_state` (D-02/IMP-11, 1.3.0).** The single top-level `loop` object tracks the **most recently transitioned** unit's correction-loop substate — `unit_id, state, retries, iteration` (fsm-state.schema.json:42-58). But waves run *in parallel*, so more than one unit may be mid-loop at once, and one slot cannot represent them all. The fix: each `units[]` item **may additionally carry** its own durable `retries` (0..2) and `loop_state` (fsm-state.schema.json:59-79). The schema's description states the design directly: the single `loop` slot is a "back-compat snapshot of the last unit to transition, while each unit's durable per-unit loop state lives in its `units[]` item" (fsm-state.schema.json:44). The validator's I4 bound `iteration ≤ retries+1` is enforced for **both** the `loop` slot *and* every `units[]` item that records `retries` (fsm-state.schema.json:5, :72; page 14 §4). Crucially, this REVISES only the *cross-check surface*, not the loop itself: per-unit state is an *offline* representation validated post-hoc, so the correction-loop termination proof is **preserved** (D-02).

**Optional `validator_version` stamp (F1/WP-E, 1.7.0).** `init_run.sh` records the plugin/validator version that scaffolded the run in `fsm-state.json.validator_version` (fsm-state.schema.json:24-27). It is OPTIONAL and **gates nothing** — an absent stamp (legacy / pre-1.7.0 runs) is judged exactly as before. It only *labels* provenance so the validator's **single-truth** findings (it always applies the current invariant set) on a run stamped with an *older* version read as **expected version-skew, not defects** — the version-skew policy (state-machine.md §5; page 14 §4.2).

**Optional BGA `expansion` fuel budget (1.7.0).** For Bounded Graph Amendments the state file MAY carry an `expansion` object — `fuel_initial`, `fuel_remaining`, `amendments_applied`, each 0..32 (fsm-state.schema.json:80-89). It is the monotone-decreasing graph-amendment budget seeded at Phase 4 (default `min(N0, 8)`); `0` or absent ⇒ BGA disabled (today's default). Only an amendment writes it — mirroring the `retries` counter — and `validate_run.py`'s I18 cross-checks `fuel_remaining == fuel_initial − Σ fuel_cost ≥ 0`, the pipeline-level termination budget (`N ≤ N0 + fuel₀`).

### Deep dive — `verify.schema.json`: the optional panel fields

The nine required keys are unchanged, and `executor_reasoning_seen` is a `const false` — the schema-level statement of maker≠checker independence (verify.schema.json:14-18). What 1.3.0 adds are three **optional** fields for the panel-of-3 / loop-until-dry machinery (verify.schema.json:24-53):

- **`panel[]`** — minItems 3; each panelist carries a distinct `lens ∈ {correctness, reproduce, guardrail}` and its own `verdict`. When present, the top-level `verdict` MUST equal the *discrete majority* of the panel (no softmax); a split with no strict majority routes to `DISAGREE` (verify.schema.json:24-43). It is *optional in the schema* but *required by the validator's I16* on any unit tagged `high-stakes`.
- **`verify_rounds`** — 1..3; the number of loop-until-dry adversarial sweeps run *inside* this single `VERIFY` node (defects accumulate until a round is "dry" or the R_max=3 cap hits) (verify.schema.json:44-49).
- **`converged`** — `true` iff the sweep stopped dry, `false` iff it hit the cap (coverage may be incomplete — surface honestly) (verify.schema.json:50-53).

The design note that makes these safe: recording a panel or extra rounds is **node-internal** — it adds no FSM edge, so the termination proof is untouched (verify.schema.json:27, :48). See page 06 for the verification story and page 14 for I16.

### Deep dive — `debrief.schema.json`: the retry echo is schema-required

Two 1.3.0 tightenings (PR-6):

1. **`footprint.tokens_consumed` has no maximum.** A *real* overrun must be recordable truthfully rather than forced to lie under an old `maximum:32000` cap; the plan-side 32K ceiling stays on `brief.budget_tokens`/`graph.est_footprint_tokens` (debrief.schema.json:63-79). An if/then clause mirrors the honesty tie: any report of `tokens_consumed > 32000` MUST self-identify as over-budget (`within_budget:false`) (:72-78). Beyond the schema, **1.7.0/F2** ties that honesty signal to each unit's *own* budget: the validator defines `within_budget := tokens_consumed ≤ brief.budget_tokens`, so a unit briefed 16K that consumed 20K while claiming `within_budget:true` FAILs **I5** even though it never crossed the global 32K cap (validate_run.py:1403-1419; page 14 §4.2).
2. **The retry echo is schema-required on `iteration ≥ 2`.** The `prior_feedback` block echoes the previous iteration's `verify.feedback` plus ≥1 concrete `changes_made`. On a retry, the schema's `allOf` clause makes the block's *presence* + non-empty `changes_made` + the `do_not_touch` echo **mandatory** (debrief.schema.json:92-110). This closes the "evasion by omission" half of Limitation F — a schema-invalid retry debrief is dropped *before* the I14/I15 comparison, so the schema is now the load-bearing presence gate and I14/I15 remain the semantic backstop (:94). First attempts (`iteration:1`) are untouched.

---

## What the validator does *not* auto-check: `manifest.json`

The large-dataset partitioning schema is the one deliberate exception to "every JSON sidecar is validated by the run validator." `manifest.json` is the shard map a *deterministic sharder* (a script, not an LLM) emits for a judgment-heavy pass over a dataset larger than one unit's 32K budget (manifest.schema.json:5). Its own description is explicit:

> NOT auto-run against a run by `validate_run.py`; it is the schema a partitioned run validates its manifest against. (manifest.schema.json:5)

Concretely: `validate_run.py`'s top-artifact list (personas/clarifications/cartography/graph/fsm-state) and its per-unit list (brief/debrief/verify/disagreement) do **not** include `manifest.json`, so a plain run never loads it. Instead the **decomposer** validates the manifest against `manifest.schema.json` when it builds a partitioned map-reduce run (page 12; SOURCE-MAP §A partitioning row). The consequence to internalize: on a partitioned run, the manifest's shape is checked *by the phase that produces it*, not by the standing validator — so its correctness is a Phase-4 responsibility, not a gate on every later transition.

*Asserted (consistent) / located:* that the standing validator never loads `manifest.json` is *located* (its artifact lists in `validate_run.py` omit it); that the decomposer validates it is the documented partitioning-path discipline (data-partitioning.md; SKILL.md:305-327).

---

## Cross-references

- **Page 14 — Validator & invariants:** what `validate_run.py` *does* with these schemas (schema self-check, top-artifact + per-unit validation, and the I1–I19 / I1b–I1d / I3b / I3c / I-dod invariant catalog — including the BGA I17/I18/I19 amendment checks — that layers structural checks on top of shape).
- **Page 08 — How it all fits:** the ledger-is-truth first principle in the context of the whole nine-phase machine, and where each artifact is produced.
- **Page 05 — Learnings:** the `learnings.json` propagation semantics and cross-run stores.
- **Page 06 — Verification:** the panel-of-3 / loop-until-dry story behind `verify.json`'s optional fields.
- **Page 12 — Large-dataset partitioning:** the map-reduce path that produces (and self-validates) `manifest.json`.
