# Fixture: i43_superseded_at_signoff (RED — pins the `I43` label stem)

Phase `DONE`, all five gates true including `signoff_confirmed: true`. `units/U01/debrief.json`
`iteration: 3`; the aggregated `units/U01/verify.json` `iteration: 2`, `verdict: "PASS"`. Both
schema-valid, `unit_id` matched. `loop.retries: 2` / `loop.iteration: 3` so I4's ceiling
(`iteration <= retries+1`) is satisfied and cannot mask the assertion.

PROVES: SUPERSEDED verification is caught off-window AND under sign-off. Spec §1.6 P1-R1 (arm P1-a)
and §2.5 P2-R2 (arm P2-d) deliberately OVERLAP on this witness and neither subsumes the other, so
the spec requires the case to assert on BOTH label stems. `expectations.tsv` carries one substring
per fixture directory, so the witness is shipped as two byte-identical directories —
`i43_superseded_at_signoff` pins `I43 verification currency (units/U01)` and
`i44_superseded_at_signoff` pins `I44 sign-off closure (units/U01)`. Asserting on exit 1 alone would
let a missing P2-d hide behind P1 (and vice versa) — the L11 dropped-sub-clause shape.

EXPECTED: exit 1 AND a FAIL row labelled `I43 verification currency (units/U01)`.

DOES NOT COVER: the `AHEAD` direction (see `i43_ahead_of_debrief`); the off-window-WITHOUT-sign-off
sub-case (this fixture is signed off, so P2 co-fires — an implementation that only ever fires under
sign-off still passes here); the FAIL detail-text ordering required by §1.1.

