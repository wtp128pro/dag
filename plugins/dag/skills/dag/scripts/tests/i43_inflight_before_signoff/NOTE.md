# Fixture: i43_inflight_before_signoff (GREEN over-fire control — the carve-out, spec §1.3/§1.6 P1-G2)

Phase `P6_EXECUTE_VERIFY`; `fsm.units[U01].status: "verifying"`; `gates.signoff_confirmed`
**ABSENT**. `debrief.iteration: 2`, aggregated `verify.iteration: 1` — i.e. `NOT CURRENT`, which per
§1.3 holds BY CONSTRUCTION at every legitimate `RETRY` (LT7 sets `iteration := iteration+1` on the
way into the next EXECUTE, so the newest verify still attests to N-1).

PROVES: the in-flight carve-out is EXIT-NEUTRAL before sign-off. A hard FAIL here would halt a
COMPLIANT orchestrator mid-loop — a validator predicate acting as a de-facto live guard on the
correction loop's sole back-edge, the LT7 hazard class of §6. This row therefore fails the suite if
P1 is implemented WITHOUT the `WINDOW` conjuncts.

**Iteration-2 repin (was `RESULT: PASS`).** §1.6 P1-G2 requires BOTH variants — `signoff_confirmed`
absent AND present-and-`false` — to assert "an `N-I43 verification currency (in-flight)` NOTE row".
Only the `false` variant was mechanically pinned; the absent variant sat on `RESULT: PASS` even
though it emits, verbatim, `NOTE  N-I43 verification currency (in-flight) (units/U01):
debrief.iteration=2 vs aggregated verify.iteration=1 (fsm status verifying at P6,
gates.signoff_confirmed=None)`. Pinning that NOTE is a **strict** strengthening — col 2 = `0`
already forbids any FAIL row, so nothing is traded away — and it is what closes the silent-`continue`
mode §0.7 declares inadmissible: if the carve-out degenerated into a bare `continue` for the absent
case, a `RESULT: PASS` row would stay green.

EXPECTED (two rows): exit 0 AND stdout contains `N-I43 verification currency (in-flight) (units/U01)`;
plus a must-NOT-contain row asserting `FAIL  I43 verification currency` is absent. Twin:
`i43_inflight_signoff_expired` (identical shape + `signoff_confirmed: true` => FAIL). That PAIR is the
discriminating witness of §1.3.

DOES NOT COVER: the `executing` half of the window (only `verifying` is exercised); the NOTE
emission itself (see `i43_inflight_signoff_false`); a `WINDOW`-true unit at a phase other than
`P6_EXECUTE_VERIFY`.

