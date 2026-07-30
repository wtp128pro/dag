# Fixture: i46_nonconverged_fail_verdict (GREEN over-fire control — the VERDICT boundary; spec §4.4 P4-G3)

Phase `P6_EXECUTE_VERIFY` with all five gates true including `signoff_confirmed: true` (a
non-terminal phase because pre-existing I10 forbids a non-PASS verdict at `DONE`);
`units/U01` debrief
`iteration: 3` / verify `iteration: 3` (CURRENT) with `verdict: "FAIL"`, `converged: false`, one
`major` defect, non-empty `actionable_changes`, `fsm.units[U01].status: "escalated"`,
`loop.retries: 2`.

PROVES: P4's arm is a CONJUNCTION — `verdict == "PASS"` **and** `converged is False`. Here the
`converged` conjunct holds and the verdict conjunct does not, and a non-converged FAIL is a coherent
ESCALATION INPUT, not a defect: the verifier is saying "I did not finish sweeping, and what I did
sweep failed." An implementation that drops the verdict conjunct (arming on `converged is False`
alone) exits 1 here.

Pinned substring is `RESULT: PASS`.

DOES NOT COVER: `verdict: "DISAGREE"` with `converged: false` (the third verdict value, unexercised);
a non-converged FAIL BELOW sign-off, where P4-a's NOTE must also stay silent.

