# Fixture: units_loop_overrun (NEGATIVE — D-02/IMP-11)

Exercises the **`I4 units[] cross-check`** (state-machine.md §1a/§2a, I4): when an
`fsm-state.units[]` item records its own per-unit `retries`, the unit's `verify.iteration` must
still satisfy `iteration <= retries + 1` — the same I4 bound the top-level `loop` slot enforces,
now extended to every parallel-wave unit that records its own count.

Copied from `good/`. The failing unit is caught by the **units[] record, not the `loop` slot**:

- `loop` points at `U02` (`state: EXECUTE`, the currently-transitioning wave-2 unit); `U02` has no
  `verify.json`, so the loop-slot cross-check is skipped — it does NOT mask the defect.
- `units[]` `U01` records `{ retries: 0, loop_state: "DONE" }`, but `units/U01/verify.json` reports
  `iteration=2`, so `iteration (2) > retries+1 (1)`.

This is exactly the durable inconsistency D-02/IMP-11 makes representable: U01's per-unit record
claims zero retries while its verify shows a second attempt. `iteration=2` is under the universal
`I4 iteration ceiling` (>3), so ONLY the new per-unit `units[]` cross-check catches it.

EXPECTED: exit 1 with the single operative message
`FAIL I4 units[] cross-check (units/U01): verify.iteration=2 > retries+1=1 (fsm units[] retries=0)`
and no Python traceback. Twin: `units_loop_ok`.
