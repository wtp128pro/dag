# unfenced_cycle — negative fixture for I3 DAG fail-closed (unfenced dependency graph)

Minimal fixture: a single `GRAPH.md` that declares U-id dependency arrows **outside** any code fence,
with **no** authoritative `graph.json` to back them. `validate_run.py` MUST reject it (exit 1).

## Intended / primary defect — I3 DAG fail-closed
The originally-declared defect still fires (two lines):

```
FAIL  I3 DAG fail-closed (E): GRAPH.md present but no VALID authoritative graph.json edge set ...
FAIL  I3 DAG fail-closed (E): GRAPH.md declares dependencies OUTSIDE a code fence and no graph.json
      backs them — 0 edges parsed; refusing to pass
```

## Accompanying (expected) failures
This is a bare structural fixture — it intentionally omits `personas.json`, `fsm-state.json`, and
`clarifications.json` — so two other fail-closed guards also fire, which is correct:

* **G-personas non-skippable** — post-Phase-1 work (`graph`) with no valid `personas.json`.
* **I-dod DoD/non-goals present** — `GRAPH.md` is a post-clarification artifact, so the
  broadened `I-dod` trigger (any of cartography / graph / units / synthesis) fires here with no DoD-bearing
  `clarifications.json` present.

Neither masks I3: the intended `I3 DAG fail-closed` violation remains the primary, operative defect and
still prints on every run. Expected: exit 1; primary defect = `I3 DAG fail-closed`.
