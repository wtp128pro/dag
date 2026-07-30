# Fixture: i43_ahead_of_debrief (RED — arm P1-b ALONE; spec §1.1, §1.6 P1-R3)

Phase `DONE`, all five DONE gates true. `debrief.iteration: 2`, aggregated `verify.iteration: 3` —
the verify attests to a LATER iteration than the debrief it adjudicates.

PROVES: the `AHEAD` arm is independently pinned. Per §1.1, no legal LT7 transient can put the
verify ahead of the debrief (LT7 increments `iteration` BEFORE the next `EXECUTE` writes its
debrief), so this direction closes the fabricated-bump class: either the debrief was rolled back
under a live verification, or the verify's `iteration` was authored rather than observed. A
`SUPERSEDED`-only implementation passes `i43_superseded_at_signoff` and silently passes THIS
fixture — exactly the L11 dropped-sub-clause shape, which is why the arm gets its own directory.

EXPECTED (two rows, iteration 2): exit 1 AND a FAIL row labelled `I43 verification currency
(units/U01)`, **and** exit 1 with the detail substring `the verification is AHEAD OF THE DEBRIEF`.
The second row is what actually discharges §1.6 P1-R3, whose expectation is "exit 1 with `I43
verification currency (units/U01)` **and a detail naming `ahead of the debrief`**". Until it landed,
this dir and `i43_superseded_at_signoff` pinned the IDENTICAL stem, so an implementation that merged
P1-a and P1-b into one "iterations differ" FAIL emitting the SUPERSEDED wording in both directions
passed both rows — losing §1.1's mandate that the detail name the direction. The symmetric row on
`i43_superseded_at_signoff` (`the verification is SUPERSEDED`) closes the other direction, so the two
dirs are now mutually discriminating. Two rows on one dir rather than a byte-clone dir: each
expectations row is an independent validator invocation, so a second row is how one substrate asserts
a second substring without incurring the clone-drift hazard.

DOES NOT COVER: `AHEAD` INSIDE the in-flight window (P1-d should downgrade it to a NOTE there —
untested); the detail-text field ORDER (§1.1's five-field sequence is still unpinned — the pinned
phrase is the direction word only).

