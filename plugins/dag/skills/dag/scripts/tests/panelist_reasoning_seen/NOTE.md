# Fixture: panelist_reasoning_seen (NEGATIVE — D-04(a)/IMP-20)

Exercises the **audit-blindness requirement** on a blessed panelist file: a `verify_p<N>.json` must
be schema-valid against `verify.schema.json`, which pins `executor_reasoning_seen` to `const: false`
(the I1 blindness attestation). A panel member that saw executor reasoning is a broken audit trail.

Copied from `panel_high_stakes_pass/` + the three panelist files of `panelist_files_ok`, but
`units/U01/verify_p1.json` sets `executor_reasoning_seen: true`. The validate-if-present path
schema-checks it and REJECTS it (the aggregated `verify.json` is untouched and still blind, so the
failure is specifically the panelist audit file).

EXPECTED: exit 1 with a schema FAIL on `units/U01/verify_p1.json: $.executor_reasoning_seen`
(wording differs by backend — mini: "must equal const False, got True"; jsonschema: "False was
expected"). Twin: `panelist_files_ok`.
