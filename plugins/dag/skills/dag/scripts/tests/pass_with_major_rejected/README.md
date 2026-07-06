# pass_with_major_rejected — NEGATIVE (RESULT: FAIL, I6 PASS clause via schema)

`U01`'s `verify.json` verdict is `PASS` but it carries a `major` defect. The revised I6 PASS clause
(schema `allOf`) forbids a blocker/major defect on a PASS, so the `verify.json` is schema-INVALID and
the run is rejected (I9 sees an invalid/absent verdict).

Expected: **exit 1**, with a schema error `$.defects[0].severity: 'major' not in enum ['minor']` and
`FAIL  I9 missing verification (units/U01): verify.json present but INVALID`.
