# Fixture: regrounded_g_unlisted (NEGATIVE twin of regrounded_g_listed — enforcement still bites)

The negative twin of `../regrounded_g_listed/`: with the `learnings_applied` pattern widened to
`^[LG][0-9]+$`, a re-grounded global `G#` import that a tag-carrying unit OMITS must still FAIL I12
(widening the pattern must not weaken propagation enforcement).

Copied from `p4_advisory/regrounded_required/` with the project store entry renamed `L7 → G7`
(`grounding: "re-grounded"` → ACTIVE), and `units/U01/brief.json` left as `learnings_applied: ["L1"]`
(G7 NOT listed).

EXPECTED: exit 1 with the operative message
`FAIL I12 learnings propagation: units/U01 carries tag:core at wave 1 >= since_wave 1: MUST list G7
in learnings_applied (has ['L1'])` and no Python traceback. (A non-gating `NOTE contradiction (03/P5)`
about L1+G7 sharing tag:core is expected and harmless.)
