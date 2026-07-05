# Fixture: ao2_disjoint (POSITIVE — I14 / I15 pass branch with real defects)

Positive companion to `ao2_do_not_touch/`. Proves I14 (AO-2) and I15 (AO-6) PASS on a well-formed
retry that has REAL defects which are **disjoint** from the prior `do_not_touch` set.

Setup (copied from `good/`): `units/U01/debrief.json` is an `iteration:2` retry with a full
`prior_feedback` echo — `do_not_touch = ["the maker!=checker mandate framing", …]` and non-empty
`changes_made`. `units/U01/verify.json` is `verdict: FAIL` with one legitimate defect against the
criterion `"10-14 findings"` (a real `brief.acceptance_criteria` member, so I6 PASSes). Because
`"10-14 findings"` is NOT in `do_not_touch`, I14 is a genuine (non-trivial) disjoint PASS; the
non-empty `changes_made` makes I15 PASS.

A `FAIL` verdict alone does not fail the run at phase `P6_EXECUTE_VERIFY` (I10 only bites at
P8/DONE), so the run exits 0 while exercising the intersection logic on a non-empty defect set.

EXPECTED: exit 0 (RESULT: PASS); `PASS I14 AO-2 do_not_touch disjointness (units/U01)` and
`PASS I15 AO-6 responsive change (units/U01)`. No `NOTE.md` (this is a positive fixture).
