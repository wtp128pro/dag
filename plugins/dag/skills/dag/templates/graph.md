<!-- GRAPH.md — atomic work units + dependency DAG + wave ordering (output of Phase 4). -->

# Work Graph — <run label>

## Units
| ID | Title | Goal (single responsibility) | Executor persona | Verifier persona | Inputs (deps) | Tags (⊆ V_tag) | Outputs | Est. footprint | Acceptance criteria |
|----|-------|------------------------------|------------------|------------------|---------------|----------------|---------|----------------|---------------------|
| U01 | <…> | <…> | <persona> | <verifier> | none | `[research]` | <artifact> | <~k tokens> | <testable> |
| U02 | <…> | <…> | <persona> | <verifier> | U01 | `[schema, validator]` | <artifact> | <~k tokens> | <testable> |

Each unit's `Tags` are mirrored into its `brief.md` and drive pattern-scoped learning
propagation (a `"tag:<T>"`-scoped LEARNINGS entry force-injects into every unit carrying `T`).

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
