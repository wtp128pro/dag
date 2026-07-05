# bad — kitchen-sink negative fixture (many independent defects)

Deliberately malformed on every axis; it is NOT a single-defect isolation fixture. `validate_run.py`
MUST reject it (exit 1). The intended, originally-declared defects all still fire:

* **Schema layer** — `fsm-state.json` `loop.retries: 5 > 2`; `units/U01/brief.json` missing
  `socratic_protocol` / `tags` / `learnings_applied` and `budget_tokens > 32000`;
  `units/U01/verify.json` missing `socratic` / `premise_check`, `executor_reasoning_seen != false`,
  `feedback.actionable_changes` missing, empty `defects`.
* **I3 DAG fail-closed / acyclicity** — `GRAPH.md` present with no authoritative `graph.json`, and the
  fenced edges form the cycle `U01 → U02 → U01`.
* **I7** — two options marked `recommended`.
* **G-personas non-skippable** — post-Phase-1 work (`graph`, `units`) with no valid `personas.json`.

## Note (broadened I-dod trigger)
Because this run carries `GRAPH.md` + a `units/` tree but no DoD-bearing `clarifications.json`, the
broadened **`I-dod`** DoD gate (trigger = any of cartography / graph / units / synthesis) now ALSO fires here:

```
FAIL  I-dod DoD/non-goals present: a post-clarification artifact (cartography / graph / units / synthesis) is
      present (Phase 3+) but no VALID clarifications.json ...
```

This is expected and correct — `bad` is a kitchen-sink negative, so `I-dod` simply joins the pile. It
**masks none** of the pre-existing defects above, every one of which still prints. No single check is
"the" defect here; the point is that a thoroughly-malformed run is rejected.
