# Fixture: signoff_missing (NEGATIVE — D-06(a)/BRK-13)

Exercises the **sign-off gate** (G-signoff / T12): a run at phase `DONE` MUST carry
`gates.signoff_confirmed: true`. D-06 adds `signoff_confirmed` to `validate_run.py`'s REQUIRED_GATES
for `DONE`, so a `DONE` run that never recorded the human sign-off is INVALID (fail-closed) — this is
the skip-the-human hole the flag closes.

Identical to `signoff_ok` (a complete single-unit `DONE` run, otherwise valid) EXCEPT its
`fsm-state.json` omits `gates.signoff_confirmed`. This is the exact probe that returned rc=0
(RESULT: PASS) BEFORE D-06 — the validator could not tell sign-off had not happened.

EXPECTED: exit 1 with the operative message
`gate ordering: phase DONE requires gates ['signoff_confirmed'] = true` (identical text on both
validator backends — it is a validate_run.py rep.fail, not a schema error). Twin: `signoff_ok`.
