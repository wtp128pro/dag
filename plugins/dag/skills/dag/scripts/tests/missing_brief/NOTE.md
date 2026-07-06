# Fixture: missing_brief (NEGATIVE)

Exercises the **G-brief offline presence** check (BRK-03; T8 offline counterpart): a unit dir that
carries a debrief/verify but has no `brief.json` FAILs, because I5/I6/I11/I12/I16 all key off the
brief and SILENTLY skip a unit without it.

Copy of `good` with `units/U01/brief.json` deleted (debrief + verify kept). This is the EXACT probe
that returned rc=0 (RESULT: PASS) BEFORE the fix — the deletion silently disabled I12 for U01.

EXPECTED: exit 1 with the operative message
`FAIL  G-brief offline (units/U01): unit has a debrief/verify but NO brief.json — I5/I6/I11/I12/I16
all key off the brief and SILENTLY skip this unit without it` and no Python traceback. (Layer 1
fires; the run is at P6 so Layer 2's every-graph-unit rule does not apply.)
