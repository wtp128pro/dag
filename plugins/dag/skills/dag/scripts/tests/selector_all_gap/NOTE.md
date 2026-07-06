# Fixture: selector_all_gap (NEGATIVE — BRK-08: the `all` selector is now enforced)

Exercises the `all` disjunct of the I12 propagation predicate (D-03(a)). Before this PR the
validator enforced ONLY `tag:` selectors and SILENTLY skipped every other kind, so an `all`-scoped
learning that a brief omitted never FAILed — the doc/code drift BRK-08 describes.

Copy of `learnings_gap` with `L1.scope.applies_to = ["all"]` (graph has 2 units U01/U02, so `all` is
admissible). `units/U01/brief.json` (wave 1 >= since_wave 1) omits `L1` from `learnings_applied`.

BEFORE the fix: exit 0 (silently skipped). AFTER: exit 1.

EXPECTED: exit 1 with `FAIL  I12 learnings propagation: units/U01 matches selector all at wave 1 >=
since_wave 1: MUST list L1 in learnings_applied (has [])`, no traceback.
