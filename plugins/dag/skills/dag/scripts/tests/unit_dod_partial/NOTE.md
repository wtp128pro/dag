# Fixture: unit_dod_partial (NEGATIVE — I20 adoption closure)

Exercises the **I20 unit dod_refs adoption-closure clause**: once ANY graph unit carries
`dod_refs`, EVERY unit must. Copied from `good/`, otherwise valid — U01's ref is verbatim in
`definition_of_done` (membership green) and `units/U01/brief.json` mirrors it (mirror green) —
so it does not trip anything for the wrong reason. Sole injected defect: U01 is bound while
U02 lacks the `dod_refs` key entirely (adoption fired, closure broken).

EXPECTED: exit 1 with the single operative failure
`FAIL I20 unit dod_refs: adoption closure: units missing dod_refs: ['U02']`
and no Python traceback. expectations.tsv pins substring `I20 unit dod_refs`.
