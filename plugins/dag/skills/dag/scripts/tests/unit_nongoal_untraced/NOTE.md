# Fixture: unit_nongoal_untraced (NEGATIVE — I21 membership)

Exercises the **I21 unit non_goal_refs verbatim-membership clause**. Copied from `good/`,
otherwise valid — every unit carries the key (closure green: U02's `[]` is the explicit
none-applicable statement) and `units/U01/brief.json` mirrors the graph list (mirror green) —
so it does not trip anything for the wrong reason. Sole injected defect: U01's
`non_goal_refs` is `["ship telemetry"]`, a string NOT verbatim in `clarifications.json.non_goals`.

EXPECTED: exit 1 with the single operative failure
`FAIL I21 unit non_goal_refs (units/U01): not verbatim in non_goals: ['ship telemetry']`
and no Python traceback. expectations.tsv pins substring `I21 unit non_goal_refs`.
