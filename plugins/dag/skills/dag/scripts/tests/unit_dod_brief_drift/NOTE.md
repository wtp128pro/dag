# Fixture: unit_dod_brief_drift (NEGATIVE — I20 brief mirror)

Exercises the **I20 unit dod_refs brief-mirror clause**. Copied from `good/`, otherwise valid —
all units bound (closure green) and BOTH lists' elements are verbatim members of
`definition_of_done` (membership green on graph and brief alike), so it does not trip anything
for the wrong reason. Sole injected defect: graph U01 `dod_refs` = [DoD item 1
("validate_run.py exits 0 ...")] while `units/U01/brief.json` `dod_refs` = [DoD item 2
("the schema self-check ...")] — the mirror drifted (sorted-inequality).

EXPECTED: exit 1 with the single operative failure prefixed
`FAIL I20 unit dod_refs (units/U01): brief mirror drift: brief.dod_refs`
and no Python traceback. expectations.tsv pins substring `I20 unit dod_refs`.
