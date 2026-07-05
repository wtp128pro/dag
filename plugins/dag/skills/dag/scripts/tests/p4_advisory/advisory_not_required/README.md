# Fixture: p4_advisory/advisory_not_required (POSITIVE — 03/P4 advisory import not force-injected)

An imported cross-run learning that is NOT re-grounded is ADVISORY: loaded + citable, but its
omission from a brief NEVER FAILs I12.

Setup: the project store `.dag/learnings/L7.json` holds `L7` (`tag:core`, `since_wave 1`, **no**
`grounding`) — imported (store-loaded => in `store_ids`) and un-re-grounded => ADVISORY. The
run-local `learnings.json` holds `L1` (`tag:core`), which `U01/brief.json` lists in
`learnings_applied` (active + enforced, satisfied). `U01` carries `tag:core` at wave 1, so under
plain propagation `L7` would also be required — but 03/P4 partitions it into the advisory tier.

Observed:
`PASS advisory import (not force-injected): L7 …`, then
`PASS I12 learnings propagation (1 active entr(y/ies) … 1 advisory import(s) not force-injected (03/P4))`,
`RESULT: PASS`.

Load-bearing check (counterfactual, verified by U09): adding `grounding: "re-grounded"` to the
`L7` store file re-promotes it to ACTIVE and the run FAILs with `MUST list L7` (exit 1) — proving
the advisory demotion is what makes this run pass, not an unrelated gap.

EXPECTED: exit 0 (RESULT: PASS). No `NOTE.md` (this is a positive fixture).
