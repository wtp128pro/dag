# Fixture: p4_advisory/regrounded_required (NEGATIVE — 03/P4 re-grounded import stays I12-enforced)

Proves the ACTIVE side of 03/P4: an imported cross-run learning that HAS been re-grounded to a
local signal (`grounding == "re-grounded"`) is re-promoted to the ACTIVE set and is fully
I12-enforced — a brief that carries its tag but omits it FAILs, exactly like a run-local entry.
This preserves AO-4 on the enforced side: re-grounding restores the external-signal binding.

The run is otherwise valid (schema-valid personas / clarifications with DoD + non_goals /
cartography / graph / fsm-state; run-local `L1` is `tag:core` and IS listed by `U01`, so it does
not trip for the wrong reason). Its sole defect: the project store `.dag/learnings/L7.json` holds
`L7` (`tag:core`, `since_wave 1`, **`grounding: "re-grounded"`**), which is therefore ACTIVE;
`units/U01` carries `tag:core` at wave 1 but `units/U01/brief.json` has
`learnings_applied: ["L1"]` (omits `L7`).

EXPECTED: exit 1 with the single operative message
`FAIL I12 learnings propagation: units/U01 carries tag:core at wave 1 >= since_wave 1: MUST list
L7 in learnings_applied (has ['L1'])` and no Python traceback.

Companion positive fixture: `../advisory_not_required/` (same `L7` WITHOUT `grounding` => advisory
=> PASS). The pair is the load-bearing A/B for 03/P4.
