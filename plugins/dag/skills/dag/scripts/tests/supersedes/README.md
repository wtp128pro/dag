# Fixture: supersedes (POSITIVE — 03/P5 supersedes exclusion, in-tree project store)

Proves the P5 contradiction/`supersedes` path (added in U03): a store entry declaring
`supersedes: "<id>"` EXCLUDES the superseded entry from propagation, and the superseding entry
takes over the scope. With the brief updated to list the superseding id, the run PASSes.

In-tree staging: `supersedes/.dag/learnings/L9.json` — `L9` is `tag:core`, `since_wave 1`,
`supersedes: "L1"` (the run-local `learnings.json` entry). At load time `L1` is excluded and `L9`
becomes the live `tag:core` lesson; `units/U01/brief.json` lists `L9` in `learnings_applied`, so
the I12 propagation predicate is satisfied.

Observed:
`PASS learnings contradiction (03/P5): L1 superseded — excluded from propagation`, then I12 PASSes
against `L9` => RESULT: PASS.

Note on the "no-supersedes contradiction" branch: two LIVE entries competing for the same scope
with NO `supersedes` ordering are surfaced as a NON-failing `NOTE contradiction (03/P5) … NOT
auto-picked` line (AO-5: a genuine split escalates to a human, it is deliberately NOT a rep.fail —
so there is no exit-1 fixture for that path; it never changes the verdict).

EXPECTED: exit 0 (RESULT: PASS). No `NOTE.md` (this is a positive fixture).
