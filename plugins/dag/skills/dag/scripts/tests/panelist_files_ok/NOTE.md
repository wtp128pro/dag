# Fixture: panelist_files_ok (POSITIVE — D-04(a)/IMP-20)

Proves the validator BLESSES per-panelist verify files. Real high-stakes runs persist each panel
member's full verify as `units/<U>/verify_p<N>.json` alongside the aggregated `verify.json` +
`verify.json.panel[]`; before D-04 these were undocumented and never validated.

Copied from `panel_high_stakes_pass/`. Its addition: `units/U01/verify_p1.json`,
`verify_p2.json`, `verify_p3.json` — the three panel members' FULL individual verifies (correctness
/ reproduce / guardrail lenses), each schema-valid against `verify.schema.json`, `verdict: PASS`,
`executor_reasoning_seen: false` (blind), `unit_id: U01` matching the directory.

The validator **validates-if-present**: each panelist file emits
`units/U01/verify_p<N>.json valid against verify.schema.json (panelist audit, blind)`. They are
AUDIT artifacts — NOT inserted into unit_docs — so they never override the aggregated `verify.json`
the correction loop / I16 read.

EXPECTED: exit 0 (RESULT: PASS). Twin: `panelist_reasoning_seen`.
