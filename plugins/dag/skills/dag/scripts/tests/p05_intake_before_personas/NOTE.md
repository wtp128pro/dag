# Fixture: p05_intake_before_personas (POSITIVE — BRK-06 / D-01(a): Phase-0.5 intake must not deadlock)

Proves the Phase-0.5 → G-personas deadlock (BRK-06) is fixed. SKILL.md Phase 0.5 step 5 folds
surviving cross-run imports into the run's `learnings.json` BEFORE Phase 1. The old validator counted
`learnings.json` as post-Phase-1 work (in `post_p1`), so G-personas FAILed on the intake write and
the run hard-stopped before the persona gate could ever happen. Per D-01(a), `learnings.json` is now
excluded from `post_p1` (ledger bookkeeping, not a work-graph artifact — matching the I-dod trigger's
rationale in the same file).

Contents: only bootstrap-seeded state — `fsm-state.json` at `P0_BOOTSTRAP` (no `personas.json`, no
gates set) — plus a valid `learnings.json` holding one imported advisory entry (`G1`).

BEFORE the fix: exit 1 with `FAIL G-personas non-skippable: run shows post-Phase-1 work ['learnings']
…`. AFTER the fix: `post_p1` is empty, so G-personas does not fire.

EXPECTED: exit 0 (RESULT: PASS), no Python traceback. `tests/gate_skip` and `tests/missing_personas`
still exit 1 — the gate still bites on real work-graph artifacts (clarifications/cartography/graph/
units/synthesis), only ledger bookkeeping stops tripping it.
