# Fixture: selector_unit_gap (NEGATIVE — BRK-08: the unit-id `U0X` selector is now enforced)

Exercises the unit-id disjunct of the I12 propagation predicate (D-03(a)). A `["U01"]`-scoped
learning binds exactly that unit (single-target, always admissible — no >=2-carrier re-proof). Before
this PR it was silently skipped (tag-only enforcement).

Copy of `learnings_gap` with `L1.scope.applies_to = ["U01"]`. `units/U01/brief.json` (wave 1 >=
since_wave 1) omits `L1`.

BEFORE the fix: exit 0. AFTER: exit 1.

EXPECTED: exit 1 with `FAIL  I12 learnings propagation: units/U01 is unit U01 at wave 1 >= since_wave
1: MUST list L1 in learnings_applied (has [])`, no traceback.
