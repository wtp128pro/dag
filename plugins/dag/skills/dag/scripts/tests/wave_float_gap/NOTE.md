# Fixture: wave_float_gap (NEGATIVE)

Exercises the **I12 wave-as-float evasion** fix (BRK-04): JSON Schema `"type":"integer"` accepts
`1.0`, and the old propagation predicate did `not isinstance(w, int) → continue`, silently exempting
the unit. The validator now NORMALIZES a float-integral wave to `int` (`_as_int`) instead of
skipping.

Copy of `learnings_gap` with `units/U01/brief.json` `"wave": 1.0` (a float). Baseline `learnings_gap`
(integer `wave: 1`) is already exit 1; the same fixture with `wave: 1.0` returned rc=0 (RESULT: PASS)
BEFORE the fix — the evasion. After the fix it FAILs identically to the baseline.

EXPECTED: exit 1 with the same operative message as `learnings_gap`:
`FAIL  I12 learnings propagation: units/U01 carries tag:core at wave 1 >= since_wave 1: MUST list L1
in learnings_applied (has [])` and no Python traceback.
