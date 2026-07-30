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

Pinned substring is `RESULT: PASS` — the run must come out clean.

DOES NOT COVER: `verdict: "DISAGREE"` at sign-off, which §2.2 P2-e routes to an exit-neutral NOTE
(no fixture ships that arm); a current FAIL with `retries < 2` (an illegal early escalation, a
different class); the `I44` positive-assertion success line (§2.4), which this row does not pin.

