# Fixture: missing_verify (NEGATIVE)

Exercises the **I9 missing-verification** rejection (state-machine.md I9): every unit dir that
has a debrief MUST also have a `verify.json` carrying a verdict — an unverified unit is rejected
(closes the "executor self-passes" hole).

The run is otherwise valid — schema-valid `personas.json`, `clarifications.json`
(DoD + non_goals), `cartography.json`, `graph.json`, `fsm-state.json`
(`gates.personas_confirmed=true`) — so it does NOT trip `G-personas`, `gate ordering`, `I3`, or
`I-dod` for the wrong reason. Its sole defect: `units/U01/` has a `debrief` but no `verify.json`.

EXPECTED: exit 1 with the single operative message
`FAIL I9 missing verification (units/U01): unit has a debrief but NO verify.json` and no Python
traceback.
