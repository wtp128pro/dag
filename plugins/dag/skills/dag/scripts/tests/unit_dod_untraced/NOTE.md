# Fixture: unit_dod_untraced (NEGATIVE — I20 membership)

Exercises the **I20 unit dod_refs verbatim-membership clause** (validate_run.py, guardrails
1.8.0 family A, offline post-hoc). Copied from `good/`, otherwise valid — all units are bound
(closure green: U01 and U02 both carry `dod_refs`) and `units/U01/brief.json` mirrors the graph
list verbatim (mirror clause green; U02 has no unit dir, so no mirror applies) — so it does not
trip anything for the wrong reason. Sole injected defect: graph U01's `dod_refs` is
`["polish the docs"]`, a string NOT verbatim in `clarifications.json.definition_of_done`.

EXPECTED: exit 1 with the single operative failure
`FAIL I20 unit dod_refs (units/U01): not verbatim in definition_of_done: ['polish the docs']`
and no Python traceback. expectations.tsv pins substring `I20 unit dod_refs`.
