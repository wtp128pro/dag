I42-2: a present sha256 that is not 64 lowercase hex chars, on a path that EXISTS (so I42-4 cannot
mask) and inside a fully-object list (so I42-1b cannot mask). A malformed digest is fail-CLOSED —
it must never read as 'no digest recorded'. Exit 1 on `I42 evidence digest (malformed digest`.

R-U07-3 EXCEPTION, stated rather than implied: a schema-VALID single-failure repro of this clause is
UNREACHABLE by construction. Spec 3.1 mandates
`sha256: {type: string, pattern: "^[0-9a-f]{64}$"}` inside the `inputs_reviewed` items `oneOf`, and the
string branch requires a bare string — so ANY malformed digest fails both branches and the document is
schema-invalid, which in turn draws `I9 missing verification (present but INVALID — no usable verdict)`.
Deleting the schema pattern would make the fixture clean but would silently weaken a spec-mandated
shipped schema, so it was rejected: I42-2 exists to make the failure ATTRIBUTABLE and fail-closed, not to
replace the schema. What WAS removable is the ledger cascade — `fsm-state.json` now marks U01 `verifying`
(non-terminal) instead of `passed`, so the I2 status-vs-verdict FAIL no longer piles on. Residual output:
the schema line, the I42-2 line, and the I9-invalid line. The pin rests on the
`I42 evidence digest (malformed digest` substring, not on exit 1 alone.
