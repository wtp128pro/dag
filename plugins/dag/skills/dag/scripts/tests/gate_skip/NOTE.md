# gate_skip — negative fixture for gate-ordering enforcement

Exercises `REQUIRED_GATES`: a run reports `phase: P5_BRIEFING` but
`gates.decomposition_approved` is still `false` — i.e. it tried to reach briefing without the
Phase-4 decomposition gate. `validate_run.py` MUST reject this (exit non-zero) with a
**`gate ordering`** violation naming the missing `decomposition_approved` gate.

A valid `personas.json`, `graph.json`, and a DoD-bearing `clarifications.json` (non-empty
`definition_of_done` + `non_goals`) are included so the ONLY violation is the gate skip (persona
gate satisfied, DAG acyclic, no missing-verification, and the broadened `I-dod` DoD gate satisfied),
isolating the gate-ordering check. The `clarifications.json` is included because `graph.json` is a
post-clarification artifact, so the broadened `I-dod` trigger (any of cartography / graph / units / synthesis)
now fires here — supplying a valid DoD keeps `I-dod` green and preserves this fixture's single-defect
design.
Expected: exit 1, sole failure = `gate ordering`.
