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

**Iteration-2 repin (was `RESULT: PASS`).** The substrate DOES carry a `converged` key, so §4.2's
adoption-scoped positive assertion fires and was left unasserted. Measured: `PASS  I46 non-converged
PASS (1 verify doc(s) declare converged; none is a non-converged PASS)`. Pinning it makes the row
catch a P4 that silently stops running here — the R4 silent-skip domain §0.7's last bullet declares
inadmissible — and costs nothing, since col 2 = `0` already forbids any FAIL row.

EXPECTED (two rows): exit 0 AND stdout contains `I46 non-converged PASS (1 verify doc(s) declare
converged`; plus a must-NOT-contain row asserting the PER-UNIT row `I46 non-converged PASS
(units/U01)` is absent. Note the two are compatible on purpose: §4.4 P4-G3's "no `I46` row" means no
**per-unit** row — §4.2's aggregate `rep.ok` row still emits and is the thing being pinned.

DOES NOT COVER: `verdict: "DISAGREE"` with `converged: false` (the third verdict value, unexercised);
a non-converged FAIL BELOW sign-off, where P4-a's NOTE must also stay silent.

