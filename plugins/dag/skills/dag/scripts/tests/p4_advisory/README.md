# Fixture group: p4_advisory (03/P4 — imported cross-run learnings are ADVISORY until re-grounded)

Proves 03/P4: a learning IMPORTED from the across-run store (`.dag/learnings/`, or a global `G#`
id) is **ADVISORY** — loaded + citable but **never force-injected by I12** — until it is
**re-grounded** to a local signal in this run (top-level `grounding == "re-grounded"`). This ties
**AO-4**: an un-re-grounded import is not an external signal that binds briefs. Re-grounded imports
and every run-local authored entry stay in the **ACTIVE**, I12-enforced set.

Two run sub-directories (each is its own run dir — validate them individually):

- **`advisory_not_required/`** (POSITIVE, expect exit 0 / RESULT: PASS) — the store entry `L7`
  (`tag:core`, `since_wave 1`, **no** `grounding`) is imported and NOT re-grounded, so it is
  ADVISORY. `U01` carries `tag:core` at wave 1, so if `L7` were ACTIVE the I12 predicate would
  require `U01/brief.learnings_applied` to list it — but as an advisory import its omission never
  FAILs. `U01` lists only the run-local `L1` (which IS active + enforced). Observed:
  `PASS advisory import (not force-injected): L7 …`, then `RESULT: PASS`.
  *Load-bearing (counterfactual, verified by U09):* adding `grounding: "re-grounded"` to the `L7`
  store file flips the run to **exit 1** (`MUST list L7`), confirming the advisory demotion — not
  an unrelated gap — is what lets this run pass.

- **`regrounded_required/`** (NEGATIVE, expect exit 1 / RESULT: FAIL — see `NOTE.md`) — the SAME
  store entry `L7` but WITH `grounding: "re-grounded"`, so it is re-promoted to the ACTIVE set and
  fully I12-enforced. `U01` carries `tag:core` at wave 1 but its brief omits `L7`, so the run FAILs
  I12 (`MUST list L7`). Proves re-grounded imports stay enforced (AO-4 preserved on the active side).

In-tree staging mirrors `expiry_excluded`: the store lives at `<sub>/.dag/learnings/L7.json`; the
loader reads `<run_dir>/.dag/learnings/` (CARTOGRAPHY R6). Sibling sub-dirs do not cross-contaminate
(neither is a parent/grandparent of the other, and the `p4_advisory/` container has no `.dag/`).

Commands:
```
python3 ../../validate_run.py p4_advisory/advisory_not_required   # -> exit 0 (PASS)
python3 ../../validate_run.py p4_advisory/regrounded_required     # -> exit 1 (FAIL I12)
```
