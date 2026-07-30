# Fixture: i44_absent_verify_any_phase (RED — arm P2-a, and it pins *at ANY phase*; spec §2.2/§2.5 P2-R1)

Phase `P6_EXECUTE_VERIFY` — deliberately NON-terminal — with all five gates true INCLUDING
`signoff_confirmed: true`. `units/U01/debrief.json` present and schema-valid; `units/U01/verify.json`
**absent**. `fsm.units[U01].status: "verifying"` so pre-existing I9 emits its own in-flight NOTE
rather than a FAIL and cannot supply the exit code by itself.

PROVES: P2 has NO phase condition. §2.2 makes `SIGNED_OFF` the entire antecedent, and that is
load-bearing: the motivating run performed a deliberate `P8 -> P6` rollback while leaving
`signoff_confirmed: true`, so ANY phase-gated formulation
(`if phase in ("P8_SYNTHESIS","DONE")`) is inert on it — and passes this fixture. It also proves P2
carries NO in-flight carve-out: the unit is squarely inside the I9 window, yet `SIGNED_OFF` is the
exact negation of P1's carve-out conjunct, so a carve-out here would be self-cancelling.

EXPECTED: exit 1 AND a FAIL row labelled `I44 sign-off closure (units/U01)`.

DOES NOT COVER: arms P2-b (unusable verify) and P2-c (verify with no `verdict` key) — each needs its
own witness and neither is shipped here; the `N-I44 ... DISAGREE` NOTE arm (P2-e); multi-unit
`sorted()` domain order; the requirement that the detail text names the arm, both iterations, the fsm
status and the phase.

