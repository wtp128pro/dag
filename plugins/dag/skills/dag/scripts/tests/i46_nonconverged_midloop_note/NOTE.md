# Fixture: i46_nonconverged_midloop_note (GREEN — the mid-run tier is exit-neutral; spec §4.3/§4.4 P4-G1)

Same shape as `i46_nonconverged_pass_at_signoff` (verify `verdict: "PASS"`, `converged: false`,
iterations matched at 2) but at phase `P6_EXECUTE_VERIFY` with `fsm.units[U01].status: "verifying"`
and `gates.signoff_confirmed` **ABSENT**.

PROVES: `converged: false` is a LEGAL mid-run state — a verifier that reaches its round cap without
convergence is reporting HONESTLY. An unconditional FAIL would criminalize a legal outcome and,
worse, would punish ADOPTION of an optional honesty field, creating an incentive to omit `converged`
entirely and inverting DoD 17's purpose. The pin is the NOTE line itself, so an implementation whose
mid-run tier is a silent `continue` fails this row rather than passing it (R4, silent-skip domains).

EXPECTED: exit 0 AND stdout contains `N-I46 non-converged PASS (units/U01)`.

DOES NOT COVER: `signoff_confirmed` present-and-`false` at the P4 tier boundary (only ABSENT is
exercised); the `--quiet` posture of the N-I46 NOTE.

