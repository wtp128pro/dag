# Fixture: i43_inflight_before_signoff (GREEN over-fire control — the carve-out, spec §1.3/§1.6 P1-G2)

Phase `P6_EXECUTE_VERIFY`; `fsm.units[U01].status: "verifying"`; `gates.signoff_confirmed`
**ABSENT**. `debrief.iteration: 2`, aggregated `verify.iteration: 1` — i.e. `NOT CURRENT`, which per
§1.3 holds BY CONSTRUCTION at every legitimate `RETRY` (LT7 sets `iteration := iteration+1` on the
way into the next EXECUTE, so the newest verify still attests to N-1).

PROVES: the in-flight carve-out is EXIT-NEUTRAL before sign-off. A hard FAIL here would halt a
COMPLIANT orchestrator mid-loop — a validator predicate acting as a de-facto live guard on the
correction loop's sole back-edge, the LT7 hazard class of §6. This row therefore fails the suite if
P1 is implemented WITHOUT the `WINDOW` conjuncts.

Pinned substring is `RESULT: PASS` rather than empty: an absence assertion is not expressible in
`expectations.tsv`, so the row instead pins that the validator ran to completion and rendered a
clean verdict — a positive assertion that a crash inside a new block (§0.5 R6, crash-as-silent-
disabler) cannot satisfy.

EXPECTED: exit 0, no `I43` FAIL row. Twin: `i43_inflight_signoff_expired` (identical shape +
`signoff_confirmed: true` => FAIL). That PAIR is the discriminating witness of §1.3.

DOES NOT COVER: the `executing` half of the window (only `verifying` is exercised); the NOTE
emission itself (see `i43_inflight_signoff_false`); a `WINDOW`-true unit at a phase other than
`P6_EXECUTE_VERIFY`.

