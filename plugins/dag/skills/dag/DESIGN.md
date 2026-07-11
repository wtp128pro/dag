# DESIGN — the `dag` skill (comprehensive plan & rationale)

This is the blueprint behind the skill: architecture, how each of the 16 requirements is
satisfied and where, the grounding evidence, and the honest limitations. Read
`SKILL.md` for the operating procedure; read this to understand *why* it's built this way.

## 1. Purpose

`/dag:dag <task>` executes **any** non-trivial task through a gated, multi-phase
pipeline that (a) makes hidden assumptions explicit, (b) decomposes work into
independently verifiable atomic units, (c) runs each in a budget-capped subagent, (d)
verifies every unit with an *independent* adversarial checker, (e) refuses to assert
unbacked claims, and (f) escalates material disagreements to the human with every option
laid out. All state is durable on disk so nothing is ever rediscovered.

## 2. Design decisions (locked with the user)

| Decision | Choice | Consequence |
|---|---|---|
| Deliverable | **Full working skill** | Real SKILL.md + references + templates + bootstrap script |
| Persona sourcing | **Hybrid**: curated library + auto-synthesized, user-approved | `references/personas/` (per-file JSON + `index.json`) + Phase-1 gate |
| "Credible source" | **Adaptive by claim type** | `references/evidence-standards.md` claim→evidence table |
| Human gating | **Gate on decisions that matter** | Gates at Phase 1, 2, material disagreements (7), sign-off (8) |
| Install scope | Ships as a **plugin** (installed under `~/.claude/plugins/…` via the marketplace) | Reusable across all projects; movable to a project's `.claude/skills/` |

## 3. Architecture

**Control model:** a *Skill*, not a Workflow — because the pipeline needs interactive
Socratic gates mid-run, which background Workflows can't do. The main agent acts as
**Dag**; it spawns subagents via the **Agent tool** (isolated context per SKILL
research) and pauses at gates via **AskUserQuestion**.

**State model:** the **run directory** `.wip/<date>_<time>_<label>/` is the single source of
truth. Dag holds almost no state in its own context; it reads/writes ledger
files. This is what makes the run resumable and keeps Dag's own context lean.

```
.wip/<date>_<time>_<label>/
├── INPUT.md         raw prompt + params
├── PLAN.md          living master plan (phase table, objective, open questions)
├── DECISIONS.md     append-only decision log (choice + rationale + alternatives)
├── PROGRESS.md      append-only progress log (one line per state change)
├── LEARNINGS.md     durable generalizable lessons (self-learning loop) (+ learnings.json sidecar, emitted in Phase 6 or seeded by the Phase-0.5 intake)
├── fsm-state.json   pipeline FSM state (phase + gates + loop substate) — seeded at bootstrap
├── PERSONAS.md      confirmed roster (Phase 1)          (+ personas.json sidecar)
├── CLARIFICATIONS.md ambiguity register + resolutions (Phase 2)  (+ clarifications.json)
├── CARTOGRAPHY.md   contextual terrain map (Phase 3)    (+ cartography.json)
├── GRAPH.md         atomic units + DAG + waves (Phase 4) (+ graph.json — fail-closed parse)
├── units/<id>/
│   ├── brief.md         self-contained contract IN      (+ brief.json metadata sidecar)
│   ├── debrief.json     structured result OUT            (JSON-only — verifier + downstream read this)
│   ├── verify.json      independent adversarial report   (JSON-only — adjudication reads this)
│   └── disagreement.md  (only if escalated)              (+ disagreement.json)
├── amendments/A<NN>.json  bounded graph-amendment records (Phase 6, BGA) — append-only, one per amendment; graph.json stays authoritative
└── SYNTHESIS.md     final rolled-up deliverable (Phase 8)
```

The skill dir itself additionally ships `schemas/*.schema.json` (incl. `amendment.schema.json` +
`manifest.schema.json`), the SSR registry `spec/{fsm.json,invariants.json}` (+ their meta-schemas),
`scripts/{init_run.sh,validate_run.sh,validate_run.py,run_tests.sh,spec_check.py,run_formal.sh}`
(+ `tests/`, whose BGA runs carry `amendments/A<NN>.json`), the machine-checked models
`formal/{Pipeline.tla,Pipeline.cfg,WorkGraph.als,Amendment.als}` + the headless `formal/AlloyRun.java`
driver (`run_formal.sh` fetches the TLC/Alloy jars to /tmp — BUILD tools, never vendored),
`references/{methodology,evidence-standards,state-machine,socratic-protocol,self-learning-loops,formal-models,data-partitioning}.md`,
and the `references/personas/` catalog (`index.json` + per-file persona JSON + `GUIDE.md`).
Only the artifacts backed by a schema carry a machine-checkable `.json` (validity ≠ correctness):
**`personas`, `clarifications`, `cartography`, `graph`, `fsm-state`, and `learnings`** — while
`INPUT`/`PLAN`/`DECISIONS`/`PROGRESS`/`SYNTHESIS` are prose-only; the per-unit **debrief and verify
are JSON-only** (nothing reads a second markdown copy). The validator resolves schemas relative to
itself, so the run dir needs no schema copy.

**Pipeline:** Bootstrap(0) → Personas(1) → Clarify(2) → Cartography(3) → Decompose+DAG(4)
→ Brief(5) → Execute+Verify per wave(6) → Disagreement gates(7, as needed) → Synthesis(8).
Phases 2/3/4 can loop backward when unknowns or over-budget units are discovered.

**Data flow between isolated subagents:** the *only* channel into a subagent is its Agent
prompt, so each executor is told to **read its `brief.md`** (and only the paths it lists)
and **write its `debrief.json`**. Downstream briefs quote the upstream debriefs' handoff
notes. This is how "no rediscovery" (req 13) and the budget cap (req 7) are both held.

## 4. Requirement traceability (all 16)

| # | Requirement | Where it lives | How |
|---|-------------|----------------|-----|
| 1 | Socratic dialogue for personas | SKILL Phase 1; methodology §Socratic; **references/socratic-protocol.md** (one move-set, 2 modes); references/personas/ (index.json + per-file JSON) | Hybrid roster proposed, user confirms via AskUserQuestion gate; questioning is *selective* (material surfaces only), not a ritual; the answered `socratic` block is schema-checked (`schemas/debrief.schema.json` + `schemas/verify.schema.json`) and its genuineness re-verified in Phase 6; the **persona gate is mechanically non-skippable** — `validate_run.py` requires `gates.personas_confirmed` from Phase 2 on and rejects a confirmed flag unbacked by a valid `personas.json` (G-personas / T2), so "right-sizing" cannot drop it |
| 2 | Clarification analysis eliminating lapses | SKILL Phase 2; methodology §Clarification; templates/clarifications.md | Ambiguity register ranked by materiality; material items gated to user |
| 3 | Detailed cartography | SKILL Phase 3; templates/cartography.md | Cartographer subagent(s) produce annotated map |
| 4 | Atomic units + dependency graph | SKILL Phase 4; methodology §Decomposition; templates/graph.md; **schemas/graph.schema.json**; **Bounded Graph Amendments**: SKILL Phase 6 "Graph amendments (bounded)"; **schemas/amendment.schema.json** | Atomicity tests, DAG, topological waves, critique pass; the validator parses `graph.json` **fail-closed** — an unparseable/empty graph or a cycle is rejected; units carry `tags ⊆ V_tag` for pattern-scoped learning. The Phase-6 graph may **grow under mechanical constraints** via append-only `amendments/A<NN>.json` (kinds `add_units`/`split_unit`/`add_edges`; `cancel_unit` human-gated), bounded by a monotone-decreasing `expansion` fuel budget and validated post-hoc by **I3b** (wave layering) / **I3c** (dependency closure) / **I17** (frozen executed prefix) / **I18** (fuel bound) / **I19** (amendment scope) — none a live transition guard, so the correction-loop termination proof is PRESERVED (total units ≤ N0 + fuel₀) |
| 5 | Structured briefing per unit | SKILL Phase 5; templates/brief.md | Self-contained contract; footprint validated |
| 6 | Structured debriefing consumed up the line | templates/debrief.md; handoff notes | Evidence table + handoff notes feed downstream briefs |
| 7 | Subagent, ≤32K context budget | SKILL Phase 6 + Prime Directive 2; brief "budget contract"; **schemas/brief.schema.json** (`budget_tokens maximum: 32000`) | Atomic scope + read-only-what's-listed + self-reported footprint checked by verifier; the *declared* budget is now schema-hard-checked. **(Real consumption still disciplinary — see Limitations §1.)** |
| 8 | Right personas, propose/critique | SKILL Phase 1 & 6; references/personas/ `pair_with` pairings | Every producer paired with a critic persona |
| 9 | Independent adversarial verifier per executor | SKILL Phase 6; methodology §Verification; templates/verify.md; **schemas/verify.schema.json** | Separate subagent, refutation mandate, sees brief+debrief+artifacts only; `executor_reasoning_seen: false` is a schema invariant (AO-7); the verifier also confirms the `premise` is load-bearing then re-runs COUNTER from evidence |
| 10 | Avoid hallucination; verify with credible sources | references/evidence-standards.md | Adaptive claim→evidence table; verifier hallucination sweep; "could not verify" surfaced |
| 11 | Material disagreement → Socratic gate, every option, best marked, rollback to any stage | SKILL Phase 7; templates/disagreement.md | Full dossier, ★ Recommended, rollback incl. revising input |
| 12 | Self-learning loops (Cherny), used wisely | SKILL Phase 6; methodology §Self-learning; **references/self-learning-loops.md** (FSM + termination proof); **schemas/{verify,fsm-state}.schema.json** | Correction loop = bounded FSM `EXECUTE→VERIFY→ADJUDICATE→{DONE\|RETRY≤2\|ESCALATE}` with a checkable termination argument + AO-1…AO-7 invariants; learning loop = generalizability-gated `LEARNINGS` entries force-injected into matching later briefs (`learnings_applied`, validator-checked when a `learnings.json` sidecar is present) |
| 13 | Plan + decision log + progress log; no rediscovery | init_run.sh seeds PLAN/DECISIONS/PROGRESS; Ledger discipline | Ledger is truth; briefs quote prior decisions |
| 14 | Contextual (not mechanical) cartography | methodology §Cartography; cartography.md | Relevance/relationships/invariants/unknowns, not inventories |
| 15 | `.wip/<date>_<time>_<label>/` holds all work files | scripts/init_run.sh | Deterministic dated dir under a single gitignored `.wip/` parent; everything written under it |
| 16 | Ask for prompt if not provided | SKILL Phase 0 | `$ARGUMENTS` else AskUserQuestion |

**Formal enforcement layer (the mechanical backbone under the prose).** Reqs 1/4/7/9/12 are no
longer prose-only: each artifact has a JSON sidecar validated against `schemas/*.schema.json`
by `scripts/validate_run.sh` (→ `validate_run.py`), and the whole pipeline is a state machine
specified in `references/state-machine.md` (per-phase states, guards, invariants) with the
Phase-6 loop detailed in `references/self-learning-loops.md`. Dag runs the
validator after each artifact and before each gate (SKILL Prime Directive 7); a non-zero exit
is a hard stop. This is the "structure the plumbing, not the reasoning" split:
schemas gate handoff *shape*; the free-form prose carries the thinking.

## 5. Grounding & provenance (anti-hallucination applied to our own design)

Verified against official docs via research (URLs below); claims we could **not** fully
verify are flagged so we don't launder them into facts — practicing req 10 on ourselves.

- **Skills format / arguments** — SKILL.md = YAML frontmatter + Markdown; supporting files
  lazy-load when referenced; args via `$ARGUMENTS`. Source:
  https://code.claude.com/docs/en/skills.md . *We rely only on the core, well-attested
  fields (`name`, `description`, `argument-hint`, `allowed-tools`). Exotic frontmatter
  fields surfaced in research were NOT all independently confirmed and are deliberately
  avoided.*
- **Subagents = isolated context; only channel is the Agent prompt.** Source:
  https://code.claude.com/docs/en/agent-sdk/subagents.md . This is the basis for the
  brief/debrief-file data-flow and for verifier independence.
- **No built-in per-subagent token cap.** Same source. → The 32K budget is enforced by
  discipline, not by the platform (see Limitations). Stated honestly in SKILL.md.
- **"Self-learning loops" (Boris Cherny, co-creator of Claude Code).** The *exact term*
  is **not** in official docs. The well-attested underlying practices are **verification/
  agent loops** and **"decouple the maker from the checker"** to defeat confirmation bias
  (Cherny, public talks/posts). We implement that verified concept and label the term's
  provenance rather than inventing a definition. Do not present any specific dated verbatim
  quote as fact without re-verifying the primary source.

## 6. Known limitations (stated plainly)

1. **Budget is partially enforceable, still mostly disciplinary.** Claude Code cannot hard-cap
   a subagent's *real* consumption at 32K today. The validator now *does* hard-check the
   **declared** `budget_tokens` (`schemas/brief.schema.json`) / `est_footprint_tokens`
   (`schemas/graph.schema.json`) against the schema ceiling (`maximum: 32000`) and fails a run that declares an over-budget
   unit — but that gates the self-reported number, not actual token use. The prose disciplines
   remain load-bearing: atomic units, minimal self-contained briefs, restricted tools,
   read-only-what's-listed, self-reported footprint audited by the verifier, re-atomize on
   breach. If a future platform primitive adds hard caps, wire it into Phase 6.
2. **Verifier independence is now schema-ATTESTED, still not cryptographic.** Every `verify.json`
   must carry `executor_reasoning_seen: false` (invariant AO-7, enforced by
   `schemas/verify.schema.json`), so a verifier that admits seeing the executor's reasoning
   fails validation. But the attestation is self-declared and verifiers still **share model
   weights** with executors (self-preference). Strongest available mitigation: staff
   the verifier as a *different model* where possible, and use
   panels with *diverse lenses* (Phase 6). The platform cannot prove blindness.
3. **Enforcement is an explicit Bash step, not a passive hook.** We did **not** verify that a
   Claude Code `Stop`/`SubagentStop`/`PostToolUse` hook can auto-run the validator on subagent
   completion, so we do not rely on one. Enforcement therefore depends on Dag
   faithfully calling `bash scripts/validate_run.sh <RUN_DIR>` after each artifact and before
   each gate (Prime Directive 7) — itself an un-enforced instruction. This is the single
   biggest residual gap; if hooks are later confirmed against official docs, wire a
   `SubagentStop` hook as belt-and-suspenders.
4. **Validator checks shape + a few structural invariants, not semantic truth.** Validity ≠
   correctness: it cannot judge whether a PASS is *correct*, whether a `socratic`
   block is genuine vs. theater, or whether reported tokens are truthful. Those stay the
   independent verifier's / human's job (the verifier's premise-load-bearing check + COUNTER
   re-run, and the Phase-7/8 gates, are where genuineness is caught).
5. **Cost/latency.** Full pipeline spends many subagents per task. It's meant for
   high-stakes/complex work; for trivial tasks it is overkill — say so and offer to skip.
6. **Interactive by design.** Because of the Socratic gates, this runs in the foreground,
   not as a fire-and-forget background job.
7. **Bounded Graph Amendments are attestation-checked, not semantically proven.** BGA lets the
   Phase-6 graph grow, but the three semantic guarantees stay human/verifier judgment (validity ≠
   correctness): `human_gate` is a **presence-checked attestation** (like `signoff_confirmed`) — the
   validator cannot prove a human actually approved a scope-change/cancel; a record's `frontier_wave` is
   internally-consistency-checked against the graph (WP3: every `units_added` lands at `wave ≥
   frontier_wave`) but the *dispatch timing* it stands for is still **attested** (Limitation J); and
   `dod_refs` verbatim matching is **string membership**, not semantic traceability — that a new unit
   *genuinely* serves its cited DoD item stays the verifier/critique-pass backstop (Limitation K). What
   IS mechanical and fail-closed: the frozen executed prefix (I17 — including the WP1 baseline
   reconciliation and the WP4 executed-unit content anchor against `brief.json`: `title`/`wave`/`deps`/
   `persona`/`tags`/`acceptance_criteria`; `goal`/`est_footprint_tokens` are not brief-carried and stay
   attested), the fuel bound + tamper-evidence + bookkeeping (I18 — seed anchor, `fuel_before`/`fuel_after`
   chain, records-required, id/filename/revision/counter/frontier), acyclicity + wave layering +
   dependency closure (I3/I3b/I3c), and per-kind schema closure + split semantics + DoD string membership
   + the human-gate flag's presence (I19).

## 7. How to run

`/dag:dag <task prompt>` — or `/dag:dag` and it will ask for the prompt (req 16).
The skill creates the run dir, walks the phases, and pauses at the gates that matter.

## 8. Future extensions

- Optional Workflow-backed fan-out for large brief/verify waves (keep gates in the skill).
- A `promote-learnings` step wired to project `CLAUDE.md` at sign-off.
- Per-claim-type verifier sub-skills (e.g., delegate factual units to `deep-research`).

## 9. Enforced clarification outputs, uniform personas & authoring rules

**Mandatory clarification outputs and uniform personas:**
- **Definition of Done + Non-Goals/Guardrails are mandatory, mechanically-enforced Phase-2 outputs**
  (extends req 2). `schemas/clarifications.schema.json` requires non-empty `definition_of_done` +
  `non_goals`; `validate_run.py`'s artifact-driven **`I-dod`** invariant additionally requires them
  once a run has ANY post-clarification structural artifact (**cartography, graph, units, or
  synthesis** — the `learnings.json` ledger sidecar is deliberately excluded). Two complementary
  layers (schema "if present, well-formed" + validator "must be present"). Guardrails are **threaded**
  through Phases 4/6/8 (acceptance-criteria trace to DoD; a delivered non-goal is a verify FAIL;
  sign-off blocks on any shipped non-goal). Negative fixtures: `missing_dod/`, `postdecomp_no_dod/`,
  `synthesis_no_dod/`.
- **Uniform JSON personas across all three sources** (extends req 1). The curated catalog is now
  per-file JSON (`references/personas/<name>.json` + `index.json`), governed by the **same**
  `schemas/persona.schema.json` (required `name`, `role`, `description`; optional `mandate`,
  `optimizes_for`, `skeptical_of`, `phase`, `pair_with`, `qualifications`, `tags`) as
  `templates/persona.json` and the user/project libraries. Users drop JSON at
  `.dag/personas/*.json` (project) or `~/.claude/dag/personas/*.json` (user); Phase 1
  reads `index.json` to triage cheaply and merges all sources into the candidate pool (override
  **project > user > curated**), still behind the human gate. A documented convention —
  **no loader script**, and **not** a required run artifact (meta-validated by `--self-check` only).

**Authoring rule AR-1 (a durable maintenance discipline; D11 — renamed from "L1" to avoid colliding with Learning `L1` and the I-dod enforcement Layer-1/Layer-2).**
> Any claim that a change *mirrors / covers / matches* an existing construct, or is
> *complete / non-skippable / all*, MUST be verified by **enumerating that construct exactly and
> re-reading/re-running it** before asserting it — and prefer **precise scope wording over
> absolutes**. When you broaden a check (e.g. the `I-dod` trigger union), update **every** prose
> spot that enumerates it (SKILL.md, methodology.md, the schema `description`, the template, the
> CHANGELOG) in the same change, or the "coverage" claim silently drifts.

**AR-1 now has a dev-time backstop (Structured Spec Registry + Drift Checks, SSR).** The formerly
discipline-only "update every prose spot in the same change" clause is now **machine-checked at dev
time**: `scripts/spec_check.py` diffs the FSM tables and schema constants against a descriptive
registry (`spec/fsm.json` + `spec/invariants.json`) — **SC2** row-diffs the transition/invariant
tables against the registry, **SC4** dereferences each `(authoritative: <schema>#/<path>)` constant
pointer to its live schema value, **SC1** cross-checks every table label against the registry, and
**SC5** validates the embedded worked examples against their schemas. These are **diff / dereference /
presence checks that catch *drift*, not semantic proofs that a claim is *correct*** — the same
validity ≠ correctness boundary as the runtime validator (§4). They run under `scripts/run_tests.sh`
and add **no** runtime read: `spec/` and `spec_check.py` are **dev-time only**, never on the skill's
lazy-load path (SKILL.md is unchanged). So AR-1's "mirror" discipline now *fails a test* when a table row
or a constant pointer drifts, instead of resting solely on the author re-reading the construct.

*Why this rule exists:* adversarial verification once caught the `I-dod` trigger claiming to
"mirror the G-personas `post_p1` union" while enumerating a narrower set, and a debrief overstating
coverage as "ALL post-clarification states"; a reproduced non-reachable state falsified the absolute.
