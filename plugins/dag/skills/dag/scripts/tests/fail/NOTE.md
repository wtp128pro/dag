# Fixture: fail (NEGATIVE)

Exercises the **I4 loop cross-check** (`self-learning-loops.md` §1.2 / state-machine.md I4):
`verify.iteration` must satisfy `iteration <= retries + 1`.

The run is otherwise valid — schema-valid `personas.json`, `clarifications.json` (with
`definition_of_done` + `non_goals`), `cartography.json`, `graph.json`, and `fsm-state.json`
(`gates.personas_confirmed=true`) — so it does NOT trip `G-personas`, `gate ordering`, `I3`, or
`I-dod` for the wrong reason. Its sole defect: `units/U01/verify.json` reports `iteration=2`
while `fsm-state.loop.retries=0`, so `iteration (2) > retries+1 (1)`.

EXPECTED: exit 1 with the single operative message
`FAIL I4 loop cross-check: U01 verify.iteration=2 > retries+1=1` and no Python traceback.
