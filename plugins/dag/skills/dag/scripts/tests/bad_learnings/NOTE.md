# Fixture: bad_learnings (NEGATIVE)

Exercises the learnings.json schema/guard added in U04 (D01).

The run is otherwise valid — a schema-valid `personas.json` and `fsm-state.json`
(`gates.personas_confirmed=true`, phase `P2_CLARIFICATION`) so it does NOT trip
`G-personas` or `gate ordering` for the wrong reason. Its `learnings.json` carries a
single malformed entry: `since_wave` is the string `"x"` instead of an integer >= 1.

EXPECTED: the loader schema-validates the entry against `schemas/learnings.schema.json`
(`$defs.entry`), REPORTS it (`FAIL learnings.json[0]: $.since_wave: expected type
['integer'], got string`) and DROPS it before the I12 comparison — so the validator
exits 1 with a clean schema message and NO Python traceback.
