# Fixture: selector_unknown (NEGATIVE — BRK-08: an unknown selector kind is now a HARD FAIL)

Exercises the "unknown selector" branch (D-03(a)). Before this PR, any selector that was not `tag:`
was silently `continue`d — which is exactly how the doc/code drift stayed invisible. Now a selector
that is not one of `all | U0X | tag:T` is a hard FAIL. (`phaseN` was removed from the documented
vocabulary as unevaluable — BRK-09.)

Copy of `learnings_gap` with `L1.scope.applies_to = ["wave:2"]` (a schema-valid string, but not a
recognized selector kind).

BEFORE the fix: exit 0 (silently skipped). AFTER: exit 1.

EXPECTED: exit 1 with `FAIL  I12 selector: L1 scope.applies_to selector 'wave:2' is not a recognized
kind (all | U0X | tag:T) — `phaseN` was removed as unevaluable (BRK-09)`, no traceback.
