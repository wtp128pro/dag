# missing_dod — negative fixture for the DoD / Non-Goals enforcement mechanism

Exercises the two complementary layers that make **Definition of Done** and **Non-Goals /
Guardrails** mechanically-enforced clarification outputs. `clarifications.json`
here is well-formed in every other respect but **omits `definition_of_done` and `non_goals`**, while
`cartography.json` is present (i.e. the run is past clarification, Phase 3+).

`validate_run.py` MUST reject this (exit 1). Both DoD layers fire, and **every** printed failure is
the DoD/Non-Goals defect — no unrelated check trips:

1. **Schema layer** — `clarifications.schema.json` lists the two fields as `required` (non-empty
   arrays), so schema validation prints:
   - `FAIL  clarifications.json: $: missing required property 'definition_of_done'`
   - `FAIL  clarifications.json: $: missing required property 'non_goals'`
2. **FSM-invariant layer** — the artifact-driven **`I-dod DoD/non-goals present`** check: because the
   file is schema-invalid it never lands in `docs`, so with a post-clarification artifact present
   (here cartography **and** graph) the invariant prints:
   - `FAIL  I-dod DoD/non-goals present: a post-clarification artifact (cartography / graph / units / synthesis) is present (Phase 3+) but no VALID clarifications.json …`

The sibling files (`personas.json`, `fsm-state.json`, `graph.json`, `GRAPH.md`, `cartography.json`)
are copied from `good/` so the persona gate, gate ordering, and DAG checks all PASS — isolating the
failure to the DoD/Non-Goals mechanism.

**Expected: exit 1; the sole failing FSM invariant is `I-dod`, corroborated by the schema layer's
two missing-required-property failures on the same two fields. All three failures are the DoD/Non-Goals
defect.**
