# Fixture: unit_nongoal_partial (NEGATIVE — I21 adoption closure)

Exercises the **I21 unit non_goal_refs adoption-closure clause**: `[]` is a legal explicit
"no non-goal applies" statement, but an ABSENT key under adoption is a closure FAIL
(explicit-none vs forgot, made mechanical). Copied from `good/`, otherwise valid — U01
carries `non_goal_refs: []` in the graph AND mirrored in `units/U01/brief.json` (membership
and mirror green) — so it does not trip anything for the wrong reason. Sole injected defect:
U02 lacks the `non_goal_refs` key entirely while U01's presence triggered adoption.

EXPECTED: exit 1 with the single operative failure
`FAIL I21 unit non_goal_refs: adoption closure: units missing the non_goal_refs key: ['U02'] ([] is the explicit none-applicable statement)`
and no Python traceback. expectations.tsv pins substring `I21 unit non_goal_refs`.
