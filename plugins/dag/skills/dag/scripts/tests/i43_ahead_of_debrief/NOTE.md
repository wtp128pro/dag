# Fixture: i43_ahead_of_debrief (RED — arm P1-b ALONE; spec §1.1, §1.6 P1-R3)

Phase `DONE`, all five DONE gates true. `debrief.iteration: 2`, aggregated `verify.iteration: 3` —
the verify attests to a LATER iteration than the debrief it adjudicates.

PROVES: the `AHEAD` arm is independently pinned. Per §1.1, no legal LT7 transient can put the
verify ahead of the debrief (LT7 increments `iteration` BEFORE the next `EXECUTE` writes its
debrief), so this direction closes the fabricated-bump class: either the debrief was rolled back
under a live verification, or the verify's `iteration` was authored rather than observed. A
`SUPERSEDED`-only implementation passes `i43_superseded_at_signoff` and silently passes THIS
fixture — exactly the L11 dropped-sub-clause shape, which is why the arm gets its own directory.

EXPECTED: exit 1 AND a FAIL row labelled `I43 verification currency (units/U01)` whose detail names
`ahead of the debrief`. (The pin is on the stem; the direction word is asserted by reading the row,
because `expectations.tsv` pins one substring and the stem is the stable, spec-mandated anchor.)

DOES NOT COVER: `AHEAD` INSIDE the in-flight window (P1-d should downgrade it to a NOTE there —
untested); the detail-text field ORDER; whether the direction word is spelled exactly as §1.1 says.

