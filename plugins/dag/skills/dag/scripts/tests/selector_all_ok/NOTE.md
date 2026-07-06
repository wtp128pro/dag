# Fixture: selector_all_ok (POSITIVE — the `all` selector is satisfiable)

The positive twin of `selector_all_gap`: proves the newly-enforced `all` selector PASSes when every
brief that the predicate covers lists the entry (widening enforcement must not make a compliant run
un-satisfiable).

Copy of `learnings_gap` with `L1.scope.applies_to = ["all"]` AND `units/U01/brief.json`
`learnings_applied = ["L1"]` (the only briefed unit lists it).

EXPECTED: exit 0 (RESULT: PASS), no traceback.
