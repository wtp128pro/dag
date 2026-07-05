# synthesis_no_dod — regression fixture for the SYNTHESIS.md leg of the DoD trigger

Proves the final hardening of the `I-dod` invariant: the trigger union includes **`SYNTHESIS.md`**,
so the presence of a synthesis artifact requires a Definition of Done + Non-Goals to have been
recorded — and, because the gate is **artifact-driven**, it fires even when the `phase` field is
under-reported to hide it.

## This fixture (a phase-under-report tamper, isolating the SYNTHESIS.md leg)
* `personas.json` + `fsm-state.json` with `phase` reported as `P2_CLARIFICATION` (only
  `personas_confirmed` true) — so the persona gate + gate ordering PASS and the post-decomposition
  `I3` DAG check does NOT fire (that would need a post-decomposition phase).
* `SYNTHESIS.md` — the sole post-clarification structural artifact, dropped in despite the
  under-reported phase.
* **NO `cartography.json`/`CARTOGRAPHY.md`, NO `graph.json`/`GRAPH.md`, NO `units/`, NO
  `clarifications.json`** — so `SYNTHESIS.md` is the ONLY thing that can fire `I-dod`.

## Expected
`validate_run.py` MUST reject this run: **exit 1, and the SOLE failing check is `I-dod`**:

```
FAIL  I-dod DoD/non-goals present: a post-clarification artifact (cartography / graph / units /
      synthesis) is present (Phase 3+) but no VALID clarifications.json carrying a non-empty
      definition_of_done + non_goals ...
```

Against a validator whose `require_dod` union OMITS `SYNTHESIS.md`, this directory PASSES (exit 0);
the flip to FAIL is the proof the SYNTHESIS.md leg is wired, and that a lied-down `phase` cannot hide
it. The trigger deliberately does NOT include `learnings.json` (a bookkeeping ledger sidecar that can
legitimately stand alone — see `bad_learnings/`, which carries a `learnings.json` and must NOT trip
`I-dod`); in a real pipeline `learnings.json` only appears mid-Phase-6 alongside the structural
artifacts that already fire this gate.
