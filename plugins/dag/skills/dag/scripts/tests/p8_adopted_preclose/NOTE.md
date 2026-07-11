# Fixture: p8_adopted_preclose (NEGATIVE CONTROL — I23 stays silent before P8/DONE)

Panel-fix-6 negative control for **I23 closure's phase gate**: the run is fully adopted —
every unit is bound (`dod_refs` + `non_goal_refs` keys on both units, refs verbatim, U01's
brief mirrors both lists; U02 has no unit dir at this phase, so no mirror applies), and the
only verdict-bearing verify carries a compliant `guardrail_compliance` block covering U01's
refs — I20/I21/I22 all green. One DoD item (item 2, "the schema self-check ...") is
DELIBERATELY not yet covered by any unit's `dod_refs`, exactly the state I23 would FAIL at
P8/DONE — but `fsm-state.json` sits at the pre-P8 phase `P6_EXECUTE_VERIFY` (unchanged from
`good/`), proving I23 is phase-gated reporting, not a mid-run tripwire.

EXPECTED: exit 0, `RESULT: PASS`, zero `I23 closure` lines, no Python traceback.
expectations.tsv row has the empty substring per the header convention.
