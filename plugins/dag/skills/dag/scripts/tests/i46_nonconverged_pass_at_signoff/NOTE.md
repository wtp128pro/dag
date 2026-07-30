# Fixture: i46_nonconverged_pass_at_signoff (RED — arm P4-b; spec §4.1/§4.4 P4-R1)

Phase `DONE`, all five gates true including `signoff_confirmed: true`. `units/U01/verify.json`
`verdict: "PASS"` with `converged: false`, `iteration: 2` MATCHING the debrief's `iteration: 2` — the
iterations are matched deliberately so P1 stays silent and the assertion is unambiguous.

PROVES: under a claimed sign-off, a unit whose OWN verification declares its coverage incomplete is
verification left unfinished, and that is a hard FAIL (DECISIONS ruling 29: NOTE below sign-off,
**FAIL at sign-off** — not FAIL always, not NOTE only). It also makes an optional honesty field stop
being dead data (DoD 17).

EXPECTED: exit 1 AND a FAIL row labelled `I46 non-converged PASS (units/U01)`.

DOES NOT COVER: `verify_rounds` in the detail text (absent here, and §4.1 requires it be named only
*if present*); the §2.3 `accepted_incomplete` downgrade applied to an I46 FAIL (§4.3 says the SAME
override applies per unit to P4 — no fixture ships that composition); multi-unit domain order.

