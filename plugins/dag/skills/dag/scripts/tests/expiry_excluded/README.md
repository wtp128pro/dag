# Fixture: expiry_excluded (POSITIVE — 03/P3 expiry exclusion, in-tree project store)

Proves the across-run PROJECT learnings store (added in U03) plus the P3 expiry grammar: an
EXPIRED store entry is EXCLUDED from propagation, so a run that would OTHERWISE be forced to list
it via I12 now PASSes.

In-tree staging: the store lives at `expiry_excluded/.dag/learnings/L2.json` — the loader reads
`<run_dir>/.dag/learnings/` (CARTOGRAPHY R6 / Unknowns: the store is stageable INSIDE the fixture
run dir; verified reachable). `L2` is `tag:core`, `since_wave 1`, with `scope.expiry =
"date:2020-01-01"` (in the past). `U01` carries `tag:core` at wave 1, so if `L2` were LIVE the
I12 propagation predicate would require `U01/brief.learnings_applied` to list `L2` — but the past
expiry excludes it before the I12 block runs.

Observed:
`PASS learnings expiry (03/P3): L2 EXCLUDED from propagation (expiry 'date:2020-01-01' is in the
past)`, then I12 reverts to enforcing only the run-local `L1` (which U01 lists) => RESULT: PASS.

Load-bearing check (counterfactual, verified by U07): with the `date:` line removed L2 goes live
and the run FAILs I12 (`MUST list L2`), confirming the expiry — not an unrelated gap — is what
makes this run pass.

EXPECTED: exit 0 (RESULT: PASS). No `NOTE.md` (this is a positive fixture).
