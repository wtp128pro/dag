GREEN control pinning I41-3's `verdict == "PASS"` SCOPE GUARD (and, as a second pin, I41-6's own
`verdict == PASS` conjunct). A panel member records an UNDISPOSITIONED `major` and the top-level verdict
is FAIL. I41-3 exists because a mechanical majority may not absorb a member's blocker/major into a
**PASS**; under a FAIL the finding is not absorbed at all — the correction loop already carries it, and
demanding a disposition would mandate an adjudication record for every ordinary FAIL. Drop
`_top == "PASS"` from I41-3 and this fixture goes RED.

`panel_adjudication` is PRESENT (resolution `escalated-p7`), so ablating I41-1's PASS guard cannot flip
this fixture — the two scope guards stay separately attributable. `escalated-p7` + a FAIL verdict is
legal by I41-6 and pins that clause's PASS conjunct as well. I16 is satisfied: the discrete majority of
[FAIL, FAIL, PASS] is FAIL == the top verdict. Exit 0.
