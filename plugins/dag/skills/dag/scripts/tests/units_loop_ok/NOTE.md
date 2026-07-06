# Fixture: units_loop_ok (POSITIVE — D-02/IMP-11)

Proves the per-unit `fsm-state.units[]` loop record is accepted when consistent. Copied from
`good/`; its **sole** change: each `units[]` item now carries the optional per-unit `retries` +
`loop_state` (D-02/IMP-11) — the durable substate that a single top-level `loop` slot cannot hold
for >1 in-flight unit during parallel waves.

- `U01`: `{ retries: 1, loop_state: "DONE" }`; `units/U01/verify.json` reports `iteration=2`, and
  `2 <= retries+1 = 2`, so the new **`I4 units[] cross-check`** runs and PASSES.
- `U02`: `{ retries: 0, loop_state: "EXECUTE" }`; still in flight (no `verify.json`), so its
  cross-check is skipped — demonstrating the field is durably recorded *before* verification.

The top-level `loop` slot is unchanged (back-compat snapshot of the last-transitioned unit).

EXPECTED: exit 0 (RESULT: PASS). Twin: `units_loop_overrun`.
