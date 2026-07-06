# Fixture: disagreement_on_pass (NEGATIVE — N-06 / Task 6.3)

`verify.schema.json` documented "disagreement present **iff** verdict==DISAGREE" but enforced only
the ⇐ direction (DISAGREE ⇒ present). PR-6 adds the ⇒ direction via an `allOf` clause: a
non-DISAGREE verdict (PASS or FAIL) MUST NOT carry a `disagreement` object — expressed with the
JSON-Schema `not` keyword. The built-in mini-validator was extended to support `not` (jsonschema
supports it natively), so both backends agree.

Copied from `good/` (verdict PASS); its **sole** injected defect: `units/U01/verify.json` keeps
`verdict: "PASS"` but adds a `disagreement` object.

EXPECTED: exit 1. The operative failure is
`FAIL units/U01/verify.json: $: matched 'not' subschema (must NOT match)`; because that makes
`verify.json` schema-invalid, the validator additionally reports the downstream
`I9 ... verify.json present but INVALID — no usable verdict` (same root cause, not a second
defect). No Python traceback.
