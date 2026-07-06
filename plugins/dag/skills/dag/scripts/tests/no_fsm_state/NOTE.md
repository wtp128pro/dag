# Fixture: no_fsm_state (NEGATIVE)

Exercises the **I2 ledger-is-truth** absence check (IMP-17): `fsm-state.json` is the durable FSM
state; if it is ABSENT but the run has produced other artifacts/units, the state is not on disk and
the run fails closed. (A truly empty run dir stays a no-op — `init_run.sh` seeds `fsm-state.json`, so
an empty dir means "not a run".)

Copy of `good` with `fsm-state.json` deleted. BEFORE the fix the absence itself was never flagged
(the run still failed, but only via G-personas because gates became unreadable — no explicit I2
line). After the fix the absence is named directly.

EXPECTED: exit 1 with `FAIL  I2 ledger-is-truth: fsm-state.json absent but run artifacts exist …`.
(A `G-personas` FAIL is also expected as a consequence — gates can't be read without the file — which
is correct and not a false positive.) No Python traceback.
