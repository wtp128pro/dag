# Fixture: i44_closed_current_fail (GREEN over-fire control — a CURRENT FAIL is CLOSED verification)

Phase `P6_EXECUTE_VERIFY` with all five gates true including `signoff_confirmed: true` — the
post-rollback shape of §2.2 (the motivating run rolled `P8 -> P6` while leaving sign-off
recorded). `units/U01`: debrief
`iteration: 3`, aggregated verify `iteration: 3` (CURRENT) with `verdict: "FAIL"` carrying one
`major` defect and non-empty `feedback.actionable_changes` (so the FAIL is schema-VALID);
`fsm.units[U01].status: "escalated"`, `loop.retries: 2`. (Phase is NON-terminal because
pre-existing I10 forbids a non-PASS verdict at `DONE` — so this control also re-pins the
*at ANY phase* property of P2 from the GREEN side.)

PROVES: neither P1 nor P2 may demand `PASS`. Per CLARIFICATIONS row 1, *complete* means **CURRENT**,
not PASS: a unit legitimately holding a current FAIL at `retries == 2` exits via
`ESCALATE -> Phase 7`, and demanding PASS would be unsatisfiable for every escalated unit and would
pressure a run to MANUFACTURE a pass. `verdict == "FAIL"` is deliberately NOT an arm of P2 (§2.2) and
P1 never reads `verdict` at all (§1.4). Any implementation that adds a PASS conjunct exits 1 here.

**Iteration-2 repin (was `RESULT: PASS`).** §2.5 P2-G1 names the required substring outright — "the
`I44 sign-off closure (signoff_confirmed with N executed unit(s)…)` PASS row present" — and this
fixture emits it, measured: `PASS  I44 sign-off closure (signoff_confirmed with 1 executed unit(s);
all verified and current)`. Iteration 1 quoted that line in its own evidence table and called the
control "positively observable" while the harness pinned only `RESULT: PASS`, i.e. asserted an
observation the suite did not make. Now the row pins §2.4's positive assertion itself, so a P2 that
silently stops running on this substrate goes red instead of green.

EXPECTED (two rows): exit 0 AND stdout contains `I44 sign-off closure (signoff_confirmed with 1
executed unit(s); all verified and current)`; plus a must-NOT-contain row asserting
`FAIL  I44 sign-off closure` is absent.

DEVIATION FROM THE SPEC'S LITERAL FIXTURE TEXT, disclosed: §2.5 P2-G1 specifies a **two**-unit
population (U01 current-PASS + U02 current-FAIL at `retries: 2`) and therefore the wording "with **2**
executed unit(s)". This fixture ships **one** escalated unit, so it emits "with 1 executed unit(s)".
Arguably a stronger pin — there is no PASS unit to mask the FAIL one — but it is a deviation, and the
pinned substring is correspondingly `1`, not `2`.

DOES NOT COVER: `verdict: "DISAGREE"` at sign-off, which §2.2 P2-e routes to an exit-neutral NOTE
(now shipped as `i44_disagree_at_signoff`); a current FAIL with `retries < 2` (an illegal early
escalation, a different class); the two-unit population §2.5 P2-G1 specifies.

