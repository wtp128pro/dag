I42-3 PATH-OWNER semantics, the excused half. A CROSS-UNIT citation: unit **U02**'s verify digests
`units/U01/debrief.json` (a sibling artifact — exactly the citation R18/BB-L46 invites) and the recorded
digest no longer matches. Phase is `P6_EXECUTE_VERIFY`, U02 (the verify's own unit) is `verifying`, and
**U01 — the unit that owns the digested PATH — is also `verifying`**, i.e. legitimately still able to
rewrite the file. Expected exit 0 with `N-I42 (digest drift`.

Paired with `digest_mismatch_crossunit_fail`, which is byte-identical except U01's ledger status. This
fixture is the CONTROL of the pair: it is green under BOTH the path-owner and the (rejected) verify-owner
reading, so it pins nothing on its own — it exists so the pair differs in exactly one field, the path
owner's status. Its partner is the discriminator.
