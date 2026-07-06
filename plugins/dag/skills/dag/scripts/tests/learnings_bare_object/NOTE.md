# Fixture: learnings_bare_object (NEGATIVE)

Exercises the **bare-object learnings.json loader** fix (BRK-05 / N-24): a run-local `learnings.json`
that is a single bare ENTRY object (no `entries` key) was silently mapped to `[]` (no failure, a
bogus `SKIP I12 … no learnings.json present`), while the across-run store loader treated the
identical shape as `[raw]`. The loader now mirrors the store loader — a bare single-entry object is
wrapped as `[entry]` and loaded.

Copy of `learnings_gap` with `learnings.json` rewritten from `[ {L1…} ]` (bare array) to the bare
entry OBJECT `{L1…}`. BEFORE the fix this returned rc=0 with a `SKIP  I12` line (entry silently
dropped). After the fix the entry loads and the propagation gap is detected.

EXPECTED: exit 1 with `FAIL  I12 learnings propagation: units/U01 carries tag:core at wave 1 >=
since_wave 1: MUST list L1 in learnings_applied (has [])`, a `learnings.json non-canonical shape
tolerated` PASS line, and NO `SKIP I12 … no learnings.json present` line. No Python traceback.
