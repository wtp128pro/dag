GREEN control pinning I41-1's `verdict == "PASS"` SCOPE GUARD. A run stamped 1.11.0 (so T1 is armed)
whose verify records `verdict: FAIL` with two dissenting panel members and NO `panel_adjudication`.
Spec 2.4-I41-1 fires only on an aggregate PASS — a minority PASS under a FAIL majority is not a
laundering surface (spec 2.5 corner table, row "verdict == FAIL with a dissenting PASS member"), and the
ordinary correction loop already owns the FAIL. Drop `_top == "PASS"` from the implementation and this
fixture goes RED, which is what it pins.

The member defects are `minor` on purpose, so ablating I41-3's own PASS guard cannot flip this fixture
too (that arm is pinned separately by panel_major_on_nonpass_ok). I41-2 is satisfied: both dissenters
carry a defect with a non-blank criterion. I16 is satisfied: the discrete majority of
[FAIL, FAIL, PASS] is FAIL == the top verdict. Exit 0.
