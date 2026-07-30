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

EXPECTED (two rows, iteration 2): exit 1 AND a FAIL row labelled `I43 verification currency
(units/U01)`, **and** exit 1 with the detail substring `the verification is SUPERSEDED`. The second
row is the P1-a half of the direction discriminator §1.1 mandates ("the direction — `superseded` for
P1-a, `ahead of the debrief` for P1-b"); its twin lives on `i43_ahead_of_debrief`. Together they stop
an implementation that merged the two arms into one "iterations differ" FAIL from passing both dirs.
Note the pinned phrase is P1's own wording: P2's arm-d detail says "SUPERSEDED verification (the
verify does not adjudicate this debrief)", a different string, so the row cannot be satisfied by I44's
co-emitted row.

DOES NOT COVER: the `AHEAD` direction (see `i43_ahead_of_debrief`); the off-window-WITHOUT-sign-off
sub-case (this fixture is signed off, so P2 co-fires — an implementation that only ever fires under
sign-off still passes here); the FAIL detail-text ordering required by §1.1.

