I41-4d, SECOND arm (the majority RECOMPUTE, distinct from the panel/post_verdict desync arm pinned by
panel_repoll_majority_desync). The final panel is [FAIL, FAIL, PASS] while the top-level verdict is PASS,
so the discrete majority recomputed with I16's OWN rule is FAIL != PASS.

The verify is deliberately schema-INVALID (an unknown top-level key under additionalProperties:false).
That is the POINT: I16 reads the schema-validated unit_docs and therefore skips this document entirely,
while I41 reads units/<uid>/verify.json RAW and still holds the artifact to the majority rule. Without the
recompute arm the substring `I41-4d` never appears and this fixture fails its expectation.

R-U07-3 EXCEPTION, stated rather than implied: this fixture cannot violate exactly one thing. Its whole
subject is I41's behaviour on a document the schema rejects, so the schema FAIL is intrinsic, and a
schema-invalid verify necessarily also draws `I9 missing verification (present but INVALID — no usable
verdict)`. A schema-VALID variant is not a substitute: with the extra key removed, I16 itself fires on
the same majority mismatch and the fixture would no longer isolate I41's RAW read. What WAS removable is
the ledger cascade — `fsm-state.json` now marks U01 `verifying` (non-terminal) instead of `passed`, so
the I2 status-vs-verdict FAIL no longer piles on. Residual output: the schema line, the I41-4d line, and
the I9-invalid line. The pin rests on the `I41-4d` substring, not on exit 1 alone. Exit 1 on `I41-4d`.
