# Fixture: learnings_gap (NEGATIVE)

Exercises the **I12 learnings-propagation** predicate (`self-learning-loops.md` §4.3): a unit
whose wave is `>= since_wave` and which carries a learning's `tag:T` scope MUST list that
learning's id in its brief's `learnings_applied`.

The run is otherwise valid — schema-valid `personas.json`, `clarifications.json`
(DoD + non_goals), `cartography.json`, `graph.json`, `fsm-state.json`
(`gates.personas_confirmed=true`) and a well-formed `learnings.json` — so it does NOT trip
`G-personas`, `gate ordering`, `I3`, or `I-dod` for the wrong reason. Its sole defect:
`learnings.json` entry `L1` is `tag:core`-scoped from wave 1, and `units/U01` carries `tag:core`
at wave 1, but `units/U01/brief.json` has `learnings_applied: []` (omits `L1`).

EXPECTED: exit 1 with the single operative message
`FAIL I12 learnings propagation: units/U01 carries tag:core at wave 1 >= since_wave 1: MUST list
L1 in learnings_applied (has [])` and no Python traceback.
