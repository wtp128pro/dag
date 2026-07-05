# postdecomp_no_dod — regression fixture for the BROADENED DoD trigger (Attack E)

Reproduces the evasion the adversarial panel found against the iteration-1 mechanism and proves it
is now **closed**.

## The old evasion (Attack E)
The iteration-1 `I-dod` invariant keyed **only** on the cartography artifact
(`cartography.json` / `CARTOGRAPHY.md`). A run could therefore **delete cartography while keeping the
graph and unit tree** at a post-decomposition phase and ship with **no Definition of Done at all** —
`I-dod` never fired, so the run PASSED. Panel repro (against the old validator): `cp -R good E;
rm E/cartography.json E/clarifications.json; validate_run.py E` → **exit 0, RESULT: PASS**.

## This fixture
Built from `good/` with **both** `cartography.json` **and** `clarifications.json` removed, keeping the
post-decomposition structure:

* `fsm-state.json` — phase `P6_EXECUTE_VERIFY`, all gates true (a stale `cartography_done` gate with
  the artifact deleted — the exact tamper shape).
* `graph.json` + `GRAPH.md` — the dependency DAG.
* `units/U01/` — real per-unit work (brief/debrief/verify/disagreement).
* `personas.json`, `learnings.json` — so the persona gate, I9, I11, I12 all PASS.
* **NO `cartography.json`, NO `clarifications.json`** — i.e. genuinely no DoD/Non-Goals anywhere.

## Expected
`validate_run.py` MUST reject this run: **exit 1, and the SOLE failing check is `I-dod`**. The
broadened trigger (A8) fires on the surviving **graph / units** structure even though cartography is
gone:

```
FAIL  I-dod DoD/non-goals present: a post-clarification artifact (cartography / graph / units / synthesis) is
      present (Phase 3+) but no VALID clarifications.json carrying a non-empty definition_of_done +
      non_goals ...
```

Every other invariant (I3 DAG, I9 verification, I11 tags, I12 learnings, G-personas, gate ordering)
still PASSES — isolating the failure to the DoD gate. Against the OLD (cartography-only) validator
this same directory PASSES (exit 0); the flip from PASS→FAIL is the proof the evasion is closed.
