# Fixture: done_missing_unit (NEGATIVE)

Exercises the **I10 synthesis/DONE completeness** rescope (BRK-02): at `P8_SYNTHESIS`/`DONE` the
validator iterates the GRAPH's declared units — not just the dirs that happen to carry a debrief —
so deleting a unit's `debrief.json`+`verify.json` can no longer make it INVISIBLE at DONE.

Copy of `good` with `fsm-state.json.phase` set to `DONE` and
`units/U01/{debrief,verify,disagreement}.json` deleted (`brief.json` kept, so `units/` is still a
materialized sidecar tree → the completeness check is in scope). `U02` is a graph unit that has no
dir at all (inherited from `good`), so it is also flagged.

This is the EXACT probe that returned rc=0 (RESULT: PASS) BEFORE the fix.

EXPECTED: exit 1 with `FAIL  I10 synthesis completeness (units/U01)` (no debrief / no valid
verify.json) and `FAIL  I10 synthesis completeness (units/U02)` (no units/U02/ directory), plus a
`G-brief offline (units/U02)` line (U02 also lacks a brief at DONE). No Python traceback.
