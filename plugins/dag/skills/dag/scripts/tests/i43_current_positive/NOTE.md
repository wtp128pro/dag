# Fixture: i43_current_positive (GREEN / positive-assertion control — spec §1.2, §1.6 P1-G1)

Byte-clone of `signoff_ok/` (phase `DONE`, all five gates true incl. `signoff_confirmed`,
`units/U01` debrief `iteration: 2` and aggregated verify `iteration: 2`, verdict PASS).

PROVES: P1's mandatory positive assertion (`P1-ok`) actually EMITS on the clean path. The pinned
substring is the success line, not the exit code, so a P1 that is silently skipped (materialization
arming misread, block never reached, guard too wide) FAILS this row instead of passing it. This is
the §0.7 rule that a GREEN control asserting only `exit == 0` is inadmissible for a
materialization-armed predicate.

EXPECTED: exit 0 AND stdout contains `I43 verification currency (units/U01: iteration 2 verified)`.

DOES NOT COVER: the aggregation channel (no `verify_p*.json` present, so it cannot catch an
implementation that reaches into panel-member files — §0.3); the multi-unit case; the `sorted()`
domain order; NOTE-severity output.

