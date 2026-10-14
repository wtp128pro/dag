<!-- GRAPH.md — atomic work units + dependency DAG + wave ordering (output of Phase 4). -->

# Work Graph — <run label>

## Units
| ID | Title | Goal (single responsibility) | Executor persona | Verifier persona | Inputs (deps) | Tags (⊆ V_tag) | DoD refs (verbatim ⊆ DoD) | Non-goal refs (verbatim ⊆ non-goals; `[]` = none apply) | Outputs | Est. footprint | Acceptance criteria |
|----|-------|------------------------------|------------------|------------------|---------------|----------------|---------------------------|--------------------------------------------------------|---------|----------------|---------------------|
| U01 | <…> | <…> | <persona> | <verifier> | none | `[research]` | `["<verbatim definition_of_done item>"]` | `[]` | <artifact> | <~k tokens> | <testable> |
| U02 | <…> | <…> | <persona> | <verifier> | U01 | `[schema, validator]` | `["<verbatim definition_of_done item>"]` | `["<verbatim non_goals item>"]` | <artifact> | <~k tokens> | <testable> |

Each unit's `Tags` are mirrored into its `brief.md` and drive pattern-scoped learning
propagation (a `"tag:<T>"`-scoped LEARNINGS entry force-injects into every unit carrying `T`).

## Per-unit deliverable class (`deliverable` — emit on EVERY unit, 1.14.0)

Every unit carries **`deliverable`**: `"ships"` or `"informs"`, written **here, by the planner**.

- **`ships`** — the unit's `outputs[]` include at least one path **outside** the run directory: a
  change to the thing the human asked about.
- **`informs`** — it produces a finding, a measurement, a document section or a decision input, and
  nothing the human asked for changes when it lands.

Writing it at plan time is the whole point: the deliverable clock (`I54`) and the starvation cap
(`I56`) are then computable **before** the units run and **without trusting the agent being
counted**. Once any unit carries it, every unit must — a counter over a partly-labelled population
reads LOW, which is worse than no counter.

**Be honest here.** An `informs` unit is not a lesser unit, and the temptation runs the other way:
labelling investigation `ships` disarms the only mechanism that can see a run spending itself on
itself. Note what no predicate checks — the label's *correctness*. `I54-1` requires the value to be
present and `I54-2` recomputes the counter from the same labels, so a **consistent mislabelling is
invisible to both**. What the design buys is legibility, not enforcement: an `informs` streak that
reaches the cap with no dossier is a detectable FAIL, and a mislabelled `ships` unit is a claim about
the run's own deliverable that a maintainer reading `graph.json` can contradict.

## Per-unit DoD / non-goal binding (`dod_refs` / `non_goal_refs` — emit on EVERY unit)
Every unit row above carries **`dod_refs`** and **`non_goal_refs`**, mirrored into `graph.json`'s
unit objects and each unit's `brief.json` sidecar (the scaffolded default — do not delete them):
- **`dod_refs`** (array, ≥ 1 item): the `clarifications.json definition_of_done` items this unit
  serves — each element **verbatim**. Every unit must trace to at least one DoD item
  (no orphan work; no DoD item left unowned at closure).
- **`non_goal_refs`** (array, MAY be `[]`): the `non_goals` items this unit must actively respect —
  each element **verbatim**. `[]` is the explicit, distinguishable "no non-goal applies to this
  unit" statement; an *absent* key is not — explicit-none vs forgot is mechanical.

Enforced offline post-hoc by validate_run.py **I20**/**I21** (adoption-closure): once ANY unit
carries the field, EVERY unit must; each element must be verbatim-membership-checked against the
register array; and when `units/<id>/brief.json` exists it must mirror the graph unit's set.

## Per-unit write scope (`frame` — 1.15.0 blast radius; every `ships` unit declares one)
A unit's **`frame`** is its declared write scope, frozen **here** at Phase 4 and mirrored verbatim
into the unit's `brief.json` (and its brief.md "Frame" section). Schema-optional, so archived graphs
stay valid; once present, the three lists are required and the object is closed. It carries no key
that switches a blast check off.
- **`modifies`** (array of path patterns, workspace-relative): the only repository paths the unit
  may create, edit or delete. Patterns use the `frame_match.py` language: `*` and `?` never cross
  `/`; a whole `**` segment matches zero or more segments; a glob-free pattern, or one ending in `/`
  or `/**`, covers everything beneath it; absolute paths and `..` segments are invalid.
- **`immutable`** (array of path patterns): paths the unit must never touch.
- **`intended_changes`** (array of prose): the behaviour changes the unit is expected to cause — the
  text an integration difference (a regression differential or a test-weakening row) must cite
  **verbatim** via `integrate.py --explain`.
- **`modifies_none_reason`** (string): why `modifies` is deliberately empty — an `informs` unit that
  changes no repository path. No validator predicate reads it: it is the stated explanation, and
  `I60-5` checks the observable part (an `informs` unit's footprint has no changes).

Example: `"frame": {"modifies": ["src/parser.py", "docs/**"], "immutable": ["schemas/**"],
"intended_changes": ["parse_row() is replaced by parse_rows(), which accepts a trailing comma"]}`.

Enforced offline, post-hoc, by validate_run.py on runs stamped 1.15.0 or later: **`I60`** (a `ships`
unit declares a non-empty `modifies` of valid patterns, `brief.json` carries the same frame
(compared with each list sorted), its repo-path `outputs[]` lie inside `modifies`, and every path its captured
`units/<id>/footprint.json` changed matches `modifies` and no `immutable` pattern) and **`I61`** (no
two units of one wave share a captured path; `unattributed` is empty; the exit-neutral `N-I61` NOTE
names two same-wave units whose `modifies` patterns can match a common path). Before dispatch,
`python3 frame_match.py overlap <graph.json>` prints every pair of units with no dependency path
either way whose `modifies` overlap — keep such pairs out of one wave or add an edge. These checks
compare what a capture recorded with what a frame declared: declared, visible surfaces, not
semantic conflicts between files that never share a path. A consumer outside the frame that the
unit breaks is a finding routed to an amendment or ESCALATE, never an in-place edit beyond the
frame. Artifact formats: templates/blast.md.

## Tag vocabulary (`V_tag` — the enumerated registry; extend only by editing this list)
```
V_tag = { research, schema, validator, code, template-edit, prose-edit,
          design, verification, loop, socratic, synthesis, ops, high-stakes }
```
Tags are the *only* mechanical basis for pattern-scoped learning propagation
(references/self-learning-loops.md §4.2). A `"tag:<T>"` LEARNINGS scope is admissible only if
**≥ 2 units** carry `T` (the generalizability gate) — a tag on a single unit fails admission.
**`high-stakes`** additionally carries an operational meaning (PR1 verifier hardening): a unit
tagged `high-stakes` is verified by the **default odd panel of 3** with distinct lenses, and its
`verify.json` MUST carry that `panel[]` — enforced post-hoc by validate_run.py **I16**
(references/methodology.md §Verification; references/self-learning-loops.md §3).

## LEARNINGS entry schema (what each row of LEARNINGS.md must carry — req 12)
`id · trigger` (external signal, e.g. a verify verdict / test / cited finding) `· lesson ·
how_to_apply · scope{ applies_to: SelectorSet (required), excludes:[unit-id] (optional),
expiry: run|project|runs:N|date:<iso> (optional) } · evidence · since_wave · promotable: bool (optional)`.
`since_wave` is an int ≥ 1 — the wave from which the entry binds later briefs (propagation
predicate `U.wave ≥ since_wave`).
`applies_to` selectors: `all` / `"U0X"` / `"tag:<T>"` — the three validator-enforced kinds (an
unrecognized kind is a hard `I12 selector` FAIL; the old `"phaseN"` kind was removed as unevaluable —
BRK-09). **Propagation
rule:** any brief for a unit the entry's scope matches **and whose `wave ≥ since_wave`** MUST
list the `id` in `learnings_applied` and quote `lesson` + `how_to_apply` (validator-checked; see
references/self-learning-loops.md §4.3).

## Dependency DAG (edge A→B = B consumes A)
```
U01 → U02
U01 → U03
U02, U03 → U04
```
(no cycles — verified). **Also emit `graph.json`** (the machine-readable sidecar) beside this
file: the validator parses it fail-closed — an unparseable or empty graph is *rejected*, not
waved through (a missing or unverifiable DAG blocks the run).

## Wave ordering (units in a wave are independent → run in parallel)
- **Wave 1:** U01
- **Wave 2:** U02, U03
- **Wave 3:** U04

## Critique-pass findings (2nd persona)
- Missing edges? <…>  · Cycles? <none>  · Over/under-atomized? <…>  · Any unit > 32K? <re-split which>

## Budget audit
- Every unit's estimated footprint ≤ 32K after atomization? <yes | re-split list>

## Fuel budget (Bounded Graph Amendments)
- `expansion.fuel_initial` = <default `min(N0, 8)`; `0`/absent = BGA off>.
  This bounds how many graph amendments Phase 6 may make when executed work surfaces unknowns.
  (Decomposition is a **linear self-critique** phase — NOT one of the three human gates, D-C/U2 — so
  this default stands unless the user gave an explicit fuel instruction at an earlier gate; there is no
  separate "adjust fuel" human touchpoint here.)

## Amendments (appended in Phase 6 — only if the graph is amended)
When executed work surfaces an unknown, the graph may grow under mechanical constraints. Record each
amendment as `amendments/A<NN>.json` (the authoritative append-only record) **and** as one row here:
| Amendment | Kind | Origin (trigger) | Fuel cost | Units added | Units retired | DoD refs |
|-----------|------|------------------|-----------|-------------|---------------|----------|
| A01 | add_units | debrief_handoff (U0X) | 1 | U0Y | — | `<verbatim definition_of_done item>` |
| A02 | split_unit | footprint_breach (U0Z) | 1 | U0P, U0Q | U0Z | `<verbatim definition_of_done item>` |

`graph.json` stays authoritative and is **regenerated** after each amendment: `revision`+1,
`amendments_applied` lists the `A<NN>` ids in order, `retired_units` records `{id, replaced_by[],
amendment}`. Fuel: `expansion.fuel_remaining = fuel_initial − Σ fuel_cost ≥ 0` (each amendment costs
`max(1, |units_added| − |units_retired|)`; validate_run.py **I18**). Kinds:
`add_units`/`split_unit`/`add_edges` (autonomous, DoD-traced) · `cancel_unit` (human-gated). Only the
**not-yet-started future** is amendable — a unit whose correction loop has begun is frozen (**I17**).
See SKILL.md Phase 6 "Graph amendments (bounded)", `schemas/amendment.schema.json`, and
`templates/amendment.json`.
