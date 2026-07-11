# Fixture: guardrail_row_unregistered (NEGATIVE — I22 membership)

Exercises the **I22 guardrail compliance verbatim-membership clause**: every row's `non_goal`
must be a VERBATIM `clarifications.json.non_goals` string. Copied from `good/`, otherwise
valid — the row is `respected` on a PASS verdict (semantic clause green), closure green (the
only verdict-bearing verify carries the block), coverage dormant (no `non_goal_refs`) — so it
does not trip anything for the wrong reason. Sole injected defect: the row names
`"ship telemetry"`, which is not in `non_goals`.

EXPECTED: exit 1 with the single operative failure
`FAIL I22 guardrail compliance (units/U01): rows name strings not verbatim in non_goals: ['ship telemetry']`
and no Python traceback. expectations.tsv pins substring `I22 guardrail compliance`.
