# Fixture: cartography_socratic_ok (POSITIVE — D-07(b): cartographer socratic has a schema home)

Proves the D-07(b) resolution of IMP-10: the cartographer/planner produce no debrief.json, so their
socratic self-interrogation residue had no schema-valid landing place (cartography/graph schemas were
`additionalProperties:false`). D-07(b) adds an OPTIONAL `socratic` block to
`cartography.schema.json`/`graph.schema.json`, machine-checked by I13 like debrief/verify.

Copy of `good` with a valid 4-key `socratic` block (real counter outcome) added to `cartography.json`.

BEFORE the fix: exit 1 — `$: additional property 'socratic' not allowed` (the schema rejected the key).
AFTER: exit 0 — the block validates and `I13 socratic counter records an outcome (cartography)` PASSes.

EXPECTED: exit 0 (RESULT: PASS), with a `PASS  I13 socratic counter records an outcome (cartography)`
line, no traceback.
