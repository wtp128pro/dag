I41-4a, the resolution arm: `panel_adjudication` carries NO `resolution` at all, so `resolution` is not
one of {repoll, withdrawn, escalated-p7} and the adjudication disposes of nothing.

The absent key — rather than an out-of-enum literal like `"handled"` — is deliberate, and it is what
makes this fixture SCHEMA-VALID (`panel_adjudication` declares no `required` keys, so omitting
`resolution` is legal JSON-schema-wise while `"handled"` is rejected by the enum). Two consequences,
both load-bearing per R-U07-3: (1) the fixture now emits exactly ONE FAIL, so exit 1 is attributable to
I41-4a alone — with a schema-rejected literal the run also emitted `I9 missing verification` and
`I2 status vs verify verdict`, since a schema-invalid verify has "no usable verdict"; (2) the absent
key is the only shape of this clause the schema does NOT already reject, i.e. it is exactly I41-4a's
own contribution over the schema enum.

Satisfies I41-1, I41-2, and I41-3 (the member finding is `minor`, so there is no member major to mask
with). Exit 1 on `bad resolution`.
