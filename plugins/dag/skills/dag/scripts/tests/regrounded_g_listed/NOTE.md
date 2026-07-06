# Fixture: regrounded_g_listed (POSITIVE — BRK-01: a re-grounded G# import is listable in a brief)

Proves the loop that BRK-01 made impossible now closes: a re-grounded GLOBAL (`G#`) import is
force-injected by I12 AND is listable in a brief's `learnings_applied`. Before the fix,
`brief.schema.json`'s `learnings_applied` pattern was `^L[0-9]+$`, so listing `"G7"` made the brief
schema-INVALID even though I12 required it — the two mirrors were jointly unsatisfiable. The pattern
is now `^[LG][0-9]+$`.

Copied from `p4_advisory/regrounded_required/` with the project store entry renamed `L7 → G7`
(`.dag/learnings/G7.json`, `id: "G7"`, still `grounding: "re-grounded"` → ACTIVE/I12-enforced) and
`units/U01/brief.json` `learnings_applied` set to `["G7", "L1"]`.

BEFORE the fix: exit 1 with `$.learnings_applied[0]: 'G7' does not match pattern '^L[0-9]+$'`
(the brief is schema-invalid, so I12 can never be satisfied). AFTER the fix: exit 0 — `G7` validates,
U01 lists both its tag:core entries, and I12 passes.

EXPECTED: exit 0 (RESULT: PASS). A non-gating `NOTE contradiction (03/P5)` about L1+G7 sharing
`tag:core` is expected and harmless (two live entries, no supersedes ordering). Negative twin:
`../regrounded_g_unlisted/`.
